from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from comicpublish.config import load_workflow_config
from comicpublish.studio import (
    StudioPageArtifact,
    StudioRequest,
    create_studio_run,
    directory_size_bytes,
    generate_prepared_page_artifact,
    write_json_atomic,
)


_RUNNER_THREADS: dict[str, threading.Thread] = {}
_RUN_FILE_LOCK = threading.Lock()
_PAGE_REGEN_LOCKS: dict[str, threading.Lock] = {}
_PAGE_REGEN_LOCKS_GUARD = threading.Lock()


def start_background_run(request_payload: StudioRequest) -> str:
    config = load_workflow_config()
    config.validate()
    runner_dir = config.output_dir / "runner"
    runner_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().astimezone()
    job_id = created_at.strftime("job-%y%m%d-%H%M%S-%f")
    status_path = runner_dir / f"{job_id}.json"
    run_id = created_at.strftime("CP-%y%m%d-%H%M%S")

    initial_snapshot = {
        "job_id": job_id,
        "run_id": run_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "elapsed_seconds": 0.0,
        "status": "validating",
        "title": request_payload.resolved_title(),
        "series_name": "",
        "source_text": request_payload.source_text.strip(),
        "audience": request_payload.audience,
        "output_language": request_payload.output_language,
        "workflow_preset": request_payload.workflow_preset,
        "comic_style": request_payload.comic_style,
        "tone_notes": request_payload.tone_notes.strip(),
        "requested_page_count": request_payload.sanitized_page_count(),
        "total_pages": request_payload.sanitized_page_count(),
        "success_count": 0,
        "failure_count": 0,
        "root_path": "",
        "manifest_path": "",
        "result_path": "",
        "bundle_size_bytes": 0,
        "story_concept": "",
        "architect_output": {},
        "logs": [["00:00", "Runner thread queued."]],
        "pages": [],
        "progress": 2,
        "step": 0,
        "error": "",
    }
    _write_snapshot(status_path, initial_snapshot)

    def worker() -> None:
        latest_snapshot: dict[str, Any] = deepcopy(initial_snapshot)

        def on_progress(snapshot: dict[str, Any]) -> None:
            latest_snapshot.clear()
            latest_snapshot.update(snapshot)
            latest_snapshot["job_id"] = job_id
            _write_snapshot(status_path, latest_snapshot)

        try:
            create_studio_run(
                request_payload=request_payload,
                progress_callback=on_progress,
                run_id=run_id,
                created_at=created_at,
            )
        except Exception as exc:
            failure_snapshot = deepcopy(latest_snapshot)
            failure_snapshot["job_id"] = job_id
            failure_snapshot["status"] = "failed"
            failure_snapshot["progress"] = 42
            failure_snapshot["step"] = 1
            failure_snapshot["error"] = str(exc)
            logs = list(failure_snapshot.get("logs") or [])
            logs.append([_elapsed_label(failure_snapshot.get("elapsed_seconds", 0.0)), f"Runner failed: {exc}"])
            failure_snapshot["logs"] = logs
            _write_snapshot(status_path, failure_snapshot)
        finally:
            _RUNNER_THREADS.pop(job_id, None)

    thread = threading.Thread(target=worker, name=job_id, daemon=True)
    _RUNNER_THREADS[job_id] = thread
    thread.start()
    return job_id


def load_background_run(job_id: str) -> dict[str, Any] | None:
    config = load_workflow_config()
    status_path = config.output_dir / "runner" / f"{job_id}.json"
    if not status_path.exists():
        return None
    return json.loads(status_path.read_text(encoding="utf-8"))


def load_run_from_manifest(manifest_path: str | Path) -> dict[str, Any] | None:
    path = Path(manifest_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def regenerate_page_image(manifest_path: str | Path, page_id: str) -> dict[str, Any]:
    config = load_workflow_config()
    config.validate()
    manifest_path = Path(manifest_path)
    regen_lock = _page_regen_lock(manifest_path, page_id)
    if not regen_lock.acquire(blocking=False):
        run = load_run_from_manifest(manifest_path)
        if run is not None:
            return run
        raise RuntimeError(f"Regeneration already in progress for {page_id}")

    try:
        return _regenerate_page_image_locked(manifest_path, page_id, config)
    finally:
        regen_lock.release()


def generate_page_images(manifest_path: str | Path, page_ids: list[str] | None = None) -> dict[str, Any]:
    config = load_workflow_config()
    config.validate()
    manifest_path = Path(manifest_path)
    run = load_run_from_manifest(manifest_path)
    if run is None:
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    pages = run.get("pages") or []
    requested_ids = set(page_ids or [])
    target_ids = [
        page["id"]
        for page in pages
        if _page_needs_image(page) and (not requested_ids or page["id"] in requested_ids)
    ]
    if not target_ids:
        return run

    max_workers = min(config.image_parallelism, max(1, len(target_ids)))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="comic-manual-image") as executor:
        futures = {
            executor.submit(regenerate_page_image, manifest_path, page_id): page_id
            for page_id in target_ids
        }
        for future in as_completed(futures):
            future.result()

    refreshed = load_run_from_manifest(manifest_path)
    if refreshed is None:
        raise FileNotFoundError(f"Manifest not found after generation: {manifest_path}")
    return refreshed


