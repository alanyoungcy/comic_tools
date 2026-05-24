import json
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
    resolve_generated_title,
    resolve_suggested_hashtags,
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
            "display_title": "红树林护岸漫画",
            "comic_summary": "这部漫画用分步骤场景说明红树林如何削弱海浪、固定泥沙，并为幼鱼提供栖息环境。",
            "suggested_hashtags": [
                "#红树林",
                "#海岸保护",
                "#知识漫画",
                "#生态教育",
                "#湿地",
            ],
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
    assert run.title == "红树林护岸漫画"
    assert run.series_name == "mangrove_lessons"
    assert run.comic_summary.startswith("这部漫画用分步骤场景说明红树林如何削弱海浪")
    assert run.suggested_hashtags == ["#红树林", "#海岸保护", "#知识漫画", "#生态教育", "#湿地"]
    assert run.status == "completed"
    assert len(run.pages) == 2
    assert run.bundle_size_bytes > 0
    assert root.exists()
    assert root.parent.name == "mangrove-desk-test"
    assert (root / "manifest.json").exists()
    assert (root / "result.json").exists()
    assert (root / "session-log.json").exists()
    assert (root / "input.json").exists()
    assert (root / "pages" / "mangrove_lessons_manga_1.png").exists()
    assert (root / "pages" / "page-01.json").exists()
    assert (root / "prompts" / "01-page-mangrove_lessons.md").exists()
    assert (root / "analysis.md").exists()
    assert (root / "storyboard.md").exists()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert manifest["title"] == "红树林护岸漫画"
    assert manifest["comic_summary"] == run.comic_summary
    assert manifest["suggested_hashtags"] == run.suggested_hashtags
    assert result["comic_summary"] == run.comic_summary
    assert result["suggested_hashtags"] == run.suggested_hashtags
    assert snapshots[0]["status"] == "validating"
    assert snapshots[-1]["status"] == "completed"
    assert snapshots[-1]["title"] == "红树林护岸漫画"


def test_create_studio_run_can_stop_after_page_json_checkpoint(
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
        lambda request_payload, config: "A checkpointed comic concept.",
    )
    monkeypatch.setattr(
        studio,
        "run_manga_architect_agent",
        lambda request_payload, story_concept, config: {
            "series_name": "checkpoint_lessons",
            "total_pages": 2,
            "pages_list": [
                {"page_num": 1, "content": "第一页生成页面脚本。"},
                {"page_num": 2, "content": "第二页保留等待图片生成。"},
            ],
        },
    )

    def unexpected_image_call(prompt, config):
        raise AssertionError("image generation should not run during the planning checkpoint")

    monkeypatch.setattr(studio, "call_image_generation", unexpected_image_call)
    snapshots: list[dict] = []

    run = create_studio_run(
        StudioRequest(
            source_text="Checkpoint the prompt files before images.",
            title_override="Checkpoint Test",
            page_count=2,
            auto_generate_images=False,
        ),
        tmp_path,
        progress_callback=snapshots.append,
    )

    root = Path(run.root_path)
    assert run.status == "planned"
    assert run.title == "Checkpoint Test"
    assert run.comic_summary
    assert len(run.suggested_hashtags) == 5
    assert run.success_count == 0
    assert run.failure_count == 0
    assert len(run.pages) == 2
    assert (root / "pages" / "page-01.json").exists()
    assert (root / "pages" / "page-02.json").exists()
    assert (root / "prompts" / "01-page-checkpoint_lessons.md").exists()
    assert not (root / "pages" / "checkpoint_lessons_manga_1.png").exists()
    assert snapshots[-1]["status"] == "planned"


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


def test_generated_metadata_is_sanitized_by_language() -> None:
    chinese_request = StudioRequest(
        source_text="关于供应链韧性的课程。",
        output_language="Simplified Chinese",
    )
    english_request = StudioRequest(
        source_text="A lesson on coral reef resilience.",
        output_language="English",
    )

    chinese_title = resolve_generated_title(
        chinese_request,
        {"display_title": "這是一個超過二十個字的中文漫畫標題用來測試截斷規則"},
        "后备标题",
    )
    english_title = resolve_generated_title(
        english_request,
        {
            "display_title": (
                "one two three four five six seven eight nine ten eleven twelve "
                "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone"
            )
        },
        "Fallback Title",
    )
    hashtags = resolve_suggested_hashtags(
        english_request,
        {"suggested_hashtags": ["reef lesson", "#OceanClass", "#CoralCare"]},
        "Coral Reef Resilience",
    )

    assert len(chinese_title) <= 20
    assert len(english_title.split()) == 20
    assert len(hashtags) == 5
    assert all(tag.startswith("#") for tag in hashtags)


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


def test_generate_page_compacts_prompt_after_stream_disconnect_retry(
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
    verbose_scene = "场景说明" * 600
    artifact = StudioPageArtifact(
        id="page-01",
        page_number=1,
        title="Retry compact page",
        excerpt="Retry compact page excerpt",
        script="第一页脚本",
        notes="queued",
        filename="retry_compact_page.png",
        image_path=str(tmp_path / "retry_compact_page.png"),
        public_url=None,
        status="queued",
        prompt=(
            "请为以下漫画页面生成一张图片。\n\n"
            "当前页码：第 1 页（共 1 页）\n"
            f"本页情节：{verbose_scene}\n\n"
            "要求：\n\n- 所有对话气泡和文字必须使用中文\n"
        ),
        prompt_path=str(tmp_path / "prompt.md"),
        mime_type="image/png",
        text_response="",
    )
    seen_prompts: list[str] = []

    def flaky_image_call(prompt, config):
        seen_prompts.append(prompt)
        if len(seen_prompts) == 1:
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

    assert result.status == "success"
    assert len(seen_prompts) == 2
    assert len(seen_prompts[1]) < len(seen_prompts[0])
