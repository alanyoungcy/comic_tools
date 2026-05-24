from concurrent.futures import ThreadPoolExecutor
import json
import time
from datetime import datetime
from pathlib import Path

from comicpublish import runner
from comicpublish.config import WorkflowConfig
from comicpublish.studio import StudioPageArtifact, StudioRequest


def test_background_runner_writes_terminal_snapshot(tmp_path: Path, monkeypatch) -> None:
    config = WorkflowConfig(
        planning_api_key="planning-test",
        planning_model="gemini-3.1-pro",
        planning_base_url="https://jmrai.net",
        planning_max_tokens=12000,
        image_api_key="image-test",
        image_model="gpt-image-2",
        image_base_url="https://jmrai.net",
        image_size="1248x1664",
        image_parallelism=3,
        image_retry_attempts=2,
        output_dir=tmp_path,
        request_timeout_seconds=120,
    )
    monkeypatch.setattr(runner, "load_workflow_config", lambda: config)

    def fake_create_studio_run(request_payload, progress_callback=None, run_id=None, created_at=None):
        progress_callback(
            {
                "run_id": run_id,
                "created_at": created_at.isoformat(timespec="seconds"),
                "elapsed_seconds": 0.2,
                "status": "generating",
                "title": request_payload.resolved_title(),
                "series_name": "demo_series",
                "source_text": request_payload.source_text,
                "audience": request_payload.audience,
                "output_language": request_payload.output_language,
                "workflow_preset": request_payload.workflow_preset,
                "comic_style": request_payload.comic_style,
                "tone_notes": request_payload.tone_notes,
                "requested_page_count": request_payload.sanitized_page_count(),
                "total_pages": 2,
                "success_count": 1,
                "failure_count": 0,
                "root_path": str(tmp_path / "runs" / "demo"),
                "manifest_path": str(tmp_path / "runs" / "demo" / "manifest.json"),
                "result_path": str(tmp_path / "runs" / "demo" / "result.json"),
                "bundle_size_bytes": 0,
                "story_concept": "concept",
                "architect_output": {},
                "logs": [["00:00", "started"]],
                "pages": [],
                "progress": 60,
                "step": 2,
                "error": "",
            }
        )
        progress_callback(
            {
                "run_id": run_id,
                "created_at": created_at.isoformat(timespec="seconds"),
                "elapsed_seconds": 0.4,
                "status": "completed",
                "title": request_payload.resolved_title(),
                "series_name": "demo_series",
                "source_text": request_payload.source_text,
                "audience": request_payload.audience,
                "output_language": request_payload.output_language,
                "workflow_preset": request_payload.workflow_preset,
                "comic_style": request_payload.comic_style,
                "tone_notes": request_payload.tone_notes,
                "requested_page_count": request_payload.sanitized_page_count(),
                "total_pages": 2,
                "success_count": 2,
                "failure_count": 0,
                "root_path": str(tmp_path / "runs" / "demo"),
                "manifest_path": str(tmp_path / "runs" / "demo" / "manifest.json"),
                "result_path": str(tmp_path / "runs" / "demo" / "result.json"),
                "bundle_size_bytes": 512,
                "story_concept": "concept",
                "architect_output": {},
                "logs": [["00:00", "started"], ["00:00", "done"]],
                "pages": [],
                "progress": 100,
                "step": 4,
                "error": "",
            }
        )

    monkeypatch.setattr(runner, "create_studio_run", fake_create_studio_run)

    job_id = runner.start_background_run(
        StudioRequest(source_text="Mangroves protect coasts.", title_override="Runner Test")
    )

    snapshot = None
    deadline = time.time() + 2
    while time.time() < deadline:
        snapshot = runner.load_background_run(job_id)
        if snapshot and snapshot.get("status") == "completed":
            break
        time.sleep(0.05)

    assert snapshot is not None
    assert snapshot["job_id"] == job_id
    assert snapshot["status"] == "completed"
    assert snapshot["progress"] == 100


