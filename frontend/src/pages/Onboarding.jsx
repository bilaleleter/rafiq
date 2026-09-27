// A · First run: hero, language, interests, permissions, emergency contact.
import { useState } from "react";
import { Icon } from "../ui.jsx";
import { LANGS, useT } from "../i18n.js";
import { CATEGORY_ICON, categoryPlural, INTERESTS } from "../hazardStyle.js";
import Hero from "./Hero.jsx";

export { LANGS };

function Steps({ n }) {
  return <div className="progress" style={{ margin: "8px 0 32px" }}>{[1, 2, 3, 4].map((i) => <span key={i} className={i <= n ? "on" : ""} />)}</div>;
}

export default function Onboarding({ prefs, setPrefs, onDone, requestLocation }) {
  const { t } = useT();
  const [step, setStep] = useState(0);
  const back = step > 0 && (
    <button className="back" style={{ margin: "8px 0 0 12px" }} onClick={() => setStep(step - 1)} aria-label={t("Back")}><Icon name="arrow-left" className="flip-rtl" /></button>);

  if (step === 0) return <Hero prefs={prefs} setPrefs={setPrefs} onStart={() => setStep(1)} />;

  const shell = (n, title, sub, body, foot) => (
    <div className="screen pattern">
      {back}
      <div className="screen-body" style={{ paddingTop: 4 }}>
        <Steps n={n} />
        <div className="over">{t("Step {n} of 4", { n })}{n === 4 ? ` · ${t("optional")}` : ""}</div>
        <h1 className="h1" style={{ margin: "6px 0 8px" }}>{title}</h1>
        <p className="sec" style={{ margin: "0 0 28px", fontSize: 16, lineHeight: "24px" }}>{sub}</p>
        {body}
      </div>
      <div className="screen-foot">{foot}</div>
    </div>
  );

  if (step === 1) return shell(1, t("Choose your language"), t("The app, alerts, summaries and emergency cards follow this choice."),
    <div className="col gap8">
      {LANGS.map(([native, en, code]) => (
        <button key={code} className={`opt ${prefs.lang === code ? "on" : ""}`} onClick={() => setPrefs({ ...prefs, lang: code })}>
          <span className="col"><span className="strong" style={{ fontSize: 17 }}>{native}</span><span className="cap">{en}</span></span>
          {prefs.lang === code && <span className="check"><Icon name="check" bold /></span>}
        </button>
      ))}
    </div>,
    <button className="btn btn-primary btn-block" onClick={() => setStep(2)}>{t("Continue")}</button>);

  if (step === 2) {
    const toggle = (k) => setPrefs({ ...prefs, interests: prefs.interests.includes(k) ? prefs.interests.filter((x) => x !== k) : [...prefs.interests, k] });
    return shell(2, t("What do you love?"), t("Pick any. Suggestions follow what you choose and what is happening right now."),
      <div className="grid3">
        {INTERESTS.map((k) => {
          const on = prefs.interests.includes(k);
          return (
            <button key={k} className={`tile ${on ? "on" : ""}`} style={{ height: 88, justifyContent: "space-between", padding: 12 }} onClick={() => toggle(k)} aria-pressed={on}>
              <span className="between" style={{ width: "100%" }}><Icon name={CATEGORY_ICON[k]} style={{ color: on ? "var(--brand)" : "var(--ink)" }} />
                {on && <span className="check" style={{ width: 20, height: 20, fontSize: 12 }}><Icon name="check" bold /></span>}</span>
              <span className="strong" style={{ fontSize: 14 }}>{categoryPlural(k)}</span>
            </button>
          );
        })}
      </div>,
      <>
        <button className="btn btn-primary btn-block" onClick={() => setStep(3)}>{prefs.interests.length ? t("Continue with {n}", { n: prefs.interests.length }) : t("Continue")}</button>
        <button className="btn btn-ghost" onClick={() => setStep(3)}>{t("Skip")}</button>
      </>);
  }

  if (step === 3) return (
    <div className="screen pattern">
      {back}
      <div className="screen-body" style={{ paddingTop: 4 }}>
        <Steps n={3} />
        <div style={{ width: 96, height: 96, borderRadius: 20, background: "var(--brand-soft)", display: "flex", alignItems: "center", justifyContent: "center", margin: "32px 0 24px" }}>
          <Icon name="navigation-arrow" size={44} style={{ color: "var(--brand)" }} />
        </div>
        <div className="over">{t("Permissions · location")}</div>
        <h1 className="h1" style={{ margin: "6px 0 8px" }}>{t("Share your location")}</h1>
        <p className="sec" style={{ fontSize: 16, lineHeight: "26px", margin: "0 0 24px" }}>{t("Used to warn you about problems where you are and on your route.")}</p>
        <div className="col gap12 sec" style={{ color: "var(--ink)" }}>
          <div className="between"><span className="row gap12"><Icon name="navigation-arrow" fill style={{ color: "var(--brand)" }} size={20} />{t("Location")}</span><span className="cap" style={{ color: "var(--brand)" }}>{t("Now")}</span></div>
          <div className="row gap12"><Icon name="bell" size={20} />{t("Notifications, for alerts during your trip")}</div>
          <div className="row gap12"><Icon name="camera" size={20} />{t("Camera, only when you choose to report")}</div>
        </div>
      </div>
      <div className="screen-foot">
        <button className="btn btn-primary btn-block" onClick={async () => {
          requestLocation();
          try { if ("Notification" in window) await Notification.requestPermission(); } catch {}
          setStep(4);
        }}>{t("Allow")}</button>
        <button className="btn btn-ghost" style={{ color: "var(--ink-2)" }} onClick={() => setStep(4)}>{t("Not now")}</button>
      </div>
    </div>
  );

  return shell(4, t("Emergency contact"), t("Used only when you tap SOS, then Share. Stored on this phone, never sent to us."),
    <div className="col gap16">
      <div><label className="label" htmlFor="c-name">{t("Name")}</label>
        <input id="c-name" className="input" value={prefs.contactName || ""} onChange={(e) => setPrefs({ ...prefs, contactName: e.target.value })} placeholder={t("Name")} /></div>
      <div><label className="label" htmlFor="c-phone">{t("Phone")}</label>
        <div className="input row" style={{ padding: 0 }} dir="ltr">
          <span className="strong" style={{ padding: "0 12px 0 16px", borderRight: "1px solid var(--line)" }}>+216</span>
          <input id="c-phone" style={{ border: 0, background: "transparent", outline: "none", flex: 1, padding: "0 12px", fontSize: 16 }} inputMode="tel"
            value={prefs.contactPhone || ""} onChange={(e) => setPrefs({ ...prefs, contactPhone: e.target.value })} placeholder="20 123 456" />
        </div></div>
      <div className="row cap"><Icon name="lock-simple" size={16} />{t("Rafiq never contacts this person on its own.")}</div>
    </div>,
    <>
      <button className="btn btn-primary btn-block" onClick={onDone}>{t("Save and finish")}</button>
      <button className="btn btn-ghost" style={{ color: "var(--ink-2)" }} onClick={onDone}>{t("Skip for now")}</button>
    </>);
}
