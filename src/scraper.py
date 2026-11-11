"""Módulo de ingesta.

Dos fuentes intercambiables que producen ``Business`` normalizados:

* ``PlacesScraper``: Google Places API (New) — ``places:searchText`` con FieldMask.
* ``load_scraper_export``: importa la salida JSON/CSV de
  gosom/google-maps-scraper o omkarcloud/google-maps-scraper.

Ambas aplican el mismo filtro estricto (``qualifies``): sin sitio web,
con teléfono y con al menos ``MIN_REVIEWS`` reseñas.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import httpx

from config import Settings
from src.http_utils import ExternalAPIError, request_json
from src.models import Business, Review

log = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.internationalPhoneNumber",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.websiteUri",
        "places.reviews",
        "places.regularOpeningHours.weekdayDescriptions",
        "places.googleMapsUri",
        "places.primaryTypeDisplayName",
        "nextPageToken",
    ]
)
MAX_PAGES = 3  # la API devuelve como máximo 60 resultados (3 x 20)


# ---------------------------------------------------------------------------
# Filtro y selección de reseñas
# ---------------------------------------------------------------------------
def qualifies(biz: Business, min_reviews: int) -> bool:
    """Filtro estricto: sin web, con teléfono y >= min_reviews reseñas."""
    if biz.website and biz.website.strip():
        return False
    if len(biz.phone_digits) < 8:
        return False
    return biz.review_count >= min_reviews


def pick_top_reviews(reviews: Iterable[Review], n: int = 3) -> list[Review]:
    """Las ``n`` reseñas de 5 estrellas más sustanciosas (texto más largo)."""
    five = [r for r in reviews if r.rating == 5 and len(r.text.strip()) >= 15]
    five.sort(key=lambda r: len(r.text), reverse=True)
    return five[:n]


# ---------------------------------------------------------------------------
# Google Places API (New)
# ---------------------------------------------------------------------------
class PlacesScraper:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if settings.google_maps_api_key is None:
            raise ValueError("GOOGLE_MAPS_API_KEY es obligatorio para la fuente 'places'")
        self._settings = settings
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_maps_api_key.get_secret_value(),
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        }

    def search(self, niche: str, location: str) -> Iterator[Business]:
        """Itera los negocios que cumplen el filtro para '<niche> en <location>'."""
        query = f"{niche} en {location}" if self._settings.places_language == "es" else f"{niche} in {location}"
        body: dict[str, Any] = {
            "textQuery": query,
            "pageSize": 20,
            "languageCode": self._settings.places_language,
        }
        for page in range(MAX_PAGES):
            data = request_json(
                self._client, "POST", PLACES_SEARCH_URL,
                service="google-places", headers=self._headers, json=body,
            )
            places = data.get("places", [])
            log.info("Places página %d: %d resultados", page + 1, len(places))
            for raw in places:
                biz = self._parse(raw)
                if biz and qualifies(biz, self._settings.min_reviews):
                    yield biz
            token = data.get("nextPageToken")
            if not token:
                break
            body["pageToken"] = token

    @staticmethod
    def _parse(raw: dict[str, Any]) -> Business | None:
        phone = raw.get("internationalPhoneNumber")
        if not phone:
            return None
        reviews: list[Review] = []
        for r in raw.get("reviews", []) or []:
            text = (r.get("originalText") or r.get("text") or {}).get("text", "")
            if not text or not r.get("rating"):
                continue
            reviews.append(
                Review(
                    author=(r.get("authorAttribution") or {}).get("displayName") or "Cliente de Google",
                    rating=int(r["rating"]),
                    text=text,
                    relative_time=r.get("relativePublishTimeDescription"),
                )
            )
        return Business(
            place_id=raw["id"],
            name=(raw.get("displayName") or {}).get("text", "Negocio"),
            phone=phone,
            address=raw.get("formattedAddress", ""),
            rating=float(raw.get("rating", 0)),
            review_count=int(raw.get("userRatingCount", 0)),
            website=raw.get("websiteUri"),
            category=(raw.get("primaryTypeDisplayName") or {}).get("text"),
            maps_uri=raw.get("googleMapsUri"),
            opening_hours=(raw.get("regularOpeningHours") or {}).get("weekdayDescriptions", []),
            top_reviews=pick_top_reviews(reviews),
        )


# ---------------------------------------------------------------------------
# Importador de gosom / omkarcloud
# ---------------------------------------------------------------------------
def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _to_float(v: Any) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _maybe_json(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def _parse_export_reviews(raw: Any) -> list[Review]:
    raw = _maybe_json(raw)
    out: list[Review] = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        text = _first(r, "Description", "description", "review_text", "text")
        rating = _to_int(_first(r, "Rating", "rating"))
        if not text or not 1 <= rating <= 5:
            continue
        out.append(
            Review(
                author=_first(r, "Name", "name", "reviewer_name", "author") or "Cliente de Google",
                rating=rating,
                text=str(text),
                relative_time=_first(r, "When", "when", "published_at"),
            )
        )
    return out


def _parse_hours(raw: Any) -> list[str]:
    raw = _maybe_json(raw)
    if isinstance(raw, dict):  # gosom: {"Monday": ["9 AM-8 PM"], ...}
        return [f"{day}: {', '.join(v) if isinstance(v, list) else v}" for day, v in raw.items()]
    if isinstance(raw, list):  # omkarcloud: [{"day": "...", "times": [...]}]
        lines = []
        for item in raw:
            if isinstance(item, dict):
                times = item.get("times") or item.get("hours") or []
                lines.append(f"{item.get('day', '')}: {', '.join(times) if isinstance(times, list) else times}")
            else:
                lines.append(str(item))
        return lines
    return [str(raw)] if raw else []


def parse_export_record(rec: dict[str, Any]) -> Business | None:
    """Normaliza un registro de gosom (JSON/CSV) u omkarcloud a ``Business``."""
    place_id = _first(rec, "place_id", "cid", "data_id", "link")
    name = _first(rec, "title", "name")
    phone = _first(rec, "phone", "international_phone_number", "phone_number")
    if not (place_id and name and phone):
        return None
    reviews = _parse_export_reviews(
        _first(rec, "user_reviews", "user_reviews_extended", "featured_reviews", "detailed_reviews")
    )
    return Business(
        place_id=str(place_id),
        name=str(name),
        phone=str(phone),
        address=str(_first(rec, "address", "complete_address", "full_address") or ""),
        rating=_to_float(_first(rec, "review_rating", "rating")),
        review_count=_to_int(_first(rec, "review_count", "reviews")),
        website=_first(rec, "website", "web_site"),
        category=_first(rec, "category", "main_category"),
        maps_uri=_first(rec, "link", "url"),
        opening_hours=_parse_hours(_first(rec, "open_hours", "hours", "workday_timing")),
        top_reviews=pick_top_reviews(reviews),
    )


def load_scraper_export(path: Path, min_reviews: int) -> Iterator[Business]:
    """Lee un export JSON (array o JSON Lines) o CSV y aplica el filtro estricto."""
    text = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]]
    if path.suffix.lower() == ".csv":
        records = list(csv.DictReader(text.splitlines()))
    else:
        stripped = text.lstrip()
        if stripped.startswith("["):
            records = json.loads(stripped)
        else:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
    for rec in records:
        try:
            biz = parse_export_record(rec)
        except (ValueError, TypeError) as exc:
            log.warning("Registro inválido ignorado: %s", exc)
            continue
        if biz and qualifies(biz, min_reviews):
            yield biz


def scrape(
    settings: Settings,
    niche: str,
    location: str,
    *,
    source: str = "places",
    input_path: Path | None = None,
) -> Iterator[Business]:
    if source == "places":
        yield from PlacesScraper(settings).search(niche, location)
    elif source in {"gosom", "omkarcloud", "file"}:
        if input_path is None:
            raise ExternalAPIError("scraper", "--input es obligatorio con --source file/gosom/omkarcloud")
        yield from load_scraper_export(input_path, settings.min_reviews)
    else:
        raise ValueError(f"Fuente desconocida: {source}")
