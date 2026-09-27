"""Translation + text-to-speech, each with a fallback chain.

POST /api/translate {texts[], target}   Google Cloud Translation v2 -> AI model (NVIDIA) -> unchanged text
    Used for UI languages without a built-in dictionary (de/it/es) and for live hazard text
    (titles/descriptions written by collectors in English). Cached forever (data/translate_cache.json).
POST /api/tts {text, lang}              Google Cloud Text-to-Speech (MP3) -> 503, and the app then
    uses the phone's own voice (speechSynthesis). Arabic uses the ar-XA voice.
GET  /api/language/status               which provider is actually working right now

Both Google APIs use GOOGLE_SERVER_KEY. They must be enabled in the Cloud project AND allowed
in the key's API restrictions, otherwise Google answers 403 "... are blocked" and we fall back.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app import config, llm, trace

log = logging.getLogger("language")
router = APIRouter(tags=["language"])
LANG_NAME = {"en": "English", "fr": "French", "ar": "Arabic", "de": "German", "it": "Italian", "es": "Spanish"}
TTS_VOICE = {"ar": "ar-XA", "fr": "fr-FR", "en": "en-US", "de": "de-DE", "it": "it-IT", "es": "es-ES"}
CACHE_FILE = config.DATA_DIR / "translate_cache.json"
PERSIST = os.getenv("TRANSLATE_CACHE", "on") != "off"
_blocked_until = {"translate": 0.0, "tts": 0.0}
_last_error = {"translate": None, "tts": None}
_audio: OrderedDict[str, bytes] = OrderedDict()


def _load_cache() -> dict[str, str]:
    if not PERSIST:
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_cache: dict[str, str] = _load_cache()


def _save_cache() -> None:
    if PERSIST:
        try:
            CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def _k(target: str, text: str) -> str:
    return f"{target}␟{text}"


async def _google_translate(texts: list[str], target: str, source: str | None) -> list[str] | None:
    if not config.GOOGLE_SERVER_KEY or _blocked_until["translate"] > time.time():
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            body = {"q": texts, "target": target, "format": "text"}
            if source:
                body["source"] = source
            r = await c.post("https://translation.googleapis.com/language/translate/v2",
                             params={"key": config.GOOGLE_SERVER_KEY}, json=body)
        if r.status_code in (401, 403):
            _blocked_until["translate"] = time.time() + 600
            _last_error["translate"] = (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}")[:200]
            return None
        r.raise_for_status()
        import html
        return [html.unescape(x["translatedText"]) for x in r.json()["data"]["translations"]]
    except Exception as exc:
        _last_error["translate"] = str(exc)[:200]
        log.warning("google translate failed: %s", exc)
        return None


async def _llm_translate(texts: list[str], target: str) -> list[str] | None:
    """Numbered lines instead of JSON: small models break JSON quoting, rarely numbering."""
    out: list[str] = []
    for i in range(0, len(texts), 40):
        chunk = texts[i:i + 40]
        listing = "\n".join(f"{n + 1}. {t.replace(chr(10), ' ')}" for n, t in enumerate(chunk))
        text = await llm.chat([
            {"role": "system", "content":
                f"Translate each numbered line into {LANG_NAME.get(target, target)} for a travel-safety app. "
                "Short, plain, calm wording. Keep placeholders like {name} or {n}, numbers, units and brand names "
                "unchanged. Never add the word 'safe'. Answer with the same numbered lines only, nothing else."},
            {"role": "user", "content": listing}], max_tokens=3000, temperature=0.1,
            purpose=f"translate {len(chunk)} strings -> {target}")
        got = parse_numbered(text, len(chunk))
        if got is None:
            return None
        out += got
    return out


def parse_numbered(text: str | None, n: int) -> list[str] | None:
    if not text:
        return None
    found: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s*[.)\-:]\s*(.+?)\s*$", line)
        if m and 1 <= int(m.group(1)) <= n:
            found.setdefault(int(m.group(1)), m.group(2).strip().strip('"'))
    return [found[i] for i in range(1, n + 1)] if len(found) == n else None


async def translate(texts: list[str], target: str, source: str | None = "en") -> tuple[list[str], str]:
    target = (target or "en").split("-")[0]
    if target == (source or "") or not texts:
        return texts, "none"
    missing = list(dict.fromkeys(t for t in texts if t and _k(target, t) not in _cache))
    provider = "cache"
    if missing:
        with trace.span("api", f"Translate {len(missing)} text(s) -> {target}") as t:
            got = await _google_translate(missing, target, source)
            provider = "google"
            if got is None:
                t.step("Google Translate unavailable", reason=_last_error["translate"])
                got = await _llm_translate(missing, target)
                provider = "ai"
            if got is None:
                t.fail("no translator available: showing the original text")
                return texts, "none"
            for src, dst in zip(missing, got):
                _cache[_k(target, src)] = dst
            _save_cache()
            t.set(provider=provider, sample={missing[0][:80]: got[0][:80]})
    return [_cache.get(_k(target, t), t) if t else t for t in texts], provider


class TranslateRequest(BaseModel):
    texts: list[str]
    target: str
    source: str | None = "en"


@router.post("/api/translate")
async def translate_endpoint(req: TranslateRequest):
    if len(req.texts) > 600:
        raise HTTPException(413, "too many strings")
    texts, provider = await translate([t[:2000] for t in req.texts], req.target, req.source)
    return {"texts": texts, "provider": provider}


class TTSRequest(BaseModel):
    text: str
    lang: str = "ar"
    rate: float = 0.92


@router.post("/api/tts")
async def tts(req: TTSRequest):
    lang = req.lang.split("-")[0]
    if not config.GOOGLE_SERVER_KEY or _blocked_until["tts"] > time.time():
        raise HTTPException(503, "cloud voice unavailable: use the device voice")
    key = hashlib.sha1(f"{lang}|{req.rate}|{req.text}".encode()).hexdigest()
    if key in _audio:
        _audio.move_to_end(key)
        return Response(_audio[key], media_type="audio/mpeg")
    with trace.span("api", f"Text-to-speech ({TTS_VOICE.get(lang, lang)}, {len(req.text)} chars)") as t:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                                 params={"key": config.GOOGLE_SERVER_KEY},
                                 json={"input": {"text": req.text[:4500]},
                                       "voice": {"languageCode": TTS_VOICE.get(lang, "en-US")},
                                       "audioConfig": {"audioEncoding": "MP3", "speakingRate": req.rate}})
            if r.status_code in (401, 403):
                _blocked_until["tts"] = time.time() + 600
                _last_error["tts"] = (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}")[:200]
                t.fail(_last_error["tts"])
                raise HTTPException(503, "cloud voice unavailable: use the device voice")
            r.raise_for_status()
            audio = base64.b64decode(r.json()["audioContent"])
        except HTTPException:
            raise
        except Exception as exc:
            _last_error["tts"] = str(exc)[:200]
            t.fail(str(exc))
            raise HTTPException(503, "cloud voice unavailable: use the device voice")
        _audio[key] = audio
        while len(_audio) > 120:
            _audio.popitem(last=False)
        t.set(bytes=len(audio))
        return Response(audio, media_type="audio/mpeg")


_status_cache: dict = {"at": 0.0, "value": None}


async def status(force: bool = False) -> dict:
    """Probes both Google APIs once (cached 10 min) so the app knows what to use."""
    if not force and _status_cache["value"] and time.time() - _status_cache["at"] < 600:
        return _status_cache["value"]
    tr = await _google_translate(["hello"], "fr", "en") is not None
    tts_ok = False
    if config.GOOGLE_SERVER_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                                 params={"key": config.GOOGLE_SERVER_KEY},
                                 json={"input": {"text": "ok"}, "voice": {"languageCode": "fr-FR"},
                                       "audioConfig": {"audioEncoding": "MP3"}})
            tts_ok = r.status_code == 200
            if not tts_ok:
                _last_error["tts"] = (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}")[:200]
        except Exception as exc:
            _last_error["tts"] = str(exc)[:200]
    value = {"translate": "google" if tr else ("ai" if llm.available() else "none"),
             "tts": "google" if tts_ok else "device",
             "errors": {k: v for k, v in _last_error.items() if v}}
    _status_cache.update(at=time.time(), value=value)
    return value


@router.get("/api/language/status")
async def language_status(force: bool = False):
    return await status(force)
