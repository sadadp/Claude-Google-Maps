from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from config import Settings
from src.builder import BuildError, build_brief, extract_html, validate_html
from src.database import LeadRepository
from src.deployer import VercelDeployer, slugify
from src.models import Business, LeadStatus, Review
from src.outreach import EvolutionClient, Throttle, render_message
from src.scraper import PlacesScraper, load_scraper_export, pick_top_reviews, qualifies


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        ANTHROPIC_API_KEY="x", VERCEL_TOKEN="v", EVOLUTION_API_KEY="e",
        GOOGLE_MAPS_API_KEY="g", DATABASE_PATH=tmp_path / "leads.db",
        VERCEL_READY_TIMEOUT_S=5, _env_file=None,
    )


def make_biz(**kw: object) -> Business:
    base: dict[str, object] = dict(
        place_id="p1", name="Barbería El Rey", phone="+52 222 123 4567",
        address="Av. Juárez 10, Puebla", rating=4.8, review_count=40,
    )
    base.update(kw)
    return Business.model_validate(base)


# --- scraper -----------------------------------------------------------------
def test_filter_rules() -> None:
    assert qualifies(make_biz(), 5)
    assert not qualifies(make_biz(website="https://x.com"), 5)
    assert not qualifies(make_biz(review_count=4), 5)
    assert not qualifies(make_biz(phone="123"), 5)


def test_top_reviews_only_five_stars() -> None:
    reviews = [Review(rating=4, text="Bastante bien, recomendado")] + [
        Review(rating=5, text="x" * n) for n in (20, 80, 50, 30)
    ]
    top = pick_top_reviews(reviews)
    assert [len(r.text) for r in top] == [80, 50, 30]


