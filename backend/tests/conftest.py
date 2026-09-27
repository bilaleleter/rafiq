"""Tests never touch the network: blank every key BEFORE app.config reads .env
(python-dotenv does not override variables that already exist)."""
import os

for k in ("LLM_API_KEY", "NVIDIA_API_KEY", "GOOGLE_SERVER_KEY", "GOOGLE_BROWSER_KEY", "FIRMS_MAP_KEY",
          "YOUTUBE_API_KEY", "FLICKR_API_KEY", "ADMIN_TOKEN"):
    os.environ[k] = ""
os.environ["COLLECTORS"] = "off"
os.environ["TRANSLATE_CACHE"] = "off"
