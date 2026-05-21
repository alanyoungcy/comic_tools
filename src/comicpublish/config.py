from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_IMAGE_SIZE = "1248x1664"


class ConfigError(ValueError):
    """Raised when required workflow configuration is missing."""


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    planning_api_key: str
    planning_model: str
    planning_base_url: str
    planning_max_tokens: int
    image_api_key: str
    image_model: str
    image_base_url: str
    image_size: str
    image_parallelism: int
    image_retry_attempts: int
    output_dir: Path
    request_timeout_seconds: int

    def validate(self) -> None:
        missing: list[str] = []
        if not self.planning_base_url:
            missing.append("PLANNING_BASE_URL")
        if not self.planning_api_key:
            missing.append("PLANNING_API_KEY")
        if not self.planning_model:
            missing.append("PLANNING_MODEL")
        if not self.image_base_url:
            missing.append("IMAGE_BASE_URL")
        if not self.image_api_key:
            missing.append("IMAGE_API_KEY")
        if not self.image_model:
            missing.append("IMAGE_MODEL")

        if missing:
            raise ConfigError(
                "Missing workflow configuration: " + ", ".join(missing)
            )
        validate_image_size(self.image_size)
        if not 1 <= self.image_parallelism <= 3:
            raise ConfigError("IMAGE_PARALLELISM must be between 1 and 3")
        if not 0 <= self.image_retry_attempts <= 5:
            raise ConfigError("IMAGE_RETRY_ATTEMPTS must be between 0 and 5")


def load_env_file(path: Path = DEFAULT_ENV_PATH) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def load_workflow_config() -> WorkflowConfig:
    load_env_file()

    output_dir_raw = os.environ.get("COMICPUBLISH_OUTPUT_DIR", "build").strip() or "build"
    output_dir = Path(output_dir_raw)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    return WorkflowConfig(
        planning_api_key=os.environ.get("PLANNING_API_KEY", "").strip(),
        planning_model=os.environ.get("PLANNING_MODEL", "gemini-3.1-pro").strip(),
        planning_base_url=os.environ.get("PLANNING_BASE_URL", "https://jmrai.net").rstrip("/"),
        planning_max_tokens=int(
            os.environ.get("PLANNING_MAX_TOKENS", "12000").strip() or "12000"
        ),
        image_api_key=os.environ.get("IMAGE_API_KEY", "").strip(),
        image_model=os.environ.get("IMAGE_MODEL", "gpt-image-2").strip(),
        image_base_url=os.environ.get("IMAGE_BASE_URL", "https://jmrai.net").rstrip("/"),
        image_size=os.environ.get("IMAGE_SIZE", DEFAULT_IMAGE_SIZE).strip() or DEFAULT_IMAGE_SIZE,
        image_parallelism=int(os.environ.get("IMAGE_PARALLELISM", "3").strip() or "3"),
        image_retry_attempts=int(os.environ.get("IMAGE_RETRY_ATTEMPTS", "2").strip() or "2"),
        output_dir=output_dir,
        request_timeout_seconds=int(
            os.environ.get("REQUEST_TIMEOUT_SECONDS", "300").strip() or "300"
        ),
    )


def workflow_env_status() -> tuple[bool, str]:
    try:
        config = load_workflow_config()
        config.validate()
    except ConfigError as exc:
        return False, str(exc)
    return True, f"Configured · {config.planning_model} / {config.image_model}"


def validate_image_size(value: str) -> None:
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip())
    if not match:
        raise ConfigError("IMAGE_SIZE must use WIDTHxHEIGHT format, for example 1248x1664")

    width = int(match.group(1))
    height = int(match.group(2))
    if width % 16 or height % 16:
        raise ConfigError("IMAGE_SIZE width and height must both be divisible by 16")
    if width >= height:
        raise ConfigError("IMAGE_SIZE must be portrait for comic pages; use 1248x1664")
