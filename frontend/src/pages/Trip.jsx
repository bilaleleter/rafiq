// D · Trip: route options, all-blocked state, active trip (Route guardian), in-trip alert, reroute, arrived.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { Icon, StatusPill, EvidenceLine, HazardIcon, PhotoSlot, Skeleton } from "../ui.jsx";
import { haversine, hhmm, statusOfEvent, CATEGORY_ICON } from "../hazardStyle.js";
import { useT, useTx } from "../i18n.js";
import { speak } from "../voice.js";
import Sheet from "../components/Sheet.jsx";

const SEV = { info: 0, warning: 1, danger: 2, critical: 3 };

function cumulative(coords) {
  const c = [0];
  for (let i = 1; i < coords.length; i++) c.push(c[i - 1] + haversine({ lat: coords[i - 1][0], lon: coords[i - 1][1] }, { lat: coords[i][0], lon: coords[i][1] }));
  return c;
}
function nearestIndex(coords, me) {
  let best = 0, bd = Infinity;
  coords.forEach(([la, lo], i) => { const d = (la - me.lat) ** 2 + (lo - me.lon) ** 2; if (d < bd) { bd = d; best = i; } });
  return best;
}

function HazardLine({ h }) {
  const title = useTx(h.event.title);
  return <div className="row gap8 cap" style={{ color: "var(--ink)" }}><span className="sim" style={{ letterSpacing: 0 }}>km {h.km_along_route}</span>{title}</div>;
}

