"""Checks every key in backend/.env against the real service and prints ✅ / ❌ with the reason.

Run from the backend folder:   python -m scripts.check_keys
"""
import asyncio

import httpx

from app import config

OK, BAD, SKIP = "✅", "❌", "⚪"


async def check(name, coro):
    try:
        ok, msg = await coro
    except Exception as exc:
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    print(f"{OK if ok else (SKIP if ok is None else BAD)} {name:<28} {msg}")


async def llm_text():
    if not config.LLM_API_KEY:
        return None, "LLM_API_KEY empty — AI briefings, news agent, photo reading disabled"
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(f"{config.LLM_BASE_URL}/chat/completions",
                         headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                         json={"model": config.LLM_MODEL, "max_tokens": 5,
                               "messages": [{"role": "user", "content": "Say OK"}]})
    return r.status_code == 200, f"{config.LLM_MODEL}: HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}"


async def llm_vision():
    if not config.LLM_API_KEY:
        return None, "skipped (no LLM key)"
    import base64, io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (64, 64), (80, 120, 200)).save(b, "JPEG")
    img = base64.b64encode(b.getvalue()).decode()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{config.LLM_BASE_URL}/chat/completions",
                         headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                         json={"model": config.VISION_MODEL, "max_tokens": 10, "messages": [{"role": "user", "content": [
                             {"type": "text", "text": "What colour is this image? One word."},
                             {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]}]})
    return r.status_code == 200, f"{config.VISION_MODEL}: HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}"


async def g_places():
    if not config.GOOGLE_SERVER_KEY:
        return None, "GOOGLE_SERVER_KEY empty — using seed destinations, no nearest hospital/pharmacy"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://places.googleapis.com/v1/places:searchNearby",
                         headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY, "X-Goog-FieldMask": "places.displayName"},
                         json={"includedTypes": ["museum"], "maxResultCount": 1, "locationRestriction": {
                             "circle": {"center": {"latitude": 36.8, "longitude": 10.18}, "radius": 5000}}})
    return r.status_code == 200, f"Places (New): HTTP {r.status_code} {r.text[:150] if r.status_code != 200 else ''}"


async def g_routes():
    if not config.GOOGLE_SERVER_KEY:
        return None, "skipped — OSRM fallback will be used"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://routes.googleapis.com/directions/v2:computeRoutes",
                         headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY, "X-Goog-FieldMask": "routes.duration"},
                         json={"origin": {"location": {"latLng": {"latitude": 36.8, "longitude": 10.18}}},
                               "destination": {"location": {"latLng": {"latitude": 36.4, "longitude": 10.61}}},
                               "travelMode": "DRIVE"})
    return r.status_code == 200, f"Routes: HTTP {r.status_code} {r.text[:150] if r.status_code != 200 else ''}"


async def g_geocode():
    if not config.GOOGLE_SERVER_KEY:
        return None, "skipped — Nominatim fallback will be used"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://maps.googleapis.com/maps/api/geocode/json",
                        params={"address": "Sidi Bou Said, Tunisia", "key": config.GOOGLE_SERVER_KEY})
    st = r.json().get("status")
    return st == "OK", f"Geocoding: {st} {r.json().get('error_message', '')}"


async def g_browser():
    if not config.GOOGLE_BROWSER_KEY:
        return None, "GOOGLE_BROWSER_KEY empty — map falls back to OpenStreetMap"
    return True, f"set (test it by opening the app: the map should be Google, tilted). Map ID: {config.GOOGLE_MAP_ID}"


async def firms():
    if not config.FIRMS_MAP_KEY:
        return None, "FIRMS_MAP_KEY empty — no satellite fire detection"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{config.FIRMS_MAP_KEY}/VIIRS_SNPP_NRT/9,36,10,37/1")
    ok = r.status_code == 200 and r.text.startswith("latitude")
    return ok, f"HTTP {r.status_code} {'' if ok else r.text[:120]}"


