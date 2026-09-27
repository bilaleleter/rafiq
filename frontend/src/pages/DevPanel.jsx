// Under the hood (TESTING TOOL — hidden when the server runs with DEV_MODE=0).
// Trace: every calculation, agent step, AI call and API call, live from the server.
// Simulate: make things happen anywhere in Tunisia through the real pipelines.
// System: AI models, Google usage, translation/voice providers, collectors, store.
// Deliberately English-only: it is for the team, not for travellers.
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api, streamTraces } from "../api.js";
import { Icon } from "../ui.jsx";
import { haversine } from "../hazardStyle.js";

const KINDS = { calc: ["function", "--brand"], agent: ["robot", "--cyan"], llm: ["cpu", "--sky"], collector: ["broadcast", "--clear"],
  report: ["users-three", "--water"], sim: ["flask", "--caution"], api: ["plugs-connected", "--ink-2"] };
const PLACES = [["Tunis", 36.8008, 10.1800], ["Sidi Bou Said", 36.8702, 10.3417], ["Hammamet", 36.4000, 10.6167], ["Nabeul", 36.4561, 10.7376],
  ["Sousse", 35.8256, 10.6360], ["Sfax", 34.7406, 10.7603], ["Djerba", 33.8076, 10.8451], ["Tozeur", 33.9197, 8.1335], ["Aïn Draham", 36.7756, 8.6836],
  ["Bizerte", 37.2744, 9.8739]];
const TYPES = ["accident", "road", "flood", "fire", "power", "water", "storm", "wind", "heat", "earthquake", "health", "crowd", "other"];
const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Json({ v }) {
  if (v == null || (typeof v === "object" && !Object.keys(v).length)) return null;
  return <pre className="dev-json">{typeof v === "string" ? v : JSON.stringify(v, null, 2)}</pre>;
}

function TraceCard({ tr, onRef }) {
  const [open, setOpen] = useState(false);
  const [ic, c] = KINDS[tr.kind] || ["info", "--ink-2"];
  return (
    <div className={`dev-trace ${tr.ok ? "" : "bad"}`}>
      <button className="dev-trace-head" onClick={() => setOpen((o) => !o)}>
        <span className="dev-kind" style={{ "--c": `var(${c})` }}><Icon name={ic} size={14} />{tr.kind}</span>
        <span className="grow dev-title">{tr.title}</span>
        {!tr.ok && <Icon name="warning-circle" fill style={{ color: "var(--avoid)" }} />}
        <span className="dev-meta">{tr.ms != null ? `${tr.ms} ms` : ""}<br />{clock(tr.at)}</span>
      </button>
      {open && (
        <div className="dev-trace-body">
          <Json v={tr.data} />
          {tr.steps.map((s, i) => (
            <div key={i} className="dev-step">
              <span className="dev-t">+{s.t_ms}ms</span>
              <div className="grow">
                <span className={s.data?.ref ? "link" : ""} onClick={() => s.data?.ref && onRef(s.data.ref)}>{s.label}</span>
                {s.data && !s.data.ref && <details><summary>data</summary><Json v={s.data} /></details>}
              </div>
            </div>
          ))}
          <span className="cap">#{tr.id}{tr.parent ? ` · inside #${tr.parent}` : ""}</span>
        </div>
      )}
    </div>
  );
}