export default function Trip({ me, target, events, snap, onSnap, setMapRoutes, flyTo, onExit, onPickAlternative, toast, onReportHere, onHazard, cloudVoice, onActive }) {
  const { t, lang } = useT();
  const [mode, setMode] = useState("DRIVE");
  const [plan, setPlan] = useState(null);
  const [chosen, setChosen] = useState(0);
  const [error, setError] = useState(null);
  const [active, setActive] = useState(false);
  const [alert, setAlert] = useState(null);       // {hit}
  const [expanded, setExpanded] = useState(false);
  const [arrived, setArrived] = useState(null);
  const [voice, setVoice] = useState(true);
  const seen = useRef({});
  const alertTitle = useTx(alert?.hit.event.title);

  async function doPlan(from = me, keepActive = false) {
    setError(null); if (!keepActive) setPlan(null);
    try {
      const p = await api.planTrip(from, target, mode);
      setPlan(p); setChosen(p.recommended_index);
      setMapRoutes(p.routes, p.recommended_index);
      if (!keepActive) flyTo((from.lat + target.lat) / 2, (from.lon + target.lon) / 2, 10);
      return p;
    } catch { setError(t("Couldn't compute a route right now. Check your connection and try again.")); }
  }
  useEffect(() => { if (target && me) { setActive(false); setArrived(null); seen.current = {}; doPlan(); } }, [target?.lat, target?.lon, mode]);
  useEffect(() => { if (plan) setMapRoutes(plan.routes, chosen); }, [chosen]);
  useEffect(() => { onActive?.(active); }, [active]);

  const route = plan?.routes.find((r) => r.index === chosen);
  const cum = useMemo(() => (route ? cumulative(route.coords) : null), [route]);
  const progress = useMemo(() => {
    if (!route || !me) return null;
    const i = nearestIndex(route.coords, me);
    const total = cum[cum.length - 1], left = Math.max(0, total - cum[i]);
    const min = Math.round((route.duration_s / 60) * (left / Math.max(total, 1)));
    return { idx: i, leftKm: left / 1000, min, eta: new Date(Date.now() + min * 60000).toISOString() };
  }, [route, me?.lat, me?.lon, cum]);

  // Route guardian: remaining route re-checked every 30 s and on every live change.
  useEffect(() => {
    if (!active || !route) return;
    let stop = false;
    const run = async () => {
      const rest = route.coords.slice(progress?.idx || 0);
      if (rest.length < 2) return;
      const res = await api.checkRoute(rest).catch(() => null);
      if (!res || stop) return;
      const fresh = res.hits.filter((h) => SEV[h.event.severity] >= 1 && (seen.current[h.event.id] === undefined || SEV[h.event.severity] > seen.current[h.event.id]));
      fresh.forEach((h) => { seen.current[h.event.id] = SEV[h.event.severity]; });
      if (fresh.length) { setAlert({ hit: fresh[0], spoken: false }); setExpanded(false); navigator.vibrate?.([180, 120, 180, 120, 180]); }
    };
    run();
    const id = setInterval(run, 30000);
    return () => { stop = true; clearInterval(id); };
  }, [active, chosen, events.map((e) => e.id + e.severity).join()]);

  // Spoken alert (hands-free while driving), in the UI language once the title is translated.
  useEffect(() => {
    if (!alert || alert.spoken || !voice) return;
    const id = setTimeout(() => {
      const av = statusOfEvent(alert.hit.event) === "avoid";
      speak(`${av ? t("Avoid for now") : t("Caution")}. ${alertTitle}. ${av ? t("Take the safer route.") : t("Slow down and follow local instructions.")}`, lang, { cloud: cloudVoice });
      setAlert((a) => a && { ...a, spoken: true });
    }, 700);
    return () => clearTimeout(id);
  }, [alert?.hit?.event?.id, alertTitle, voice]);

  useEffect(() => { if (active && progress && progress.leftKm < 0.15) { setActive(false); setArrived(new Date().toISOString()); } }, [progress?.leftKm]);

  async function saferRoute() {
    const before = route?.duration_s || 0;
    const p = await doPlan(me, true);
    setAlert(null); setExpanded(false);
    if (p) {
      const r = p.routes[p.recommended_index];
      const diff = Math.round((r.duration_s - before) / 60);
      toast({ text: t("New route, {d} min, {why}", { d: `${diff >= 0 ? "+" : ""}${diff}`, why: r.hazards.length ? t("fewest reported issues") : t("avoids the problem") }) });
    }
  }

  const ended = () => { setActive(false); setAlert(null); setMapRoutes(null); onExit(); };

  // ── Active trip (guardian) ────────────────────────────────────────────
  if (active && route) {
    const next = alert?.hit;
    const av = next && statusOfEvent(next.event) === "avoid";
    const kmAhead = next ? Math.max(0.1, next.km_along_route - (cum && progress ? cum[progress.idx] / 1000 : 0)).toFixed(1) : null;
    return (
      <>
        {!next && (
          <div className="top-card">
            <div className="between"><div className="row gap8"><Icon name="check-circle" fill size={22} style={{ color: "var(--clear)" }} /><span className="strong">{t("No reported issues ahead")}</span></div>
              <button className="float-round small" style={{ boxShadow: "none", background: "var(--surface-2)" }} onClick={() => setVoice((v) => !v)}
                aria-pressed={voice} aria-label={t("Voice alerts")}><Icon name={voice ? "speaker-high" : "speaker-slash"} /></button></div>
            <hr className="divider" style={{ margin: "12px 0" }} />
            <div className="row" style={{ gap: 24 }}>
              <div className="col"><span className="big-num">{progress ? hhmm(progress.eta) : "–"}</span><span className="cap">{t("Arrival")}</span></div>
              <div className="col"><span className="big-num">{progress?.min ?? "–"} min</span><span className="cap">{t("Remaining")}</span></div>
              <div className="col"><span className="big-num">{progress ? progress.leftKm.toFixed(1) : "–"} km</span><span className="cap">{t("Distance")}</span></div>
            </div>
          </div>
        )}
        {!next && <div className="float-pill" style={{ position: "absolute", insetInlineStart: 12, top: 164, zIndex: 8 }}><Icon name="shield-check" size={16} />{t("Watching your route")}</div>}
        {next && !expanded && (
          <div className="alert-banner" style={{ "--c": `var(${av ? "--avoid" : "--caution"})` }} onClick={() => setExpanded(true)}>
            <div className="over row gap8" style={{ color: "var(--ink-2)" }}><Icon name={av ? "prohibit" : "warning"} fill size={16}
              style={{ color: `var(${av ? "--avoid" : "--caution"})` }} />
              {av ? t("Avoid for now") : t("Caution")} · {t("in {n} km", { n: kmAhead })}</div>
            <div className="h3" style={{ margin: "6px 0 4px" }}>{alertTitle}</div>
            <div className="sec" style={{ marginBottom: 8 }}>{av ? t("Take the safer route.") : t("Slow down and follow local instructions.")}</div>
            <EvidenceLine e={next.event} expandable={false} />
            <div className="row gap8" style={{ marginTop: 12 }} onClick={(e) => e.stopPropagation()}>
              <button className="btn btn-primary grow" onClick={saferRoute}>{t("Safer route")}</button>
              <button className="btn btn-secondary grow" disabled={!plan?.destination?.alternatives?.length}
                onClick={() => { setAlert(null); onPickAlternative(plan.destination.alternatives[0]); }}>{t("Similar place instead")}</button>
            </div>
          </div>
        )}
        {next && expanded && (
          <Sheet snap="half" onSnap={() => {}} foot={
            <div className="row gap8"><button className="btn btn-secondary grow" onClick={() => { setAlert(null); setExpanded(false); }}>{t("Keep route")}</button>
              <button className="btn btn-primary grow" style={{ flex: 1.6 }} onClick={saferRoute}>{t("Take safer route")}</button></div>}>
            <div className="col gap12">
              <div className="row gap12" style={{ alignItems: "flex-start" }}><HazardIcon type={next.event.type} lg />
                <div className="col gap4 grow"><span className="h3">{alertTitle}</span><EvidenceLine e={next.event} /></div></div>
              <Desc text={next.event.description} />
              <div className="inset between"><div className="col"><span className="strong row gap8"><span className="dot-s" style={{ background: "var(--ink-3)" }} />{t("Current route")}</span>
                <span className="cap" style={{ marginInlineStart: 16 }}>{alertTitle} · km {next.km_along_route}</span></div><span className="big-num" style={{ fontSize: 18 }}>{progress?.min ?? "–"} min</span></div>
              <button className="card card-pad tappable" style={{ borderColor: "var(--brand)", borderWidth: 2 }} onClick={saferRoute}>
                <div className="between"><span className="strong row gap8"><span className="dot-s" style={{ background: "var(--brand)" }} />{t("Safer route")}</span><span className="link">{t("Compare")}</span></div>
                <span className="cap" style={{ marginInlineStart: 16 }}>{t("Recalculated from where you are now")}</span></button>
            </div>
          </Sheet>
        )}
        {!(next && expanded) && (
          <div className="row gap12" style={{ position: "absolute", left: 16, right: 16, bottom: 80, zIndex: 8 }}>
            <button className="btn btn-outline grow" style={{ height: 56, color: "var(--avoid)", boxShadow: "var(--shadow-float)", border: 0 }} onClick={ended}><Icon name="x-circle" />{t("End trip")}</button>
            <button className="float-round" style={{ width: 56, height: 56 }} onClick={() => me && flyTo(me.lat, me.lon, 15)} aria-label={t("Recentre")}><Icon name="crosshair" /></button>
          </div>
        )}
      </>
    );
  }

  // ── Arrived ───────────────────────────────────────────────────────────
  if (arrived) return (
    <Sheet snap="half" onSnap={onSnap}>
      <div className="col gap12">
        <span className="over">{t("Arrived")} · {hhmm(arrived)}</span>
        <h2 className="h2">{target.name}</h2>
        <span><StatusPill status={plan?.destination?.status || "clear"} size="M" /></span>
        {plan?.destination?.reasons?.[0] && <p className="body" style={{ margin: 0 }}><Desc text={plan.destination.reasons[0].title} inline />.</p>}
        <button className="tappable row gap12" style={{ background: "var(--brand-soft)", borderRadius: 16, padding: 16 }} onClick={onReportHere}>
          <Icon name="plus-circle" size={24} style={{ color: "var(--brand)" }} />
          <div className="col grow"><span className="strong">{t("Report something here")}</span><span className="cap">{t("Water, power, a blocked street")}</span></div>
          <Icon name="caret-right" className="faint flip-rtl" />
        </button>
        <button className="btn btn-ghost" onClick={ended}>{t("Done")}</button>
      </div>
    </Sheet>
  );

  // ── Planning ──────────────────────────────────────────────────────────
  const dest = plan?.destination;
  const blocked = plan?.all_routes_unsafe;
  return (
    <>
      <button className="float-round" style={{ position: "absolute", insetInlineStart: 16, top: 16, zIndex: 8 }} onClick={ended} aria-label={t("Back")}><Icon name="arrow-left" className="flip-rtl" /></button>
      <Sheet snap={snap} onSnap={onSnap} foot={plan && <button className={`btn btn-block ${blocked ? "btn-secondary" : "btn-primary"}`} onClick={() => { setActive(true); onSnap("peek"); me && flyTo(me.lat, me.lon, 14); }}>
        <Icon name="navigation-arrow" />{blocked ? t("Go with care on this route") : t("Start trip")}</button>}>
        {!plan && !error && <div className="col gap12"><Skeleton h={24} w="60%" /><Skeleton h={44} r={12} /><Skeleton h={120} r={16} /><Skeleton h={90} r={16} /></div>}
        {error && <div className="col gap12"><span className="h3">{t("To {name}", { name: target.name })}</span><p className="sec">{error}</p><button className="btn btn-secondary" onClick={() => doPlan()}>{t("Try again")}</button></div>}
        {plan && blocked && (() => {
          const least = plan.routes.find((r) => r.index === plan.least_risk_index) || plan.routes[0];
          const firstBad = least.hazards.find((h) => statusOfEvent(h.event) === "avoid") || least.hazards[0];
          return (
            <div className="col gap12">
              <span><StatusPill status="avoid" size="M" label={t("No clear route")} /></span>
              <h2 className="h2">{plan.problem_at_destination ? t("{name} has a reported problem right now", { name: target.name })
                : t("Every route to {name} crosses a reported problem", { name: target.name })}</h2>
              {plan.detour_tried && <p className="sec" style={{ margin: 0 }}>{t("A detour around the problem was checked too. It also crosses a problem.")}</p>}
              {plan.clears_at && <div className="inset row gap12"><Icon name="clock" size={20} style={{ color: "var(--brand)" }} />
                <span className="sec" style={{ color: "var(--ink)" }}>{t("Expected to clear around {time}. You can wait, or go with care.", { time: hhmm(plan.clears_at) })}</span></div>}
              <span className="over" style={{ marginTop: 4 }}>{t("Least risky route")}</span>
              <div className="card card-pad col gap8" style={{ border: "2px solid var(--brand)" }}>
                <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
                  <span style={{ font: "700 28px/32px var(--font-display)" }} className="tnum">{Math.round(least.duration_s / 60)} min</span>
                  <span className="sec grow">{(least.distance_m / 1000).toFixed(1)} km · {least.detour ? t("Detour around the problem") : t("via {road}", { road: least.label })}</span>
                </div>
                {least.hazards.slice(0, 3).map((h) => <HazardLine key={h.event.id} h={h} />)}
                {firstBad && <EvidenceLine e={firstBad.event} />}
                <span className="cap">{t("Slow down near the problem and follow local instructions. The route guardian keeps watching.")}</span>
              </div>
              {(dest?.alternatives || []).length > 0 && <span className="over" style={{ marginTop: 8 }}>{t("Or go here instead")}</span>}
              {(dest?.alternatives || []).map((a) => (
                <button key={a.id} className="list-row tappable" onClick={() => onPickAlternative(a)}>
                  <div style={{ width: 48, flex: "none" }}><PhotoSlot photo={a.photo} height={48} w={160} icon={CATEGORY_ICON[a.category]} /></div>
                  <div className="grow col"><span className="strong">{a.name}</span><span className="cap">{t("{n} km away", { n: a.distance_km })}</span></div><Icon name="caret-right" className="faint flip-rtl" />
                </button>
              ))}
            </div>
          );
        })()}
        {plan && !blocked && (
          <div className="col gap12">
            <div className="col gap4"><span className="h3">{t("To {name}", { name: target.name })}</span>
              {dest && dest.status !== "clear" && <span className="cap row gap4"><Icon name="warning" fill style={{ color: "var(--caution)" }} />{t("Destination")}: {dest.status === "avoid" ? t("Avoid for now") : t("Caution")}{dest.reasons[0] ? <>, <Desc text={dest.reasons[0].title} inline /></> : ""}</span>}</div>
            <div className="seg">
              <button className={mode === "DRIVE" ? "on" : ""} onClick={() => setMode("DRIVE")}><Icon name="car-profile" />{t("Drive")}</button>
              <button className={mode === "WALK" ? "on" : ""} onClick={() => setMode("WALK")}><Icon name="person-simple-walk" />{t("Walk")}</button>
            </div>
            {mode === "WALK" && plan.routes[0]?.provider === "osrm" && <span className="cap row gap4"><Icon name="info" />{t("Walking routes need Google Routes. These are car routes.")}</span>}
            {[...plan.routes].sort((a, b) => (a.index === plan.recommended_index ? -1 : b.index === plan.recommended_index ? 1 : 0)).map((r) => {
              const rec = r.index === plan.recommended_index;
              return (
                <button key={r.index} className="card card-pad tappable col gap8" style={r.index === chosen ? { border: "2px solid var(--brand)" } : {}} onClick={() => setChosen(r.index)}>
                  {rec && <span className="over" style={{ color: "var(--brand)" }}>{t("Recommended")}</span>}
                  <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
                    <span style={{ font: "700 28px/32px var(--font-display)" }} className="tnum">{Math.round(r.duration_s / 60)} min</span>
                    <span className="sec grow">{(r.distance_m / 1000).toFixed(1)} km · {r.detour ? t("Detour around the problem") : t("via {road}", { road: r.label })}</span>
                    {!rec && <StatusPill status={r.safety} />}
                  </div>
                  {rec && <div className="row gap8" style={{ flexWrap: "wrap" }}><StatusPill status={r.safety} /><span className="cap"><Desc text={plan.why} inline /></span></div>}
                  {r.hazards.slice(0, 3).map((h) => <HazardLine key={h.event.id} h={h} />)}
                </button>
              );
            })}
          </div>
        )}
      </Sheet>
    </>
  );
}

function Desc({ text, inline }) {
  const tx = useTx(text);
  return inline ? tx : <p className="body" style={{ margin: 0 }}>{tx}</p>;
}
