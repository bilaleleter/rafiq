# Rafiq

**Rafiq** means "companion" in Arabic. It's a travel app for tourists in Tunisia that tells you what is going wrong right now where you want to go (floods, fires, storms, heat, power cuts, water cuts, accidents, blocked roads), gets you there on a route that avoids it, and helps you call for help in Arabic and French if something happens to you.


**Live demo**: https://rafiq-fork.vercel.app/  (open it on a phone or in a narrow window; the flask button simulates live problems)
**Demo Video:** https://drive.google.com/file/d/1ulRFa9g9amY3nTjdh1h-oiZ_Feydh-S7/view?usp=share_link



## The problem

Tourists in Tunisia have no single place to check if a beach, a road or a town has a problem today. Flash floods, forest fires, power and water cuts and closed roads get posted in French or Arabic on local news and Facebook, and most visitors can't read them in time. When something does go wrong, calling 198 and explaining where you are, in Arabic, is very hard for a foreigner.

## What Rafiq does

1. **Explore:** a live 3D map with every reported problem. Each problem shows where it comes from, how sure we are, and how old it is. Recommended places around you are ranked by rating, your interests, distance, opening hours, weather and live problems. A place with a serious problem is removed from the suggestions right away.
2. **Search any place** like on Google Maps, with real photos, hours, phone number and a short summary of the live situation there (in your language, and it can read it out loud).
3. **Trip:** routes are ranked by safety, not only by time. If every route crosses a problem, Rafiq tries a detour around it. If that fails too, it shows the least risky route, when the problem should clear, and similar places you can go to instead. You are never stuck on a "no route" screen.
4. **Route guardian:** while you drive, it re-checks the road ahead every 30 seconds and on every new report. If something appears ahead you get a banner and a spoken alert with a safer route.
5. **Report:** flood (photo or "water is at my knee"), power cut (your phone charger checks if the socket is dead), accident, blocked road, water cut, fire, health, crowd. One report is only a "caution". It becomes "avoid" when other people confirm it.
6. **SOS:** one tap gives you the right number to call, your address and Plus Code, the nearest hospital, pharmacy and police, and an emergency card in Arabic and French that the phone reads out loud to the operator or to people around you.
7. **Languages:** English, French and Arabic built in (Arabic is right to left). German, Italian and Spanish are translated automatically.

## Where the data comes from

| Source | What it gives us |
|---|---|
| Open-Meteo forecast | heavy rain, wind gusts, extreme heat for the next 6 hours |
| Open-Meteo Flood API (GloFAS) | rivers running above their normal level |
| Open-Meteo Elevation + rain | low ground that will probably flood (marked "estimated") |
| NASA FIRMS | active fires seen by satellite in the last 24 h |
| USGS | earthquakes |
| Google News (French + Arabic) | incidents read by our news agent (see below) |
| YouTube | flood videos posted during a storm, checked by our photo agent |
| Travellers | reports from the app |

Everything is refreshed every 5 minutes and pushed to the app live.

## How we use AI

We use NVIDIA NIM models (the free API at build.nvidia.com):

- **News agent** (`nvidia/nemotron-3-super-120b-a12b`): reads French and Arabic headlines, keeps only real incidents happening now, and gives back type, place and severity as JSON. We then find the place on the map ourselves. Example: "Nabeul : la route GP1 coupée près de Bir Bouregba" becomes a "road blocked" event at Bir Bouregba. News alone is capped at 50% confidence, so it can only ever show "caution".
- **Flood photo reader** (`meta/llama-3.2-11b-vision-instruct`): the model does not guess a number. It picks where the water line is on a known object (kerb, car wheel, knee) and our code turns that into centimetres.
- **Place summary:** 2 to 4 short sentences written only from the live events we give it, with an action for each problem. It is not allowed to add facts or say "safe".
- **Web photo agent:** checks flood videos (is it real, is it recent, did it rain there) before they reach the map.

Every AI call has a normal fallback. If the model is down or slow, the app uses a fixed text template, the body-height buttons, or another model. The app keeps working with no AI key at all.

## Simulated data (please read)

On the day we built this, not much was happening in Tunisia, so the app has a **Simulate** panel (the flask button on the map). It lets you create problems anywhere: a blocked road reported by 3 phones, heavy rain, a rising flood, news headlines, a flood photo. You can also "drive" a route to test the alerts.

Simulated data goes through exactly the same code as real data (same rules, same AI). It is always marked **SIMULATED** in the app, it never mixes with real reports, and it is removed with one tap, after a few hours, or when the server restarts. Real data from NASA, Open-Meteo, USGS and the news agent runs at the same time.

