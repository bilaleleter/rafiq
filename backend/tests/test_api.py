"""Run: COLLECTORS=off pytest -q   (no keys or network needed)"""
import asyncio, io, json, os
os.environ["COLLECTORS"] = "off"
from fastapi.testclient import TestClient
from app.main import app
from app.reports import flood

def client():
    return TestClient(app)

def test_demo_near_route_and_votes():
    with client() as c:
        c.post("/api/demo/reset")
        assert c.post("/api/demo/scenario").json()["created"] == 5
        near = c.get("/api/hazards/near", params={"lat": 36.40, "lon": 10.61, "radius_km": 2}).json()
        assert near["status"] == "avoid"
        far = c.get("/api/hazards/near", params={"lat": 36.87, "lon": 10.34, "radius_km": 2}).json()
        assert far["status"] == "clear"
        rc = c.post("/api/trip/check", json={"coordinates": [[36.80, 10.18], [36.55, 10.45], [36.40, 10.61]]}).json()
        assert rc["status"] == "avoid" and rc["hits"][0]["km_along_route"] < rc["hits"][-1]["km_along_route"] + 1
        eid = c.get("/api/hazards").json()[0]["id"]
        for _ in range(3):
            c.post(f"/api/hazards/{eid}/vote", json={"still_there": False})
        assert eid not in [e["id"] for e in c.get("/api/hazards").json()]

def test_crowd_reports_merge():
    with client() as c:
        c.post("/api/demo/reset")
        for i in range(3):
            e = c.post("/api/reports", json={"type": "accident", "lat": 36.7 + i * 1e-4, "lon": 10.2, "device_id": f"dev{i}"}).json()
        assert e["reports_count"] == 3 and e["severity"] == "danger" and e["confidence"] == 0.8

def test_flood_body_report_and_manual_fallback():
    with client() as c:
        c.post("/api/demo/reset")
        r = c.post("/api/flood/report", data={"lat": 36.40, "lon": 10.61, "body_level": "person_knee", "device_id": "f1"}).json()
        assert r["accepted"] and r["zone"]["type"] == "flood" and r["zone"]["data"]["depth_cm"] == 50
        from PIL import Image
        b = io.BytesIO(); Image.new("RGB", (40, 40)).save(b, "JPEG")
        r = c.post("/api/flood/report", data={"lat": 36.4, "lon": 10.61, "device_id": "f2"},
                   files={"photo": ("a.jpg", b.getvalue(), "image/jpeg")}).json()
        assert r["needs_manual"] is True

def test_flood_replay_fusion():
    items = json.load(open("data/flood_replay.json"))
    asyncio.run(flood._run_replay(items, 1e6))
    from app import store
    zones = [e for e in store.active(["flood"]) if e.is_simulated]
    assert len(zones) == 3 and all(z.data["trend_cm_per_h"] > 0 for z in zones)

def test_sos_without_keys():
    with client() as c:
        r = c.post("/api/sos", json={"kind": "accident", "lat": 36.8, "lon": 10.18, "people": 2, "injured": True}).json()
        assert r["primary_number"] == "198" and "حادث" in r["card"]["ar"] and r["public_hazard_id"]

def test_recommend_hides_avoid():
    with client() as c:
        c.post("/api/demo/reset"); c.post("/api/demo/scenario")
        r = c.get("/api/destinations/recommend", params={"lat": 36.8, "lon": 10.18, "interests": "beach", "max_km": 200}).json()
        names = [d["name"] for d in r["recommended"]]
        assert "Hammamet Medina & beach" not in names
        assert any(d["name"].startswith("Hammamet") for d in r["avoid_now"])
        chk = c.get("/api/destinations/check", params={"lat": 36.3997, "lon": 10.6167, "name": "Hammamet", "category": "beach"}).json()
        assert chk["status"] == "avoid" and chk["alternatives"][0]["category"] == "beach"


