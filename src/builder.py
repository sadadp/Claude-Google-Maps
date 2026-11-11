"""Generador de landing pages con Claude (SDK oficial de Anthropic)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

import anthropic

from config import ROOT_DIR, TEMPLATES_DIR, Settings
from src.models import Business

log = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = TEMPLATES_DIR / "landing_system_prompt.md"
DESIGN_SKILL_DIR = ROOT_DIR / ".claude" / "skills" / "premium-web-design"
DESIGN_SKILL_FILES = ("SKILL.md", "design-tokens.md")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_HTML_RE = re.compile(r"<!DOCTYPE html>.*</html>", re.IGNORECASE | re.DOTALL)


class BuildError(RuntimeError):
    pass


def build_brief(biz: Business, language: str) -> dict[str, object]:
    """Datos estructurados que recibe Claude (el modelo no inventa el contacto)."""
    query = quote_plus(f"{biz.name}, {biz.address}")
    return {
        "language": language,
        "business_name": biz.name,
        "category": biz.category or "negocio local",
        "address": biz.address,
        "phone_display": biz.phone,
        "phone_e164": f"+{biz.phone_digits}",
        "whatsapp_url": f"https://wa.me/{biz.phone_digits}",
        "rating": biz.rating,
        "review_count": biz.review_count,
        "reviews": [r.model_dump(exclude_none=True) for r in biz.top_reviews],
        "opening_hours": biz.opening_hours,
        "maps_url": biz.maps_uri or f"https://www.google.com/maps/search/?api=1&query={query}",
        "map_embed_url": f"https://www.google.com/maps?q={query}&output=embed",
    }


def extract_html(text: str) -> str:
    match = _HTML_RE.search(text)
    if not match:
        raise BuildError("La respuesta del modelo no contiene un documento HTML completo")
    return match.group(0)


def validate_html(html: str, biz: Business) -> None:
    """Comprobaciones mínimas de que la página cumple el contrato."""
    required = {
        "Tailwind CDN": "cdn.tailwindcss.com",
        "botón WhatsApp": f"wa.me/{biz.phone_digits}",
        "enlace tel:": "tel:",
        "mapa embebido": "output=embed",
    }
    missing = [label for label, needle in required.items() if needle not in html]
    if missing:
        raise BuildError(f"HTML incompleto, falta: {', '.join(missing)}")


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip()
    return text


def load_system_prompt() -> str:
    """Contrato de la landing + guía de diseño premium (si la skill está instalada)."""
    parts = [SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")]
    guides = [
        _strip_frontmatter((DESIGN_SKILL_DIR / name).read_text(encoding="utf-8"))
        for name in DESIGN_SKILL_FILES
        if (DESIGN_SKILL_DIR / name).is_file()
    ]
    if guides:
        parts.append(
            "<design_guide>\nApply this design system to every visual and copy decision. "
            "Where it conflicts with the output contract or required sections above, the contract wins "
            "(e.g. skip logo bars, pricing tiers or FAQ the brief has no data for, and never invent testimonials).\n\n"
            + "\n\n".join(guides)
            + "\n</design_guide>"
        )
    return "\n\n".join(parts)


class SiteBuilder:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self._settings = settings
        # max_retries: el SDK reintenta 408/409/429/5xx y errores de conexión con backoff.
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(), max_retries=4
        )
        self._system = load_system_prompt()

    def generate(self, biz: Business, *, attempts: int = 2) -> str:
        brief = build_brief(biz, self._settings.places_language)
        user_msg = (
            "Build the landing page for this business. Brief (JSON):\n\n"
            f"<brief>\n{json.dumps(brief, ensure_ascii=False, indent=2)}\n</brief>"
        )
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                html = self._call(user_msg)
                validate_html(html, biz)
                return html
            except BuildError as exc:
                last_err = exc
                log.warning("Intento %d/%d de generación falló: %s", attempt, attempts, exc)
        raise BuildError(str(last_err))

    def _call(self, user_msg: str) -> str:
        try:
            # Streaming: evita timeouts HTTP con salidas largas (HTML completo).
            # `fallbacks="default"`: si el modelo declina, la API reintenta en otro modelo.
            with self._client.beta.messages.stream(
                model=self._settings.anthropic_model,
                max_tokens=self._settings.anthropic_max_tokens,
                # Prompt de sistema grande y estable: se cachea entre negocios del mismo lote.
                system=[{"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                message = stream.get_final_message()
        except anthropic.BadRequestError as exc:
            raise BuildError(f"Petición inválida a Claude: {exc.message}") from exc
        except anthropic.AuthenticationError as exc:
            raise BuildError("ANTHROPIC_API_KEY inválida") from exc
        except anthropic.APIStatusError as exc:
            raise BuildError(f"Error de API de Anthropic ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise BuildError(f"Sin conexión con la API de Anthropic: {exc}") from exc

        if message.stop_reason == "refusal":
            raise BuildError("El modelo rechazó la solicitud")
        if message.stop_reason == "max_tokens":
            raise BuildError("Salida truncada (max_tokens); aumenta ANTHROPIC_MAX_TOKENS")
        text = "".join(b.text for b in message.content if b.type == "text")
        return extract_html(text)


def save_html(html: str, output_dir: Path, slug: str) -> Path:
    path = output_dir / slug / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
