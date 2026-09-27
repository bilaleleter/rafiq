// G · SOS: entry (numbers + what happened), details, result (call, emergency card, read aloud, location, share, nearest help).
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Icon, BackHeader } from "../ui.jsx";
import { useT } from "../i18n.js";
import { speak, stopSpeaking, hasDeviceVoice } from "../voice.js";

const NUM_LABEL = { civil_protection: "Civil protection", ambulance: "Ambulance", police: "Police", national_guard: "National guard" };
const ORDER = ["civil_protection", "ambulance", "police", "national_guard"];
const KINDS = [["accident", "car-profile", "Road accident"], ["medical", "first-aid", "Medical"], ["flood_stuck", "waves", "Stuck in water"],
  ["fire", "fire", "Fire"], ["crime", "hand-palm", "Assault or theft"], ["lost", "compass", "Lost"]];
const NUM_FOR = { accident: "civil_protection", flood_stuck: "civil_protection", fire: "civil_protection", medical: "ambulance", crime: "police", lost: "police" };

function useSpeech(cloud) {
  const [playing, setPlaying] = useState(null);
  const [word, setWord] = useState(0);
  const [engine, setEngine] = useState(null);
  useEffect(() => () => stopSpeaking(), []);
  const play = async (key, text, lang) => {
    setPlaying(key); setWord(0);
    const how = await speak(text, lang, { cloud, rate: 0.9, onEnd: () => { setPlaying(null); setWord(0); }, onBoundary: setWord });
    setEngine(how);
    if (how === "none" && lang === "ar") setPlaying(null);
  };
  const stop = () => { stopSpeaking(); setPlaying(null); };
  return { playing, word, play, stop, engine };
}

function Wave() {
  return <span className="row" style={{ gap: 3, flex: 1 }}>{Array.from({ length: 26 }).map((_, i) => (
    <span key={i} style={{ width: 4, height: 8 + ((i * 7) % 18), borderRadius: 2, background: i < 10 ? "var(--water)" : "rgba(255,255,255,.35)",
      animation: `rfq-pulse ${0.8 + (i % 5) * 0.15}s ease-in-out infinite` }} />))}</span>;
}

