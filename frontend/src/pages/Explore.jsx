// B · Explore sheet (search any place, recommendations, live near you) and C · Destination.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { Icon, StatusPill, PhotoSlot, HazardRow, EvidenceLine, Skeleton, Stars, SimTag } from "../ui.jsx";
import { CATEGORY_ICON, CATEGORY_LABEL, categoryPlural, INTERESTS, dist, haversine, statusOfEvent } from "../hazardStyle.js";
import { useT, useTx } from "../i18n.js";
import { speak, stopSpeaking } from "../voice.js";

const SEV = { info: 0, warning: 1, danger: 2, critical: 3 };

function whyText(w, t) {
  switch (w.k) {
    case "interest": return t("Matches your interests");
    case "open": return t("Open now");
    case "closed": return t("Closed now");
    case "indoor_weather": return t("Indoors, good for today's weather");
    case "outdoor_weather": return t("Outdoors, weather warning nearby");
    default: return null;
  }
}

export function ScoreLine({ d }) {
  const b = d.breakdown;
  if (!b) return null;
  return (
    <span className="dev-score" title="100*(0.30*quality+0.15*popularity+0.30*interest+0.25*proximity)*safety*open*weather">
      {b.score ?? d.score} = q{b.quality} p{b.popularity} i{b.interest} d{b.proximity} x s{b.safety} o{b.open} w{b.weather}
    </span>
  );
}

function DestCard({ d, onOpen, dev, wide }) {
  const { t } = useT();
  const w = (d.why || []).map((x) => whyText(x, t)).find(Boolean);
  const reason = useTx(d.status !== "clear" ? d.reasons?.[0]?.title : null);
  return (
    <button className={`dest-card tappable col gap8 ${wide ? "wide" : ""}`} onClick={() => onOpen(d)}>
      <PhotoSlot photo={d.photo} status={d.status} icon={CATEGORY_ICON[d.category]} w={wide ? 640 : 440} />
      <div className="col" style={{ gap: 2 }}>
        <span className="strong ellipsis" style={{ fontSize: 15 }}>{d.name}</span>
        <span className="cap row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <span className="ellipsis">{CATEGORY_LABEL[d.category] || t("Sight")} · {d.distance_km} km</span><Stars rating={d.rating} count={d.rating_count} /></span>
        {reason ? <span className="cap ellipsis" style={{ color: "var(--ink)" }}>{reason}</span>
          : w && <span className="cap ellipsis" style={{ color: "var(--clear)" }}>{w}</span>}
        {dev && <ScoreLine d={d} />}
      </div>
    </button>
  );
}

function Row({ title, sub, items, onOpen, dev, wide }) {
  if (!items.length) return null;
  return (
    <div className="col gap8">
      <div className="col"><span className="h3">{title}</span>{sub && <span className="sec">{sub}</span>}</div>
      <div className="row gap12 hide-scroll hscroll">
        {items.map((d) => <DestCard key={d.id} d={d} onOpen={onOpen} dev={dev} wide={wide} />)}
      </div>
    </div>
  );
}

