// First screen a new traveller sees: what Rafiq does, in their language, then "Get started".
import { useState } from "react";
import { Icon, Wordmark } from "../ui.jsx";
import { LANGS, useT } from "../i18n.js";

function LiveMapArt() {
  const reduce = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const route = "M40 250 C 90 240, 110 200, 120 160 S 170 90, 250 70";
  return (
    <svg viewBox="0 0 300 300" className="hero-art" role="img" aria-label="" direction="ltr" dir="ltr">
      <defs>
        <pattern id="hgrid" width="30" height="30" patternUnits="userSpaceOnUse">
          <path d="M30 0H0V30" fill="none" stroke="currentColor" strokeOpacity=".10" />
        </pattern>
      </defs>
      <rect x="0" y="0" width="300" height="300" rx="28" fill="url(#hgrid)" />
      <path d="M-10 40 C 60 70, 120 20, 190 40 S 290 20, 320 10" fill="none" stroke="currentColor" strokeOpacity=".22" strokeWidth="10" />
      {/* hazard: flood ring the route avoids */}
      <g transform="translate(185 190)">
        <circle r="46" fill="var(--hero-water)" fillOpacity=".28" />
        <circle r="46" fill="none" stroke="var(--hero-water)" strokeWidth="2">
          {!reduce && <animate attributeName="r" values="30;58;30" dur="3.2s" repeatCount="indefinite" />}
          {!reduce && <animate attributeName="stroke-opacity" values=".9;0;.9" dur="3.2s" repeatCount="indefinite" />}
        </circle>
        <circle r="15" fill="#fff" /><path d="M-8 1 q4 -5 8 0 t8 0 M-8 6 q4 -5 8 0 t8 0" stroke="var(--hero-water)" strokeWidth="2.2" fill="none" />
      </g>
      {/* hazard: fire */}
      <g transform="translate(70 95)"><circle r="22" fill="var(--hero-fire)" fillOpacity=".25" /><circle r="12" fill="#fff" />
        <path d="M0 -6 C 4 -1, 5 2, 0 7 C -5 2, -3 -2, 0 -6Z" fill="var(--hero-fire)" /></g>
      {/* the blocked fastest route, dashed, and the chosen one */}
      <path d="M40 250 C 110 250, 170 220, 190 180 S 230 100, 250 70" fill="none" stroke="currentColor" strokeOpacity=".35" strokeWidth="4" strokeDasharray="6 7" />
      <path d={route} fill="none" stroke="#fff" strokeWidth="9" strokeLinecap="round" />
      <path d={route} fill="none" stroke="var(--hero-route)" strokeWidth="5" strokeLinecap="round" />
      <g transform="translate(250 70)"><circle r="13" fill="var(--hero-route)" stroke="#fff" strokeWidth="3" />
        <path d="M-4 5 V-6 L5 -3 L-4 0" stroke="#fff" strokeWidth="2" fill="none" /></g>
      {/* the traveller: 8-point star moving along the chosen route */}
      <g>
        <g transform="translate(-9 -9)">
          <rect width="18" height="18" fill="#fff" /><rect width="18" height="18" fill="#fff" transform="rotate(45 9 9)" />
          <rect x="3" y="3" width="12" height="12" fill="var(--hero-route)" /><rect x="3" y="3" width="12" height="12" fill="var(--hero-route)" transform="rotate(45 9 9)" />
        </g>
        {reduce ? <animateTransform attributeName="transform" type="translate" values="120 160" dur="1s" fill="freeze" />
          : <animateMotion dur="6s" repeatCount="indefinite" path={route} />}
      </g>
      <g transform="translate(196 118)">
        <rect x="0" y="-15" width="96" height="30" rx="15" fill="#fff" />
        <circle cx="15" cy="0" r="5" fill="var(--hero-ok)" />
        <text x="26" y="4.5" fontSize="12" fontWeight="700" fill="#0B1B2B" fontFamily="Inter, sans-serif">LIVE</text>
      </g>
    </svg>
  );
}

export default function Hero({ prefs, setPrefs, onStart }) {
  const { t } = useT();
  const [langOpen, setLangOpen] = useState(false);
  const features = [
    ["broadcast", t("Live conditions"), t("Weather, satellites, news and travellers, checked every 5 minutes.")],
    ["path", t("Routes around trouble"), t("Every route is checked against live reports while you travel.")],
    ["siren", t("Help in the local language"), t("One tap shows and reads an emergency card in Arabic and French.")],
  ];
  return (
    <div className="screen hero pattern-strong">
      <div className="hero-top">
        <Wordmark size={30} color="#F7FAFC" starColor="#F7FAFC" />
        <button className="hero-lang" onClick={() => setLangOpen((o) => !o)} aria-expanded={langOpen} aria-label={t("Language")}>
          <Icon name="globe-hemisphere-east" size={18} />{LANGS.find((l) => l[2] === prefs.lang)?.[0] || "English"}<Icon name="caret-down" size={14} />
        </button>
      </div>
      {langOpen && (
        <div className="hero-langs" role="listbox">
          {LANGS.map(([native, , code]) => (
            <button key={code} role="option" aria-selected={prefs.lang === code} className={prefs.lang === code ? "on" : ""}
              onClick={() => { setPrefs({ ...prefs, lang: code }); setLangOpen(false); }}>{native}</button>
          ))}
        </div>
      )}
      <div className="hero-body hide-scroll">
        <LiveMapArt />
        <h1 className="hero-title">{t("Know what is happening before you go")}</h1>
        <p className="hero-sub">{t("Floods, fires, storms, power cuts and blocked roads across Tunisia, live. Rafiq steers you around them and gets you help in the local language.")}</p>
        <div className="col gap16" style={{ marginTop: 8 }}>
          {features.map(([ic, title, text]) => (
            <div key={ic} className="row gap12" style={{ alignItems: "flex-start" }}>
              <span className="hero-ic"><Icon name={ic} size={22} /></span>
              <div className="col"><span style={{ font: "700 16px/22px var(--font-display)" }}>{title}</span>
                <span style={{ font: "400 14px/20px var(--font-ui)", opacity: 0.85 }}>{text}</span></div>
            </div>
          ))}
        </div>
      </div>
      <div className="hero-foot">
        <button className="btn btn-block hero-cta" onClick={onStart}>{t("Get started")}<Icon name="arrow-right" className="flip-rtl" /></button>
        <span className="hero-note"><Icon name="lock-simple" size={14} />{t("No account needed. Reports are anonymous.")}</span>
      </div>
    </div>
  );
}
