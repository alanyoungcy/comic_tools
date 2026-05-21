from pathlib import Path

from comicpublish.pipeline import generate_comic_bundle, slugify


def test_slugify() -> None:
    assert slugify("The Neon Alley Case!") == "the-neon-alley-case"


def test_generate_comic_bundle(tmp_path: Path) -> None:
    root = generate_comic_bundle(
        title="Sky Harbor",
        premise="A courier smuggles a seed through a floating war zone.",
        genre="dieselpunk",
        pages=3,
        output_dir=tmp_path,
    )

    assert root.exists()
    assert (root / "manifest.json").exists()
    assert (root / "story_outline.md").exists()
    assert (root / "pages" / "page-01.md").exists()
    assert (root / "download" / "sky-harbor.zip").exists()