def test_places_parse_and_filter(settings: Settings) -> None:
    payload = {"places": [
        {"id": "a", "displayName": {"text": "Sin Web"}, "internationalPhoneNumber": "+52 222 111 2222",
         "formattedAddress": "Puebla", "rating": 4.9, "userRatingCount": 12,
         "reviews": [{"rating": 5, "text": {"text": "Excelente corte y atención"},
                      "authorAttribution": {"displayName": "Ana"}}]},
        {"id": "b", "displayName": {"text": "Con Web"}, "internationalPhoneNumber": "+52 1",
         "userRatingCount": 50, "websiteUri": "https://b.mx"},
        {"id": "c", "displayName": {"text": "Sin Tel"}, "userRatingCount": 50},
    ]}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["X-Goog-FieldMask"].startswith("places.id")
        return httpx.Response(200, json=payload)

    s = PlacesScraper(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    out = list(s.search("barberías", "Puebla"))
    assert [b.place_id for b in out] == ["a"]
    assert out[0].top_reviews[0].author == "Ana"


def test_gosom_export(tmp_path: Path) -> None:
    rows = [
        {"place_id": "g1", "title": "Plomería Ruiz", "phone": "+1 305 555 0100", "address": "Miami",
         "review_rating": 4.7, "review_count": 9, "website": "",
         "open_hours": {"Monday": ["8 AM-6 PM"]},
         "user_reviews": [{"Name": "Bob", "Rating": 5, "Description": "Fixed my leak in an hour!"}]},
        {"place_id": "g2", "title": "Has Site", "phone": "+1 305 555 0101",
         "review_count": 30, "website": "https://x.com"},
    ]
    f = tmp_path / "out.json"
    f.write_text(json.dumps(rows))
    out = list(load_scraper_export(f, 5))
    assert len(out) == 1 and out[0].opening_hours == ["Monday: 8 AM-6 PM"]


# --- database ----------------------------------------------------------------
def test_dedupe_and_status(settings: Settings) -> None:
    repo = LeadRepository(settings.database_path)
    biz = make_biz()
    assert repo.insert_if_new(biz) is True
    assert repo.insert_if_new(biz) is False
    repo.mark_generated("p1", "https://x.vercel.app")
    repo.mark_sent("p1")
    lead = repo.get("p1")
    assert lead and lead.status == LeadStatus.SENT and lead.contacted_at
    assert repo.actionable(10) == []
    assert repo.sent_today() == 1
    assert repo.phone_already_contacted(biz.phone_digits, "other")
    assert repo.get_business("p1") == biz


def test_failures_reject_after_max(settings: Settings) -> None:
    repo = LeadRepository(settings.database_path)
    repo.insert_if_new(make_biz())
    assert repo.record_failure("p1", "boom", 2) == LeadStatus.PENDING
    assert repo.record_failure("p1", "boom", 2) == LeadStatus.REJECTED


# --- builder -----------------------------------------------------------------
def test_extract_and_validate_html() -> None:
    biz = make_biz()
    brief = build_brief(biz, "es")
    html = (
        "Aquí tienes:\n<!DOCTYPE html><html><head><script src=\"https://cdn.tailwindcss.com\"></script>"
        f"</head><body><a href=\"tel:{brief['phone_e164']}\"></a><a href=\"{brief['whatsapp_url']}\"></a>"
        f"<iframe src=\"{brief['map_embed_url']}\"></iframe></body></html>\n```"
    )
    doc = extract_html(html)
    assert doc.startswith("<!DOCTYPE") and doc.endswith("</html>")
    validate_html(doc, biz)
    with pytest.raises(BuildError):
        validate_html("<!DOCTYPE html><html></html>", biz)


# --- deployer ----------------------------------------------------------------
def test_slugify() -> None:
    s = slugify("Barbería «El Rey» & Co.", "abc")
    assert s.startswith("barberia-el-rey-co-") and len(s) <= 48


def test_vercel_deploy_polls_until_ready(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["files"][0]["file"] == "index.html"
            return httpx.Response(200, json={"id": "dpl_1", "readyState": "QUEUED", "url": "x-hash.vercel.app"})
        return httpx.Response(200, json={"id": "dpl_1", "readyState": "READY", "url": "x-hash.vercel.app",
                                         "alias": ["x-team.vercel.app", "x.vercel.app"]})

    d = VercelDeployer(settings, httpx.Client(base_url="https://api.vercel.com",
                                              transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("src.deployer.time.sleep", lambda _s: None)
    assert d.deploy("<html></html>", "x") == "https://x.vercel.app"
    assert calls == ["POST /v13/deployments", "GET /v13/deployments/dpl_1"]


# --- outreach ----------------------------------------------------------------
def test_message_and_send(settings: Settings) -> None:
    msg = render_message("Barbería El Rey", "https://x.vercel.app", footer="Responde no")
    assert msg.startswith("Hola Barbería El Rey,") and "https://x.vercel.app" in msg

    sent: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["apikey"] == "e"
        sent.append({"path": req.url.path, **json.loads(req.content)})
        return httpx.Response(201, json={"key": {"id": "1"}})

    c = EvolutionClient(settings, httpx.Client(base_url="http://evo", transport=httpx.MockTransport(handler)))
    c.send_text("522221234567", msg)
    assert sent[0]["path"] == "/message/sendText/outreach" and sent[0]["number"] == "522221234567"


def test_throttle_jitter_bounds() -> None:
    slept: list[float] = []
    t = Throttle(60, 180, sleep=slept.append)
    assert t.wait() == 0.0
    for _ in range(20):
        t.wait()
    assert len(slept) == 20 and all(60 <= s <= 180 for s in slept)


def test_builder_request_shape(settings: Settings) -> None:
    """La petición a Claude usa streaming, el modelo configurado y fallbacks."""
    import anthropic
    import httpx2  # el SDK de Anthropic >= 2.x usa httpx2

    from src.builder import SiteBuilder

    seen: dict[str, object] = {}

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(req.content)
        seen["beta"] = req.headers.get("anthropic-beta")
        return httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "x"}})

    client = anthropic.Anthropic(api_key="x", max_retries=0,
                                 http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with pytest.raises(BuildError):
        SiteBuilder(settings, client).generate(make_biz(), attempts=1)
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-sonnet-5-5" and body["stream"] is True
    assert body["fallbacks"] == "default"
    assert "server-side-fallback" in str(seen["beta"])
    assert "wa.me/522221234567" in body["messages"][0]["content"]
