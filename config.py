"""Configuración central del pipeline (cargada desde variables de entorno / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT_DIR / "templates"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Anthropic -------------------------------------------------------
    anthropic_api_key: SecretStr = Field(..., alias="ANTHROPIC_API_KEY")
    # Claude 3.5 Sonnet fue retirado (oct-2025); su sucesor actual es Sonnet 5.5.
    anthropic_model: str = Field("claude-sonnet-5-5", alias="ANTHROPIC_MODEL")
    anthropic_max_tokens: int = Field(32000, alias="ANTHROPIC_MAX_TOKENS")

    # --- Google Places (API New) ----------------------------------------
    google_maps_api_key: SecretStr | None = Field(None, alias="GOOGLE_MAPS_API_KEY")
    places_language: str = Field("es", alias="PLACES_LANGUAGE")
    min_reviews: int = Field(5, alias="MIN_REVIEWS")

    # --- Vercel ------------------------------------------------------------
    vercel_token: SecretStr = Field(..., alias="VERCEL_TOKEN")
    vercel_team_id: str | None = Field(None, alias="VERCEL_TEAM_ID")
    vercel_project_prefix: str = Field("", alias="VERCEL_PROJECT_PREFIX")
    vercel_ready_timeout_s: int = Field(180, alias="VERCEL_READY_TIMEOUT_S")

    # --- Evolution API (WhatsApp) ---------------------------------------
    evolution_api_url: HttpUrl = Field("http://localhost:8080", alias="EVOLUTION_API_URL")  # type: ignore[assignment]
    evolution_api_key: SecretStr = Field(..., alias="EVOLUTION_API_KEY")
    evolution_instance: str = Field("outreach", alias="EVOLUTION_INSTANCE")
    verify_whatsapp_numbers: bool = Field(True, alias="VERIFY_WHATSAPP_NUMBERS")

    # --- Outreach ----------------------------------------------------------
    jitter_min_s: float = Field(60, alias="JITTER_MIN_S")
    jitter_max_s: float = Field(180, alias="JITTER_MAX_S")
    daily_send_cap: int = Field(30, alias="DAILY_SEND_CAP")
    sender_name: str = Field("", alias="SENDER_NAME")
    opt_out_footer: str = Field(
        "Si prefieres no recibir más mensajes, respóndeme \"no\" y no vuelvo a escribir.",
        alias="OPT_OUT_FOOTER",
    )

    # --- Persistencia / salida --------------------------------------------
    database_path: Path = Field(ROOT_DIR / "leads.db", alias="DATABASE_PATH")
    output_dir: Path = Field(ROOT_DIR / "output", alias="OUTPUT_DIR")
    max_attempts: int = Field(3, alias="MAX_ATTEMPTS")

    @field_validator("jitter_max_s")
    @classmethod
    def _jitter_order(cls, v: float, info) -> float:  # type: ignore[no-untyped-def]
        lo = info.data.get("jitter_min_s", 0)
        if v < lo:
            raise ValueError("JITTER_MAX_S debe ser >= JITTER_MIN_S")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
