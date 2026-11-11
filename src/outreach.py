"""Mensajería WhatsApp a través de Evolution API (v2)."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

from config import TEMPLATES_DIR, Settings
from src.http_utils import ExternalAPIError, request_json

log = logging.getLogger(__name__)

MESSAGE_TEMPLATE_PATH = TEMPLATES_DIR / "outreach_message.txt"


def render_message(name: str, preview_url: str, *, footer: str = "", sender: str = "") -> str:
    template = MESSAGE_TEMPLATE_PATH.read_text(encoding="utf-8").strip()
    msg = template.format(name=name.strip(), preview_url=preview_url)
    if sender:
        msg += f"\n\n— {sender}"
    if footer:
        msg += f"\n\n{footer}"
    return msg


class EvolutionClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._instance = settings.evolution_instance
        self._client = client or httpx.Client(
            base_url=str(settings.evolution_api_url).rstrip("/"),
            timeout=30,
        )
        self._headers = {"apikey": settings.evolution_api_key.get_secret_value()}

    def connection_state(self) -> str:
        data = request_json(
            self._client, "GET", f"/instance/connectionState/{self._instance}",
            service="evolution", headers=self._headers,
        )
        return str((data.get("instance") or data).get("state", "unknown"))

    def has_whatsapp(self, number: str) -> bool:
        """Consulta si el número tiene WhatsApp. Si la consulta falla, no bloquea el envío."""
        try:
            data = request_json(
                self._client, "POST", f"/chat/whatsappNumbers/{self._instance}",
                service="evolution", headers=self._headers, json={"numbers": [number]},
            )
        except ExternalAPIError as exc:
            log.warning("No se pudo verificar %s: %s", number, exc)
            return True
        if isinstance(data, list) and data:
            return bool(data[0].get("exists", True))
        return True

    def send_text(self, number: str, text: str) -> dict[str, object]:
        """POST /message/sendText/{instance}."""
        return request_json(
            self._client, "POST", f"/message/sendText/{self._instance}",
            service="evolution", headers=self._headers,
            json={"number": number, "text": text, "linkPreview": True},
        )


class Throttle:
    """Espera aleatoria (jitter) entre envíos consecutivos; no espera antes del primero."""

    def __init__(self, lo: float, hi: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self._lo, self._hi, self._sleep = lo, hi, sleep
        self._sent_any = False

    def wait(self) -> float:
        if not self._sent_any:
            self._sent_any = True
            return 0.0
        delay = random.uniform(self._lo, self._hi)
        log.info("Esperando %.0f s antes del siguiente envío…", delay)
        self._sleep(delay)
        return delay
