"""Despliegue instantáneo de previews mediante la API REST de Vercel (v13)."""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from typing import Any

import httpx

from config import Settings
from src.http_utils import ExternalAPIError, request_json

log = logging.getLogger(__name__)

VERCEL_API = "https://api.vercel.com"


def slugify(name: str, place_id: str, prefix: str = "", max_len: int = 48) -> str:
    """'Barbería El Rey' -> 'barberia-el-rey-3f9a1c' (válido como nombre de proyecto Vercel)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "negocio"
    suffix = hashlib.sha1(place_id.encode()).hexdigest()[:6]
    head = f"{prefix}{base}"[: max_len - len(suffix) - 1].rstrip("-")
    return f"{head}-{suffix}"


class VercelDeployer:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            base_url=VERCEL_API,
            timeout=60,
        )
        self._headers = {"Authorization": f"Bearer {settings.vercel_token.get_secret_value()}"}
        self._params = {"teamId": settings.vercel_team_id} if settings.vercel_team_id else {}

    def deploy(self, html: str, slug: str) -> str:
        """Publica ``index.html`` como sitio estático y devuelve la URL pública."""
        payload: dict[str, Any] = {
            "name": slug,
            "target": "production",  # producción => alias público <slug>.vercel.app
            "files": [{"file": "index.html", "data": html}],
            "projectSettings": {
                "framework": None,
                "buildCommand": None,
                "installCommand": None,
                "outputDirectory": None,
            },
        }
        data = request_json(
            self._client, "POST", "/v13/deployments",
            service="vercel", headers=self._headers,
            params={**self._params, "skipAutoDetectionConfirmation": "1"}, json=payload,
        )
        deployment_id: str = data["id"]
        log.info("Deployment %s creado (%s)", deployment_id, data.get("readyState"))
        data = self._wait_until_ready(deployment_id, data)
        return self._public_url(data)

    def _wait_until_ready(self, deployment_id: str, data: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self._settings.vercel_ready_timeout_s
        delay = 2.0
        while data.get("readyState") not in {"READY", "ERROR", "CANCELED"}:
            if time.monotonic() > deadline:
                raise ExternalAPIError("vercel", f"Timeout esperando deployment {deployment_id}")
            time.sleep(delay)
            delay = min(delay * 1.5, 10)
            data = request_json(
                self._client, "GET", f"/v13/deployments/{deployment_id}",
                service="vercel", headers=self._headers, params=self._params,
            )
        if data["readyState"] != "READY":
            raise ExternalAPIError("vercel", f"Deployment {deployment_id} terminó en {data['readyState']}")
        return data

    @staticmethod
    def _public_url(data: dict[str, Any]) -> str:
        aliases: list[str] = data.get("alias") or []
        # Preferimos el alias más corto (p.ej. <slug>.vercel.app) sobre la URL con hash.
        host = min(aliases, key=len) if aliases else data["url"]
        return host if host.startswith("http") else f"https://{host}"
