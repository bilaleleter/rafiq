// F · Report: hub, flood camera, body picker, analysing, results, web video, power (charger check), quick reports.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, DEVICE_ID } from "../api.js";
import { Icon, StarMark, BackHeader } from "../ui.jsx";
import { typeOf } from "../hazardStyle.js";
import { useT } from "../i18n.js";

const QUICK = [["accident", "Accident"], ["road", "Road blocked"], ["water", "Water cut"], ["fire", "Fire or smoke"], ["health", "Health"], ["crowd", "Crowd"]];
const BODY = [["person_waist", "Waist", 100], ["person_thigh", "Thigh", 75], ["person_knee", "Knee", 50], ["person_mid_calf", "Mid-calf", 30], ["person_ankle", "Ankle", 10]];
const ANCHOR = { person_ankle: "ankle", person_mid_calf: "mid-calf", person_knee: "knee", person_thigh: "thigh", person_waist: "waist", person_chest: "chest",
  kerb_top: "kerb top", below_kerb: "below the kerb", door_step: "door step", car_tyre_half: "half a car tyre", car_tyre_top: "top of a car tyre",
  car_tyre_bottom_third: "bottom of a car tyre", car_door_bottom: "bottom of a car door", car_bonnet: "car bonnet", car_roof: "car roof",
  door_handle: "door handle", window_sill: "window sill", wet_road_no_depth: "wet road", ground_floor_ceiling: "ground floor ceiling" };
const Portal = ({ children }) => createPortal(children, document.getElementById("overlays"));

async function battery() { try { return navigator.getBattery ? await navigator.getBattery() : null; } catch { return null; } }

export function ReportHub({ onStart }) {
  const { t } = useT();
  return (
    <div className="col gap16" style={{ paddingTop: 4 }}>
      <div className="col gap4"><h2 className="h2">{t("Report what you see")}</h2>
        <span className="sec">{t("Reports warn other travellers instantly. Your location only places the report.")}</span></div>
      <div className="grid2">
        <button className="tile" style={{ background: "color-mix(in srgb, var(--water) 12%, var(--surface))", border: 0, height: 128, justifyContent: "space-between" }} onClick={() => onStart("flood")}>
          <Icon name="waves" size={32} style={{ color: "var(--water)" }} /><span className="col"><span className="strong">{t("Flood water")}</span><span className="cap">{t("Photo or body height")}</span></span></button>
        <button className="tile" style={{ background: "color-mix(in srgb, var(--power) 20%, var(--surface))", border: 0, height: 128, justifyContent: "space-between" }} onClick={() => onStart("power")}>
          <Icon name="lightning-slash" size={32} style={{ color: "color-mix(in srgb, var(--power) 60%, var(--ink))" }} /><span className="col"><span className="strong">{t("Power cut")}</span><span className="cap">{t("Check with your charger")}</span></span></button>
      </div>
      <div className="grid3">
        {QUICK.map(([ty, l]) => <button key={ty} className="qtile" onClick={() => onStart("quick", ty)}><Icon name={typeOf(ty).icon} style={{ color: `var(${typeOf(ty).color})` }} />{t(l)}</button>)}
      </div>
      <button className="inset between tappable" onClick={() => onStart("video")}>
        <span className="row gap12 sec" style={{ color: "var(--ink)" }}><Icon name="video-camera" size={20} />{t("Share a web video")}</span><Icon name="caret-right" className="faint flip-rtl" /></button>
    </div>
  );
}