def _regenerate_page_image_locked(manifest_path: Path, page_id: str, config: Any) -> dict[str, Any]:
    run = load_run_from_manifest(manifest_path)
    if run is None:
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    root = Path(run["root_path"])
    pages_dir = root / "pages"
    page_number = int(page_id.removeprefix("page-"))
    page_path = pages_dir / f"page-{page_number:02d}.json"
    artifact = StudioPageArtifact(**json.loads(page_path.read_text(encoding="utf-8")))
    artifact.status = "in-progress"
    artifact.notes = "Manual regeneration request is in flight."
    artifact.error = None
    if not artifact.filename:
        artifact.filename = f"{run['series_name']}_manga_{page_number}.png"
    artifact.image_path = str(pages_dir / artifact.filename)
    _write_page_json(page_path, artifact)
    _sync_run_files(root, run, pages_dir)

    try:
        result = generate_prepared_page_artifact(
            artifact=artifact,
            pages_dir=pages_dir,
            config=config,
            started_at=datetime.now().timestamp(),
            logs=[],
        )
    except Exception as exc:
        result = StudioPageArtifact(
            id=artifact.id,
            page_number=artifact.page_number,
            title=artifact.title,
            excerpt=artifact.excerpt,
            script=artifact.script,
            notes="Manual regeneration failed before a local image file was saved.",
            filename=None,
            image_path="",
            public_url=None,
            status="failed",
            prompt=artifact.prompt,
            prompt_path=artifact.prompt_path,
            mime_type="image/png",
            text_response="",
            error=str(exc),
        )
    _write_page_json(page_path, result)
    return _sync_run_files(root, run, pages_dir)


def snapshot_is_terminal(snapshot: dict[str, Any] | None) -> bool:
    if snapshot is None:
        return False
    return snapshot.get("status") in {"planned", "completed", "partial", "failed"}


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    write_json_atomic(path, snapshot)


def _elapsed_label(value: float) -> str:
    total_seconds = max(0, int(round(value)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _write_page_json(path: Path, artifact: StudioPageArtifact) -> None:
    write_json_atomic(path, artifact.to_dict())


def _sync_run_files(root: Path, run: dict[str, Any], pages_dir: Path) -> dict[str, Any]:
    with _RUN_FILE_LOCK:
        pages = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(pages_dir.glob("page-*.json"))
        ]
        success_count = sum(1 for page in pages if page.get("status") == "success")
        failure_count = sum(1 for page in pages if page.get("status") == "failed")
        queued_count = sum(1 for page in pages if page.get("status") == "queued")
        in_progress_count = sum(1 for page in pages if page.get("status") == "in-progress")

        run["pages"] = pages
        run["success_count"] = success_count
        run["failure_count"] = failure_count
        run["bundle_size_bytes"] = directory_size_bytes(root)
        if in_progress_count:
            run["status"] = "generating"
        elif queued_count:
            run["status"] = "partial" if failure_count else "planned"
        elif failure_count:
            run["status"] = "partial" if success_count else "failed"
        else:
            run["status"] = "completed"
            run["error"] = ""
        run["progress"], run["step"] = _run_progress_step(
            status=run["status"],
            finished_count=success_count + failure_count,
            total_count=len(pages),
        )

        result_path = root / "result.json"
        result = {"story_concept": run.get("story_concept", ""), "architect_output": run.get("architect_output", {})}
        if result_path.exists() and result_path.stat().st_size > 0:
            try:
                loaded_result = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded_result = result
            if isinstance(loaded_result, dict):
                result.update(loaded_result)
        result["pages"] = pages
        write_json_atomic(result_path, result)

        manifest_path = root / "manifest.json"
        write_json_atomic(manifest_path, run)
        return run


def _page_needs_image(page: dict[str, Any]) -> bool:
    if page.get("status") in {"queued", "failed"}:
        return True
    image_path = str(page.get("image_path") or "")
    return bool(image_path and not Path(image_path).exists())


def _run_progress_step(status: str, finished_count: int, total_count: int) -> tuple[int, int]:
    if status == "planned":
        return 52, 2
    if status == "generating":
        generated_progress = int((finished_count / max(total_count, 1)) * 40)
        return min(92, 52 + generated_progress), 2
    if status == "completed":
        return 100, 4
    if status == "partial":
        return 100, 4
    if status == "failed":
        return 42, 1
    return 0, 0


def _page_regen_lock(manifest_path: Path, page_id: str) -> threading.Lock:
    key = f"{manifest_path.resolve()}::{page_id}"
    with _PAGE_REGEN_LOCKS_GUARD:
        lock = _PAGE_REGEN_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PAGE_REGEN_LOCKS[key] = lock
        return lock