def test_power_reports_and_history():
    from app.reports import power
    power.HISTORY_FILE = power.config.DATA_DIR / "test_power_history.json"
    power.HISTORY_FILE.unlink(missing_ok=True)
    with client() as c:
        e = c.post("/api/power/report", json={"lat": 36.81, "lon": 10.17, "device_id": "p1", "charger_verified": True}).json()["event"]
        assert e["confidence"] == 0.6 and "charger-verified" in e["title"]
        e = c.post("/api/power/report", json={"lat": 36.8102, "lon": 10.1701, "device_id": "p2"}).json()["event"]
        assert e["reports_count"] == 2 and e["confidence"] == 0.65
        dup = c.post("/api/power/report", json={"lat": 36.81, "lon": 10.17, "device_id": "p2"})
        assert dup.status_code == 429
        # half of the reporters (1 of 2) say it's back -> outage closed and saved to history
        r = c.post("/api/power/report", json={"lat": 36.81, "lon": 10.17, "device_id": "p1", "status": "on"}).json()
        assert r["closed"] is True
        h = c.get("/api/power/history", params={"lat": 36.81, "lon": 10.17}).json()
        assert h["cuts"] == 1
    power.HISTORY_FILE.unlink(missing_ok=True)


def test_flood_estimate_from_terrain():
    from app.collectors.flood_model import estimate_cells, GRID
    elev = [20.0] * (GRID * GRID)
    elev[3 * GRID + 3] = 15.0          # a 5 m hollow in the middle
    cells = estimate_cells(36.4, 10.6, elev, rain_mm=40)
    assert len(cells) == 1 and cells[0]["depth_cm"] > 30
    assert estimate_cells(36.4, 10.6, elev, rain_mm=5) == []   # not enough rain

def test_web_candidate_rejections():
    from datetime import datetime, timedelta, timezone
    from app.collectors import web_photos
    old = {"id": "yt-old", "platform": "youtube", "url": "u", "title": "t", "thumb": "x",
           "published": datetime.now(timezone.utc) - timedelta(days=3)}
    r = asyncio.run(web_photos.verify_and_add(old))
    assert r["accepted"] is False and "old" in r["reason"]

def test_web_candidate_full_pipeline_mocked(monkeypatch):
    import json as _j
    from datetime import datetime, timezone
    from PIL import Image
    from app.collectors import web_photos
    from app import llm
    b = io.BytesIO(); Image.new("RGB", (64, 64), (90, 120, 200)).save(b, "JPEG"); img = b.getvalue()

    class FakeResp:
        content = img
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **k): return FakeResp()
    monkeypatch.setattr(web_photos.httpx, "AsyncClient", FakeClient)
    async def chat(*a, **k): return _j.dumps({"is_flood_scene": True, "real_photo": True, "looks_ai_generated_or_edited": False,
        "is_graphic_or_text_card": False, "anchor": "car_tyre_half", "flowing_water": True, "visible_dangers": [], "confidence": 0.8})
    async def chat_json(*a, **k): return {"place": "Avenue Habib Bourguiba, Nabeul", "specificity": "street", "confidence": 0.8}
    async def geocode(*a, **k): return (36.456, 10.735)
    async def rain(*a, **k): return 25.0
    monkeypatch.setattr(llm, "chat", chat); monkeypatch.setattr(llm, "chat_json", chat_json)
    monkeypatch.setattr(web_photos, "geocode", geocode); monkeypatch.setattr(web_photos, "rain_mm_last_day", rain)
    item = {"id": "yt-new", "platform": "youtube", "url": "https://youtu.be/x", "title": "فيضانات نابل",
            "thumb": "https://i.ytimg.com/x.jpg", "published": datetime.now(timezone.utc)}
    r = asyncio.run(web_photos.verify_and_add(item))
    assert r["accepted"] and r["depth_cm"] == 33 and r["confidence"] <= 0.5
    async def dry(*a, **k): return 0.0
    monkeypatch.setattr(web_photos, "rain_mm_last_day", dry)
    r2 = asyncio.run(web_photos.verify_and_add({**item, "id": "yt-new2"}))
    assert not r2["accepted"] and "no rain" in r2["reason"]