async def youtube():
    if not config.YOUTUBE_API_KEY:
        return None, "YOUTUBE_API_KEY empty — web flood-photo agent uses Flickr/links only"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://www.googleapis.com/youtube/v3/search",
                        params={"part": "snippet", "q": "Tunisie", "maxResults": 1, "type": "video", "key": config.YOUTUBE_API_KEY})
    return r.status_code == 200, f"HTTP {r.status_code} {r.text[:150] if r.status_code != 200 else ''}"


async def flickr():
    if not config.FLICKR_API_KEY:
        return None, "FLICKR_API_KEY empty (optional)"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://www.flickr.com/services/rest/", params={
            "method": "flickr.test.echo", "api_key": config.FLICKR_API_KEY, "format": "json", "nojsoncallback": 1})
    return r.json().get("stat") == "ok", f"{r.json().get('stat')} {r.json().get('message', '')}"


async def g_translate():
    if not config.GOOGLE_SERVER_KEY:
        return None, "skipped — built-in en/fr/ar texts; other languages via the AI model"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://translation.googleapis.com/language/translate/v2", params={"key": config.GOOGLE_SERVER_KEY},
                         json={"q": ["No reported issues"], "target": "ar", "format": "text"})
    if r.status_code == 200:
        return True, "Cloud Translation: OK"
    return False, ("Cloud Translation: " + (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}")[:110]
                   + " -> enable 'Cloud Translation API' and allow it in the key's API restrictions")


async def g_tts():
    if not config.GOOGLE_SERVER_KEY:
        return None, "skipped — the phone's own voice reads the emergency card"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://texttospeech.googleapis.com/v1/text:synthesize", params={"key": config.GOOGLE_SERVER_KEY},
                         json={"input": {"text": "مرحبا"}, "voice": {"languageCode": "ar-XA"}, "audioConfig": {"audioEncoding": "MP3"}})
    if r.status_code == 200:
        return True, "Cloud Text-to-Speech (ar-XA): OK"
    return False, ("Cloud Text-to-Speech: " + (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}")[:110]
                   + " -> enable 'Cloud Text-to-Speech API' and allow it in the key's API restrictions")


async def g_autocomplete_photos():
    if not config.GOOGLE_SERVER_KEY:
        return None, "skipped — search only filters the seed list, placeholder images"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.post("https://places.googleapis.com/v1/places:autocomplete",
                         headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY}, json={"input": "sidi bou"})
        if r.status_code != 200:
            return False, f"Autocomplete: HTTP {r.status_code} {r.text[:120]}"
        r = await c.post("https://places.googleapis.com/v1/places:searchText",
                         headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY, "X-Goog-FieldMask": "places.photos"},
                         json={"textQuery": "Bardo Museum Tunis", "maxResultCount": 1})
        ph = ((r.json().get("places") or [{}])[0].get("photos") or [{}])[0].get("name")
        if not ph:
            return False, "Text search returned no photo"
        r = await c.get(f"https://places.googleapis.com/v1/{ph}/media", params={"maxWidthPx": 200, "key": config.GOOGLE_SERVER_KEY})
    return r.status_code == 200, f"Autocomplete + Text search + Photos: HTTP {r.status_code}"


async def open_meteo():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params={"latitude": 36.8, "longitude": 10.18, "current": "temperature_2m"})
    return r.status_code == 200, f"no key needed: HTTP {r.status_code}"


async def main():
    print("\nChecking keys from backend/.env …\n")
    for name, fn in [("AI text model", llm_text), ("AI vision model", llm_vision),
                     ("Google Places (server key)", g_places), ("Google Routes (server key)", g_routes),
                     ("Google Geocoding (server)", g_geocode), ("Google Maps JS (browser)", g_browser),
                     ("Google search + photos", g_autocomplete_photos), ("Google Translate (server)", g_translate),
                     ("Google Text-to-Speech", g_tts),
                     ("NASA FIRMS", firms), ("YouTube Data API", youtube), ("Flickr", flickr),
                     ("Open-Meteo", open_meteo)]:
        await check(name, fn())
    print("\n✅ working   ❌ key present but failing (read the message)   ⚪ not set (fallback in use)\n")


if __name__ == "__main__":
    asyncio.run(main())
