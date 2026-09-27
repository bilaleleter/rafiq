import { useEffect, useMemo, useRef, useState } from "react";
import { api, streamHazards } from "./api.js";
import { Icon, StarMark, Wordmark, Toast } from "./ui.jsx";
import { TYPE, haversine, bearing } from "./hazardStyle.js";
import { I18nProvider, useT, LANG_NAME } from "./i18n.js";
import HazardMap from "./components/HazardMap.jsx";
import Sheet from "./components/Sheet.jsx";
import Onboarding from "./pages/Onboarding.jsx";
import { ExploreSheet, DestinationView, LiveFeed } from "./pages/Explore.jsx";
import Trip from "./pages/Trip.jsx";
import { HazardDetail, HazardFoot } from "./pages/HazardDetail.jsx";
import { ReportHub, FloodFlow, VideoFlow, PowerFlow, PowerWatchPrompt, QuickReport } from "./pages/Report.jsx";
import SOS from "./pages/SOS.jsx";
import { DataSources, MenuSheet } from "./pages/Menu.jsx";
import DevPanel from "./pages/DevPanel.jsx";

const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
const FILTERS = [["flood", "Flood"], ["fire", "Fire"], ["power", "Power"], ["storm", "Storm"], ["road", "Roads"], ["accident", "Accidents"], ["water", "Water"]];

export default function App() {
  const [prefs, setPrefsRaw] = useState(() => load("rafiq_prefs", { lang: "en", interests: ["beach", "history", "food"], contactName: "", contactPhone: "", theme: "system" }));
  const setPrefs = (p) => { setPrefsRaw(p); save("rafiq_prefs", p); };
  return <I18nProvider lang={prefs.lang}><Shell prefs={prefs} setPrefs={setPrefs} /></I18nProvider>;
}

function nearestIndex(coords, p) {
  let best = 0, bd = Infinity;
  coords.forEach(([la, lo], i) => { const d = (la - p.lat) ** 2 + (lo - p.lon) ** 2; if (d < bd) { bd = d; best = i; } });
  return best;
}