## Tech stack

- Backend: Python 3.12, FastAPI, httpx, Pydantic, Server-Sent Events for live updates
- Frontend: React 18, Vite, deck.gl on top of Google Maps (3D, vector map)
- Google Maps Platform: Maps JS, Places (search, photos, details), Routes, Geocoding, Cloud Translation, Cloud Text-to-Speech
- AI: NVIDIA NIM (Nemotron 3 Super for text, Llama 3.2 11B Vision for photos)
- Fallbacks when a key is missing: CARTO map tiles, OSRM routes, OpenStreetMap geocoding, the phone's own voice

## Run it locally

You need Python 3.11+ and Node 18+.

```bash
# backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # put your keys in .env (all optional)
python -m scripts.check_keys       # tests every key you added
uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 3

# frontend (second terminal)
cd frontend
npm install
npm run dev                        # open http://localhost:5173
```

The app runs with no keys at all (free fallbacks). Keys unlock the Google map, place photos, AI features, NASA fires and web videos. See `backend/.env.example` for the list and where to get each one.

Two settings in `backend/.env`:
- `DEV_MODE=1` shows the full testing panel (a live log of every calculation and AI call). Use it on your machine only.
- `DEMO_MODE=1` shows only the Simulate panel. This is what we use in the public demo.

## Deploy (what we did)

The frontend is on **Vercel**. The backend is on **Render**, because it keeps running jobs every 5 minutes and holds a live connection open to every phone, which Vercel's serverless functions can't do.

**Backend on Render**
1. Push this repo to GitHub.
2. On render.com: New, then Blueprint, then pick the repo. It reads `render.yaml`.
3. Fill the secret values it asks for: `LLM_API_KEY`, `GOOGLE_SERVER_KEY`, `GOOGLE_BROWSER_KEY`, `GOOGLE_MAP_ID`, `FIRMS_MAP_KEY`, `YOUTUBE_API_KEY`.
4. Wait for the deploy, then open `https://YOUR-API.onrender.com/api/health`. You should see `"ok": true`.

**Frontend on Vercel**
1. On vercel.com: Add New, then Project, then import the same repo.
2. Set **Root Directory** to `frontend`. Vercel detects Vite by itself.
3. Add the environment variable `BACKEND_URL` = `https://YOUR-API.onrender.com` (no slash at the end). It stays private: `frontend/api/proxy.js` forwards `/api` calls to it from Vercel's servers.
4. Deploy.

**Google key:** in Google Cloud, open the browser key and add `https://YOUR-APP.vercel.app/*` to its allowed websites, or the map will not load.

**Docker (optional):** `docker build -t rafiq . && docker run -p 8000:8000 --env-file backend/.env rafiq` runs everything in one container on http://localhost:8000.

## Tests

```bash
cd backend && COLLECTORS=off python -m pytest -q    # 30 tests, under 1 second, no internet needed
cd frontend && node scripts/i18n-keys.mjs --check   # every screen text exists in French and Arabic
```

The tests cover the "avoid / caution" rules, report merging, flood depth fusion, SOS without any key, recommendations, detours when all routes are blocked, the admin lock, translation fallbacks and the AI model fallback. `TESTING.md` is a step by step checklist to test the whole app by hand with the Simulate panel.

What we measured on 27 September:
- News agent: 8 test headlines in French and Arabic, 6 real incidents kept, the football result and the 2003 anniversary ignored, 8.5 seconds. It put "A1 near Enfidha" 140 km away at first. We fixed the place cleaning and tested again.
- A fire dropped on the top suggested place (Zitouna Mosque) removed it from the suggestions in under 3 seconds.
- A road blocked in the middle of the Tunis to Hammamet highway: Rafiq found a clear detour (+39 min).
- Place photos load in 0.1 to 0.4 seconds.

## Responsible AI

- We never say a place is "safe". The positive status is "No reported issues".
- Every problem shows its source, confidence and age.
- One person or one news article can never mark a place "avoid" on its own.
- The AI never invents numbers (depths come from a fixed table) and summaries only use our own data.
- Photos are analysed and deleted, never stored. SOS alerts on the map are anonymous and rounded to about 100 m.
- No account. The phone gets a random ID only to stop spam.

## Known limits

- Live events are kept in memory, so they are lost when the server restarts.
- Alerts only work while the app is open (no push notifications yet).
- Flood photo depth is not measured against real labelled photos yet.
- Emergency numbers (197 police, 198 civil protection, 190 SAMU, 193 national guard) should be checked again before a real launch.

## What's next

Save events in a database, send push alerts when the app is closed, measure flood photo accuracy on real photos, and add a second country.

