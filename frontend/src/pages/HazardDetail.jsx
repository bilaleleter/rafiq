// E · Hazard detail: one template + type-specific modules (flood, estimated flood, power, fire, weather, crowd).
import { api } from "../api.js";
import { Icon, HazardIcon, StatusPill, EvidenceLine, DepthGauge, TrendChip, SimTag } from "../ui.jsx";
import { isEstimated, hhmm, ago, dist, haversine, statusOfEvent } from "../hazardStyle.js";
import { useT, useTx } from "../i18n.js";

export const statusOf = statusOfEvent;

function Text({ text }) {
  const tx = useTx(text);
  return tx ? <p className="body" style={{ margin: 0 }}>{tx}</p> : null;
}

function FloodModule({ e }) {
  const { t } = useT();
  const d = e.data || {};
  const depth = d.depth_cm ?? 20;
  const note = depth >= 60 ? t("Do not drive or walk through. Vehicles can be swept away at this depth.")
    : depth >= 30 ? t("Do not drive through. Cars can float from 30–60 cm.")
      : depth >= 15 ? t("Don't walk through moving water. It can knock you over at this depth.") : t("Walk carefully and avoid open drains.");
  const M = { photo: ["camera", "{n} photo(s), waterline read"], body: ["person-simple", "{n} body report(s)"], web: ["video-camera", "{n} web video(s), checked"] };
  return (
    <div className="col gap12">
      <div className="card card-pad col gap12">
        <div className="between" style={{ alignItems: "flex-end" }}>
          <div className="col"><span className="over">{t("Water depth")}</span><span className="tnum" style={{ font: "800 34px/40px var(--font-display)" }}>{depth} cm</span></div>
          <TrendChip trend={d.trend_cm_per_h} minutes={d.minutes_to_next_level} />
        </div>
        <DepthGauge depth={depth} />
        <div className="row gap8" style={{ background: "color-mix(in srgb, var(--avoid) 10%, var(--surface))", borderRadius: 12, padding: "10px 12px", alignItems: "flex-start" }}>
          <Icon name="warning" fill size={18} style={{ color: "var(--avoid)", marginTop: 1 }} /><span className="sec" style={{ color: "var(--ink)" }}>{note}</span>
        </div>
      </div>
      {d.kind === "river" && <Text text={e.description} />}
      {d.evidence?.length > 0 && (
        <div className="col gap8"><span className="over">{t("Evidence")}</span>
          <div className="row gap8 hide-scroll" style={{ overflowX: "auto" }}>
            {d.evidence.map((ev, i) => (
              <a key={i} href={ev.url} target="_blank" rel="noreferrer" className="col gap4" style={{ width: 132, flex: "none", textDecoration: "none", color: "var(--ink)" }}>
                <div className="photo" style={{ height: 96, backgroundImage: `url(${ev.thumb})`, backgroundSize: "cover" }}>
                  <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <span className="float-round small"><Icon name="play" fill /></span></span></div>
                <span className="cap">{ev.url?.includes("tiktok") ? "TikTok" : ev.url?.includes("flickr") ? "Flickr" : "YouTube"} · {ago(ev.at)}</span>
              </a>
            ))}
          </div></div>
      )}
      {d.methods && (
        <div className="col">
          {Object.entries(M).map(([k, [ic, label]]) => d.methods[k] > 0 && (
            <div key={k} className="list-row"><Icon name={ic} size={20} /><span className="grow">{t(label, { n: d.methods[k] })}</span></div>))}
          {d.methods.replay > 0 && <div className="list-row"><Icon name="flask" size={20} /><span className="grow">{t("{n} simulated reports", { n: d.methods.replay })}</span><SimTag /></div>}
        </div>
      )}
    </div>
  );
}

function EstimatedModule({ e }) {
  const { t } = useT();
  const d = e.data || {};
  const lo = Math.max(5, Math.round((d.depth_cm * 0.7) / 5) * 5), hi = Math.round((d.depth_cm * 1.2) / 5) * 5;
  return (
    <div className="col gap12">
      <div className="card card-pad col gap12" style={{ borderStyle: "dashed" }}>
        <div className="col"><span className="over">{t("Estimated depth")}</span><span className="tnum" style={{ font: "800 30px/36px var(--font-display)" }}>~{lo}–{hi} cm</span></div>
        <DepthGauge depth={d.depth_cm} estimated />
      </div>
      <p className="body" style={{ margin: 0 }}>{t("Estimated from {mm} mm of rain and low ground ({sink} m below its surroundings). No photo yet.", { mm: d.rain_mm, sink: d.sink_m })}</p>
    </div>
  );
}

