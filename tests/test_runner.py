import time
from datetime import datetime
from pathlib import Path

from comicpublish import runner
from comicpublish.config import WorkflowConfig
from comicpublish.studio import StudioRequest


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
                "archive_path": str(tmp_path / "runs" / "demo" / "export" / "demo_series.zip"),
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
                "archive_path": str(tmp_path / "runs" / "demo" / "export" / "demo_series.zip"),
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
