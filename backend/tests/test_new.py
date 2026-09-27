"""Tests for the testing tools and the new features: traces, simulation lab, admin guard,
stable ids, recommendations, place search/photos, translation/TTS fallbacks, AI model fallback.
Run: pytest -q   (no keys or network needed; every external call is mocked)"""
import asyncio
import io
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, llm, store, trace
from app.main import app
from app.models import HazardEvent


@pytest.fixture(autouse=True)
def empty_store():
    """Other test files leave real events (e.g. the SOS test's accident in Tunis): start clean."""
    store.clear(simulated_only=False)
    yield


def client():
    return TestClient(app)


def reset(c):
    assert c.post("/api/sim/reset").status_code == 200


# ── traces ──────────────────────────────────────────────────────────────────
def test_trace_spans_nest_and_truncate():
    trace.clear()
    with trace.span("calc", "outer", big="x" * 5000) as outer:
        outer.step("first", n=1)
        with trace.span("llm", "inner"):
            trace.step("inside inner")
    recs = trace.recent()
    inner = next(r for r in recs if r["title"] == "inner")
    out = next(r for r in recs if r["title"] == "outer")
    assert inner["title"] == "inner" and inner["parent"] == out["id"]
    assert inner["steps"][0]["label"] == "inside inner"
    assert any(s["label"].startswith("-> llm: inner") for s in out["steps"])
    assert len(out["data"]["big"]) < 2000
    # a title key inside data must not clash with the span title
    trace.event("agent", "t", title="also fine")


def test_debug_endpoints():
    with client() as c:
        c.post("/api/sim/hazard", json={"type": "fire", "lat": 36.8, "lon": 10.2})
        assert c.get("/api/debug/traces").json()
        st = c.get("/api/debug/state").json()
        assert st["events"]["simulated"] >= 1 and "ai" in st and "language" in st


# ── stable ids ──────────────────────────────────────────────────────────────
def test_stable_ids_across_processes():
    from app.collectors.news_agent import stable_id
    here = stable_id("news", "https://example.com/a")
    code = "from app.collectors.news_agent import stable_id; print(stable_id('news', 'https://example.com/a'))"
    other = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert here == other and here.startswith("news-") and len(here) == 15


# ── simulation lab ──────────────────────────────────────────────────────────
def test_sim_single_report_is_caution_three_phones_is_avoid():
    with client() as c:
        reset(c)
        one = c.post("/api/sim/crowd", json={"type": "accident", "lat": 36.7, "lon": 10.1, "devices": 1}).json()
        assert one["progression"][-1]["status"] == "caution"          # one unverified report never = avoid
        three = c.post("/api/sim/crowd", json={"type": "road", "lat": 36.6, "lon": 10.3, "devices": 3}).json()
        prog = three["progression"]
        assert [p["status"] for p in prog] == ["caution", "caution", "avoid"]
        assert prog[-1]["confidence"] == 0.8 and prog[-1]["severity"] == "danger"
        ev = next(e for e in c.get("/api/hazards").json() if e["id"] == prog[-1]["event_id"])
        assert ev["is_simulated"] is True


def test_sim_power_and_flood_crowd_are_simulated():
    with client() as c:
        reset(c)
        p = c.post("/api/sim/crowd", json={"type": "power", "lat": 36.7, "lon": 10.1, "devices": 2}).json()
        assert p["progression"][-1]["confidence"] == 0.65
        f = c.post("/api/sim/crowd", json={"type": "flood", "lat": 36.4, "lon": 10.6, "devices": 3,
                                           "body_level": "person_knee"}).json()
        assert f["progression"][-1]["reports"] == 3
        evs = c.get("/api/hazards").json()
        assert all(e["is_simulated"] for e in evs)
        reset(c)
        assert c.get("/api/hazards").json() == []


def test_sim_weather_uses_real_thresholds():
    with client() as c:
        reset(c)
        r = c.post("/api/sim/weather", json={"lat": 36.4, "lon": 10.6, "rain_mm_h": 18, "gust_kmh": 50,
                                             "feels_like_c": 43, "river_ratio": 4.5}).json()
        got = {(e["type"], e["severity"]) for e in r["events"]}
        assert got == {("storm", "danger"), ("heat", "danger"), ("flood", "danger")}   # 50 km/h wind: below 60
        assert c.post("/api/sim/weather", json={"lat": 36.4, "lon": 10.6, "rain_mm_h": 5}).json()["events"] == []


