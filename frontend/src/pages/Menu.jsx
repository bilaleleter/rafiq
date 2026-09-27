// H · Settings menu and Data sources (transparency).
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Icon, BackHeader, StatusPill } from "../ui.jsx";
import { LANGS, useT } from "../i18n.js";

const SOURCES = [
  ["open-meteo", "Weather forecast", "cloud-rain"], ["open-meteo-flood", "River forecast", "waves"], ["firms", "NASA fires", "fire"],
  ["usgs", "Earthquakes", "wave-sine"], ["news", "News agent", "newspaper"], ["web-photos", "Web videos", "video-camera"],
  ["model", "Terrain model", "mountains"],
];

export function DataSources({ onClose, events }) {
  const { t } = useT();
  const [h, setH] = useState(null);
  const [log, setLog] = useState([]);
  const agoTs = (ts) => { if (!ts) return t("not run yet"); const m = Math.round((Date.now() / 1000 - ts) / 60); return m <= 0 ? t("just now") : m < 60 ? t("{n} min ago", { n: m }) : t("{n} h ago", { n: Math.round(m / 60) }); };
  useEffect(() => {
    const load = () => { api.health().then(setH).catch(() => setH({ error: true })); api.webLog().then(setLog).catch(() => {}); };
    load(); const id = setInterval(load, 15000); return () => clearInterval(id);
  }, []);
  const crowd = events.filter((e) => e.source === "crowd").length;
  const delayed = h?.sources ? Object.values(h.sources).filter((s) => !s.ok).length : 0;
  return (
    <div className="screen">
      <BackHeader onBack={onClose} />
      <div className="screen-body col gap4" style={{ paddingTop: 8 }}>
        <h1 className="h1">{t("Data sources")}</h1>
        <p className="sec" style={{ margin: "4px 0 16px" }}>{t("Everything Rafiq shows comes from these.")}{delayed ? ` ${t("{n} delayed.", { n: delayed })}` : ""}</p>
        {h?.error && <p className="sec">{t("Server unreachable.")}</p>}
        {SOURCES.map(([k, name, ic]) => {
          const s = h?.sources?.[k];
          const off = !s ? (k === "firms" && h && !h.firms) || (k === "web-photos" && h && !h.llm) : false;
          return (
            <div key={k} className="list-row" style={{ alignItems: "center" }}>
              <Icon name={ic} size={22} className="muted" />
              <div className="col grow"><span className="strong">{t(name)}</span>
                <span className="cap row gap4"><span className="dot-s" style={{ background: off ? "var(--unknown)" : s?.ok === false ? "var(--caution)" : s ? "var(--clear)" : "var(--unknown)" }} />
                  {off ? t("Not configured") : s?.ok === false ? `${t("Delayed")} · ${s.error?.slice(0, 40)}` : s ? t("Updated {when}", { when: agoTs(s.last_run) }) : t("Waiting for first run")}</span></div>
              <span className="cap strong tnum">{s?.events != null ? t("{n} items", { n: s.events }) : s?.accepted != null ? t("{n} accepted", { n: s.accepted }) : ""}</span>
            </div>
          );
        })}
        <div className="list-row" style={{ alignItems: "center" }}><Icon name="users-three" size={22} className="muted" />
          <div className="col grow"><span className="strong">{t("Traveller reports")}</span><span className="cap row gap4"><span className="dot-s" style={{ background: "var(--clear)" }} />{t("Live")}</span></div>
          <span className="cap strong">{t("{n} now", { n: crowd })}</span></div>
        {h && <div className="row gap8" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <StatusPill status={h.llm ? "clear" : "unknown"} label={h.llm ? t("AI model connected") : t("AI model not set")} />
          <StatusPill status={h.google ? "clear" : "unknown"} label={h.google ? t("Google connected") : t("Google not set")} /></div>}
        {log.length > 0 && <>
          <span className="over" style={{ marginTop: 24 }}>{t("Web video checks")}</span>
          {log.slice(0, 12).map((l, i) => (
            <div key={i} className="list-row"><Icon name={l.accepted ? "check-circle" : "x-circle"} fill size={20} style={{ color: l.accepted ? "var(--clear)" : "var(--avoid)" }} />
              <div className="col grow"><span className="strong ellipsis" style={{ fontSize: 14 }}>{l.title || l.url}</span><span className="cap">{l.platform} · {l.reason}</span></div></div>
          ))}
        </>}
      </div>
    </div>
  );
}

