from pathlib import Path

from comicpublish import studio
from comicpublish.config import WorkflowConfig
from comicpublish.studio import (
    StudioPageArtifact,
    StudioRequest,
    WorkflowExecutionError,
    build_image_prompt,
    create_studio_run,
    generate_prepared_page_artifact,
    parse_architect_json,
)


def test_parse_architect_json_handles_code_fences() -> None:
    parsed = parse_architect_json(
        """```json
        {
          "series_name": "coastal_defense",
          "total_pages": 2,
          "pages_list": [
            {"page_num": 1, "content": "第一页"},
            {"page_num": 2, "content": "第二页"}
          ]
        }
        ```"""
    )

    assert parsed["series_name"] == "coastal_defense"
    assert parsed["total_pages"] == 2
    assert len(parsed["pages_list"]) == 2


def test_create_studio_run_writes_review_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
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

    monkeypatch.setattr(studio, "load_workflow_config", lambda: config)
    monkeypatch.setattr(
        studio,
        "run_story_concept_agent",
        lambda request_payload, config: "A clear educational comic concept.",
    )
    monkeypatch.setattr(
        studio,
        "run_manga_architect_agent",
        lambda request_payload, story_concept, config: {
            "series_name": "mangrove_lessons",
            "total_pages": 2,
            "pages_list": [
                {"page_num": 1, "content": "第一页介绍红树林如何削弱海浪。"},
                {"page_num": 2, "content": "第二页解释泥沙沉积和幼鱼栖息地。"},
            ],
        },
    )
    monkeypatch.setattr(
        studio,
        "call_image_generation",
        lambda prompt, config: {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "ok"},
                            {"inlineData": {"data": "iVBORw0KGgo=", "mimeType": "image/png"}},
                        ]
                    }
                }
            ]
        },
    )
    snapshots: list[dict] = []

    run = create_studio_run(
        StudioRequest(
            source_text="Mangroves reduce wave energy and protect biodiversity.",
            title_override="Mangrove Desk Test",
            page_count=2,
        ),
        tmp_path,
        progress_callback=snapshots.append,
    )

    root = Path(run.root_path)
    assert run.title == "Mangrove Desk Test"
    assert run.series_name == "mangrove_lessons"
    assert run.status == "completed"
    assert len(run.pages) == 2
    assert run.bundle_size_bytes > 0
    assert root.exists()
    assert root.parent.name == "mangrove-desk-test"
    assert (root / "manifest.json").exists()
    assert (root / "result.json").exists()
    assert (root / "input.json").exists()
    assert (root / "pages" / "mangrove_lessons_manga_1.png").exists()
    assert (root / "pages" / "page-01.json").exists()
    assert (root / "prompts" / "01-page-mangrove_lessons.md").exists()
    assert (root / "analysis.md").exists()
    assert (root / "storyboard.md").exists()
    assert not Path(run.archive_path).exists()
    assert snapshots[0]["status"] == "validating"
    assert snapshots[-1]["status"] == "completed"


def test_first_page_prompt_includes_comic_title() -> None:
    request_payload = StudioRequest(
        source_text="A lesson about pricing strategy.",
        title_override="Pricing Strategy Battle",
    )

    first_page_prompt = build_image_prompt(
        page_number=1,
        total_pages=3,
        content="第一页内容",
        request_payload=request_payload,
    )
    second_page_prompt = build_image_prompt(
        page_number=2,
        total_pages=3,
        content="第二页内容",
        request_payload=request_payload,
    )

    assert "第一页必须包含醒目的漫画标题：Pricing Strategy Battle" in first_page_prompt
    assert "Pricing Strategy Battle" not in second_page_prompt


def test_generate_page_retries_two_transient_image_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    artifact = StudioPageArtifact(
        id="page-01",
        page_number=1,
        title="Retry page",
        excerpt="Retry page excerpt",
        script="第一页脚本",
        notes="queued",
        filename="retry_page.png",
        image_path=str(tmp_path / "retry_page.png"),
        public_url=None,
        status="queued",
        prompt="prompt",
        prompt_path=str(tmp_path / "prompt.md"),
        mime_type="image/png",
        text_response="",
    )
    attempts = {"count": 0}

    def flaky_image_call(prompt, config):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise WorkflowExecutionError(
                'Image generation request failed: HTTP 502 {"error":{"message":"stream disconnected before completion"}}'
            )
        return {
            "data": [
                {
                    "b64_json": "iVBORw0KGgo=",
                    "revised_prompt": "ok",
                }
            ]
        }

    monkeypatch.setattr(studio, "call_image_generation", flaky_image_call)
    monkeypatch.setattr(studio, "sleep_before_retry", lambda attempt: None)

    result = generate_prepared_page_artifact(
        artifact=artifact,
        pages_dir=tmp_path,
        config=config,
        started_at=0,
        logs=[],
    )

    assert attempts["count"] == 3
    assert result.status == "success"
    assert Path(result.image_path).exists()