function SearchBox({ me, lang, onOpen, onActive, toast }) {
  const { t } = useT();
  const [q, setQ] = useState("");
  const [sugg, setSugg] = useState(null);
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const session = useRef(crypto.randomUUID?.() || String(Math.random()));
  useEffect(() => { onActive?.(!!q); }, [!!q]);
  useEffect(() => {
    setResults(null);
    if (q.trim().length < 2) { setSugg(null); return; }
    const id = setTimeout(() => api.autocomplete(q, me, session.current, lang).then((r) => setSugg(r.suggestions)).catch(() => setSugg([])), 220);
    return () => clearTimeout(id);
  }, [q]);
  const pick = async (s) => {
    setBusy(true);
    try {
      const d = await api.placeDetails(s.place_id, me, session.current, lang);
      session.current = crypto.randomUUID?.() || String(Math.random());
      setQ(""); setSugg(null); onOpen(d);
    } catch { toast?.({ text: t("Couldn't open this place."), kind: "error" }); } finally { setBusy(false); }
  };
  const searchAll = async () => {
    if (q.trim().length < 2) return;
    setBusy(true);
    try { setResults((await api.placeSearch(q, me, lang)).results); setSugg(null); } catch { setResults([]); } finally { setBusy(false); }
  };
  return (
    <div className="col gap8">
      <form className="search" onSubmit={(e) => { e.preventDefault(); searchAll(); }} role="search">
        <Icon name="magnifying-glass" />
        <input className="input" placeholder={t("Search any place")} value={q} onChange={(e) => setQ(e.target.value)} enterKeyHint="search" aria-label={t("Search any place")} />
        {q && <button type="button" className="search-clear" onClick={() => { setQ(""); setSugg(null); setResults(null); }} aria-label={t("Clear")}><Icon name="x-circle" fill /></button>}
      </form>
      {busy && <Skeleton h={48} r={12} />}
      {sugg && !results && (
        <div className="col">
          {sugg.length === 0 && <span className="sec" style={{ padding: "8px 4px" }}>{t("No places found.")}</span>}
          {sugg.map((s) => (
            <button key={s.place_id} className="list-row tappable" style={{ alignItems: "center" }} onClick={() => pick(s)}>
              <span className="hz-ic" style={{ "--c": "var(--brand)" }}><Icon name="map-pin" /></span>
              <div className="grow col"><span className="strong ellipsis">{s.main}</span><span className="cap ellipsis">{s.secondary}</span></div>
              {s.distance_m != null && <span className="cap tnum">{dist(s.distance_m)}</span>}
            </button>
          ))}
          {sugg.length > 0 && <button className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }} onClick={searchAll}>
            <Icon name="list-magnifying-glass" />{t("See all results for \"{q}\"", { q })}</button>}
        </div>
      )}
      {results && (
        <div className="col">
          {results.length === 0 && <span className="sec">{t("No places found.")}</span>}
          {results.map((d) => (
            <button key={d.id} className="list-row tappable" onClick={() => { setQ(""); setResults(null); onOpen(d); }}>
              <div style={{ width: 72, flex: "none" }}><PhotoSlot photo={d.photo} height={72} w={200} icon={CATEGORY_ICON[d.category]} /></div>
              <div className="grow col gap4">
                <span className="strong ellipsis">{d.name}</span>
                <span className="cap row" style={{ gap: 6 }}>{CATEGORY_LABEL[d.category]}{d.distance_km != null && ` · ${d.distance_km} km`}<Stars rating={d.rating} count={d.rating_count} /></span>
                <span><StatusPill status={d.status} /></span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ExploreSheet({ me, prefs, setPrefs, snap, eventsVersion, events, recs, setRecs, onOpen, onHazard, onLive, dev, toast }) {
  const { t, lang } = useT();
  const [searching, setSearching] = useState(false);
  const interests = prefs.interests;
  // Re-rank whenever live problems change. Only the newest answer is kept: an older, slower
  // request must never put back a place that has just become "avoid".
  const seq = useRef(0);
  useEffect(() => {
    if (!me) return;
    const n = ++seq.current;
    const id = setTimeout(() => api.recommend(me.lat, me.lon, interests, lang)
      .then((r) => n === seq.current && setRecs(r))
      .catch(() => n === seq.current && setRecs((old) => old || { recommended: [], avoid_now: [], error: true })), 250);
    return () => clearTimeout(id);
  }, [me?.lat?.toFixed(2), me?.lon?.toFixed(2), interests.join(), eventsVersion, lang]);

  const clearCount = recs?.recommended?.filter((d) => d.status === "clear").length || 0;
  const toggle = (k) => setPrefs({ ...prefs, interests: interests.includes(k) ? interests.filter((x) => x !== k) : [...interests, k] });
  const nearby = useMemo(() => (me ? events.map((e) => ({ e, d: haversine(me, e) })).filter((x) => x.d < 25000 + x.e.radius_m)
    .sort((a, b) => SEV[b.e.severity] - SEV[a.e.severity] || a.d - b.d) : []), [events, me?.lat, me?.lon]);
  const sections = useMemo(() => {
    const rec = recs?.recommended || [];
    const cats = [...new Set([...interests, ...rec.map((d) => d.category)])].filter((c) => rec.some((d) => d.category === c));
    return cats.map((c) => ({ c, items: rec.filter((d) => d.category === c).slice(0, 10) })).filter((s) => s.items.length >= 1);
  }, [recs, interests.join()]);

  if (snap === "peek") return (
    <div className="between" style={{ paddingTop: 4 }}>
      <div className="col"><span className="h3">{t("Where to today?")}</span>
        <span className="sec">{recs ? t("{n} places near you with no reported issues", { n: clearCount }) : t("Checking live conditions")}</span></div>
      <Icon name="caret-up" size={20} className="faint" />
    </div>
  );

  return (
    <div className="col gap16" style={{ paddingTop: 4 }}>
      <h2 className="h2">{t("Where to today?")}</h2>
      <SearchBox me={me} lang={lang} onOpen={onOpen} onActive={setSearching} toast={toast} />
      {!searching && <>
        <div className="chips hide-scroll">
          {INTERESTS.map((k) => <button key={k} className={`chip ${interests.includes(k) ? "on" : ""}`} onClick={() => toggle(k)} aria-pressed={interests.includes(k)}>
            <Icon name={CATEGORY_ICON[k]} />{categoryPlural(k)}</button>)}
        </div>
        {nearby.length > 0 && (
          <div className="col">
            <div className="between"><span className="h3">{t("Live near you")}</span>
              <button className="link" onClick={onLive}>{t("See all {n}", { n: events.length })}</button></div>
            {nearby.slice(0, 3).map(({ e, d }) => <HazardRow key={e.id} e={e} distance={d} onClick={() => onHazard(e)} />)}
          </div>
        )}
        {!recs && <div className="row gap12"><div className="col gap8" style={{ width: 220 }}><Skeleton h={124} r={16} /><Skeleton h={14} w="70%" /></div>
          <div className="col gap8" style={{ width: 220 }}><Skeleton h={124} r={16} /><Skeleton h={14} w="60%" /></div></div>}
        {recs?.error && <p className="sec">{t("Can't reach live data right now.")}</p>}
        {recs && !recs.error && recs.recommended.length === 0 && <p className="sec">{t("No places match. Try other interests.")}</p>}
        {recs && !recs.error && <Row title={t("Top picks right now")} sub={t("Ranked by rating, your interests, distance and live conditions.")}
          items={recs.recommended.slice(0, 8)} onOpen={onOpen} dev={dev} wide />}
        {sections.map((s) => <Row key={s.c} title={categoryPlural(s.c)} items={s.items} onOpen={onOpen} dev={dev} />)}
        {recs?.avoid_now?.length > 0 && (
          <div className="col">
            <span className="h3">{t("Avoid for now")}</span>
            <span className="sec" style={{ marginBottom: 4 }}>{t("Places you might like, with problems reported today.")}</span>
            {recs.avoid_now.map((d) => <AvoidRow key={d.id} d={d} onOpen={onOpen} />)}
          </div>
        )}
      </>}
    </div>
  );
}

function AvoidRow({ d, onOpen }) {
  const reason = useTx(d.reasons?.[0]?.title);
  return (
    <button className="list-row tappable" onClick={() => onOpen(d)}>
      <div style={{ width: 72, flex: "none" }}><PhotoSlot photo={d.photo} height={72} w={200} icon={CATEGORY_ICON[d.category]} /></div>
      <div className="grow col gap4">
        <div className="between"><span className="strong ellipsis">{d.name}</span><span className="cap tnum">{d.distance_km} km</span></div>
        <span><StatusPill status="avoid" /></span>
        <span className="cap" style={{ color: "var(--ink-2)" }}>{reason}</span>
      </div>
    </button>
  );
}

function InfoRow({ icon, children, href }) {
  const body = <><Icon name={icon} size={20} className="muted" /><span className="grow sec" style={{ color: "var(--ink)" }}>{children}</span></>;
  return href ? <a className="list-row" style={{ textDecoration: "none", alignItems: "center" }} href={href} target="_blank" rel="noreferrer">{body}<Icon name="arrow-up-right" className="faint flip-rtl" /></a>
    : <div className="list-row" style={{ alignItems: "center" }}>{body}</div>;
}

function Briefing({ brief, lang, cloudVoice }) {
  const { t } = useT();
  const [playing, setPlaying] = useState(false);
  useEffect(() => () => stopSpeaking(), []);
  return (
    <div className="inset col gap8">
      <div className="between"><span className="over row gap8"><Icon name="article" size={14} />{t("Summary from live reports")}</span>
        <button className="link row gap4" onClick={async () => {
          if (playing) { stopSpeaking(); setPlaying(false); return; }
          setPlaying(true); await speak(brief.text, lang, { cloud: cloudVoice, onEnd: () => setPlaying(false) });
        }}><Icon name={playing ? "stop" : "speaker-high"} />{playing ? t("Stop") : t("Listen")}</button></div>
      <span className="body" style={{ fontSize: 15, lineHeight: "22px" }}>{brief.text}</span>
      {!brief.ai && <span className="cap">{t("Written from a fixed template (the AI model was not used).")}</span>}
    </div>
  );
}

export function DestinationView({ d: d0, me, events, onClose, onPlan, onOpen, onHazard, dev, cloudVoice }) {
  const { t, lang } = useT();
  const [check, setCheck] = useState(null);
  const [brief, setBrief] = useState(null);
  const [power, setPower] = useState(null);
  const [details, setDetails] = useState(null);
  const [hours, setHours] = useState(false);
  useEffect(() => {
    setCheck(null); setBrief(null); setPower(null); setDetails(null);
    api.powerHistory(d0.lat, d0.lon).then(setPower).catch(() => {});
    if (d0.place_id && !d0.hours) api.placeDetails(d0.place_id, me, null, lang).then(setDetails).catch(() => {});
  }, [d0.id, d0.lat, lang]);
  // Status + summary follow live problems near this place (re-checked when one appears, changes or ends).
  const nearKey = useMemo(() => events.filter((e) => haversine(d0, e) < 5000 + e.radius_m)
    .map((e) => `${e.id}:${e.severity}:${Math.round(e.confidence * 10)}`).sort().join("|"), [events, d0.lat, d0.lon]);
  useEffect(() => {
    api.checkDestination(d0).then(setCheck).catch(() => setCheck((c) => c || { status: "unknown", reasons: [], alternatives: [] }));
    api.briefing(d0, lang).then(setBrief).catch(() => {});
  }, [d0.id, d0.lat, lang, nearKey]);

  const d = { ...d0, ...(details || {}), breakdown: d0.breakdown, score: d0.score };
  const status = check?.status || d.status || "unknown";
  const km = d.distance_km ?? (me ? Math.round(haversine(me, d) / 100) / 10 : null);
  const reasonEvents = useMemo(() => (check?.reasons || []).map((r) => ({ r, e: events.find((x) => x.id === r.id) })).filter((x) => x.e), [check, events]);
  const top = reasonEvents[0]?.e;
  const topTitle = useTx(top?.title), topDesc = useTx(top?.description);
  const photos = d.photos?.length ? d.photos : d.photo ? [d.photo] : [];
  const summary = d.summary;   // Google already answers in the UI language

  const header = (
    <div className="col gap4"><h1 className="h1">{d.name}</h1>
      <span className="sec row" style={{ gap: 6, flexWrap: "wrap" }}>{CATEGORY_LABEL[d.category] || t("Sight")}{km != null ? ` · ${t("{n} km away", { n: km })}` : ""}
        <Stars rating={d.rating} count={d.rating_count} />
        {d.open_now != null && <b style={{ color: d.open_now ? "var(--clear)" : "var(--avoid)", fontWeight: 600 }}>· {d.open_now ? t("Open now") : t("Closed now")}</b>}</span></div>
  );
  const info = (
    <div className="col">
      {summary && <p className="body" style={{ margin: "0 0 4px", color: "var(--ink-2)" }}>{summary}</p>}
      {d.address && <InfoRow icon="map-pin">{d.address}</InfoRow>}
      {d.hours && <button className="list-row tappable" style={{ alignItems: "flex-start" }} onClick={() => setHours((h) => !h)}>
        <Icon name="clock" size={20} className="muted" />
        <span className="grow sec col" style={{ color: "var(--ink)" }}>{hours ? d.hours.map((h) => <span key={h}>{h}</span>) : t("Opening hours")}</span>
        <Icon name={hours ? "caret-up" : "caret-down"} className="faint" /></button>}
      {d.phone && <InfoRow icon="phone" href={`tel:${d.phone.replace(/\s/g, "")}`}><span dir="ltr">{d.phone}</span></InfoRow>}
      {d.website && <InfoRow icon="globe" href={d.website}>{d.website.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]}</InfoRow>}
      {d.maps_url && <InfoRow icon="map-trifold" href={d.maps_url}>{t("Open in Google Maps")}</InfoRow>}
    </div>
  );
  const devBox = dev && d.breakdown && (
    <div className="dev-box"><span className="over">{t("Under the hood")} · {t("score")}</span>
      <ScoreLine d={d} />
      <span className="cap">{t("quality = Bayesian rating, popularity = reviews, interest match, proximity, x safety x open x weather")}</span></div>
  );

  if (status === "avoid") return (
    <div className="col gap16">
      <div className="row gap16" style={{ alignItems: "flex-start" }}>
        <div style={{ width: 88, flex: "none" }}><PhotoSlot photo={photos[0]} height={88} w={240} icon={CATEGORY_ICON[d.category]} /></div>
        <div className="grow">{header}</div>
        <button className="float-round small" onClick={onClose} aria-label={t("Close")}><Icon name="x" /></button>
      </div>
      <span><StatusPill status="avoid" size="M" /></span>
      {top && <div className="col gap8"><span className="body">{topTitle}. {topDesc}</span><EvidenceLine e={top} /></div>}
      <Alternatives list={check?.alternatives || []} d={d} onOpen={onOpen} />
      {reasonEvents.length > 1 && <div className="col"><span className="over">{t("All reported issues")}</span>
        {reasonEvents.map(({ r, e }) => <HazardRow key={r.id} e={e} distance={r.distance_m} onClick={() => onHazard(e)} />)}</div>}
      {info}
      {devBox}
      <button className="btn btn-secondary btn-block" onClick={() => onPlan(d)}>{t("Plan anyway")}</button>
    </div>
  );

  return (
    <div className="col gap16">
      <div style={{ position: "relative" }}>
        {photos.length > 1 ? (
          <div className="row gap8 hide-scroll hscroll snap">{photos.map((p, i) => <div key={p} style={{ width: "86%", flex: "none" }}>
            <PhotoSlot photo={p} height={200} w={800} status={i === 0 ? null : null} /></div>)}</div>
        ) : <PhotoSlot photo={photos[0]} label={d.name} height={200} w={800} icon={CATEGORY_ICON[d.category]} />}
        <div className="row" style={{ position: "absolute", insetInlineEnd: 10, top: 10 }}>
          <button className="float-round small" aria-label={t("Share")} onClick={() => navigator.share?.({ title: d.name, url: `https://maps.google.com/?q=${d.lat},${d.lon}` })}><Icon name="share-network" /></button>
          <button className="float-round small" aria-label={t("Close")} onClick={onClose}><Icon name="x" /></button>
        </div>
      </div>
      {header}
      <div className="col gap8"><span>{check ? <StatusPill status={status} size="M" /> : <Skeleton h={32} w={160} r={99} />}</span>
        {top && <span className="body">{topTitle}{reasonEvents[0].r.distance_m > 100 ? `, ${t("{d} away", { d: dist(reasonEvents[0].r.distance_m) })}` : ""}.</span>}</div>
      {brief ? <Briefing brief={brief} lang={lang} cloudVoice={cloudVoice} /> : <Skeleton h={72} r={16} />}
      {reasonEvents.length > 0 && <div className="col">{reasonEvents.map(({ r, e }) => <HazardRow key={r.id} e={e} distance={r.distance_m} onClick={() => onHazard(e)} />)}</div>}
      {info}
      {power && (
        <div className="card row gap12" style={{ padding: "12px 16px" }}>
          <Icon name="lightning" size={20} className="muted" />
          <span className="sec" style={{ color: "var(--ink)" }}>{power.cuts ? t("Power cuts nearby: {n} in {d} days, usually ~{m} min", { n: power.cuts, d: power.days, m: power.median_minutes })
            : t("No power cuts reported nearby in {d} days", { d: power.days })}</span>
        </div>
      )}
      <Alternatives list={check?.alternatives || []} d={d} onOpen={onOpen} scroll />
      {devBox}
    </div>
  );
}

function Alternatives({ list, d, onOpen, scroll }) {
  const { t } = useT();
  if (!list.length) return null;
  const same = list.some((a) => a.same_kind);
  const why = (a) => (a.same_kind ? t("Same kind of place, {n} km from {name}", { n: Math.round(a.distance_km), name: d.name })
    : t("No reported issues right now, {n} km from {name}", { n: Math.round(a.distance_km), name: d.name }));
  return (
    <div className="col gap8">
      <span className="h3">{t("Better options right now")}</span>
      <span className="sec">{same ? t("Same kind of place, no reported issues.") : t("Places with no reported issues.")}</span>
      {scroll ? (
        <div className="row gap12 hide-scroll hscroll" style={{ alignItems: "flex-start" }}>
          {list.map((a) => (
            <button key={a.id} className="tappable col gap8" style={{ width: 156, flex: "none" }} onClick={() => onOpen(a)}>
              <PhotoSlot photo={a.photo} height={88} w={320} status="clear" icon={CATEGORY_ICON[a.category]} />
              <span className="strong ellipsis">{a.name}</span><span className="cap">{why(a)}</span>
            </button>
          ))}
        </div>
      ) : list.map((a) => (
        <button key={a.id} className="card card-pad tappable row gap12" onClick={() => onOpen(a)}>
          <div style={{ width: 64, flex: "none" }}><PhotoSlot photo={a.photo} height={64} w={200} icon={CATEGORY_ICON[a.category]} /></div>
          <div className="grow col gap4"><span className="strong">{a.name}</span><span className="cap">{why(a)}</span><span><StatusPill status="clear" /></span></div>
          <Icon name="caret-right" className="faint flip-rtl" />
        </button>
      ))}
    </div>
  );
}

// Live reports feed (tap the "N live reports" pill).
export function LiveFeed({ events, me, onHazard, onClose }) {
  const { t } = useT();
  const [filter, setFilter] = useState("near");
  const list = useMemo(() => {
    const withD = events.map((e) => ({ e, d: me ? haversine(me, e) : null }));
    const f = filter === "near" ? withD.filter((x) => x.d == null || x.d < 50000 + x.e.radius_m)
      : filter === "avoid" ? withD.filter((x) => statusOfEvent(x.e) === "avoid") : withD;
    return f.sort((a, b) => new Date(b.e.observed_at) - new Date(a.e.observed_at));
  }, [events, me?.lat, me?.lon, filter]);
  const counts = { avoid: events.filter((e) => statusOfEvent(e) === "avoid").length, caution: events.filter((e) => statusOfEvent(e) === "caution").length };
  return (
    <div className="col gap12" style={{ paddingTop: 4 }}>
      <div className="between"><h2 className="h2">{t("Live reports")}</h2>
        <button className="float-round small" style={{ boxShadow: "none", background: "var(--surface-2)" }} onClick={onClose} aria-label={t("Close")}><Icon name="x" /></button></div>
      <div className="row gap8" style={{ flexWrap: "wrap" }}>
        <StatusPill status="avoid" label={`${counts.avoid} ${t("Avoid for now")}`} />
        <StatusPill status="caution" label={`${counts.caution} ${t("Caution")}`} />
        {events.some((e) => e.is_simulated) && <SimTag />}
      </div>
      <div className="seg">
        {[["near", t("Near me")], ["all", t("All Tunisia")], ["avoid", t("Avoid only")]].map(([k, l]) =>
          <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>)}
      </div>
      {list.length === 0 && <div className="col" style={{ alignItems: "center", padding: "24px 0", gap: 8 }}>
        <Icon name="check-circle" size={32} style={{ color: "var(--clear)" }} /><span className="sec">{t("No reported issues right now")}</span></div>}
      <div className="col">{list.map(({ e, d }) => <HazardRow key={e.id} e={e} distance={d} onClick={() => onHazard(e)} />)}</div>
      <span className="cap">{t("Every item shows its source, how sure it is, and how old it is. Tap one for details.")}</span>
    </div>
  );
}
