// Rafiq UI primitives, matching the Claude Design "Rafiq Design System".
import { useState } from "react";
import { STATUS, typeOf, sourceOf, confWord, ago, isEstimated, dist } from "./hazardStyle.js";
import { useT, useTx } from "./i18n.js";
import { photoUrl } from "./api.js";

export const Icon = ({ name, fill, bold, size, style, className = "" }) => (
  <i className={`${fill ? "ph-fill" : bold ? "ph-bold" : "ph"} ph-${name} ${className}`} style={{ fontSize: size, ...style }} aria-hidden="true" />
);

export function StarMark({ size = 24, color = "var(--brand)", spin = false }) {
  return (
    <span style={{ position: "relative", width: size, height: size, flex: "none", display: "inline-block", verticalAlign: "top",
      animation: spin ? "rfq-spin 6s linear infinite" : "none" }}>
      <span style={{ position: "absolute", inset: "14.6%", background: color }} />
      <span style={{ position: "absolute", inset: "14.6%", background: color, transform: "rotate(45deg)" }} />
    </span>
  );
}

export function Wordmark({ size = 28, color = "var(--ink)", starColor }) {
  const s = Math.round(size * 0.27);
  return (
    <span dir="ltr" style={{ display: "inline-flex", alignItems: "baseline", font: `800 ${size}px/1 var(--font-display)`, letterSpacing: "-0.02em", color }} aria-label="rafiq">
      raf<span style={{ position: "relative", display: "inline-block" }}>ı
        <span style={{ position: "absolute", left: "50%", top: Math.round(size * 0.03), width: s, height: s, transform: "translateX(-50%)", lineHeight: 0, fontSize: 0 }}>
          <StarMark size={s} color={starColor || (color === "var(--ink)" ? "var(--brand)" : color)} />
        </span>
      </span>q
    </span>
  );
}

export function StatusPill({ status = "clear", size = "S", label }) {
  const s = STATUS[status] || STATUS.unknown;
  return (
    <span className={`pill ${size === "M" ? "m" : ""}`} style={{ "--c": `var(${s.color})` }}>
      <Icon name={s.icon} fill />{label || s.label}
    </span>
  );
}

export const SimTag = () => { const { t } = useT(); return <span className="sim">{t("SIMULATED")}</span>; };

export function Meter({ conf, estimated }) {
  const n = estimated ? 0 : Math.max(1, Math.round((conf * 100) / 20));
  return <span className="meter" aria-hidden="true">{[0, 1, 2, 3, 4].map((i) => <span key={i} className={i < n ? "on" : ""} />)}</span>;
}

const METHOD = { photo: ["camera", "traveller photo", "traveller photos"], body: ["person-simple", "body-height report", "body-height reports"],
  web: ["video-camera", "web video", "web videos"], replay: ["flask", "simulated report", "simulated reports"] };

/** The signature component: source · confidence · age. Tap to see every source. */
export function EvidenceLine({ e, expandable = true }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const s = sourceOf(e);
  const est = isEstimated(e);
  const methods = e.data?.methods;
  return (
    <div>
      <button className="ev" onClick={() => expandable && setOpen((o) => !o)}
        aria-label={`${s.name}, ${confWord(e.confidence, est)}, ${ago(e.observed_at)}`}>
        <Icon name={s.icon} /><span className="src">{s.name}</span><span className="dot">·</span>
        <Meter conf={e.confidence} estimated={est} /><span className="conf">{confWord(e.confidence, est)}</span>
        <span className="dot">·</span><span>{ago(e.observed_at)}</span>
        {expandable && <Icon name={open ? "caret-up" : "caret-down"} size={12} />}
      </button>
      {open && (
        <div className="inset ev-more">
          <div className="cap" style={{ marginBottom: 4, fontWeight: 600 }}>{t("Every source behind this item")}</div>
          {methods ? Object.entries(methods).map(([k, v]) => (
            <div className="row" key={k}><span className="row gap8"><Icon name={METHOD[k]?.[0] || "info"} />
              {v} {t(METHOD[k] ? METHOD[k][v > 1 ? 2 : 1] : k)}</span></div>
          )) : <div className="row"><span className="row gap8"><Icon name={s.icon} />{s.name}</span><span className="faint">{ago(e.observed_at)}</span></div>}
          {e.source_url && <div className="row"><a href={e.source_url} target="_blank" rel="noreferrer" className="link">{t("Open source")}</a></div>}
          {e.votes_still_there + e.votes_gone > 0 && <div className="row faint">{t("{a} said still there · {b} said gone", { a: e.votes_still_there, b: e.votes_gone })}</div>}
        </div>
      )}
    </div>
  );
}

export function HazardIcon({ type, lg }) {
  const t = typeOf(type);
  return <span className={`hz-ic ${lg ? "lg" : ""}`} style={{ "--c": `var(${t.color})` }}><Icon name={t.icon} /></span>;
}

