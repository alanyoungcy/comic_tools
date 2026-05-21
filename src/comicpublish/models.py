from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class PageSpec:
    page_number: int
    title: str
    beat: str
    visual_prompt: str
    dialogue_prompt: str


@dataclass(slots=True)
class ComicSpec:
    title: str
    premise: str
    genre: str
    pages: list[PageSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