function Shell({ prefs, setPrefs }) {
  const { t, lang } = useT();
  const [onboarded, setOnboarded] = useState(() => load("rafiq_onboarded", false));
  const [config, setConfig] = useState(null);
  const [realMe, setRealMe] = useState(null);
  const [gpsState, setGpsState] = useState("idle");      // idle | asking | on | denied | unavailable
  const [events, setEvents] = useState([]);
  const [live, setLive] = useState(false);
  const [tab, setTab] = useState("explore");
  const [snap, setSnap] = useState("half");
  const [dest, setDest] = useState(null);
  const [target, setTarget] = useState(null);
  const [recs, setRecs] = useState(null);
  const [sel, setSel] = useState(null);
  const [feed, setFeed] = useState(false);
  const [flow, setFlow] = useState(null);       // {name:'flood'|'video'|'power', at}
  const [quick, setQuick] = useState(null);
  const [menu, setMenu] = useState(false);
  const [sources, setSources] = useState(false);
  const [layers, setLayers] = useState(false);
  const [hidden, setHidden] = useState([]);
  const [pitch, setPitch] = useState(45);
  const [routes, setRoutes] = useState(null);
  const [routeIndex, setRouteIndex] = useState(0);
  const [toast, setToastRaw] = useState(null);
  const [watch, setWatch] = useState(false);
  const [watchAsk, setWatchAsk] = useState(false);
  const [dark, setDark] = useState(false);
  const [follow, setFollow] = useState(true);
  // testing tools
  const [devOpen, setDevOpen] = useState(false);
  const [fakeGps, setFakeGps] = useState(() => load("rafiq_fake_gps", false));
  const [testLoc, setTestLoc] = useState(() => load("rafiq_test_loc", null));
  const [testLocSource, setTestLocSource] = useState(() => load("rafiq_test_loc_src", "Tunis"));
  const [pickMode, setPickMode] = useState(false);
  const [drive, setDrive] = useState({ on: false, km: 0 });
  const mapRef = useRef(null);
  const toastTimer = useRef(null);
  const watchId = useRef(null);
  const lastFix = useRef(null);
  const driveTimer = useRef(null);

  const toastFn = (x) => { setToastRaw(x); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToastRaw(null), 4000); };
  useEffect(() => { save("rafiq_fake_gps", fakeGps); }, [fakeGps]);
  useEffect(() => { if (testLoc) save("rafiq_test_loc", { lat: testLoc.lat, lon: testLoc.lon }); save("rafiq_test_loc_src", testLocSource); }, [testLoc?.lat, testLoc?.lon, testLocSource]);

  // theme
  useEffect(() => {
    const root = document.documentElement;
    if (prefs.theme === "light" || prefs.theme === "dark") root.dataset.theme = prefs.theme; else delete root.dataset.theme;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const upd = () => setDark(prefs.theme === "dark" || (prefs.theme !== "light" && mq.matches));
    upd(); mq.addEventListener("change", upd); return () => mq.removeEventListener("change", upd);
  }, [prefs.theme]);

  // config + live stream
  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig({ center: [36.8, 10.18], features: {} }));
    return streamHazards(setEvents, setLive);
  }, []);

  // location: one watcher for the whole session; heading from the GPS or from the last two fixes
  const requestLocation = () => {
    if (!navigator.geolocation) { setGpsState("unavailable"); return; }
    if (watchId.current != null) return;
    setGpsState("asking");
    watchId.current = navigator.geolocation.watchPosition((p) => {
      const c = p.coords;
      const fix = { lat: c.latitude, lon: c.longitude, accuracy: c.accuracy, speed: c.speed, at: p.timestamp || Date.now(), heading: null };
      const prev = lastFix.current;
      if (c.heading != null && !Number.isNaN(c.heading) && (c.speed == null || c.speed > 0.5)) fix.heading = c.heading;
      else if (prev && haversine(prev, fix) > 6) fix.heading = bearing(prev, fix);
      else if (prev?.heading != null && Date.now() - prev.at < 20000) fix.heading = prev.heading;
      lastFix.current = fix;
      setRealMe(fix); setGpsState("on");
    }, (err) => { setGpsState(err.code === 1 ? "denied" : "unavailable"); watchId.current = null; },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 });
  };
  useEffect(() => { if (onboarded) requestLocation(); }, [onboarded]);
  // A phone standing still may stop sending updates: re-read the position so "you are here" stays fresh.
  useEffect(() => {
    if (gpsState !== "on") return;
    const id = setInterval(() => navigator.geolocation.getCurrentPosition((p) => {
      setRealMe((m) => (m ? { ...m, lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy, at: p.timestamp || Date.now() } : m));
    }, () => {}, { maximumAge: 15000, timeout: 15000 }), 30000);
    return () => clearInterval(id);
  }, [gpsState]);

  const center = config?.center || [36.8, 10.18];
  const me = useMemo(() => {
    if (fakeGps && testLoc) return { ...testLoc, accuracy: 8, at: Number.MAX_SAFE_INTEGER, fake: true };
    return realMe || { lat: center[0], lon: center[1], at: 0, approx: true };
  }, [fakeGps, testLoc, realMe, center[0], center[1]]);
  const hasPosition = !!realMe || (fakeGps && !!testLoc);

  // follow the traveller while they move (off as soon as they pan the map)
  const flewOnce = useRef(false);
  useEffect(() => {
    if (!hasPosition) return;
    if (!flewOnce.current) { flewOnce.current = true; setTimeout(() => mapRef.current?.flyTo(me.lat, me.lon, 14), 500); return; }
    if (follow) mapRef.current?.panTo(me.lat, me.lon);
  }, [me.lat, me.lon, hasPosition]);

  // Power Watch: charging stops while watching -> ask
  useEffect(() => {
    if (!watch || !navigator.getBattery) return;
    let b, was;
    const on = () => { if (was && !b.charging) { setWatchAsk(true); navigator.vibrate?.([300, 100, 300]); } was = b.charging; };
    navigator.getBattery().then((x) => { b = x; was = x.charging; b.addEventListener("chargingchange", on); });
    return () => b?.removeEventListener("chargingchange", on);
  }, [watch]);

  // simulated driving along the active route (testing)
  const stopDrive = () => { clearInterval(driveTimer.current); driveTimer.current = null; setDrive((d) => ({ ...d, on: false })); };
  const driveKmh = useRef(0);
  const startDrive = (kmh) => {
    driveKmh.current = kmh;
    const r = routes?.[routeIndex];
    if (!r) return;
    const coords = r.coords;
    let i = nearestIndex(coords, me), pos = { lat: coords[i][0], lon: coords[i][1] }, done = 0, heading = 0;
    setFakeGps(true); setTestLocSource("driving"); setTestLoc(pos); setFollow(true); setDevOpen(false);
    clearInterval(driveTimer.current);
    const stepM = (kmh / 3.6) * 0.5;
    driveTimer.current = setInterval(() => {
      let left = stepM;
      const prev = pos;
      while (left > 0 && i < coords.length - 1) {
        const next = { lat: coords[i + 1][0], lon: coords[i + 1][1] };
        const d = haversine(pos, next);
        if (d <= left) { left -= d; done += d; pos = next; i++; }
        else { const f = left / d; pos = { lat: pos.lat + (next.lat - pos.lat) * f, lon: pos.lon + (next.lon - pos.lon) * f }; done += left; left = 0; }
      }
      if (haversine(prev, pos) > 0.5) heading = bearing(prev, pos);
      setTestLoc({ ...pos, heading, speed: kmh / 3.6 });
      setDrive({ on: true, km: done / 1000 });
      if (i >= coords.length - 1) stopDrive();
    }, 500);
  };
  useEffect(() => () => clearInterval(driveTimer.current), []);
  // rerouted ("Safer route") while driving: keep driving, on the new route
  useEffect(() => { if (driveTimer.current && routes?.[routeIndex]) startDrive(driveKmh.current); }, [routes, routeIndex]);

  const visibleEvents = useMemo(() => events.filter((e) => !hidden.includes(e.type === "wind" || e.type === "heat" ? "storm" : e.type === "health" || e.type === "crowd" ? "accident" : e.type)), [events, hidden]);
  const eventsVersion = useMemo(() => events.map((e) => e.id + e.severity).sort().join("|"), [events]);
  const flyTo = (lat, lon, z) => { setFollow(false); mapRef.current?.flyTo(lat, lon, z); };
  const openHazard = (e) => { setSel(e); setSnap("half"); setMenu(false); flyTo(e.lat, e.lon, 14); };
  const openPlace = (d) => { setDest(d); setSel(null); setFeed(false); setTab("explore"); setSnap("full"); flyTo(d.lat, d.lon, 14); };
  const goTab = (k) => { setTab(k); setSel(null); setMenu(false); setQuick(null); setFeed(false); if (k !== "trip") { setRoutes(null); } setSnap(k === "trip" ? "half" : snap === "peek" ? "half" : snap); };
  const planTrip = (d) => { setTarget(d); setDest(null); setTab("trip"); setSnap("half"); };
  const sendUpdate = (e) => { setSel(null); setFlow({ name: "flood", at: haversine(me, e) < 300 ? { lat: e.lat, lon: e.lon } : null }); };
  const demo = async (k) => {
    try {
      if (k === "scenario") { await api.demoScenario(); toastFn({ text: t("Simulated incidents added. They are labelled SIMULATED.") }); flyTo(36.4, 10.4, 8); }
      if (k === "flood") { await api.demoFlood(); toastFn({ text: t("Simulated flood replay started around Hammamet.") }); flyTo(36.39, 10.59, 12); }
      if (k === "reset") { await api.demoReset(); toastFn({ text: t("Simulated data cleared.") }); }
      setMenu(false);
    } catch (e) { toastFn({ text: e.message === "admin token required" ? e.message : t("Couldn't reach the server."), kind: "error" }); }
  };
  const liveSel = sel && (events.find((e) => e.id === sel.id) || sel);
  const cloudVoice = config?.features?.tts === "google";
  const devAvailable = !!config?.dev_mode;                       // full testing panel (traces, system)
  const simAvailable = devAvailable || !!config?.demo_mode;      // simulation panel (also in the public demo)
  const onMapClick = (p) => {
    if (!pickMode) return;
    setTestLoc(p); setTestLocSource("tapped on map"); setPickMode(false); setDevOpen(true);
  };

  if (!onboarded) return <Onboarding prefs={prefs} setPrefs={setPrefs} requestLocation={requestLocation}
    onDone={() => { setOnboarded(true); save("rafiq_onboarded", true); }} />;

  if (import.meta.env.DEV) window.__rafiqState = { routes: routes?.length, routeIndex, tab, target: target?.name, fakeGps, testLoc, drive };
  const tripActiveView = tab === "trip" && target;
  const showChrome = !tripActiveView && tab !== "sos";
  const gpsBanner = showChrome && config && !hasPosition && ["denied", "unavailable", "idle"].includes(gpsState);

  // ── sheet content ───────────────────────────────────────
  let sheet = null;
  if (menu) sheet = { body: <MenuSheet prefs={prefs} setPrefs={setPrefs} theme={prefs.theme} setTheme={(th) => setPrefs({ ...prefs, theme: th })} onClose={() => setMenu(false)}
    onSources={() => { setSources(true); setMenu(false); }} onDemo={demo} onResetOnboarding={() => { setOnboarded(false); save("rafiq_onboarded", false); }}
    devAvailable={simAvailable} devFull={devAvailable} onDev={() => { setMenu(false); setDevOpen(true); }} /> };
  else if (liveSel && tab !== "sos") sheet = { z: 12, body: <HazardDetail e={liveSel} me={me} onClose={() => setSel(null)} onSendPhoto={sendUpdate} />,
    foot: <HazardFoot e={liveSel} me={me} toast={toastFn} onDone={() => setSel(null)} onSendPhoto={sendUpdate} /> };
  else if (feed && tab !== "sos") sheet = { body: <LiveFeed events={events} me={me} onHazard={openHazard} onClose={() => setFeed(false)} /> };
  else if (tab === "explore") sheet = dest
    ? { body: <DestinationView d={dest} me={me} events={events} onClose={() => setDest(null)} onPlan={planTrip} dev={devAvailable}
        onOpen={openPlace} onHazard={openHazard} cloudVoice={cloudVoice} />,
        foot: <button className="btn btn-primary btn-block" onClick={() => planTrip(dest)}><Icon name="path" />{t("Plan my trip")}</button> }
    : { body: <ExploreSheet me={me} prefs={prefs} setPrefs={setPrefs} snap={snap} eventsVersion={eventsVersion} events={events} recs={recs} setRecs={setRecs}
        onOpen={openPlace} onHazard={openHazard} onLive={() => setFeed(true)} dev={devAvailable} toast={toastFn} /> };
  else if (tab === "report") sheet = quick
    ? { body: <QuickReport type={quick} me={me} onClose={() => setQuick(null)} onDone={(e) => { setQuick(null); toastFn({ text: t(e.reports_count > 1 ? "Report sent. {n} people reported this." : "Report sent. {n} person reported this.", { n: e.reports_count }) }); flyTo(e.lat, e.lon, 15); }} /> }
    : { body: <ReportHub onStart={(k, ty) => (k === "quick" ? setQuick(ty) : setFlow({ name: k }))} /> };
  else if (tab === "trip" && !target) sheet = { body: (
    <div className="col gap12" style={{ paddingTop: 8 }}><h2 className="h2">{t("Plan a trip")}</h2>
      <p className="sec" style={{ margin: 0 }}>{t("Choose a place in Explore. Rafiq checks every route against live reports and watches the road while you travel.")}</p>
      <button className="btn btn-primary" onClick={() => goTab("explore")}><Icon name="compass" />{t("Find a place")}</button></div>) };

  const places = tab === "explore" && !sel ? (dest ? [] : (recs?.recommended || []).slice(0, 40)) : [];

  return (
    <div className="app">
      <HazardMap ref={mapRef} config={config} dark={dark} events={visibleEvents} routes={tab === "trip" ? routes : null} routeIndex={routeIndex}
        target={target && tab === "trip" ? target : dest} me={hasPosition ? me : null} selectedId={sel?.id} onPick={openHazard}
        places={places} onPickPlace={openPlace} onMapClick={onMapClick} onUserPan={() => setFollow(false)} labels
        pickPoint={devOpen && testLoc && !fakeGps ? testLoc : null} />
      <div className="map-fade" />

      {!config && (
        <div className="col" style={{ position: "absolute", inset: 0, alignItems: "center", justifyContent: "center", gap: 12, zIndex: 3, paddingBottom: "40vh" }}>
          <StarMark size={32} spin /><span className="sec">{t("Loading live reports")}</span></div>
      )}

      {showChrome && (
        <header className="topbar">
          <span className="float-pill" style={{ padding: "0 16px" }}><Wordmark size={22} /></span>
          <button className="float-pill" onClick={() => { setFeed(true); setSel(null); setMenu(false); setSnap("half"); }} aria-label={t("Live reports")}>
            <span className={`live-dot ${live ? "" : "off"}`} />{live ? t(events.length === 1 ? "{n} live report" : "{n} live reports", { n: events.length }) : t("Offline")}</button>
          <span className="grow" />
          <button className="float-round small" onClick={() => setMenu(true)} aria-label={t("Language and settings")} style={{ fontSize: 12 }}>{prefs.lang.toUpperCase()}</button>
          <button className="float-round small" onClick={() => setMenu((m) => !m)} aria-label={t("Menu")}><Icon name="dots-three-vertical" bold /></button>
        </header>
      )}

      {gpsBanner && (
        <div className="card row gap12" style={{ position: "absolute", left: 16, right: 16, top: 64, zIndex: 5, padding: "8px 8px 8px 16px", boxShadow: "var(--shadow-float)", border: 0 }}>
          <Icon name="gps-slash" size={20} /><span className="sec grow" style={{ color: "var(--ink)" }}>{gpsState === "denied" ? t("Location blocked in the browser, showing Tunis") : t("Location off, showing Tunis")}</span>
          <button className="btn btn-sm" style={{ background: "var(--brand-soft)", color: "var(--brand)" }} onClick={() => { watchId.current = null; requestLocation(); }}>{t("Turn on")}</button></div>
      )}
      {showChrome && fakeGps && (
        <button className="fake-gps-pill" onClick={() => setDevOpen(true)}><Icon name="flask" size={14} />{t("Test position")}: {testLocSource}{drive.on ? ` · ${drive.km.toFixed(1)} km` : ""}</button>
      )}
      {pickMode && <div className="pick-hint"><Icon name="hand-tap" />{t("Tap the map to choose the test location")}<button className="link" onClick={() => { setPickMode(false); setDevOpen(true); }}>{t("Cancel")}</button></div>}

      {showChrome && (
        <div className="map-ctrls" style={{ top: gpsBanner ? 124 : 68 }}>
          <button className="float-round" onClick={() => setLayers((l) => !l)} aria-label={t("Layers")}><Icon name="stack" /></button>
          <button className="float-round" onClick={() => { const p = pitch ? 0 : 45; setPitch(p); mapRef.current?.setPitch(p); }} aria-label={t("Toggle 3D")}>{pitch ? "2D" : "3D"}</button>
          <button className={`float-round ${follow && hasPosition ? "on" : ""}`} onClick={() => { setFollow(true); mapRef.current?.flyTo(me.lat, me.lon, 15); }} aria-label={t("Recentre")} aria-pressed={follow}>
            <Icon name={follow && hasPosition ? "navigation-arrow" : "crosshair"} fill={follow && hasPosition} style={{ color: "var(--brand)" }} /></button>
        </div>
      )}
      {showChrome && layers && (
        <div className="card col gap8" style={{ position: "absolute", insetInlineEnd: 76, top: 68, zIndex: 14, padding: 14, width: 230, boxShadow: "var(--shadow-float)" }}>
          <span className="over">{t("Show on map")}</span>
          {FILTERS.map(([k, l]) => (
            <label key={k} className="between sec" style={{ color: "var(--ink)" }}>
              <span className="row gap8"><span className="hz-ic" style={{ "--c": `var(${TYPE[k].color})`, width: 28, height: 28 }}><Icon name={TYPE[k].icon} size={16} /></span>{t(l)}</span>
              <input type="checkbox" checked={!hidden.includes(k)} onChange={() => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k]))} />
            </label>
          ))}
          <span className="cap">{t("Estimated flooding is drawn faint and dashed. Observed water stands in 3D.")}</span>
        </div>
      )}

      {tripActiveView && (
        <Trip me={me} target={target} events={events} snap={snap} onSnap={setSnap} flyTo={flyTo} toast={toastFn} onHazard={openHazard} cloudVoice={cloudVoice}
          setMapRoutes={(r, i) => { setRoutes(r); setRouteIndex(i ?? 0); }}
          onActive={(a) => a && setFollow(true)}
          onExit={() => { stopDrive(); setTarget(null); setRoutes(null); setTab("explore"); setSnap("half"); }}
          onPickAlternative={(d) => { setTarget(d); toastFn({ text: t("Going to {name} instead.", { name: d.name }), kind: "info" }); }}
          onReportHere={() => { setTarget(null); setRoutes(null); setTab("report"); }} />
      )}

      {sheet && <Sheet snap={menu || sel || feed ? (snap === "peek" ? "half" : snap) : snap} onSnap={setSnap} foot={sheet.foot} style={sheet.z ? { zIndex: sheet.z } : undefined}>{sheet.body}</Sheet>}

      {tab === "sos" && <SOS me={me} numbers={config?.emergency_numbers} prefs={prefs} cloudVoice={cloudVoice} />}

      {sources && <DataSources events={events} onClose={() => setSources(false)} />}
      {flow?.name === "flood" && <FloodFlow me={me} at={flow.at} onClose={() => setFlow(null)} onDone={(z) => { setFlow(null); setTab("explore"); setSel(z); flyTo(z.lat, z.lon, 15); }} />}
      {flow?.name === "video" && <VideoFlow me={me} onClose={() => setFlow(null)} />}
      {flow?.name === "power" && <PowerFlow me={me} watch={watch} setWatch={setWatch} onClose={() => setFlow(null)} onDone={(e) => e && flyTo(e.lat, e.lon, 15)} />}
      {watchAsk && <PowerWatchPrompt onNo={() => setWatchAsk(false)} onYes={() => { setWatchAsk(false); api.power(me, "off", false, "watch").then(() => toastFn({ text: t("Power cut reported. Thanks.") })).catch((e) => toastFn({ text: e.message, kind: "error" })); }} />}

      {simAvailable && !pickMode && (
        <DevPanel open={devOpen} setOpen={setDevOpen} config={config} full={devAvailable} toast={toastFn} flyTo={flyTo}
          me={me} realMe={realMe} loc={testLoc || me} setLoc={setTestLoc} locSource={testLoc ? testLocSource : "your position"} setLocSource={setTestLocSource}
          fakeGps={fakeGps} setFakeGps={(v) => { if (v && !testLoc) setTestLoc({ lat: me.lat, lon: me.lon }); setFakeGps(v); if (!v) stopDrive(); }}
          pick={() => { setPickMode(true); setDevOpen(false); }} mapCenter={() => mapRef.current?.center()}
          route={tab === "trip" && routes ? routes[routeIndex] : null} drive={{ ...drive, start: startDrive, stop: stopDrive }} />
      )}

      <Toast toast={toast} />
      <div id="overlays" />

      <nav className="tabbar" aria-label={t("Main")}>
        {[["explore", "compass", "Explore"], ["trip", "path", "Trip"], ["report", "plus-circle", "Report"], ["sos", "siren", "SOS"]].map(([k, ic, l]) => (
          <button key={k} className={`tab ${tab === k ? "on" : ""} ${k === "sos" ? "sos" : ""}`} onClick={() => goTab(k)} aria-current={tab === k}>
            <Icon name={ic} fill={tab === k} /><span>{t(l)}</span></button>
        ))}
      </nav>
    </div>
  );
}

export { LANG_NAME };