def test_page_regeneration_deduplicates_same_page_workers(tmp_path: Path, monkeypatch) -> None:
    config = WorkflowConfig(
        planning_api_key="planning-test",
        planning_model="gemini-3.1-pro",
        planning_base_url="https://jmrai.net",
        planning_max_tokens=12000,
        image_api_key="image-test",
        image_model="gpt-image-2",
        image_base_url="https://jmrai.net",
        image_size="1248x1664",
        image_parallelism=3,
        image_retry_attempts=2,
        output_dir=tmp_path,
        request_timeout_seconds=120,
    )
    root = tmp_path / "projects" / "demo" / "CP-260101-000000"
    pages_dir = root / "pages"
    pages_dir.mkdir(parents=True)
    manifest_path = root / "manifest.json"
    page = StudioPageArtifact(
        id="page-01",
        page_number=1,
        title="Page one",
        excerpt="Page one",
        script="第一页",
        notes="ready",
        filename="demo_manga_1.png",
        image_path=str(pages_dir / "demo_manga_1.png"),
        public_url=None,
        status="failed",
        prompt="prompt",
        prompt_path=str(root / "prompts" / "01-page-demo.md"),
        mime_type="image/png",
        text_response="",
        error="previous failure",
    )
    (pages_dir / "page-01.json").write_text(json.dumps(page.to_dict()), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "CP-260101-000000",
                "series_name": "demo",
                "root_path": str(root),
                "manifest_path": str(manifest_path),
                "result_path": str(root / "result.json"),
                "story_concept": "concept",
                "architect_output": {},
                "pages": [page.to_dict()],
                "success_count": 0,
                "failure_count": 1,
                "bundle_size_bytes": 0,
                "status": "partial",
            }
        ),
        encoding="utf-8",
    )
    started = False
    calls = {"count": 0}

    def fake_generate_prepared_page_artifact(
        artifact,
        pages_dir,
        config,
        started_at,
        logs,
        session_log_path=None,
        session_elapsed_label=None,
    ):
        nonlocal started
        started = True
        calls["count"] += 1
        time.sleep(0.1)
        artifact.status = "success"
        artifact.error = None
        artifact.notes = "done"
        return artifact

    monkeypatch.setattr(runner, "load_workflow_config", lambda: config)
    monkeypatch.setattr(runner, "generate_prepared_page_artifact", fake_generate_prepared_page_artifact)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner.regenerate_page_image, manifest_path, "page-01")
        deadline = time.time() + 1
        while not started and time.time() < deadline:
            time.sleep(0.01)
        second = pool.submit(runner.regenerate_page_image, manifest_path, "page-01")
        first.result()
        second.result()

    assert calls["count"] == 1


def test_planned_snapshot_is_terminal() -> None:
    assert runner.snapshot_is_terminal({"status": "planned"})


def test_generate_page_images_runs_only_missing_pages(tmp_path: Path, monkeypatch) -> None:
    config = WorkflowConfig(
        planning_api_key="planning-test",
        planning_model="gemini-3.1-pro",
        planning_base_url="https://jmrai.net",
        planning_max_tokens=12000,
        image_api_key="image-test",
        image_model="gpt-image-2",
        image_base_url="https://jmrai.net",
        image_size="1248x1664",
        image_parallelism=2,
        image_retry_attempts=2,
        output_dir=tmp_path,
        request_timeout_seconds=120,
    )
    root = tmp_path / "projects" / "demo" / "CP-260101-010000"
    pages_dir = root / "pages"
    prompts_dir = root / "prompts"
    pages_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)
    manifest_path = root / "manifest.json"

    pages = []
    for number, status in [(1, "queued"), (2, "failed"), (3, "success")]:
        image_path = pages_dir / f"demo_manga_{number}.png"
        if status == "success":
            image_path.write_bytes(b"ok")
        page = StudioPageArtifact(
            id=f"page-{number:02d}",
            page_number=number,
            title=f"Page {number}",
            excerpt=f"Page {number}",
            script=f"第 {number} 页",
            notes=status,
            filename=f"demo_manga_{number}.png",
            image_path=str(image_path),
            public_url=None,
            status=status,
            prompt="prompt",
            prompt_path=str(prompts_dir / f"{number:02d}-page-demo.md"),
            mime_type="image/png",
            text_response="",
            error="previous failure" if status == "failed" else None,
        )
        (pages_dir / f"page-{number:02d}.json").write_text(json.dumps(page.to_dict()), encoding="utf-8")
        pages.append(page.to_dict())

    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "CP-260101-010000",
                "series_name": "demo",
                "root_path": str(root),
                "manifest_path": str(manifest_path),
                "result_path": str(root / "result.json"),
                "story_concept": "concept",
                "architect_output": {},
                "pages": pages,
                "success_count": 1,
                "failure_count": 1,
                "bundle_size_bytes": 0,
                "status": "planned",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_generate_prepared_page_artifact(
        artifact,
        pages_dir,
        config,
        started_at,
        logs,
        session_log_path=None,
        session_elapsed_label=None,
    ):
        calls.append(artifact.id)
        artifact.status = "success"
        artifact.error = None
        artifact.notes = "done"
        Path(artifact.image_path).write_bytes(b"ok")
        return artifact

    monkeypatch.setattr(runner, "load_workflow_config", lambda: config)
    monkeypatch.setattr(runner, "generate_prepared_page_artifact", fake_generate_prepared_page_artifact)

    updated = runner.generate_page_images(manifest_path)

    assert sorted(calls) == ["page-01", "page-02"]
    assert updated["status"] == "completed"
    assert updated["success_count"] == 3
    assert updated["failure_count"] == 0
    assert updated["progress"] == 100
    assert updated["step"] == 4
    session_log = json.loads((root / "session-log.json").read_text(encoding="utf-8"))
    assert any("Dispatching image generation" in entry[1] for entry in session_log["logs"])
