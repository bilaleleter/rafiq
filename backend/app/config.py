"""All settings come from environment variables (.env in dev). Every key is optional:
missing keys switch the matching feature to its fallback instead of crashing."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
load_dotenv(BASE_DIR / ".env")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in (os.getenv(name) or default).split(",") if x.strip()]


LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("NVIDIA_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL") or "nvidia/nemotron-3-super-120b-a12b"
VISION_MODEL = os.getenv("VISION_MODEL") or "meta/llama-3.2-11b-vision-instruct"
# Tried in order when the main model times out or is gone (NIM models get retired / overloaded).
LLM_FALLBACK_MODELS = _list("LLM_FALLBACK_MODELS", "meta/llama-3.2-11b-vision-instruct,mistralai/mistral-nemotron")
VISION_FALLBACK_MODELS = _list("VISION_FALLBACK_MODELS",
                               "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning,meta/llama-3.2-90b-vision-instruct")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "25"))

GOOGLE_SERVER_KEY = os.getenv("GOOGLE_SERVER_KEY", "")
GOOGLE_BROWSER_KEY = os.getenv("GOOGLE_BROWSER_KEY", "")
GOOGLE_MAP_ID = os.getenv("GOOGLE_MAP_ID") or "DEMO_MAP_ID"

FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
FLICKR_API_KEY = os.getenv("FLICKR_API_KEY", "")
WEB_MAX_AGE_H = float(os.getenv("WEB_MAX_AGE_H", "24"))
COUNTRY = os.getenv("COUNTRY", "TN")
COLLECT_EVERY_MIN = float(os.getenv("COLLECT_EVERY_MIN", "5"))

# Testing tools. DEV_MODE=1 shows the "Under the hood" panel + simulation lab in the app.
# ADMIN_TOKEN (optional): when set, demo/sim/admin endpoints need header X-Admin-Token.
# Before a public deploy: DEV_MODE=0 and set ADMIN_TOKEN.
DEV_MODE = os.getenv("DEV_MODE", "1") == "1"
# DEMO_MODE=1 keeps only the simulation panel (for demos when nothing real is happening). Traces stay hidden.
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
MAX_SIMULATED = int(os.getenv("MAX_SIMULATED", "400"))   # public demo: cap on simulated items at once
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Country profile — add a block to expand to a new country.
COUNTRIES = {
    "TN": {
        "name": "Tunisia",
        "bbox": [7.5, 30.2, 11.6, 37.6],          # west, south, east, north
        "center": [36.8, 10.18],
        "news_queries": [
            ("fr", "inondation OR incendie OR \"coupure d'eau\" OR \"coupure d'électricité\" OR accident OR \"route coupée\" Tunisie when:1d"),
            ("ar", "فيضانات OR حريق OR \"انقطاع الماء\" OR \"انقطاع الكهرباء\" OR حادث تونس when:1d"),
        ],
        "flood_queries": [
            ("fr", "inondation Tunisie"), ("fr", "inondations pluie"),
            ("ar", "فيضانات تونس"), ("ar", "أمطار غزيرة فيضان"),
        ],
        "emergency_numbers": {"police": "197", "civil_protection": "198",
                              "ambulance": "190", "national_guard": "193"},
    },
}
PROFILE = COUNTRIES.get(COUNTRY, COUNTRIES["TN"])
