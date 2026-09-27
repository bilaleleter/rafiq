// Every backend call in one place. All paths are proxied to FastAPI by Vite in dev.
// VITE_ADMIN_TOKEN (frontend/.env.local) is sent to demo/simulation endpoints when the server requires it.
const ADMIN = import.meta.env.VITE_ADMIN_TOKEN || "";
// Where the backend lives. Empty in dev (Vite proxies /api). On Vercel: VITE_API_BASE=https://your-backend.onrender.com
export const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

async function j(path, opts = {}) {
  const headers = opts.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  if (ADMIN) headers["X-Admin-Token"] = ADMIN;
  const r = await fetch(API_BASE + path, { ...opts, headers });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { const d = (await r.json()).detail; detail = typeof d === "string" ? d : JSON.stringify(d) || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();
}
const post = (path, body) => j(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body) });
const qs = (o) => new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v != null && v !== ""))).toString();

// Anonymous device id (no account): lets the server count distinct phones and rate-limit spam.
export const DEVICE_ID = (() => {
  try {
    let id = localStorage.getItem("rafiq_device");
    if (!id) { id = crypto.randomUUID(); localStorage.setItem("rafiq_device", id); }
    return id;
  } catch { return "anon-" + Math.random().toString(36).slice(2); }
})();

export const photoUrl = (name, w = 480) => (name ? `${API_BASE}/api/places/photo?${qs({ name, w })}` : null);

export const api = {
  config: () => j("/api/public-config"),
  health: () => j("/api/health"),
  hazards: () => j("/api/hazards"),
  vote: (id, still_there) => post(`/api/hazards/${id}/vote`, { still_there }),
  recommend: (lat, lon, interests = [], lang = "en") =>
    j(`/api/destinations/recommend?${qs({ lat, lon, interests: interests.join(","), max_km: 150, lang })}`),
  checkDestination: (d) => j(`/api/destinations/check?${qs({ lat: d.lat, lon: d.lon, name: d.name, category: d.category || "sight" })}`),
  briefing: (d, lang) => post("/api/briefing", { lat: d.lat, lon: d.lon, name: d.name, lang }),
  planTrip: (origin, d, mode = "DRIVE") =>
    post("/api/trip/plan", { origin_lat: origin.lat, origin_lon: origin.lon, dest_lat: d.lat, dest_lon: d.lon,
      dest_name: d.name, dest_category: d.category || "sight", mode }),
  checkRoute: (coordinates) => post("/api/trip/check", { coordinates }),
  report: (type, me, note = "") => post("/api/reports", { type, lat: me.lat, lon: me.lon, accuracy_m: me.accuracy, note, device_id: DEVICE_ID }),
  power: (me, status, charger_verified = false, source = "tap") =>
    post("/api/power/report", { lat: me.lat, lon: me.lon, accuracy_m: me.accuracy, status, charger_verified, source, device_id: DEVICE_ID }),
  powerHistory: (lat, lon) => j(`/api/power/history?${qs({ lat, lon })}`),
  floodLink: (url, pin) => post("/api/flood/link", { url, lat: pin?.lat, lon: pin?.lon, device_id: DEVICE_ID }),
  webLog: () => j("/api/flood/web-log"),
  floodReport: (fd) => post("/api/flood/report", fd),
  sos: (body) => post("/api/sos", body),
  // places (Google, server-proxied)
  autocomplete: (input, me, session, lang) => j(`/api/places/autocomplete?${qs({ input, lat: me?.lat, lon: me?.lon, session, lang })}`),
  placeDetails: (id, me, session, lang) => j(`/api/places/details?${qs({ id, lat: me?.lat, lon: me?.lon, session, lang })}`),
  placeSearch: (q, me, lang) => j(`/api/places/search?${qs({ q, lat: me?.lat, lon: me?.lon, lang })}`),
  // language
  translate: (texts, target) => post("/api/translate", { texts, target }),
  tts: async (text, lang) => {
    const r = await fetch(API_BASE + "/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, lang }) });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.blob();
  },
  languageStatus: (force) => j(`/api/language/status?${qs({ force: force ? 1 : "" })}`),
  // demo + simulation lab (testing)
  demoScenario: () => post("/api/demo/scenario", {}),
  demoFlood: () => post("/api/flood/replay/start?speed=60", {}),
  demoReset: () => post("/api/sim/reset", {}),
  collectNow: () => post("/api/collect-now", {}),
  sim: {
    presets: () => j("/api/sim/presets"),
    scenario: (name, at, speed) => post("/api/sim/scenario", { name, lat: at?.lat, lon: at?.lon, speed }),
    hazard: (spec) => post("/api/sim/hazard", spec),
    crowd: (spec) => post("/api/sim/crowd", spec),
    weather: (spec) => post("/api/sim/weather", spec),
    rainModel: (spec) => post("/api/sim/rain-model", spec),
    news: (headlines) => post("/api/sim/news", { headlines }),
    floodPhoto: (fd) => post("/api/sim/flood-photo", fd),
    onRoute: (spec) => post("/api/sim/on-route", spec),
    reset: () => post("/api/sim/reset", {}),
  },
  debug: {
    state: () => j("/api/debug/state"),
    traces: (kind) => j(`/api/debug/traces?${qs({ kind })}`),
    clear: () => post("/api/debug/clear", {}),
  },
};

// Live hazards over Server-Sent Events -> onChange(eventsArray), onStatus(connected)
export function streamHazards(onChange, onStatus) {
  const map = new Map();
  const emit = () => onChange([...map.values()]);
  const es = new EventSource(API_BASE + "/api/stream");
  es.onopen = () => onStatus?.(true);
  es.onerror = () => onStatus?.(false);
  es.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.kind === "snapshot") { map.clear(); msg.events.forEach((e) => map.set(e.id, e)); }
    if (msg.kind === "upsert") map.set(msg.event.id, msg.event);
    if (msg.kind === "remove") map.delete(msg.id);
    onStatus?.(true);
    emit();
  };
  return () => es.close();
}

// Under-the-hood traces (testing panel) -> onTrace(trace), onRecent(list)
export function streamTraces(onTrace, onRecent) {
  const es = new EventSource(API_BASE + "/api/debug/stream");
  es.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.kind === "hello") onRecent?.(msg.recent);
    if (msg.kind === "trace") onTrace(msg.trace);
  };
  return () => es.close();
}