export function HazardRow({ e, distance, onClick }) {
  const title = useTx(e.title);
  return (
    <button className="list-row tappable" onClick={onClick}>
      <HazardIcon type={e.type} />
      <div className="grow col gap4">
        <div className="row"><span className="strong ellipsis" style={{ font: "600 15px/20px var(--font-ui)" }}>{title}</span>{e.is_simulated && <SimTag />}</div>
        <EvidenceLine e={e} expandable={false} />
      </div>
      {distance != null && <span className="strong tnum" style={{ font: "600 13px/20px var(--font-ui)", whiteSpace: "nowrap" }}>{dist(distance)}</span>}
    </button>
  );
}

export function DepthGauge({ depth = 48, estimated = false, height = 220 }) {
  const { t } = useT();
  const k = height / 180;
  const marks = [[12, t("Ankle")], [50, t("Knee")], [60, t("Cars float")], [100, t("Waist")], [150, "150 cm"]];
  return (
    <div className="gauge" dir="ltr" style={{ height }} aria-label={t("Water about {n} centimetres", { n: depth }) + (estimated ? `, ${t("estimated")}` : "")}>
      <div className="person" style={{ height }}><Icon name="person-simple" fill size={Math.round((170 * k) / 0.875)} style={{ lineHeight: 1, marginBottom: -Math.round((170 * k) / 0.875 * 0.04) }} /></div>
      {marks.map(([cm, label]) => (
        <div key={cm} className="tick" style={{ bottom: Math.round(cm * k), borderTopStyle: cm === 60 ? "solid" : "dashed",
          borderColor: cm === 60 ? "var(--avoid)" : cm === 150 ? "var(--ink-3)" : "var(--ink-2)" }}>
          <span style={{ color: cm === 60 ? "var(--avoid)" : cm === 150 ? "var(--ink-3)" : "var(--ink-2)", ...(cm === 60 ? { left: 0, right: "auto" } : {}) }}>{label}</span>
        </div>
      ))}
      <div className="water" style={{ height: Math.round(Math.min(depth, 170) * k),
        background: estimated ? "repeating-linear-gradient(45deg, color-mix(in srgb, var(--water-est) 70%, transparent) 0 3px, transparent 3px 8px)"
          : "color-mix(in srgb, var(--water) 38%, transparent)",
        borderTop: `2px ${estimated ? "dashed" : "solid"} var(--water)` }} />
    </div>
  );
}

export function TrendChip({ trend, minutes }) {
  const { t } = useT();
  if (trend == null) return null;
  const up = trend > 1, down = trend < -1;
  return (
    <span className="trend" style={{ "--c": up ? "var(--avoid)" : down ? "var(--clear)" : "var(--ink-2)" }}>
      <Icon name={up ? "trend-up" : down ? "trend-down" : "minus"} />
      {up ? t("Rising {n} cm/h", { n: Math.round(trend) }) : down ? t("Falling {n} cm/h", { n: Math.round(-trend) }) : t("Stable")}
      {up && minutes ? ` · ${t("next level in ~{n} min", { n: minutes })}` : ""}
    </span>
  );
}

/** Place photo (Google Places, proxied by our server) or the striped placeholder. */
export function PhotoSlot({ label, status, height = 124, photo, w = 480, children, icon }) {
  const [failed, setFailed] = useState(false);
  const src = photo && !failed ? photoUrl(photo, w) : null;
  return (
    <div className="photo" style={{ height }}>
      {src && <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} />}
      {!src && icon && <span className="ph-icon"><Icon name={icon} /></span>}
      {status && <span className="ph-status"><StatusPill status={status} /></span>}
      {!src && label && <span className="ph-label">{label}</span>}
      {children}
    </div>
  );
}

export function Toast({ toast, onUndo }) {
  const { t } = useT();
  if (!toast) return null;
  const ic = { success: ["check-circle", "var(--clear)"], info: ["info", "var(--brand)"], error: ["x-circle", "var(--avoid)"] }[toast.kind || "success"];
  return (
    <div className="toast" role="status">
      <Icon name={ic[0]} fill className="t-ic" style={{ color: ic[1] }} />
      <span className="grow">{toast.text}</span>
      {toast.undo && <button className="link" style={{ color: "var(--water-est)" }} onClick={onUndo}>{t("Undo")}</button>}
    </div>
  );
}

export function Skeleton({ h = 16, w = "100%", r }) {
  return <div className="skel" style={{ height: h, width: w, borderRadius: r }} />;
}

export function BackHeader({ onBack, title, right, icon = "arrow-left" }) {
  const { t } = useT();
  return (
    <div className="between" style={{ padding: "8px 20px 0" }}>
      <button className="back" onClick={onBack} aria-label={t("Back")}><Icon name={icon} className="flip-rtl" /></button>
      {title && <span className="h3 grow">{title}</span>}
      {right}
    </div>
  );
}

export function Stars({ rating, count }) {
  if (!rating) return null;
  return <span className="row" style={{ gap: 3, display: "inline-flex" }}><Icon name="star" fill size={12} style={{ color: "var(--caution)" }} />
    <span className="tnum">{rating.toFixed(1)}</span>{count ? <span className="faint tnum">({count >= 1000 ? `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}k` : count})</span> : null}</span>;
}