def test_sim_rain_model_bowl_and_collectors_keep_sim_events():
    with client() as c:
        reset(c)
        r = c.post("/api/sim/rain-model", json={"lat": 36.8, "lon": 10.2, "rain_mm": 70, "terrain": "bowl"}).json()
        assert r["events"] and all(e["data"]["kind"] == "estimated" for e in r["events"])
        store.replace_source("model", [])        # a real collector refresh with nothing new...
        assert any(e.id == r["events"][0]["id"] for e in store.active())   # ...keeps simulated events


def test_sim_on_route_and_scenarios():
    with client() as c:
        reset(c)
        route = [[36.80, 10.18], [36.70, 10.30], [36.60, 10.42], [36.40, 10.61]]
        r = c.post("/api/sim/on-route", json={"coordinates": route, "at_fraction": 0.5}).json()
        chk = c.post("/api/trip/check", json={"coordinates": route}).json()
        assert chk["status"] == "avoid" and chk["hits"][0]["event"]["id"] == r["event"]["id"]
        reset(c)
        s = c.post("/api/sim/scenario", json={"name": "around_me", "lat": 36.8, "lon": 10.18}).json()
        assert s["created"] >= 10
        statuses = {e["type"]: store.status_of([HazardEvent(**e)]) for e in c.get("/api/hazards").json()}
        assert statuses["road"] == "avoid" and statuses["accident"] == "caution" and statuses["water"] == "caution"
        assert c.post("/api/sim/scenario", json={"name": "country"}).json()["created"] == 5


