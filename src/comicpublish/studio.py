from __future__ import annotations

import base64
import http.client
import json
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, request

from comicpublish.config import WorkflowConfig, load_workflow_config
from comicpublish.pipeline import slugify

DEFAULT_SOURCE_TEXT = (
    "Mangrove forests protect coastlines in three ways: their roots break wave "
    "energy, their soil traps sediment, and their canopy helps create habitat "
    "for juvenile fish. During storms, that root network acts like a living "
    "barrier, reducing erosion and slowing the water before it reaches villages "
    "behind the shore."
)

DEFAULT_TONE_NOTES = (
    "Keep the narrator calm and factual. Let one student character ask short "
    "clarifying questions so the page turns feel teachable rather than "
    "lecture-heavy."
)

DEFAULT_COMIC_IMAGE_SIZE = "1248x1664"

AUDIENCE_OPTIONS = (
    "Middle school science",
    "High school biology",
    "Teacher explainer",
)

LANGUAGE_OPTIONS = (
    "Simplified Chinese",
    "English",
    "Bilingual",
)

WORKFLOW_PRESETS = (
    "Lesson comic",
    "Exam prep",
    "Narrated explainer",
    "Character-driven",
)

STYLE_PRESETS = (
    "Editorial classroom",
    "Manga explainer",
    "Infographic hybrid",
)


class WorkflowExecutionError(RuntimeError):
    """Raised when the external comic workflow fails."""


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class StudioRequest:
    source_text: str
    title_override: str = ""
    audience: str = AUDIENCE_OPTIONS[0]
    output_language: str = LANGUAGE_OPTIONS[0]
    workflow_preset: str = WORKFLOW_PRESETS[0]
    page_count: int = 4
    comic_style: str = STYLE_PRESETS[0]
    tone_notes: str = DEFAULT_TONE_NOTES
    auto_generate_images: bool = True

    def resolved_title(self) -> str:
        override = self.title_override.strip()
        if override:
            return override
        return infer_title(self.source_text)

    def sanitized_page_count(self) -> int:
        return max(1, min(int(self.page_count), 8))