function TraceTab({ traces, setTraces, paused, setPaused }) {
  const [kind, setKind] = useState("all");
  const [q, setQ] = useState("");
  const [focus, setFocus] = useState(null);
  const list = useMemo(() => traces.filter((t) => (kind === "all" || t.kind === kind) && (!focus || t.id === focus || t.parent === focus)
    && (!q || JSON.stringify(t).toLowerCase().includes(q.toLowerCase()))), [traces, kind, q, focus]);
  return (
    <div className="col gap8">
      <div className="chips hide-scroll">
        {["all", ...Object.keys(KINDS)].map((k) => <button key={k} className={`chip ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>{k}
          <span className="faint">{k === "all" ? traces.length : traces.filter((t) => t.kind === k).length}</span></button>)}
      </div>
      <div className="row gap8">
        <input className="input" style={{ height: 40 }} placeholder="Filter (text, place, model…)" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-secondary btn-sm" onClick={() => setPaused((p) => !p)}><Icon name={paused ? "play" : "pause"} />{paused ? "Resume" : "Pause"}</button>
        <button className="btn btn-secondary btn-sm" onClick={() => { api.debug.clear(); setTraces([]); }}><Icon name="trash" /></button>
      </div>
      {focus && <button className="chip on" onClick={() => setFocus(null)}>Showing #{focus} and its children · show all</button>}
      {list.length === 0 && <p className="sec">Nothing yet. Use the app or the Simulate tab: every step appears here live.</p>}
      {list.slice(0, 200).map((t) => <TraceCard key={t.id} tr={t} onRef={setFocus} />)}
    </div>
  );
}

function Card({ title, icon, children, hint }) {
  return (
    <div className="dev-card">
      <div className="row gap8"><Icon name={icon} size={18} /><span className="strong">{title}</span></div>
      {hint && <span className="cap">{hint}</span>}
      {children}
    </div>
  );
}
const Slider = ({ label, v, set, min, max, step = 1, unit = "" }) => (
  <label className="dev-slider"><span className="between cap"><span>{label}</span><b className="tnum">{v}{unit}</b></span>
    <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => set(+e.target.value)} /></label>
);
const Select = ({ v, set, options }) => (
  <select className="input" style={{ height: 40 }} value={v} onChange={(e) => set(e.target.value)}>{options.map((o) => <option key={o} value={o}>{o}</option>)}</select>
);

function SimTab({ loc, setLoc, locSource, setLocSource, me, realMe, fakeGps, setFakeGps, pick, route, drive, toast, flyTo, mapCenter, onDone }) {
  const [busy, setBusy] = useState(null);
  const [out, setOut] = useState({});
  const [presets, setPresets] = useState(null);
  const [hz, setHz] = useState({ type: "accident", severity: "danger", confidence: 0.8, radius_m: 400 });
  const [crowd, setCrowd] = useState({ type: "road", devices: 3, body_level: "person_knee", charger_verified: false, slow: false });
  const [wx, setWx] = useState({ rain_mm_h: 20, gust_kmh: 0, feels_like_c: 0, river_ratio: 0 });
  const [rain, setRain] = useState({ rain_mm: 60, terrain: "real" });
  const [news, setNews] = useState("");
  const [speed, setSpeed] = useState(60);
  const [onRouteType, setOnRouteType] = useState("accident");
  const [driveSpeed, setDriveSpeed] = useState(120);
  const photoRef = useRef(null);
  useEffect(() => { api.sim.presets().then((p) => { setPresets(p); setNews(p.headlines.join("\n")); }).catch(() => {}); }, []);

  const run = async (key, fn, after) => {
    setBusy(key);
    try { const r = await fn(); setOut((o) => ({ ...o, [key]: r })); after?.(r); onDone?.(key); }
    catch (e) { setOut((o) => ({ ...o, [key]: { error: e.message } })); toast({ text: `${key}: ${e.message}`, kind: "error" }); }
    finally { setBusy(null); }
  };
  const at = { lat: loc.lat, lon: loc.lon };
  const B = ({ k, children, onClick, kind = "btn-secondary", disabled }) => (
    <button className={`btn btn-sm ${kind}`} disabled={!!busy || disabled} onClick={onClick}>
      {busy === k ? <Icon name="circle-notch" style={{ animation: "rfq-spin 1s linear infinite" }} /> : null}{children}</button>);

  return (
    <div className="col gap12">
      <Card title="Test location" icon="crosshair-simple" hint="Everything below happens here. Pretend GPS moves you (and the route guardian) too.">
        <span className="tnum sec" style={{ color: "var(--ink)" }}>{loc.lat.toFixed(4)}, {loc.lon.toFixed(4)} · {locSource}
          {realMe && ` · ${(haversine(realMe, loc) / 1000).toFixed(1)} km from your real GPS`}</span>
        <div className="chips" style={{ flexWrap: "wrap" }}>
          <button className="chip" onClick={() => { setLoc(realMe || me); setLocSource("my GPS"); }} disabled={!realMe && !me}><Icon name="gps-fix" />My GPS</button>
          <button className="chip" onClick={() => { const c = mapCenter(); if (c) { setLoc(c); setLocSource("map centre"); } }}><Icon name="map-trifold" />Map centre</button>
          <button className="chip" onClick={pick}><Icon name="hand-tap" />Tap on map</button>
          {PLACES.map(([n, la, lo]) => <button key={n} className="chip" onClick={() => { setLoc({ lat: la, lon: lo }); setLocSource(n); flyTo(la, lo, 12); }}>{n}</button>)}
        </div>
        <label className="between sec" style={{ color: "var(--ink)" }}><span className="col"><span className="strong">Pretend I'm here (fake GPS)</span>
          <span className="cap">Recommendations, reports, SOS and the trip use this position.</span></span>
          <button className={`switch brand ${fakeGps ? "on" : ""}`} aria-pressed={fakeGps} onClick={() => setFakeGps(!fakeGps)} /></label>
      </Card>

      <Card title="Scenarios" icon="stack" hint="Ready-made situations. All data is SIMULATED and goes through the real pipelines.">
        <div className="grid2">
          <B k="around" onClick={() => run("around", () => api.sim.scenario("around_me", at), () => flyTo(loc.lat, loc.lon, 13))}>Mix around here</B>
          <B k="floodhere" onClick={() => run("floodhere", () => api.sim.scenario("flood_here", at, speed), () => flyTo(loc.lat, loc.lon, 15))}>Rising flood here</B>
          <B k="country" onClick={() => run("country", () => api.sim.scenario("country"), () => flyTo(35.8, 9.8, 7))}>Across Tunisia</B>
          <B k="hammamet" onClick={() => run("hammamet", () => api.sim.scenario("flood_hammamet", null, speed), () => flyTo(36.39, 10.59, 13))}>Hammamet flood</B>
        </div>
        <div className="row gap8"><span className="cap">Flood replay speed</span>
          {[60, 180, 600].map((s) => <button key={s} className={`chip ${speed === s ? "on" : ""}`} onClick={() => setSpeed(s)}>x{s}</button>)}</div>
        <B k="reset" kind="btn-outline" onClick={() => run("reset", () => api.sim.reset())}><Icon name="trash" />Clear all simulated data</B>
        {out.around?.progression && <Json v={out.around.progression.map((p) => `phone ${p.phone}: ${p.severity} ${Math.round(p.confidence * 100)}% -> ${p.status}`)} />}
      </Card>

      <Card title="One hazard" icon="map-pin-plus" hint="Status rule: 'avoid' needs danger/critical AND confidence ≥ 50%. Try 40% to see it stay 'caution'.">
        <div className="grid2"><Select v={hz.type} set={(v) => setHz({ ...hz, type: v })} options={TYPES} />
          <Select v={hz.severity} set={(v) => setHz({ ...hz, severity: v })} options={["info", "warning", "danger", "critical"]} /></div>
        <Slider label="Confidence" v={hz.confidence} set={(v) => setHz({ ...hz, confidence: v })} min={0.05} max={0.95} step={0.05} />
        <Slider label="Radius" v={hz.radius_m} set={(v) => setHz({ ...hz, radius_m: v })} min={100} max={10000} step={100} unit=" m" />
        <B k="hazard" kind="btn-primary" onClick={() => run("hazard", () => api.sim.hazard({ ...hz, ...at }), () => flyTo(loc.lat, loc.lon, 14))}>Drop it here</B>
        {out.hazard && <span className="sec">{out.hazard.error || `Status rule -> ${out.hazard.status_rule}`}</span>}
      </Card>

      <Card title="Crowd: several phones report" icon="users-three" hint="Same merge rules as real users: 1 report 35% (caution), 2 -> 60%, 3+ -> 80% and roads/accidents/fires escalate to danger.">
        <div className="grid2"><Select v={crowd.type} set={(v) => setCrowd({ ...crowd, type: v })} options={["road", "accident", "fire", "water", "health", "crowd", "power", "flood"]} />
          {crowd.type === "flood" ? <Select v={crowd.body_level} set={(v) => setCrowd({ ...crowd, body_level: v })} options={["person_ankle", "person_mid_calf", "person_knee", "person_thigh", "person_waist"]} />
            : crowd.type === "power" ? <label className="row gap8 cap"><input type="checkbox" checked={crowd.charger_verified} onChange={(e) => setCrowd({ ...crowd, charger_verified: e.target.checked })} />charger-verified</label> : <span />}</div>
        <Slider label="Phones" v={crowd.devices} set={(v) => setCrowd({ ...crowd, devices: v })} min={1} max={8} />
        <label className="row gap8 cap"><input type="checkbox" checked={crowd.slow} onChange={(e) => setCrowd({ ...crowd, slow: e.target.checked })} />one report every 5 s (watch the map change)</label>
        <B k="crowd" kind="btn-primary" onClick={() => run("crowd", () => api.sim.crowd({ type: crowd.type, devices: crowd.devices, body_level: crowd.body_level,
          charger_verified: crowd.charger_verified, interval_s: crowd.slow ? 5 : 0, ...at }), () => flyTo(loc.lat, loc.lon, 15))}>Send reports</B>
        {out.crowd?.progression && <Json v={out.crowd.progression.map((p) => `phone ${p.phone}: ${p.severity} ${Math.round(p.confidence * 100)}% -> ${p.status}`)} />}
        {out.crowd?.started && <span className="sec">Reports arriving every 5 s. Watch the map and the Trace tab.</span>}
      </Card>

      <Card title="Weather readings" icon="cloud-lightning" hint="Thresholds: rain 7.5/15/30 mm/h · gusts 60/80/100 km/h · feels-like 38/42/46 °C · river 2/4/8× normal.">
        <Slider label="Rain" v={wx.rain_mm_h} set={(v) => setWx({ ...wx, rain_mm_h: v })} min={0} max={50} unit=" mm/h" />
        <Slider label="Wind gusts" v={wx.gust_kmh} set={(v) => setWx({ ...wx, gust_kmh: v })} min={0} max={130} unit=" km/h" />
        <Slider label="Feels-like" v={wx.feels_like_c} set={(v) => setWx({ ...wx, feels_like_c: v })} min={0} max={50} unit=" °C" />
        <Slider label="River discharge" v={wx.river_ratio} set={(v) => setWx({ ...wx, river_ratio: v })} min={0} max={10} step={0.5} unit="× normal" />
        <B k="weather" kind="btn-primary" onClick={() => run("weather", () => api.sim.weather({ ...wx, ...at, name: locSource }), () => flyTo(loc.lat, loc.lon, 11))}>Apply readings</B>
        {out.weather && <span className="sec">{out.weather.error || `${out.weather.events.length} event(s): ${out.weather.events.map((e) => `${e.severity} ${e.type}`).join(", ") || "nothing crossed a threshold"}`}</span>}
      </Card>

      <Card title="Terrain flood model" icon="mountains" hint="Made-up rain + REAL elevation around the place: low ground that would pool water shows as faint dashed 'estimated' flooding.">
        <Slider label="Rain (last 6 h + next 3 h)" v={rain.rain_mm} set={(v) => setRain({ ...rain, rain_mm: v })} min={10} max={150} unit=" mm" />
        <div className="seg">{["real", "bowl"].map((k) => <button key={k} className={rain.terrain === k ? "on" : ""} onClick={() => setRain({ ...rain, terrain: k })}>{k === "real" ? "Real terrain" : "Synthetic bowl"}</button>)}</div>
        <B k="rain" kind="btn-primary" onClick={() => run("rain", () => api.sim.rainModel({ ...rain, ...at, name: locSource }), () => flyTo(loc.lat, loc.lon, 14))}>Run the model</B>
        {out.rain && <span className="sec">{out.rain.error || `${out.rain.events.length} estimated flood cell(s)`}</span>}
      </Card>

      <Card title="News agent (AI)" icon="newspaper" hint="Your headlines -> the real AI extraction -> geocoding -> map. It should ignore sport and past events, and news alone is capped at 50% confidence.">
        <textarea className="input" rows={6} style={{ fontSize: 13 }} value={news} onChange={(e) => setNews(e.target.value)} />
        <B k="news" kind="btn-primary" disabled={presets && !presets.llm} onClick={() => run("news", () => api.sim.news(news.split("\n").filter((x) => x.trim())), () => flyTo(35.8, 9.8, 7))}>Run the agent</B>
        {presets && !presets.llm && <span className="cap">Needs LLM_API_KEY.</span>}
        {out.news && (out.news.error ? <span className="sec">{out.news.error}</span> : <Json v={out.news.events.map((e) => `${e.type}/${e.severity} ${Math.round(e.confidence * 100)}% · ${e.title} · ${e.data?.place}`)} />)}
      </Card>

      <Card title="Flood photo (vision AI)" icon="image" hint="Any photo, placed at the test location. The model picks WHERE the waterline sits; code turns that into cm. EXIF date check is skipped here.">
        <input ref={photoRef} type="file" accept="image/*" hidden onChange={(e) => {
          const f = e.target.files[0]; if (!f) return;
          const fd = new FormData(); fd.append("lat", loc.lat); fd.append("lon", loc.lon); fd.append("photo", f);
          run("photo", () => api.sim.floodPhoto(fd), (r) => r.accepted && flyTo(loc.lat, loc.lon, 15)); e.target.value = "";
        }} />
        <B k="photo" kind="btn-primary" onClick={() => photoRef.current.click()}><Icon name="upload-simple" />Choose a photo</B>
        {out.photo && <Json v={out.photo.error || { accepted: out.photo.accepted, depth_cm: out.photo.depth_cm, reason: out.photo.reason, analysis: out.photo.analysis }} />}
      </Card>

      <Card title="Trip and route guardian" icon="path" hint={route ? `Active route: ${(route.distance_m / 1000).toFixed(1)} km. Start the trip, then drive it here.` : "Plan a trip first (Explore -> a place -> Plan my trip)."}>
        <div className="row gap8"><Select v={onRouteType} set={setOnRouteType} options={["accident", "road", "flood", "fire"]} />
          <B k="onroute" disabled={!route} onClick={() => run("onroute", () => api.sim.onRoute({ coordinates: route.coords, type: onRouteType, at_fraction: 0.6 }))}>Drop on route ahead</B></div>
        <div className="row gap8"><span className="cap">Drive speed</span>{[50, 120, 400, 1500].map((s) => <button key={s} className={`chip ${driveSpeed === s ? "on" : ""}`} onClick={() => setDriveSpeed(s)}>{s} km/h</button>)}</div>
        <div className="grid2">
          <B k="drive" kind="btn-primary" disabled={!route || drive.on} onClick={() => drive.start(driveSpeed)}><Icon name="car-profile" />Drive the route</B>
          <B k="stopdrive" disabled={!drive.on} onClick={drive.stop}><Icon name="stop" />Stop</B></div>
        {drive.on && <span className="sec tnum">Driving… {drive.km.toFixed(1)} km done. The alert banner should appear before the hazard.</span>}
        {out.onroute && <span className="sec">{out.onroute.error || `Hazard placed at km ${out.onroute.km}.`}</span>}
      </Card>

      <Card title="Real collectors" icon="broadcast" hint="Runs weather, rivers, NASA fires, earthquakes, the news agent and the terrain model once, on real live data.">
        <B k="collect" kind="btn-primary" onClick={() => run("collect", () => api.collectNow())}><Icon name="arrows-clockwise" />Run all collectors now</B>
        {out.collect && <Json v={out.collect.error || Object.fromEntries(Object.entries(out.collect.sources).map(([k, s]) => [k, s.ok ? `${s.events ?? s.accepted ?? 0} items, ${s.seconds ?? "?"} s` : `FAILED: ${s.error}`]))} />}
      </Card>
    </div>
  );
}

function SystemTab({ config }) {
  const [s, setS] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const load = () => api.debug.state().then((x) => { setS(x); setErr(null); }).catch((e) => setErr(e.message));
    load(); const id = setInterval(load, 5000); return () => clearInterval(id);
  }, []);
  if (err) return <p className="sec">{err}</p>;
  if (!s) return <p className="sec">Loading…</p>;
  const ago = (ts) => (ts ? `${Math.round(Date.now() / 1000 - ts)} s ago` : "never");
  const lang = s.language;
  return (
    <div className="col gap12">
      <Card title="AI models (NVIDIA)" icon="cpu">
        <div className="dev-kv"><span>Key</span><b>{s.ai.key ? "set" : "missing"}</b><span>Text</span><b>{s.ai.text_model}</b><span>Vision</span><b>{s.ai.vision_model}</b>
          <span>Fallbacks</span><b>{[...s.ai.fallbacks.text, ...s.ai.fallbacks.vision].join(", ")}</b>
          {Object.entries(s.ai.last_ok).map(([k, v]) => <Fragment key={k}><span>Last {k} OK</span><b>{v.model} · {v.ms} ms · {ago(v.at)}</b></Fragment>)}
          {Object.entries(s.ai.cooling_down).map(([m, sec]) => <Fragment key={m}><span>Cooling down</span><b style={{ color: "var(--caution)" }}>{m} ({sec} s)</b></Fragment>)}</div>
      </Card>
      <Card title="Language" icon="translate">
        <div className="dev-kv"><span>Translation</span><b>{{ google: "Google Cloud Translation", ai: "AI model (Google Translate not enabled)", none: "none: English only" }[lang.translate]}</b>
          <span>Voice</span><b>{lang.tts === "google" ? "Google Cloud Text-to-Speech" : "Phone's own voice (Cloud TTS not enabled)"}</b></div>
        {Object.entries(lang.errors || {}).map(([k, v]) => <span key={k} className="cap" style={{ color: "var(--caution)" }}>{k}: {v}</span>)}
        {(lang.translate !== "google" || lang.tts !== "google") && <span className="cap">To enable: Google Cloud console → APIs & Services → enable "Cloud Translation API" and "Cloud Text-to-Speech API" → Credentials → your server key → API restrictions → add both.</span>}
      </Card>
      <Card title="Google Maps Platform" icon="map-trifold">
        <div className="dev-kv"><span>Server key</span><b>{s.google.server_key ? "set" : "missing"}</b><span>Browser key</span><b>{s.google.browser_key ? "set" : "missing"}</b>
          {Object.entries(s.google.usage).map(([k, v]) => <Fragment key={k}><span>{k.replaceAll("_", " ")}</span><b>{v}</b></Fragment>)}
          <span>Cached queries / photos</span><b>{s.google.cached_queries} / {s.google.cached_photos}</b></div>
      </Card>
      <Card title="Live events" icon="broadcast">
        <div className="dev-kv"><span>Total</span><b>{s.events.total} ({s.events.simulated} simulated)</b>
          <span>By status</span><b>{Object.entries(s.events.by_status).map(([k, v]) => `${k} ${v}`).join(" · ") || "-"}</b>
          <span>By source</span><b>{Object.entries(s.events.by_source).map(([k, v]) => `${k} ${v}`).join(" · ") || "-"}</b>
          <span>By type</span><b>{Object.entries(s.events.by_type).map(([k, v]) => `${k} ${v}`).join(" · ") || "-"}</b></div>
      </Card>
      <Card title="Collectors" icon="clock-clockwise">
        <div className="dev-kv"><span>Every</span><b>{s.collectors.every_min} min · {s.collectors.watch_points} watched places</b>
          <span>Last round</span><b>{s.collectors.last_round.at ? `${ago(s.collectors.last_round.at)} · ${s.collectors.last_round.seconds} s` : "not yet"}{s.collectors.last_round.running ? " · running" : ""}</b>
          {Object.entries(s.collectors.health).map(([k, v]) => <Fragment key={k}><span>{k}</span><b style={{ color: v.ok ? "var(--ink)" : "var(--avoid)" }}>{v.ok ? `${v.events ?? v.accepted ?? 0} · ${ago(v.last_run)}` : `FAILED ${v.error}`}</b></Fragment>)}</div>
      </Card>
      <Card title="Fusion state" icon="waves">
        <div className="dev-kv"><span>Flood zones</span><b>{s.flood_zones.map((z) => `${z.id} (${z.reports}${z.simulated ? ", sim" : ""})`).join(" · ") || "-"}</b>
          <span>Power cells</span><b>{s.power_cells.map((c) => `${c.cell}: ${c.devices_off} off`).join(" · ") || "-"}</b>
          <span>Devices seen</span><b>{s.trust.devices_seen}</b><span>Traces buffered</span><b>{s.traces_buffered}</b></div>
      </Card>
      <Card title="App" icon="gear">
        <div className="dev-kv"><span>Dev mode</span><b>{String(config?.dev_mode)}</b><span>Admin token</span><b>{config?.admin_required ? "required" : "not set (open)"}</b>
          <span>Map</span><b>{config?.google_maps_key ? "Google vector" : "CARTO fallback"}</b></div>
      </Card>
    </div>
  );
}

export default function DevPanel({ open, setOpen, config, full = true, ...sim }) {
  const [tab, setTab] = useState(full ? "trace" : "sim");
  const [traces, setTraces] = useState([]);
  const [paused, setPaused] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const pausedRef = useRef(paused); pausedRef.current = paused;
  const openRef = useRef(open); openRef.current = open;
  useEffect(() => (full ? streamTraces(
    (t) => { if (pausedRef.current) return; setTraces((l) => [t, ...l].slice(0, 400)); if (!openRef.current) setUnseen((n) => n + 1); },
    (recent) => setTraces(recent)) : undefined), [full]);
  useEffect(() => { if (open) setUnseen(0); }, [open]);

  if (!open) return (
    <button className="dev-fab" onClick={() => setOpen(true)} aria-label={full ? "Open under the hood" : "Simulate live problems"}>
      <Icon name={full ? "terminal-window" : "flask"} size={20} />{unseen > 0 && <span className="dev-badge">{unseen > 99 ? "99+" : unseen}</span>}
    </button>
  );
  return (
    <aside className="dev-drawer" dir="ltr" aria-label="Under the hood">
      <div className="between" style={{ padding: "12px 16px 8px" }}>
        <div className="col"><span className="h3">{full ? "Under the hood" : "Simulate live problems"}</span>
          <span className="cap">{full ? "Testing tool · hidden when DEV_MODE=0" : "Demo tool · everything made here is labelled SIMULATED"}</span></div>
        <div className="row gap8">
          <button className="float-round small" style={{ boxShadow: "none", background: "var(--surface-2)" }} onClick={() => setOpen(false)} aria-label="Hide to watch the map"><Icon name="arrows-in-simple" /></button>
        </div>
      </div>
      {full && <div style={{ padding: "0 16px 8px" }}><div className="seg">{[["trace", "Trace"], ["sim", "Simulate"], ["system", "System"]].map(([k, l]) =>
        <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div></div>}
      <div className="dev-body">
        {tab === "trace" && <TraceTab traces={traces} setTraces={setTraces} paused={paused} setPaused={setPaused} />}
        {tab === "sim" && <SimTab {...sim} onDone={() => {}} />}
        {tab === "system" && <SystemTab config={config} />}
      </div>
    </aside>
  );
}
