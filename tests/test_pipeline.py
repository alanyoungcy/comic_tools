from comicpublish.pipeline import slugify


def test_slugify() -> None:
    assert slugify("The Neon Alley Case!") == "the-neon-alley-case"
