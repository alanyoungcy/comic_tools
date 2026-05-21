from __future__ import annotations

import json
import threading
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
)


_RUNNER_THREADS: dict[str, threading.Thread] = {}
_RUN_FILE_LOCK = threading.Lock()


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
        "archive_path": "",
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
    return snapshot.get("status") in {"completed", "partial", "failed"}


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _elapsed_label(value: float) -> str:
    total_seconds = max(0, int(round(value)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _write_page_json(path: Path, artifact: StudioPageArtifact) -> None:
    path.write_text(
        json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sync_run_files(root: Path, run: dict[str, Any], pages_dir: Path) -> dict[str, Any]:
    with _RUN_FILE_LOCK:
        pages = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(pages_dir.glob("page-*.json"))
        ]
        success_count = sum(1 for page in pages if page.get("status") == "success")
        failure_count = sum(1 for page in pages if page.get("status") == "failed")
        in_progress_count = sum(1 for page in pages if page.get("status") in {"queued", "in-progress"})

        run["pages"] = pages
        run["success_count"] = success_count
        run["failure_count"] = failure_count
        run["bundle_size_bytes"] = directory_size_bytes(root)
        if in_progress_count:
            run["status"] = "generating"
        elif failure_count:
            run["status"] = "partial" if success_count else "failed"
        else:
            run["status"] = "completed"

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
        _write_json_atomic(result_path, result)

        manifest_path = root / "manifest.json"
        _write_json_atomic(manifest_path, run)
        return run


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