export function MenuSheet({ prefs, setPrefs, onClose, onSources, onDemo, onResetOnboarding, theme, setTheme, devAvailable, devFull, onDev }) {
  const { t, loading, failed } = useT();
  return (
    <div className="col gap16" style={{ paddingTop: 4 }}>
      <div className="between"><h2 className="h2">{t("Settings")}</h2><button className="float-round small" style={{ boxShadow: "none", background: "var(--surface-2)" }} onClick={onClose} aria-label={t("Close")}><Icon name="x" /></button></div>
      <div className="col gap8"><span className="over">{t("Language")}</span>
        <div className="chips hide-scroll" style={{ flexWrap: "wrap" }}>
          {LANGS.map(([n, , c]) => <button key={c} className={`chip ${prefs.lang === c ? "on" : ""}`} onClick={() => setPrefs({ ...prefs, lang: c })}>{n}</button>)}</div>
        {loading && <span className="cap row gap4"><Icon name="circle-notch" style={{ animation: "rfq-spin 1s linear infinite" }} />{t("Translating the app…")}</span>}
        {failed && <span className="cap" style={{ color: "var(--caution)" }}>{t("Translation service unavailable: showing English.")}</span>}</div>
      <div className="col gap8"><span className="over">{t("Appearance")}</span>
        <div className="seg">{[["system", t("Auto")], ["light", t("Light")], ["dark", t("Dark")]].map(([k, l]) => <button key={k} className={theme === k ? "on" : ""} onClick={() => setTheme(k)}>{l}</button>)}</div></div>
      <button className="inset between tappable" onClick={onSources}><span className="row gap12"><Icon name="broadcast" size={20} />{t("Data sources")}</span><Icon name="caret-right" className="faint flip-rtl" /></button>
      {devAvailable && <button className="inset between tappable" onClick={onDev}><span className="row gap12"><Icon name={devFull ? "terminal-window" : "flask"} size={20} />{devFull ? t("Under the hood (testing)") : t("Simulate live problems (demo)")}</span><Icon name="caret-right" className="faint flip-rtl" /></button>}
      {devAvailable && <div className="col gap8"><span className="over">{t("Demo mode")}</span>
        <span className="cap">{t("Simulated items are always labelled SIMULATED on the map.")}</span>
        <div className="grid2">
          <button className="btn btn-secondary" onClick={() => onDemo("scenario")}>{t("Simulated incidents")}</button>
          <button className="btn btn-secondary" onClick={() => onDemo("flood")}>{t("Simulated flood")}</button>
        </div>
        <button className="btn btn-outline" onClick={() => onDemo("reset")}>{t("Clear simulated data")}</button></div>}
      <div className="col gap8"><span className="over">{t("Privacy")}</span>
        <ul className="sec" style={{ margin: 0, paddingInlineStart: 18, color: "var(--ink)" }}>
          <li>{t("No account. Your phone gets a random anonymous ID.")}</li>
          <li>{t("Photos are analysed, then deleted. They are never stored.")}</li>
          <li>{t("SOS alerts on the map are anonymous and rounded to about 100 m.")}</li>
          <li>{t("Your location only places reports and checks your route.")}</li>
        </ul></div>
      <button className="btn btn-ghost" style={{ color: "var(--ink-2)" }} onClick={onResetOnboarding}>{t("Show the introduction again")}</button>
    </div>
  );
}