export default function SOS({ me, numbers, prefs, cloudVoice }) {
  const { t, lang } = useT();
  const [kind, setKind] = useState(null);
  const [people, setPeople] = useState(1);
  const [injured, setInjured] = useState(false);
  const [note, setNote] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const sp = useSpeech(cloudVoice);
  const nums = numbers || { civil_protection: "198", ambulance: "190", police: "197", national_guard: "193" };

  async function send() {
    setBusy(true);
    try { setRes(await api.sos({ kind, lat: me.lat, lon: me.lon, people, injured, note, lang })); }
    catch {
      // Offline fallback: numbers + location still work without the server.
      setRes({ offline: true, primary_number: nums[NUM_FOR[kind]], numbers: nums, card: null,
        location: { lat: me.lat, lon: me.lon, maps_link: `https://maps.google.com/?q=${me.lat.toFixed(5)},${me.lon.toFixed(5)}` },
        nearest: {}, share_text: `EMERGENCY. I need help. My location: https://maps.google.com/?q=${me.lat.toFixed(5)},${me.lon.toFixed(5)}` });
    } finally { setBusy(false); }
  }

  // ── result ─────────────────────────────────────────────
  if (res) {
    const contact = prefs.contactPhone ? `+216${prefs.contactPhone.replace(/\s/g, "")}` : "";
    const primaryKey = Object.keys(res.numbers).find((k) => res.numbers[k] === res.primary_number);
    const highlight = (text) => {
      if (sp.playing !== "ar" || sp.engine !== "device") return text;
      const end = text.indexOf(".", sp.word) + 1 || text.length;
      return <>{text.slice(0, sp.word)}<mark style={{ background: "var(--brand-soft)", color: "var(--ink)", borderRadius: 4 }}>{text.slice(sp.word, end)}</mark>{text.slice(end)}</>;
    };
    const mine = lang === "en" ? res.card?.en : res.card_mine;
    const noArabicVoice = !cloudVoice && !hasDeviceVoice("ar");
    return (
      <div className="screen alt" style={{ bottom: 64 }}>
        <div className="screen-body col gap12" style={{ paddingTop: 16 }}>
          <a className="big-call" href={`tel:${res.primary_number}`}><Icon name="phone" fill />
            <span className="col"><span style={{ font: "700 20px/24px var(--font-display)" }}>{t("Call {n}", { n: res.primary_number })}</span><span style={{ fontSize: 13, opacity: .9 }}>{t(NUM_LABEL[primaryKey] || "")}</span></span></a>
          {res.card ? (
            <div className="ecard col gap12">
              <span className="over">{t("Show this screen or play it aloud")}</span>
              <div className="ar-text" lang="ar" dir="rtl">{highlight(res.card.ar)}</div>
              {sp.playing === "ar" ? (
                <div className="col gap8"><div className="row gap12" style={{ background: "#0B1B2B", borderRadius: 12, padding: "12px 12px 12px 14px" }}><Wave />
                  <button className="float-round small" onClick={sp.stop} aria-label={t("Stop")}><Icon name="stop" fill /></button></div>
                  <span className="cap">{t("Playing at full volume · hold the phone toward the listener")}</span></div>
              ) : <button className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-end" }} onClick={() => sp.play("ar", res.card.ar, "ar")}><Icon name="speaker-high" />{t("Read aloud")} · العربية</button>}
              {noArabicVoice && <span className="cap">{t("This phone has no Arabic voice installed. Show the text instead, or play the French version.")}</span>}
              <hr className="divider" />
              <div className="fr-text" lang="fr" dir="ltr">{res.card.fr}</div>
              {sp.playing === "fr" ? <button className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-start" }} onClick={sp.stop}><Icon name="stop" fill />Arrêter</button>
                : <button className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => sp.play("fr", res.card.fr, "fr")}><Icon name="speaker-high" />Lire à voix haute</button>}
              {mine && lang !== "fr" && lang !== "ar" && <><hr className="divider" /><span className="over">{t("Your copy")}</span><span className="sec" style={{ color: "var(--ink)" }}>{mine}</span></>}
            </div>
          ) : <div className="ecard sec">{t("No connection: the emergency card needs the server. Call the number above and share your location below.")}</div>}
          <div className="ecard col gap4">
            <div className="between"><span className="over">{t("Your location")}</span>
              <button className="link row gap4" onClick={() => { navigator.clipboard?.writeText(`${res.location.address || ""} ${res.location.plus_code || ""} ${me.lat.toFixed(5)}, ${me.lon.toFixed(5)}`); setCopied(true); }}>
                <Icon name="copy" />{copied ? t("Copied") : t("Copy")}</button></div>
            {res.location.address && <span className="strong">{res.location.address}</span>}
            <span className="tnum" dir="ltr" style={{ font: "500 13px/18px var(--font-mono)", color: "var(--ink-2)" }}>{res.location.plus_code ? `${res.location.plus_code} · ` : ""}{me.lat.toFixed(4)}, {me.lon.toFixed(4)}</span>
          </div>
          <div className="ecard col gap12">
            <span className="strong">{t("Share my location")}</span>
            <div className="grid2">
              <a className="btn btn-secondary" href={`https://wa.me/${contact.replace("+", "")}?text=${encodeURIComponent(res.share_text)}`} target="_blank" rel="noreferrer"><Icon name="whatsapp-logo" />WhatsApp</a>
              <a className="btn btn-secondary" href={`sms:${contact}?&body=${encodeURIComponent(res.share_text)}`}><Icon name="chat-text" />SMS</a>
            </div>
            <span className="cap">{prefs.contactName ? t("To {name}, or anyone you pick.", { name: prefs.contactName }) : t("To anyone you pick.")}</span>
          </div>
          {["hospital", "pharmacy", "police"].some((k) => res.nearest?.[k]?.length) && (
            <div className="ecard" style={{ padding: "4px 16px" }}>
              {[["hospital", "hospital"], ["pharmacy", "pill"], ["police", "police-car"]].map(([k, ic]) => {
                const p = res.nearest?.[k]?.[0];
                return p && (
                  <div key={k} className="list-row" style={{ alignItems: "center" }}>
                    <Icon name={ic} size={22} />
                    <div className="col grow"><span className="strong" style={{ fontSize: 14 }}>{p.name}</span>
                      <span className="cap">{(p.distance_m / 1000).toFixed(1)} km{p.open_now != null && <> · <b style={{ color: p.open_now ? "var(--clear)" : "var(--avoid)" }}>{p.open_now ? t("Open") : t("Closed")}</b></>}</span></div>
                    {p.phone && <a className="call-btn soft" href={`tel:${p.phone}`} aria-label={t("Call {n}", { n: p.name })}><Icon name="phone" fill /></a>}
                  </div>
                );
              })}
            </div>
          )}
          <button className="btn btn-ghost" onClick={() => { sp.stop(); setRes(null); setKind(null); setNote(""); setPeople(1); setInjured(false); }}>{t("Close")}</button>
        </div>
      </div>
    );
  }

  // ── details ────────────────────────────────────────────
  if (kind) return (
    <div className="screen" style={{ bottom: 64 }}>
      <BackHeader onBack={() => setKind(null)} />
      <div className="screen-body col gap16" style={{ paddingTop: 4 }}>
        <div className="col"><span className="cap strong" style={{ color: "var(--ink-2)" }}>{t(KINDS.find((k) => k[0] === kind)[2])}</span><h1 className="h1">{t("A few details")}</h1></div>
        <div className="between" style={{ paddingBottom: 16, borderBottom: "1px solid var(--line)" }}><span className="strong">{t("People involved")}</span>
          <div className="stepper"><button onClick={() => setPeople(Math.max(1, people - 1))} aria-label={t("Fewer")}><Icon name="minus" /></button>
            <span className="big-num" style={{ minWidth: 24, textAlign: "center" }}>{people}</span>
            <button onClick={() => setPeople(people + 1)} aria-label={t("More")}><Icon name="plus" /></button></div></div>
        <div className="between" style={{ paddingBottom: 16, borderBottom: "1px solid var(--line)" }}><span className="strong">{t("Someone is injured")}</span>
          <button className={`switch ${injured ? "on" : ""}`} onClick={() => setInjured(!injured)} aria-pressed={injured} /></div>
        <div><label className="label">{t("Note · optional, any language")}</label>
          <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("What happened, in your own words")} /></div>
      </div>
      <div className="screen-foot"><button className="btn btn-danger btn-block" disabled={busy} onClick={send}><Icon name="siren" />{busy ? t("Preparing…") : t("Get help now")}</button></div>
    </div>
  );

  // ── entry ──────────────────────────────────────────────
  return (
    <div className="screen" style={{ bottom: 64 }}>
      <div className="screen-body col gap16" style={{ paddingTop: 24 }}>
        <h1 className="h1" style={{ fontSize: 32, lineHeight: "38px" }}>{t("Emergency")}</h1>
        <div className="card" style={{ overflow: "hidden" }}>
          {ORDER.map((k) => (
            <a key={k} className="call-row" href={`tel:${nums[k]}`}>
              <span className="strong">{t(NUM_LABEL[k])}</span>
              <span className="row gap16"><span className="big-num" style={{ fontSize: 20 }}>{nums[k]}</span><span className="call-btn"><Icon name="phone" fill /></span></span>
            </a>
          ))}
        </div>
        <span className="h3">{t("What happened?")}</span>
        <div className="grid2">
          {KINDS.map(([k, ic, l]) => (
            <button key={k} className="tile" style={{ flexDirection: "row", alignItems: "center", height: 72 }} onClick={() => setKind(k)}>
              <Icon name={ic} size={22} /><span className="strong" style={{ fontSize: 15 }}>{t(l)}</span></button>
          ))}
        </div>
      </div>
    </div>
  );
}