@dataclass(slots=True)
class StudioPageArtifact:
    id: str
    page_number: int
    title: str
    excerpt: str
    script: str
    notes: str
    filename: str | None
    image_path: str
    public_url: str | None
    status: str
    prompt: str
    prompt_path: str
    mime_type: str
    text_response: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StudioRunArtifact:
    run_id: str
    created_at: str
    elapsed_seconds: float
    status: str
    title: str
    series_name: str
    source_text: str
    audience: str
    output_language: str
    workflow_preset: str
    comic_style: str
    tone_notes: str
    requested_page_count: int
    total_pages: int
    success_count: int
    failure_count: int
    root_path: str
    manifest_path: str
    result_path: str
    bundle_size_bytes: int
    story_concept: str
    architect_output: dict[str, Any]
    progress: int = 0
    step: int = 0
    error: str = ""
    logs: list[list[str]] = field(default_factory=list)
    pages: list[StudioPageArtifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_title(source_text: str) -> str:
    cleaned = normalize_whitespace(source_text)
    if not cleaned:
        return "Untitled Lesson Comic"

    words = re.findall(r"[A-Za-z0-9']+", cleaned)
    if not words:
        return "Untitled Lesson Comic"

    return " ".join(words[:5]).title()


def create_studio_run(
    request_payload: StudioRequest,
    output_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> StudioRunArtifact:
    config = load_workflow_config()
    config.validate()

    started_at = time.monotonic()
    created_at = created_at or datetime.now().astimezone()
    run_id = run_id or created_at.strftime("CP-%y%m%d-%H%M%S")
    title = request_payload.resolved_title()
    project_slug = slugify(title)
    root = (output_dir or config.output_dir) / "projects" / project_slug / run_id
    pages_dir = root / "pages"
    prompts_dir = root / "prompts"
    root.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    result_path = root / "result.json"

    logs: list[list[str]] = []
    story_concept = ""
    architect_output: dict[str, Any] = {}
    page_artifacts: list[StudioPageArtifact] = []
    total_pages = request_payload.sanitized_page_count()
    series_name = ""

    def publish(status: str, progress: int, step: int, error_text: str = "") -> None:
        if progress_callback is None:
            return
        snapshot = {
            "run_id": run_id,
            "created_at": created_at.isoformat(timespec="seconds"),
            "elapsed_seconds": round(time.monotonic() - started_at, 2),
            "status": status,
            "title": title,
            "series_name": series_name,
            "source_text": request_payload.source_text.strip(),
            "audience": request_payload.audience,
            "output_language": request_payload.output_language,
            "workflow_preset": request_payload.workflow_preset,
            "comic_style": request_payload.comic_style,
            "tone_notes": request_payload.tone_notes.strip(),
            "requested_page_count": request_payload.sanitized_page_count(),
            "total_pages": total_pages,
            "success_count": sum(1 for page in page_artifacts if page.status == "success"),
            "failure_count": sum(1 for page in page_artifacts if page.status == "failed"),
            "root_path": str(root),
            "manifest_path": str(manifest_path),
            "result_path": str(result_path),
            "bundle_size_bytes": directory_size_bytes(root),
            "story_concept": story_concept,
            "architect_output": architect_output,
            "logs": list(logs),
            "pages": [page.to_dict() for page in sort_pages_for_display(page_artifacts)],
            "progress": progress,
            "step": step,
            "error": error_text,
        }
        progress_callback(snapshot)

    def write_progress_files(status: str) -> None:
        pages_snapshot = [page.to_dict() for page in page_artifacts]
        write_json_atomic(
            result_path,
            {
                "story_concept": story_concept,
                "architect_output": architect_output,
                "pages": pages_snapshot,
            },
        )
        write_json_atomic(
            manifest_path,
            {
                "run_id": run_id,
                "created_at": created_at.isoformat(timespec="seconds"),
                "elapsed_seconds": round(time.monotonic() - started_at, 2),
                "status": status,
                "title": title,
                "series_name": series_name,
                "source_text": request_payload.source_text.strip(),
                "audience": request_payload.audience,
                "output_language": request_payload.output_language,
                "workflow_preset": request_payload.workflow_preset,
                "comic_style": request_payload.comic_style,
                "tone_notes": request_payload.tone_notes.strip(),
                "requested_page_count": request_payload.sanitized_page_count(),
                "total_pages": total_pages,
                "success_count": sum(1 for page in page_artifacts if page.status == "success"),
                "failure_count": sum(1 for page in page_artifacts if page.status == "failed"),
                "root_path": str(root),
                "manifest_path": str(manifest_path),
                "result_path": str(result_path),
                "bundle_size_bytes": directory_size_bytes(root),
                "story_concept": story_concept,
                "architect_output": architect_output,
                "logs": list(logs),
                "pages": pages_snapshot,
            },
        )

    log_line(logs, started_at, "Run created and operator inputs snapshotted.")
    publish(status="validating", progress=6, step=0)
    write_json_atomic(root / "input.json", asdict(request_payload))

    story_concept = run_story_concept_agent(request_payload, config)
    log_line(logs, started_at, "Story concept agent returned the teaching concept.")
    publish(status="validating", progress=18, step=0)
    write_text_atomic(root / "analysis.md", build_analysis_markdown(request_payload, story_concept))

    architect_output = run_manga_architect_agent(request_payload, story_concept, config)
    log_line(logs, started_at, "Manga architect agent returned structured page JSON.")

    series_name = sanitize_series_name(
        str(architect_output.get("series_name") or slugify(title).replace("-", "_"))
    )
    pages_payload = architect_output.get("pages_list") or []
    if not isinstance(pages_payload, list):
        raise WorkflowExecutionError("pages_list must be an array in the architect JSON.")

    total_pages = int(architect_output.get("total_pages") or len(pages_payload) or 0)
    if total_pages <= 0:
        raise WorkflowExecutionError("The architect agent returned zero pages.")
    write_text_atomic(
        root / "storyboard.md",
        build_storyboard_markdown(title=title, series_name=series_name, pages_payload=pages_payload),
    )
    publish(status="generating", progress=32, step=2)

    for page_data in pages_payload:
        artifact = prepare_page_artifact(
            page_data=page_data,
            request_payload=request_payload,
            series_name=series_name,
            pages_dir=pages_dir,
            prompts_dir=prompts_dir,
            config=config,
            started_at=started_at,
            logs=logs,
        )
        page_artifacts.append(artifact)
        publish(status="generating", progress=32, step=2)

    write_progress_files(status="generating")

    if not request_payload.auto_generate_images:
        log_line(
            logs,
            started_at,
            "Planning checkpoint reached; page JSON and prompt files are ready for manual image generation.",
        )
        run = StudioRunArtifact(
            run_id=run_id,
            created_at=created_at.isoformat(timespec="seconds"),
            elapsed_seconds=round(time.monotonic() - started_at, 2),
            status="planned",
            title=title,
            series_name=series_name,
            source_text=request_payload.source_text.strip(),
            audience=request_payload.audience,
            output_language=request_payload.output_language,
            workflow_preset=request_payload.workflow_preset,
            comic_style=request_payload.comic_style,
            tone_notes=request_payload.tone_notes.strip(),
            requested_page_count=request_payload.sanitized_page_count(),
            total_pages=total_pages,
            success_count=0,
            failure_count=0,
            root_path=str(root),
            manifest_path=str(manifest_path),
            result_path=str(result_path),
            bundle_size_bytes=directory_size_bytes(root),
            story_concept=story_concept,
            architect_output=architect_output,
            progress=52,
            step=2,
            logs=logs,
            pages=page_artifacts,
        )
        write_json_atomic(
            result_path,
            {
                "story_concept": story_concept,
                "architect_output": architect_output,
                "pages": [page.to_dict() for page in page_artifacts],
            },
        )
        write_json_atomic(manifest_path, run.to_dict())
        publish(status="planned", progress=52, step=2)
        return run

    parallelism = min(config.image_parallelism, max(1, len(page_artifacts)))
    log_line(logs, started_at, f"Dispatching image generation with {parallelism} parallel workers.")
    for artifact in page_artifacts:
        artifact.status = "in-progress"
        artifact.notes = "Image request is in flight."
        write_page_artifact(pages_dir, artifact)
    write_progress_files(status="generating")
    publish(status="generating", progress=36, step=2)

    page_index = {page.id: index for index, page in enumerate(page_artifacts)}
    completed_count = 0
    with ThreadPoolExecutor(max_workers=parallelism, thread_name_prefix="comic-image") as executor:
        futures = {
            executor.submit(
                generate_prepared_page_artifact,
                artifact=artifact,
                pages_dir=pages_dir,
                config=config,
                started_at=started_at,
                logs=logs,
            ): artifact.id
            for artifact in page_artifacts
        }
        for future in as_completed(futures):
            completed_count += 1
            artifact_id = futures[future]
            try:
                page_artifacts[page_index[artifact_id]] = future.result()
            except Exception as exc:
                failed_artifact = mark_page_artifact_failed(
                    artifact=page_artifacts[page_index[artifact_id]],
                    error_text=str(exc),
                    pages_dir=pages_dir,
                )
                page_artifacts[page_index[artifact_id]] = failed_artifact
                log_line(logs, started_at, f"{failed_artifact.id.replace('-', ' ').title()} failed unexpectedly: {exc}")
            write_progress_files(status="generating")
            progress = 36 + int((completed_count / max(total_pages, 1)) * 48)
            publish(status="generating", progress=min(progress, 92), step=2)

    success_count = sum(1 for page in page_artifacts if page.status == "success")
    failure_count = max(0, len(page_artifacts) - success_count)
    status = resolve_run_status(success_count=success_count, total_pages=len(page_artifacts))
    log_line(
        logs,
        started_at,
        f"Run finished with {success_count}/{len(page_artifacts)} successful pages.",
    )

    run = StudioRunArtifact(
        run_id=run_id,
        created_at=created_at.isoformat(timespec="seconds"),
        elapsed_seconds=round(time.monotonic() - started_at, 2),
        status=status,
        title=title,
        series_name=series_name,
        source_text=request_payload.source_text.strip(),
        audience=request_payload.audience,
        output_language=request_payload.output_language,
        workflow_preset=request_payload.workflow_preset,
        comic_style=request_payload.comic_style,
        tone_notes=request_payload.tone_notes.strip(),
        requested_page_count=request_payload.sanitized_page_count(),
        total_pages=total_pages,
        success_count=success_count,
        failure_count=failure_count,
        root_path=str(root),
        manifest_path=str(manifest_path),
        result_path=str(result_path),
        bundle_size_bytes=0,
        story_concept=story_concept,
        architect_output=architect_output,
        progress=100 if status != "failed" else 42,
        step=4 if status != "failed" else 1,
        logs=logs,
        pages=page_artifacts,
    )

    write_json_atomic(
        result_path,
        {
            "story_concept": story_concept,
            "architect_output": architect_output,
            "pages": [page.to_dict() for page in page_artifacts],
        },
    )
    write_json_atomic(manifest_path, run.to_dict())
    publish(status=status if status != "completed" else "generating", progress=94, step=3)

    bundle_size_bytes = directory_size_bytes(root)
    run.bundle_size_bytes = bundle_size_bytes
    write_json_atomic(manifest_path, run.to_dict())
    publish(status=status, progress=100 if status != "failed" else 42, step=4 if status != "failed" else 1)
    return run


def run_story_concept_agent(
    request_payload: StudioRequest,
    config: WorkflowConfig,
) -> str:
    user_prompt = (
        "让兩個商戰漫畫主人公交互討論的風格不帶有商業IP，以漫画的形式，带领读者由浅入深地学习并了解以下内容的主要观点：\n\n"
        f"{request_payload.source_text.strip()}\n\n"
        f"补充要求：目标读者是 {request_payload.audience}。"
        f" 输出语言偏好：{request_payload.output_language}。"
        f" 风格预设：{request_payload.workflow_preset} / {request_payload.comic_style}。"
        f" 语气备注：{request_payload.tone_notes.strip() or DEFAULT_TONE_NOTES}"
    )
    system_prompt = "你是一位专业的漫画编剧，擅长用商業風格的漫畫来讲解知识。"
    return call_planning_agent(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        config=config,
    )


def run_manga_architect_agent(
    request_payload: StudioRequest,
    story_concept: str,
    config: WorkflowConfig,
) -> dict[str, Any]:
    user_prompt = (
        "以下是漫画编剧提供的故事概念：\n\n"
        f"{story_concept}\n\n"
        "请基于以上故事概念，分析并告知这个漫画学习读本要划分为多少页比较合适，每页的内容是什么。"
        "每页内容必须用中文详细描述，包括对话内容。\n\n"
        f"优先控制在 {request_payload.sanitized_page_count()} 页左右，并确保内容适配 {request_payload.audience}。\n\n"
        "同时，请为这个漫画系列生成一个简短的英文名称（用下划线连接单词，例如：learn_python_basics、understanding_gravity、math_adventures）。"
        "这个名称应该基于主题内容，简洁明了。\n\n"
        "请严格返回以下 JSON 格式：\n"
        "{\n"
        ' "series_name": "topic_name_here",\n'
        ' "total_pages": 5,\n'
        ' "pages_list": [\n'
        ' {"page_num": 1, "content": "详细的中文场景描述和对话内容..."},\n'
        ' {"page_num": 2, "content": "详细的中文场景描述和对话内容..."}\n'
        " ]\n"
        "}"
    )
    system_prompt = (
        "你是一位漫画主编，必须且仅能输出标准的 JSON 数据，严禁输出任何文字说明。"
        "series_name 必须是英文，用下划线连接，简洁明了。"
        "pages_list 中的 content 必须是详细的中文描述。"
    )
    raw_output = call_planning_agent(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        config=config,
    )
    return parse_architect_json(raw_output)


def prepare_page_artifact(
    page_data: dict[str, Any],
    request_payload: StudioRequest,
    series_name: str,
    pages_dir: Path,
    prompts_dir: Path,
    config: WorkflowConfig,
    started_at: float,
    logs: list[list[str]],
) -> StudioPageArtifact:
    page_number = int(page_data.get("page_num") or 1)
    script = normalize_whitespace(str(page_data.get("content") or "")).strip()
    total_pages = int(page_data.get("total_pages") or request_payload.sanitized_page_count())
    prompt = build_image_prompt(
        page_number=page_number,
        total_pages=total_pages,
        content=script,
        request_payload=request_payload,
        image_size=config.image_size,
        comic_title=request_payload.resolved_title(),
    )
    prompt_path = prompts_dir / f"{page_number:02d}-page-{series_name}.md"
    write_text_atomic(
        prompt_path,
        build_prompt_markdown(
            page_number=page_number,
            total_pages=total_pages,
            series_name=series_name,
            script=script,
            prompt=prompt,
        ),
    )
    log_line(logs, started_at, f"Saved prompt file for page {page_number:02d}.")

    artifact = StudioPageArtifact(
        id=f"page-{page_number:02d}",
        page_number=page_number,
        title=build_page_title(script, page_number),
        excerpt=build_page_excerpt(script),
        script=script,
        notes="Prompt saved; waiting for image worker.",
        filename=f"{series_name}_manga_{page_number}.png",
        image_path=str(pages_dir / f"{series_name}_manga_{page_number}.png"),
        public_url=None,
        status="queued",
        prompt=prompt,
        prompt_path=str(prompt_path),
        mime_type="image/png",
        text_response="",
    )
    write_page_artifact(pages_dir, artifact)
    return artifact


def generate_prepared_page_artifact(
    artifact: StudioPageArtifact,
    pages_dir: Path,
    config: WorkflowConfig,
    started_at: float,
    logs: list[list[str]],
) -> StudioPageArtifact:
    page_number = artifact.page_number
    max_attempts = 1 + config.image_retry_attempts
    last_error = ""
    text_response = ""
    log_line(logs, started_at, f"Page {page_number:02d} image request started.")

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            log_line(logs, started_at, f"Page {page_number:02d} retry {attempt - 1}/{config.image_retry_attempts} started.")
        try:
            response_json = call_image_generation(prompt=artifact.prompt, config=config)
            image_bytes, mime_type, text_response = extract_image_payload(response_json)
            if not image_bytes:
                last_error = "No image generated from API"
                log_line(logs, started_at, f"Page {page_number:02d} returned no image payload.")
                if attempt < max_attempts:
                    sleep_before_retry(attempt)
                    continue
                break

            file_name = artifact.filename or f"page_{page_number}.png"
            image_path = pages_dir / file_name
            write_bytes_atomic(image_path, image_bytes)
            retry_note = f" after {attempt} attempts" if attempt > 1 else ""
            log_line(logs, started_at, f"Page {page_number:02d} generated and saved locally{retry_note}.")
            artifact = StudioPageArtifact(
                id=f"page-{page_number:02d}",
                page_number=page_number,
                title=artifact.title,
                excerpt=artifact.excerpt,
                script=artifact.script,
                notes="Image generated and saved in the local project folder.",
                filename=file_name,
                image_path=str(image_path),
                public_url=None,
                status="success",
                prompt=artifact.prompt,
                prompt_path=artifact.prompt_path,
                mime_type=mime_type,
                text_response=text_response,
            )
            write_page_artifact(pages_dir, artifact)
            return artifact
        except WorkflowExecutionError as exc:
            last_error = str(exc)
            log_line(logs, started_at, f"Page {page_number:02d} failed attempt {attempt}/{max_attempts}: {exc}")
            if attempt >= max_attempts or not is_retriable_generation_error(last_error):
                break
            sleep_before_retry(attempt)

    artifact = StudioPageArtifact(
        id=f"page-{page_number:02d}",
        page_number=page_number,
        title=artifact.title,
        excerpt=artifact.excerpt,
        script=artifact.script,
        notes="Image generation failed before a local image file was saved.",
        filename=None,
        image_path="",
        public_url=None,
        status="failed",
        prompt=artifact.prompt,
        prompt_path=artifact.prompt_path,
        mime_type="image/png",
        text_response=text_response,
        error=last_error or "Image generation failed",
    )

    write_page_artifact(pages_dir, artifact)
    return artifact


def is_retriable_generation_error(message: str) -> bool:
    lowered = message.lower()
    non_retriable_markers = ("http 400", "invalid size", "user_error", "invalid_request")
    if any(marker in lowered for marker in non_retriable_markers):
        return False
    retriable_markers = (
        "http 408",
        "http 409",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "timed out",
        "timeout",
        "stream disconnected",
        "remote end closed",
        "connection reset",
        "nodename nor servname",
        "temporary failure",
    )
    return any(marker in lowered for marker in retriable_markers)


def sleep_before_retry(attempt: int) -> None:
    time.sleep(min(20, 3 * attempt))


def write_page_artifact(pages_dir: Path, artifact: StudioPageArtifact) -> None:
    path = pages_dir / f"page-{artifact.page_number:02d}.json"
    write_json_atomic(path, artifact.to_dict())


def mark_page_artifact_failed(
    artifact: StudioPageArtifact,
    error_text: str,
    pages_dir: Path,
) -> StudioPageArtifact:
    failed_artifact = StudioPageArtifact(
        id=artifact.id,
        page_number=artifact.page_number,
        title=artifact.title,
        excerpt=artifact.excerpt,
        script=artifact.script,
        notes="Image generation worker failed before a local image file was saved.",
        filename=None,
        image_path="",
        public_url=None,
        status="failed",
        prompt=artifact.prompt,
        prompt_path=artifact.prompt_path,
        mime_type="image/png",
        text_response=artifact.text_response,
        error=error_text,
    )
    write_page_artifact(pages_dir, failed_artifact)
    return failed_artifact


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_text_atomic(path: Path, content: str) -> None:
    temp_path = temp_sibling_path(path)
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def write_bytes_atomic(path: Path, content: bytes) -> None:
    temp_path = temp_sibling_path(path)
    temp_path.write_bytes(content)
    temp_path.replace(path)


def temp_sibling_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.{threading.get_ident()}.{time.monotonic_ns()}.tmp")


def build_image_prompt(
    page_number: int,
    total_pages: int,
    content: str,
    request_payload: StudioRequest,
    image_size: str = DEFAULT_COMIC_IMAGE_SIZE,
    comic_title: str = "",
) -> str:
    first_page_title_instruction = ""
    if page_number == 1:
        resolved_title = comic_title.strip() or request_payload.resolved_title()
        first_page_title_instruction = (
            f"- 第一页必须包含醒目的漫画标题：{resolved_title}\n"
            "- 标题应作为封面/开篇标题清晰排版，不要遮挡主要角色或关键画面\n"
        )

    return (
        "请为以下漫画页面生成一张图片。\n\n"
        f"当前页码：第 {page_number} 页（共 {total_pages} 页）\n"
        f"本页情节：{content}\n\n"
        "要求：\n\n"
        f"{first_page_title_instruction}"
        f"- 风格：商業漫画风格，清晰的线条，彩色，并偏向 {request_payload.comic_style}\n"
        f"- 分辨率：{image_size}（3:4 竖版漫画页面，宽高均为 16 的倍数）\n"
        f"- 目标读者：{request_payload.audience}\n"
        f"- 输出语言：{request_payload.output_language}\n"
        "- 重要：所有对话气泡和文字必须使用中文\n"
        "- 对话气泡中的文字要清晰可读，字体适中\n"
        "- 根据情节内容添加相应的中文对话\n"
        "- 生动有趣，适合教育用途\n"
        f"- 语气提示：{request_payload.tone_notes.strip() or DEFAULT_TONE_NOTES}\n"
        "- 背景要与情节相符"
    )


def call_planning_agent(
    user_prompt: str,
    system_prompt: str,
    config: WorkflowConfig,
) -> str:
    headers = {
        "Authorization": f"Bearer {config.planning_api_key}",
    }

    payload = {
        "model": config.planning_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": config.planning_max_tokens,
    }
    response_json = http_post_json(
        url=openai_compatible_url(config.planning_base_url, "/chat/completions"),
        headers=headers,
        payload=payload,
        timeout_seconds=config.request_timeout_seconds,
        error_label="Planning request failed",
    )

    try:
        content = response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WorkflowExecutionError(
            f"Unexpected planning response shape: {exc}"
        ) from exc

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content).strip()


def call_image_generation(prompt: str, config: WorkflowConfig) -> dict[str, Any]:
    payload = {
        "model": config.image_model,
        "prompt": prompt,
        "size": config.image_size,
        "response_format": "b64_json",
    }
    return http_post_json(
        url=openai_compatible_url(config.image_base_url, "/images/generations"),
        headers={"Authorization": f"Bearer {config.image_api_key}"},
        payload=payload,
        timeout_seconds=config.request_timeout_seconds,
        error_label="Image generation request failed",
    )


def extract_image_payload(response_json: dict[str, Any]) -> tuple[bytes | None, str, str]:
    openai_data = response_json.get("data")
    if isinstance(openai_data, list) and openai_data:
        first = openai_data[0]
        if isinstance(first, dict):
            image_base64 = first.get("b64_json")
            revised_prompt = str(first.get("revised_prompt") or "")
            if image_base64:
                try:
                    return base64.b64decode(str(image_base64)), "image/png", revised_prompt
                except (ValueError, TypeError) as exc:
                    raise WorkflowExecutionError(f"Failed to decode image payload: {exc}") from exc
            if first.get("url"):
                raise WorkflowExecutionError(
                    "Image API returned a URL instead of base64 data. Set the endpoint to support response_format=b64_json."
                )

    candidates = response_json.get("candidates") or []
    if not candidates:
        return None, "image/png", ""

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    image_base64 = None
    mime_type = "image/png"
    text_response = ""

    for part in parts:
        if not isinstance(part, dict):
            continue
        inline_data = part.get("inlineData")
        if isinstance(inline_data, dict) and inline_data.get("data"):
            image_base64 = str(inline_data["data"])
            mime_type = str(inline_data.get("mimeType") or mime_type)
        if part.get("text"):
            text_response = str(part["text"])

    if not image_base64 and len(parts) > 1:
        second = parts[1]
        if isinstance(second, dict):
            inline_data = second.get("inlineData")
            if isinstance(inline_data, dict) and inline_data.get("data"):
                image_base64 = str(inline_data["data"])
                mime_type = str(inline_data.get("mimeType") or mime_type)

    if not image_base64:
        return None, mime_type, text_response

    try:
        return base64.b64decode(image_base64), mime_type, text_response
    except (ValueError, TypeError) as exc:
        raise WorkflowExecutionError(f"Failed to decode image payload: {exc}") from exc


def parse_architect_json(raw_output: str) -> dict[str, Any]:
    cleaned = re.sub(r"```json|```", "", raw_output).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise WorkflowExecutionError(
            f"Failed to parse architect JSON: {exc.msg}"
        ) from exc

    if not isinstance(parsed, dict):
        raise WorkflowExecutionError("Architect output must be a JSON object.")
    return parsed


def sanitize_series_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return cleaned or "manga_series"


def build_page_title(script: str, page_number: int) -> str:
    chunks = [
        chunk.strip("：:，,。.!? ")
        for chunk in re.split(r"[。！？\n]", script)
        if chunk.strip()
    ]
    if not chunks:
        return f"Page {page_number}"
    title = chunks[0]
    return title[:20]


def build_page_excerpt(script: str, limit: int = 120) -> str:
    text = normalize_whitespace(script)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def resolve_run_status(success_count: int, total_pages: int) -> str:
    if success_count <= 0:
        return "failed"
    if success_count < total_pages:
        return "partial"
    return "completed"


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def sort_pages_for_display(pages: list[StudioPageArtifact]) -> list[StudioPageArtifact]:
    return sorted(
        pages,
        key=lambda page: (0 if page.status == "failed" else 1, page.page_number),
    )


def build_analysis_markdown(request_payload: StudioRequest, story_concept: str) -> str:
    return (
        "# Analysis\n\n"
        f"- Audience: {request_payload.audience}\n"
        f"- Output language: {request_payload.output_language}\n"
        f"- Workflow preset: {request_payload.workflow_preset}\n"
        f"- Comic style: {request_payload.comic_style}\n"
        f"- Requested pages: {request_payload.sanitized_page_count()}\n\n"
        "## Source Text\n\n"
        f"{request_payload.source_text.strip()}\n\n"
        "## Story Concept\n\n"
        f"{story_concept}\n"
    )


def build_storyboard_markdown(
    title: str,
    series_name: str,
    pages_payload: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Series slug: `{series_name}`",
        "",
        "## Storyboard",
        "",
    ]
    for page in pages_payload:
        page_num = int(page.get("page_num") or 1)
        content = str(page.get("content") or "").strip()
        lines.extend(
            [
                f"### Page {page_num:02d}",
                content,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_prompt_markdown(
    page_number: int,
    total_pages: int,
    series_name: str,
    script: str,
    prompt: str,
) -> str:
    return (
        "---\n"
        f"page_number: {page_number}\n"
        f"total_pages: {total_pages}\n"
        f"series_name: {series_name}\n"
        "---\n\n"
        "## Page Script\n\n"
        f"{script}\n\n"
        "## Final Prompt\n\n"
        f"{prompt}\n"
    )


def log_line(logs: list[list[str]], started_at: float, message: str) -> None:
    elapsed = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed, 60)
    logs.append([f"{minutes:02d}:{seconds:02d}", message])


def directory_size_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def humanize_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"

    value = float(size)
    units = ("KB", "MB", "GB")
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{size} B"


def openai_compatible_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    if normalized_base.endswith("/v1"):
        return f"{normalized_base}{path}"
    return f"{normalized_base}/v1{path}"


def http_post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
    error_label: str,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json", **headers}
    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset("utf-8")
            body = response.read().decode(charset)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WorkflowExecutionError(f"{error_label}: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise WorkflowExecutionError(f"{error_label}: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise WorkflowExecutionError(
            f"{error_label}: timed out after {timeout_seconds} seconds"
        ) from exc
    except (http.client.HTTPException, ConnectionError, OSError) as exc:
        raise WorkflowExecutionError(f"{error_label}: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WorkflowExecutionError(f"{error_label}: invalid JSON response") from exc
    if not isinstance(parsed, dict):
        raise WorkflowExecutionError(f"{error_label}: expected JSON object response")
    return parsed


def http_post_binary(
    url: str,
    headers: dict[str, str],
    payload: bytes,
    timeout_seconds: int,
    error_label: str,
) -> None:
    req = request.Request(
        url=url,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds):
            return
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WorkflowExecutionError(f"{error_label}: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise WorkflowExecutionError(f"{error_label}: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise WorkflowExecutionError(
            f"{error_label}: timed out after {timeout_seconds} seconds"
        ) from exc
