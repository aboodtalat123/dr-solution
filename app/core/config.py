from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv(encoding="utf-8-sig")


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Dr. Solution.")
    app_version: str = os.getenv("APP_VERSION", "3.2.0")
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = _as_bool("DEBUG", False)
    require_user_api_key: bool = _as_bool("REQUIRE_USER_API_KEY", False)

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip()
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

    max_upload_mb: int = _as_int("MAX_UPLOAD_MB", 15)
    max_text_chars: int = _as_int("MAX_TEXT_CHARS", 600_000)
    max_images: int = _as_int("MAX_IMAGES", 200)
    max_pages: int = _as_int("MAX_PAGES", 200)
    analysis_batch_size: int = _as_int("ANALYSIS_BATCH_SIZE", 4)
    request_timeout_seconds: int = _as_int("REQUEST_TIMEOUT_SECONDS", 180)

    video_max_duration_seconds: int = _as_int("VIDEO_MAX_DURATION_SECONDS", 7200)
    video_max_playlist_items: int = _as_int("VIDEO_MAX_PLAYLIST_ITEMS", 3)
    video_max_segments: int = _as_int("VIDEO_MAX_SEGMENTS", 12)
    video_max_segment_seconds: int = _as_int("VIDEO_MAX_SEGMENT_SECONDS", 120)
    video_scene_threshold: float = _as_float("VIDEO_SCENE_THRESHOLD", 27.0)
    video_min_scene_seconds: int = _as_int("VIDEO_MIN_SCENE_SECONDS", 10)
    video_enable_scene_detection: bool = _as_bool("VIDEO_ENABLE_SCENE_DETECTION", True)
    video_enable_whisper: bool = _as_bool("VIDEO_ENABLE_WHISPER", True)
    video_whisper_max_duration_seconds: int = _as_int("VIDEO_WHISPER_MAX_DURATION_SECONDS", 1800)
    whisper_model: str = os.getenv("WHISPER_MODEL", "tiny").strip()
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def allowed_origins(self) -> list[str]:
        raw = os.getenv("ALLOWED_ORIGINS", "").strip()
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def provider_is_configured(self, provider: str) -> bool:
        keys = {
            "gemini": self.gemini_api_key,
            "claude": self.anthropic_api_key,
            "deepseek": self.deepseek_api_key,
        }
        return bool(keys.get(provider, ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