def test_admin_token_guards_sim_and_demo(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret")
    with client() as c:
        assert c.post("/api/sim/reset").status_code == 403
        assert c.post("/api/demo/scenario").status_code == 403
        assert c.post("/api/hazards", json={"type": "fire", "severity": "danger", "title": "x", "lat": 1, "lon": 1}).status_code == 403
        assert c.post("/api/sim/reset", headers={"X-Admin-Token": "s3cret"}).status_code == 200
        assert c.get("/api/hazards").status_code == 200        # reading stays public


def test_dev_mode_off_hides_lab(monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEMO_MODE", False)
    with client() as c:
        assert c.get("/api/sim/presets").status_code == 404
        assert c.get("/api/debug/traces").status_code == 404
        assert c.get("/api/public-config").json()["dev_mode"] is False


def test_demo_mode_keeps_simulation_only(monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(config, "MAX_SIMULATED", 2)
    with client() as c:
        reset(c)
        assert c.get("/api/debug/traces").status_code == 404          # traces hidden in production
        assert c.get("/api/sim/presets").status_code == 200           # simulation still works
        for _ in range(2):
            assert c.post("/api/sim/hazard", json={"lat": 36.8, "lon": 10.2}).status_code == 200
        assert c.post("/api/sim/hazard", json={"lat": 36.8, "lon": 10.2}).status_code == 429   # abuse cap
        assert c.post("/api/sim/reset").status_code == 200


# ── recommendations ─────────────────────────────────────────────────────────
def _place(pid, name, lat, lon, types, rating=4.5, n=500, open_now=True):
    return {"id": pid, "displayName": {"text": name}, "location": {"latitude": lat, "longitude": lon},
            "rating": rating, "userRatingCount": n, "primaryType": types[0], "types": types,
            "currentOpeningHours": {"openNow": open_now}, "photos": [{"name": f"places/{pid}/photos/abc"}]}


def test_recommend_scores_diversifies_and_explains(monkeypatch):
    from app.services import destinations, google
    cafes = [_place(f"c{i}", f"Cafe {i}", 36.80 + i * 0.001, 10.18, ["cafe"], 4.6, 900) for i in range(6)]
    beach = [_place("b1", "Gammarth beach", 36.91, 10.28, ["beach"], 4.4, 3000)]

    async def fake_nearby(lat, lon, radius, types, max_results=20, rank_by_distance=False, language="en"):
        return cafes if "cafe" in types else beach if "beach" in types else []

    async def fake_text(*a, **k):
        return []
    monkeypatch.setattr(google, "places_nearby", fake_nearby)
    monkeypatch.setattr(google, "places_text", fake_text)
    monkeypatch.setattr(google, "has_key", lambda: True)
    destinations._seed_enriched.clear()
    with client() as c:
        reset(c)
        r = c.get("/api/destinations/recommend", params={"lat": 36.8, "lon": 10.18, "interests": "cafe,beach",
                                                         "max_km": 30}).json()
        rec = r["recommended"]
        top5 = [x["category"] for x in rec[:5]]
        assert "beach" in top5                      # diversity: not only cafés at the top
        cafe = next(x for x in rec if x["id"] == "c0")
        assert cafe["photo"] == "places/c0/photos/abc" and cafe["open_now"] is True
        assert {w["k"] for w in cafe["why"]} >= {"interest", "rating", "open", "status"}
        b = cafe["breakdown"]
        assert 0 < b["quality"] <= 1 and b["interest"] == 1.0 and b["safety"] == 1.0
        # a hazard on the beach hides it from recommendations
        c.post("/api/sim/hazard", json={"type": "storm", "severity": "danger", "confidence": 0.9,
                                        "lat": 36.91, "lon": 10.28, "radius_m": 2000})
        r = c.get("/api/destinations/recommend", params={"lat": 36.8, "lon": 10.18, "interests": "cafe,beach",
                                                         "max_km": 30}).json()
        assert "b1" not in [x["id"] for x in r["recommended"]] and "b1" in [x["id"] for x in r["avoid_now"]]
    destinations._seed_enriched.clear()


# ── places proxy ────────────────────────────────────────────────────────────
def test_places_without_key_and_photo_proxy(monkeypatch):
    from app.services import google
    with client() as c:
        assert c.get("/api/places/autocomplete", params={"input": "sidi"}).json()["suggestions"] == []
        assert c.get("/api/places/photo", params={"name": "places/x/photos/y"}).status_code == 404

    async def fake_photo(name, w=480):
        return "https://lh3.googleusercontent.com/p/abc=w480"
    monkeypatch.setattr(google, "place_photo_url", fake_photo)
    with client() as c:
        r = c.get("/api/places/photo", params={"name": "places/x/photos/y"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].startswith("https://lh3.googleusercontent.com")
        assert "key=" not in r.headers["location"] and "max-age" in r.headers["cache-control"]


# ── language ────────────────────────────────────────────────────────────────
def test_translate_fallbacks_and_cache(monkeypatch):
    from app.services import language
    with client() as c:
        r = c.post("/api/translate", json={"texts": ["Road blocked"], "target": "ar"}).json()
        assert r == {"texts": ["Road blocked"], "provider": "none"}          # no key, no AI: original text

    async def fake_google(texts, target, source):
        return [f"[{target}] {t}" for t in texts]
    monkeypatch.setattr(language, "_google_translate", fake_google)
    with client() as c:
        r = c.post("/api/translate", json={"texts": ["Road blocked", "Water cut"], "target": "de"}).json()
        assert r["texts"] == ["[de] Road blocked", "[de] Water cut"] and r["provider"] == "google"

    async def broken(*a):
        raise AssertionError("cache should answer")
    monkeypatch.setattr(language, "_google_translate", broken)
    with client() as c:
        assert c.post("/api/translate", json={"texts": ["Water cut"], "target": "de"}).json()["provider"] == "cache"
        assert c.post("/api/tts", json={"text": "مرحبا", "lang": "ar"}).status_code == 503   # -> device voice


def test_briefing_fallback_never_says_safe():
    with client() as c:
        reset(c)
        b = c.post("/api/briefing", json={"lat": 30.5, "lon": 9.5, "name": "Nowhere", "lang": "en"}).json()
        assert b["ai"] is False and "safe" not in b["text"].lower()


# ── AI model fallback chain ─────────────────────────────────────────────────
def test_llm_falls_back_when_model_is_gone(monkeypatch):
    calls = []

    def handler(req):
        model = __import__("json").loads(req.content)["model"]
        calls.append(model)
        if model == "retired/model":
            return httpx.Response(410, json={"detail": "gone"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(config, "LLM_API_KEY", "test")
    monkeypatch.setattr(config, "LLM_MODEL", "retired/model")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODELS", ["backup/model"])
    llm._down_until.clear()
    out = asyncio.run(llm.chat_json("sys", "hi"))
    assert out == {"ok": True} and calls == ["retired/model", "backup/model"]
    calls.clear()
    asyncio.run(llm.chat_json("sys", "hi"))
    assert calls == ["backup/model"]           # the retired model is skipped (circuit breaker)
    llm._down_until.clear()


def test_sim_flood_photo_without_ai_asks_for_body_level():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 40)).save(b, "JPEG")
    with client() as c:
        r = c.post("/api/sim/flood-photo", data={"lat": 36.4, "lon": 10.6},
                   files={"photo": ("a.jpg", b.getvalue(), "image/jpeg")}).json()
        assert r["accepted"] is False and r["needs_manual"] is True


def test_single_flood_report_never_causes_avoid():
    """Status rule (CLAUDE.md 7.2): one unverified source can never cause 'avoid' on its own."""
    with client() as c:
        reset(c)
        one = c.post("/api/sim/crowd", json={"type": "flood", "lat": 36.5, "lon": 10.5, "devices": 1,
                                             "body_level": "person_waist"}).json()["progression"]
        assert one[-1]["severity"] == "critical" and one[-1]["confidence"] < 0.5 and one[-1]["status"] == "caution"
        two = c.post("/api/sim/crowd", json={"type": "flood", "lat": 36.6, "lon": 10.6, "devices": 2,
                                             "body_level": "person_waist"}).json()["progression"]
        assert two[-1]["status"] == "avoid"


def test_blocked_trip_tries_detour_then_least_risky(monkeypatch):
    from app.services import trip
    straight = [[36.80, 10.18], [36.70, 10.30], [36.60, 10.42], [36.40, 10.61]]
    other = [[36.80, 10.18], [36.72, 10.25], [36.58, 10.45], [36.40, 10.61]]
    calls = []

    async def fake_routes(o_lat, o_lon, d_lat, d_lon, mode="DRIVE", via=None):
        calls.append(via)
        if via:   # the detour waypoint route goes far east: clear
            return [{"coords": [[36.80, 10.18], [via[0], via[1]], [36.40, 10.61]], "duration_s": 4200,
                     "distance_m": 80000, "label": "x", "provider": "test"}]
        return [{"coords": straight, "duration_s": 3000, "distance_m": 66000, "label": "A1", "provider": "test"},
                {"coords": other, "duration_s": 3300, "distance_m": 70000, "label": "C35", "provider": "test"}]
    monkeypatch.setattr(trip, "routes", fake_routes)
    body = {"origin_lat": 36.80, "origin_lon": 10.18, "dest_lat": 36.40, "dest_lon": 10.61, "dest_name": "Hammamet"}
    with client() as c:
        reset(c)
        # one wide storm cell over the middle blocks both normal routes
        c.post("/api/sim/hazard", json={"type": "storm", "severity": "danger", "confidence": 0.9,
                                        "lat": 36.63, "lon": 10.38, "radius_m": 6000})
        r = c.post("/api/trip/plan", json=body).json()
        assert r["detour_tried"] and any(x.get("detour") for x in r["routes"])
        rec = next(x for x in r["routes"] if x["index"] == r["recommended_index"])
        assert rec.get("detour") and rec["safety"] != "avoid" and not r["all_routes_unsafe"]
        # problem sitting on the destination: no detour possible -> least risky route, clears_at given
        reset(c)
        c.post("/api/sim/hazard", json={"type": "road", "severity": "danger", "confidence": 0.9,
                                        "lat": 36.40, "lon": 10.61, "radius_m": 800, "minutes": 90})
        r = c.post("/api/trip/plan", json=body).json()
        assert r["all_routes_unsafe"] and r["problem_at_destination"] and not r["detour_tried"]
        assert r["recommended_index"] == r["least_risk_index"] and r["clears_at"]


def test_clean_place_strips_road_codes():
    from app.collectors.news_agent import clean_place
    assert clean_place("A1 highway near Enfidha") == "Enfidha"
    assert clean_place("Enfidha, A1") == "Enfidha"
    assert clean_place("Bir Bouregba, Nabeul") == "Bir Bouregba, Nabeul"