function PowerModule({ e }) {
  const { t } = useT();
  const d = e.data || {};
  const since = d.since ? new Date(d.since) : new Date(e.observed_at);
  const mins = Math.max(1, Math.round((Date.now() - since.getTime()) / 60000));
  return (
    <div className="col gap12">
      <div className="row gap8 sec" style={{ color: "var(--ink)" }}><Icon name="plug" size={18} />{t("{n} people reported", { n: d.devices || e.reports_count })}{d.charger_verified ? `, ${t("{n} verified by charger", { n: d.charger_verified })}` : ""}</div>
      <div className="col gap4">
        <div style={{ height: 10, borderRadius: 5, background: "var(--surface-2)", position: "relative", overflow: "hidden" }}>
          <div style={{ position: "absolute", inset: 0,
            background: "repeating-linear-gradient(45deg, var(--power) 0 6px, color-mix(in srgb, var(--power) 55%, var(--surface)) 6px 12px)" }} />
        </div>
        <div className="between cap tnum"><span>{t("Cut at {time}", { time: hhmm(since.toISOString()) })}</span><span>{mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`}</span><span>{t("Now")} {hhmm(new Date().toISOString())}</span></div>
      </div>
      <p className="body" style={{ margin: 0 }}>{t("Expect no lights, lifts, card machines or AC. Phone signal may weaken.")}</p>
    </div>
  );
}

function FireModule({ e }) {
  const { t } = useT();
  return (
    <div className="col gap12">
      <div className="row" style={{ gap: 32 }}>
        <div className="col"><span className="big-num">{e.data?.hotspots ?? e.reports_count}</span><span className="cap">{t("Hotspots")}</span></div>
        <div className="col"><span className="big-num">{ago(e.observed_at)}</span><span className="cap">{t("Detected")}</span></div>
        {e.data?.frp_mw != null && <div className="col"><span className="big-num">{Math.round(e.data.frp_mw)} MW</span><span className="cap">{t("Fire power")}</span></div>}
      </div>
      <Text text={e.description} />
    </div>
  );
}

function WeatherModule({ e }) {
  const { t } = useT();
  const v = e.data?.value, u = e.data?.unit;
  return (
    <div className="col gap8">
      {v != null && <div className="row" style={{ alignItems: "baseline", gap: 6 }}><span className="tnum" style={{ font: "800 34px/40px var(--font-display)" }}>{Math.round(v)}</span><span className="sec">{u}</span>
        <span className="cap grow" style={{ textAlign: "end" }}>{t("Next 6 hours")}{e.data?.threshold ? ` · ${t("threshold {n}", { n: e.data.threshold })}` : ""}</span></div>}
      <Text text={e.description} />
    </div>
  );
}

function CrowdModule({ e }) {
  const notes = (e.data?.notes || []).filter(Boolean).slice(-3);
  return (
    <div className="col gap8">
      <Text text={e.description} />
      {notes.map((n, i) => <div key={i} className="inset sec" style={{ color: "var(--ink)", fontStyle: "italic" }}>“{n}”</div>)}
    </div>
  );
}

export function HazardDetail({ e, me, onClose, onSendPhoto }) {
  const { t } = useT();
  const title = useTx(e.title);
  const est = isEstimated(e);
  const d = me ? haversine(me, e) : null;
  const Module = e.type === "flood" ? (est ? EstimatedModule : FloodModule) : e.type === "power" ? PowerModule : e.type === "fire" ? FireModule
    : ["storm", "wind", "heat", "earthquake"].includes(e.type) ? WeatherModule : CrowdModule;
  return (
    <div className="col gap12">
      <div className="row gap12" style={{ alignItems: "flex-start" }}>
        <HazardIcon type={e.type} lg />
        <div className="col grow gap4"><span className="h3">{title}</span>
          <span className="cap">{e.data?.place ? `${e.data.place} · ` : ""}{d != null ? (d < 40 ? t("Right here") : t("{d} away", { d: dist(d) })) : ""}</span></div>
        <button className="float-round small" style={{ boxShadow: "none", background: "var(--surface-2)" }} onClick={onClose} aria-label={t("Close")}><Icon name="x" /></button>
      </div>
      <div className="row gap8">{est ? <StatusPill status="caution" /> : <StatusPill status={statusOf(e)} />}{e.is_simulated && <SimTag />}</div>
      <EvidenceLine e={e} />
      <Module e={e} />
      {!est && e.type === "flood" && <button className="btn btn-outline" onClick={() => onSendPhoto(e)}><Icon name="plus-circle" />{t("Report an update")}</button>}
    </div>
  );
}

export function HazardFoot({ e, me, onDone, onSendPhoto, toast }) {
  const { t } = useT();
  if (isEstimated(e)) return <button className="btn btn-primary btn-block" onClick={() => onSendPhoto(e)}><Icon name="camera" />{t("I'm here, send a photo")}</button>;
  if (e.type === "power") return (
    <div className="row gap8">
      <button className="btn btn-secondary grow" onClick={() => api.power(me, "off").then(() => toast({ text: t("Thanks. Marked as still out.") })).catch((x) => toast({ text: x.message, kind: "error" }))}>{t("Still out")}</button>
      <button className="btn btn-primary grow" onClick={() => api.power(me, "on").then((r) => { toast({ text: r.closed ? t("Thanks. Outage marked as over.") : t("Thanks. Waiting for one more confirmation.") }); onDone(); }).catch((x) => toast({ text: x.message, kind: "error" }))}>{t("Power is back")}</button>
    </div>
  );
  return (
    <div className="row gap8">
      <button className="btn btn-secondary grow" onClick={() => api.vote(e.id, true).then(() => toast({ text: t("Thanks. Confirmed for other travellers.") })).catch((x) => toast({ text: x.message, kind: "error" }))}><Icon name="check" />{t("Still there")}</button>
      <button className="btn btn-secondary grow" onClick={() => api.vote(e.id, false).then(() => { toast({ text: t("Thanks. It will be removed once others agree.") }); onDone(); }).catch((x) => toast({ text: x.message, kind: "error" }))}><Icon name="x" />{t("It's gone")}</button>
    </div>
  );
}