/* ───────────────────────── flood ───────────────────────── */
export function FloodFlow({ me, at, onClose, onDone, startWith = "camera" }) {
  const { t } = useT();
  const where = at || me;   // "Report an update" near a flood zone reports AT the zone
  const [step, setStep] = useState(startWith);   // camera | body | analysing | accepted | rejected
  const [photoUrl, setPhotoUrl] = useState(null);
  const [res, setRes] = useState(null);
  const [checks, setChecks] = useState(0);
  const [pick, setPick] = useState("person_knee");
  const [note, setNote] = useState(null);
  const fileRef = useRef(null);

  async function send({ photo, body_level }) {
    const fd = new FormData();
    fd.append("lat", where.lat); fd.append("lon", where.lon); fd.append("device_id", DEVICE_ID);
    if (me.accuracy) fd.append("accuracy_m", me.accuracy);
    if (photo) fd.append("photo", photo);
    if (body_level) fd.append("body_level", body_level);
    if (photo) { setPhotoUrl(URL.createObjectURL(photo)); setStep("analysing"); setChecks(0); }
    const tick = photo && setInterval(() => setChecks((c) => Math.min(c + 1, 2)), 1400);
    try {
      const r = await api.floodReport(fd);
      setRes(r);
      if (r.accepted) { setChecks(3); setTimeout(() => setStep("accepted"), photo ? 500 : 0); }
      else if (r.needs_manual) { setNote(t("The depth couldn't be read from this photo. Tap where the water reaches instead.")); setStep("body"); }
      else setStep("rejected");
    } catch (e) { setRes({ accepted: false, reason: e.message }); setStep("rejected"); }
    finally { tick && clearInterval(tick); }
  }

  const fileInput = <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => e.target.files[0] && send({ photo: e.target.files[0] })} />;

  if (step === "camera") return (
    <Portal><div className="screen dark" style={{ background: "#0B1B2B" }}>
      {fileInput}
      <div className="between" style={{ padding: "16px 20px" }}>
        <button className="float-round small" style={{ background: "rgba(255,255,255,.12)", color: "#fff", boxShadow: "none" }} onClick={onClose} aria-label={t("Close")}><Icon name="x" /></button>
        <span className="float-pill" style={{ background: "rgba(255,255,255,.12)", color: "#fff", boxShadow: "none" }}><Icon name="crosshair" style={{ color: "#3CCB8A" }} />
          {at ? t("At the flood zone") : me.accuracy ? `GPS ±${Math.round(me.accuracy)} m` : t("GPS approximate")}</span>
        <span style={{ width: 40 }} />
      </div>
      <div className="grow" style={{ position: "relative", background: "repeating-linear-gradient(135deg, #0F2033 0 14px, #0B1B2B 14px 28px)" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: "58%", borderTop: "2px dashed rgba(255,255,255,.85)" }} />
        <div style={{ position: "absolute", left: 20, right: 20, top: "calc(58% + 14px)", background: "rgba(11,27,43,.85)", borderRadius: 12, padding: "12px 16px",
          font: "500 14px/20px var(--font-ui)", color: "#fff", textAlign: "center" }}>{t("Line up the waterline. Include a kerb, car wheel, door or a person's legs.")}</div>
      </div>
      <div className="col" style={{ alignItems: "center", gap: 14, padding: "24px 20px 28px" }}>
        <button onClick={() => fileRef.current.click()} aria-label={t("Take photo")}
          style={{ width: 78, height: 78, borderRadius: 99, border: "4px solid #fff", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <span style={{ width: 62, height: 62, borderRadius: 99, background: "#fff" }} /></button>
        <button className="link" style={{ color: "#9CC4FF" }} onClick={() => setStep("body")}>{t("No photo? Tell us where the water reaches")}</button>
      </div>
    </div></Portal>
  );

  if (step === "body") {
    const sel = BODY.find((b) => b[0] === pick);
    return (
      <Portal><div className="screen">
        <BackHeader onBack={() => (startWith === "body" ? onClose() : setStep("camera"))} />
        <div className="screen-body" style={{ paddingTop: 8 }}>
          <h2 className="h2">{t("Where does the water reach?")}</h2>
          <p className="sec" style={{ margin: "4px 0 16px" }}>{note || t("On an adult standing in it.")}</p>
          <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
            <div dir="ltr" style={{ position: "relative", width: 150, height: 420, flex: "none", overflow: "hidden" }}>
              <Icon name="person-simple" fill size={470} style={{ position: "absolute", left: -160, bottom: -16, color: "var(--ink-3)", opacity: .45, lineHeight: 1 }} />
              <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${(sel[2] / 180) * 420}px`,
                background: "color-mix(in srgb, var(--water) 40%, transparent)", borderTop: "2px solid var(--water)", transition: "height .25s" }} />
            </div>
            <div className="col gap8 grow">
              {BODY.map(([k, l, cm]) => (
                <button key={k} className={`opt ${pick === k ? "on" : ""}`} style={{ padding: "12px 14px" }} onClick={() => setPick(k)}>
                  <span className="strong" style={{ color: pick === k ? "var(--brand)" : "var(--ink)" }}>{t(l)}</span><span className="cap">~{cm} cm</span></button>
              ))}
            </div>
          </div>
        </div>
        <div className="screen-foot"><button className="btn btn-primary btn-block" onClick={() => send({ body_level: pick })}>{t("Send: water at the {part}", { part: t(sel[1]).toLowerCase() })}</button></div>
      </div></Portal>
    );
  }

  if (step === "analysing") return (
    <Portal><div className="screen dark" style={{ justifyContent: "flex-end" }}>
      <div style={{ position: "absolute", inset: 0, backgroundImage: `url(${photoUrl})`, backgroundSize: "cover", backgroundPosition: "center", opacity: .35 }} />
      <div className="ecard col gap12" style={{ margin: 20, position: "relative", color: "var(--ink)" }}>
        <div className="row gap12"><StarMark size={28} spin /><span className="h3">{t("Reading your photo")}</span></div>
        {[t("Checking the photo is recent"), t("Reading the waterline"), t("Placing it on the map")].map((label, i) => (
          <div key={label} className="check-step" style={{ color: i > checks ? "var(--ink-3)" : "var(--ink)" }}>
            {i < checks ? <Icon name="check-circle" fill style={{ color: "var(--clear)" }} /> : i === checks ? <Icon name="circle-notch" style={{ color: "var(--brand)", animation: "rfq-spin 1s linear infinite" }} /> : <Icon name="circle" className="faint" />}{label}
          </div>
        ))}
      </div>
    </div></Portal>
  );

  if (step === "accepted") {
    const a = res.analysis, z = res.zone;
    return (
      <Portal><div className="screen">
        {photoUrl && <div style={{ height: "42%", position: "relative", backgroundImage: `url(${photoUrl})`, backgroundSize: "cover", backgroundPosition: "center" }}>
          <span className="float-pill" style={{ position: "absolute", insetInlineEnd: 16, bottom: 16, background: "var(--water)", color: "#fff" }}>≈ {res.depth_cm} cm</span></div>}
        <div className="screen-body col gap12">
          <span className="row gap8 strong" style={{ fontSize: 14 }}><Icon name="check-circle" fill style={{ color: "var(--clear)" }} />{t("Added to the map")}</span>
          <h1 className="h1">{t("About {n} cm", { n: res.depth_cm })}</h1>
          <p className="body" style={{ margin: 0, color: "var(--ink-2)" }}>{a?.ok ? t("Water at the {part}.", { part: t(ANCHOR[a.anchor] || a.anchor) }) : t("From your body-height report.")}</p>
          <div className="inset row gap12"><Icon name="map-pin" size={22} style={{ color: "var(--brand)" }} />
            <div className="col"><span className="strong">{z.data?.place || t("Flood zone near you")}</span>
              <span className="cap">{t("{n} report(s) · now {p}% confirmed", { n: z.reports_count, p: Math.round(z.confidence * 100) })}</span></div></div>
        </div>
        <div className="screen-foot"><button className="btn btn-primary btn-block" onClick={() => onDone(z)}>{t("See on map")}</button></div>
      </div></Portal>
    );
  }

  const old = /days? ago|taken \d/.test(res?.reason || "");
  return (
    <Portal><div className="screen">
      <div className="screen-body col gap12" style={{ paddingTop: 48 }}>
        {photoUrl && <div style={{ width: 120, height: 160, borderRadius: 12, backgroundImage: `url(${photoUrl})`, backgroundSize: "cover" }} />}
        <span className="row gap8 strong" style={{ fontSize: 14 }}><Icon name="x-circle" fill style={{ color: "var(--avoid)" }} />{t("Not added")}</span>
        <h1 className="h1">{res?.reason || t("Something went wrong")}</h1>
        <p className="body" style={{ margin: 0, color: "var(--ink-2)" }}>{old ? t("Only recent photos can show where the water is now. Take a new one from where you stand.") : t("Please try again, or tell us where the water reaches instead.")}</p>
      </div>
      <div className="screen-foot">
        {fileInput}
        <button className="btn btn-primary btn-block" onClick={() => fileRef.current.click()}><Icon name="camera" />{t("Take a new photo")}</button>
        <button className="btn btn-ghost" onClick={() => setStep("body")}>{t("Tell us where the water reaches")}</button>
      </div>
    </div></Portal>
  );
}

/* ───────────────────────── web video ───────────────────────── */
export function VideoFlow({ me, onClose }) {
  const { t } = useT();
  const [url, setUrl] = useState("");
  const [here, setHere] = useState(false);
  const [state, setState] = useState(null); // null | checking | result
  const [res, setRes] = useState(null);
  const CHECKS = [t("Posted in the last 24 h"), t("Not a re-post of an older video"), t("Real flood, readable waterline"), t("Location found"), t("Rain recorded there")];
  const failIdx = (r) => {
    const s = (r || "").toLowerCase();
    if (/old|date/.test(s)) return 0; if (/recycled|re-post/.test(s)) return 1;
    if (/flood|ai|graphic|waterline|image|vision/.test(s)) return 2; if (/location|locate|vague|outside/.test(s)) return 3; if (/rain/.test(s)) return 4; return 2;
  };
  async function go() {
    setState("checking");
    try { setRes(await api.floodLink(url.trim(), here ? me : null)); } catch (e) { setRes({ accepted: false, reason: e.message }); }
    setState("result");
  }
  const fi = res && !res.accepted ? failIdx(res.reason) : 99;
  return (
    <Portal><div className="screen">
      <BackHeader onBack={onClose} />
      <div className="screen-body col gap16" style={{ paddingTop: 8 }}>
        <div className="col gap4"><h2 className="h2">{t("Share a web video")}</h2><span className="sec">{t("Saw a flood video on TikTok or YouTube? It is checked before it reaches the map.")}</span></div>
        <input className="input" dir="ltr" placeholder="https://www.tiktok.com/@…/video/…" value={url} onChange={(e) => setUrl(e.target.value)} />
        <label className="between sec" style={{ color: "var(--ink)" }}>{t("I'm at the place in the video")}
          <button className={`switch brand ${here ? "on" : ""}`} onClick={() => setHere((h) => !h)} aria-pressed={here} /></label>
        {state && (
          <div className="card card-pad col gap12">
            {CHECKS.map((c, i) => {
              const ok = state === "result" && (res.accepted || i < fi), bad = state === "result" && !res.accepted && i === fi;
              return (
                <div key={c} className="check-step" style={{ color: state === "result" && !ok && !bad ? "var(--ink-3)" : "var(--ink)" }}>
                  {ok ? <Icon name="check-circle" fill style={{ color: "var(--clear)" }} /> : bad ? <Icon name="x-circle" fill style={{ color: "var(--avoid)" }} />
                    : state === "checking" ? <Icon name="circle-notch" style={{ color: "var(--brand)", animation: "rfq-spin 1s linear infinite" }} /> : <Icon name="circle" className="faint" />}
                  <span className="grow">{c}</span></div>
              );
            })}
            {state === "result" && (res.accepted
              ? <div className="inset"><span className="strong">{t("Added to the map")}</span><div className="cap">{t("About {n} cm near {place} · {p}% confidence", { n: res.depth_cm, place: res.place, p: Math.round(res.confidence * 100) })}</div></div>
              : <div className="inset"><span className="strong">{t("Not added")}</span><div className="cap">{res.reason}</div></div>)}
          </div>
        )}
      </div>
      <div className="screen-foot"><button className="btn btn-primary btn-block" disabled={!url.trim() || state === "checking"} onClick={go}>{state === "checking" ? t("Checking…") : t("Check and add")}</button></div>
    </div></Portal>
  );
}

/* ───────────────────────── power ───────────────────────── */
export function PowerFlow({ me, onClose, onDone, watch, setWatch }) {
  const { t } = useT();
  const [batt, setBatt] = useState(undefined);
  const [result, setResult] = useState(null); // charging | reported | error
  const [msg, setMsg] = useState("");
  useEffect(() => { battery().then(setBatt); }, []);
  async function report(status, verified = false, source = "tap") {
    try {
      const r = await api.power(me, status, verified, source);
      if (status === "on") { setMsg(r.closed ? t("Outage marked as over. Thanks.") : t("Thanks. Waiting for one more confirmation.")); setResult("reported"); }
      else { setMsg(`${verified ? t("Verified by your charger.") + " " : ""}${t("Reported. {n} device(s) so far.", { n: r.event?.reports_count || 1 })}`); setResult("reported"); onDone?.(r.event); }
    } catch (e) { setMsg(e.message); setResult("error"); }
  }
  const check = () => { if (batt.charging) setResult("charging"); else report("off", true, "charger"); };
  return (
    <Portal><div className="screen">
      <BackHeader onBack={onClose} />
      <div className="screen-body col gap16" style={{ paddingTop: 8 }}>
        <h1 className="h1">{t("Power cut")}</h1>
        {batt && (
          <div className="card col" style={{ alignItems: "center", textAlign: "center", padding: "24px 20px", gap: 12 }}>
            <div className="row gap8" style={{ color: "var(--ink)" }}><Icon name="device-mobile" size={40} /><span className="faint">···</span><Icon name="plug" size={40} /></div>
            <span className="strong" style={{ fontSize: 17, lineHeight: "24px" }}>{t("Plug your phone into a wall socket, then tap Check.")}</span>
            <span className="sec">{t("If it charges, the socket has power.")}</span>
          </div>
        )}
        {batt === null && <p className="body" style={{ margin: 0, color: "var(--ink-2)" }}>{t("Tell us if the electricity is out where you are. Reports from several phones confirm a cut.")}</p>}
        {result === "charging" && <div className="row gap12" style={{ background: "color-mix(in srgb, var(--clear) 12%, var(--surface))", borderRadius: 16, padding: 16 }}>
          <Icon name="check-circle" fill size={24} style={{ color: "var(--clear)" }} /><div className="col"><span className="strong">{t("Your phone is charging")}</span><span className="cap">{t("So this socket has power. Nothing to report.")}</span></div></div>}
        {(result === "reported" || result === "error") && <div className="row gap12" style={{ background: `color-mix(in srgb, var(${result === "error" ? "--avoid" : "--clear"}) 12%, var(--surface))`, borderRadius: 16, padding: 16 }}>
          <Icon name={result === "error" ? "x-circle" : "check-circle"} fill size={24} style={{ color: `var(${result === "error" ? "--avoid" : "--clear"})` }} /><span className="sec" style={{ color: "var(--ink)" }}>{msg}</span></div>}
        {batt && (
          <label className="between card" style={{ padding: "14px 16px" }}>
            <span className="col"><span className="strong">{t("Power Watch")}</span><span className="cap">{t("Ask me when my charger stops. Keep the app open.")}</span></span>
            <button className={`switch brand ${watch ? "on" : ""}`} onClick={() => setWatch(!watch)} aria-pressed={watch} />
          </label>
        )}
      </div>
      <div className="screen-foot">
        {batt ? <><button className="btn btn-primary btn-block" onClick={check}>{t("Check")}</button>
          <button className="btn btn-ghost" onClick={() => report("off")}>{t("Report without checking")}</button></>
          : <button className="btn btn-primary btn-block" onClick={() => report("off")}>{t("The power is out here")}</button>}
        <button className="btn btn-secondary" onClick={() => report("on")}>{t("Power is back")}</button>
      </div>
    </div></Portal>
  );
}

export function PowerWatchPrompt({ onYes, onNo }) {
  const { t } = useT();
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <section className="sheet" style={{ height: "auto", zIndex: 25, bottom: 64 }}>
      <div className="sheet-handle"><span /></div>
      <div style={{ padding: "0 20px 20px" }} className="col gap12">
        <span className="over row gap8"><Icon name="plug" size={14} />{t("Power Watch")} · {time}</span>
        <span className="h2">{t("Your phone just stopped charging. Did the power go out?")}</span>
        <button className="btn btn-primary btn-block" onClick={onYes}>{t("Yes, power cut")}</button>
        <button className="btn btn-secondary btn-block" onClick={onNo}>{t("No, I unplugged it")}</button>
      </div>
    </section>
  );
}

/* ───────────────────────── quick report ───────────────────────── */
export function QuickReport({ type, me, onClose, onDone }) {
  const { t } = useT();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const ty = typeOf(type);
  return (
    <div className="col gap16" style={{ paddingTop: 4 }}>
      <div className="row gap12"><span className="hz-ic lg" style={{ "--c": `var(${ty.color})` }}><Icon name={ty.icon} /></span>
        <div className="col grow"><span className="h3">{t(QUICK.find((q) => q[0] === type)?.[1] || "Report")}</span><span className="cap">{t("At your location")}{me.accuracy ? ` · GPS ±${Math.round(me.accuracy)} m` : ""}</span></div>
        <button className="float-round small" style={{ boxShadow: "none", background: "var(--surface-2)" }} onClick={onClose} aria-label={t("Close")}><Icon name="x" /></button></div>
      <textarea className="input" placeholder={t("Optional note: what you see, how many lanes, since when…")} value={note} onChange={(e) => setNote(e.target.value)} />
      <span className="cap">{t("One report shows as caution. It turns into 'avoid' only when other people confirm it.")}</span>
      {err && <span className="sec" style={{ color: "var(--avoid)" }}>{err}</span>}
      <button className="btn btn-primary btn-block" disabled={busy} onClick={async () => {
        setBusy(true);
        try { const e = await api.report(type, me, note); onDone(e); } catch (x) { setErr(x.message); } finally { setBusy(false); }
      }}>{busy ? t("Sending…") : t("Send report")}</button>
    </div>
  );
}
