from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from comicpublish.models import ComicSpec, PageSpec


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "comic"


def build_comic_spec(title: str, premise: str, genre: str, pages: int) -> ComicSpec:
    comic_pages: list[PageSpec] = []
    beats = [
        "Introduce the world and the central tension.",
        "Complicate the goal with a surprising obstacle.",
        "Escalate the stakes through conflict or revelation.",
        "Force a hard choice that changes the hero.",
        "Deliver the turning point and aftermath.",
    ]

    for index in range(1, pages + 1):
        beat = beats[min(index - 1, len(beats) - 1)]
        comic_pages.append(
            PageSpec(
                page_number=index,
                title=f"Page {index}",
                beat=beat,
                visual_prompt=(
                    f"{genre} comic page {index}. Premise: {premise} "
                    f"Use dynamic framing, readable panel flow, and expressive characters."
                ),
                dialogue_prompt=(
                    f"Write concise dialogue and captions for page {index} of '{title}'. "
                    f"Story beat: {beat}"
                ),
            )
        )

    return ComicSpec(title=title, premise=premise, genre=genre, pages=comic_pages)


def render_outline(spec: ComicSpec) -> str:
    lines = [
        f"# {spec.title}",
        "",
        f"Genre: {spec.genre}",
        "",
        "## Premise",
        spec.premise,
        "",
        "## Page Plan",
    ]
    for page in spec.pages:
        lines.extend(
            [
                f"### {page.title}",
                f"- Beat: {page.beat}",
                f"- Visual skill prompt: {page.visual_prompt}",
                f"- Dialogue skill prompt: {page.dialogue_prompt}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_page(page: PageSpec) -> str:
    return (
        f"# {page.title}\n\n"
        f"## Story Beat\n{page.beat}\n\n"
        f"## Visual Prompt\n{page.visual_prompt}\n\n"
        f"## Dialogue Prompt\n{page.dialogue_prompt}\n"
    )


def generate_comic_bundle(
    title: str,
    premise: str,
    genre: str,
    pages: int,
    output_dir: Path,
) -> Path:
    spec = build_comic_spec(title=title, premise=premise, genre=genre, pages=pages)
    slug = slugify(title)
    root = output_dir / slug
    pages_dir = root / "pages"
    download_dir = root / "download"

    pages_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    (root / "manifest.json").write_text(
        json.dumps(spec.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (root / "story_outline.md").write_text(render_outline(spec), encoding="utf-8")

    for page in spec.pages:
        filename = pages_dir / f"page-{page.page_number:02d}.md"
        filename.write_text(render_page(page), encoding="utf-8")

    archive_path = download_dir / f"{slug}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path == archive_path or path.is_dir():
                continue
            archive.write(path, arcname=path.relative_to(root))

    return root

