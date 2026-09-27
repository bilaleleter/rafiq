// Live 3D hazard map in the Rafiq visual language.
// Google vector map (tilted) + deck.gl overlay; falls back to deck.gl + CARTO muted tiles without a Google key.
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import { PathStyleExtension } from "@deck.gl/extensions";
import { Deck, FlyToInterpolator, PolygonLayer, ColumnLayer, ScatterplotLayer, PathLayer, TextLayer, IconLayer, TileLayer, BitmapLayer } from "deck.gl";
import { typeOf, isEstimated, FLOOD_COLORS, CATEGORY_ICON } from "../hazardStyle.js";

// Phosphor SVGs -> map marker images (white disc + coloured icon), built once.
const RAW = import.meta.glob("/node_modules/@phosphor-icons/core/assets/regular/*.svg", { query: "?raw", import: "default", eager: true });
const RAW_FILL = import.meta.glob("/node_modules/@phosphor-icons/core/assets/fill/*-fill.svg", { query: "?raw", import: "default", eager: true });
const svgInner = (name, fill) => {
  const raw = fill ? RAW_FILL[`/node_modules/@phosphor-icons/core/assets/fill/${name}-fill.svg`] || ""
    : RAW[`/node_modules/@phosphor-icons/core/assets/regular/${name}.svg`] || "";
  return raw.replace(/^<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
};
const url = (svg) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
const markerCache = {};
function markerIcon(type, dark) {
  const key = type + (dark ? "d" : "l");
  if (markerCache[key]) return markerCache[key];
  const t = typeOf(type);
  const [r, g, b] = t.rgb;
  const bg = dark ? "#0F1A26" : "#FFFFFF";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80">
    <circle cx="40" cy="41" r="30" fill="rgba(8,17,27,0.18)"/><circle cx="40" cy="39" r="30" fill="${bg}"/>
    <g transform="translate(24,23) scale(0.125)" fill="rgb(${r},${g},${b})">${svgInner(t.icon)}</g></svg>`;
  markerCache[key] = { url: url(svg), width: 80, height: 80, anchorY: 40 };
  return markerCache[key];
}
const STATUS_RGB = { clear: "#1F8A5B", caution: "#C98A00", avoid: "#D7263D", unknown: "#7A8CA0" };
function placeIcon(cat, status, dark) {
  const key = `p-${cat}-${status}-${dark ? "d" : "l"}`;
  if (markerCache[key]) return markerCache[key];
  const bg = dark ? "#0F1A26" : "#FFFFFF";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="76" viewBox="0 0 64 76">
    <path d="M32 74 L22 56 H42 Z" fill="${bg}"/><circle cx="32" cy="32" r="26" fill="${bg}" stroke="${STATUS_RGB[status] || "#1553D1"}" stroke-width="4"/>
    <g transform="translate(18,18) scale(0.109)" fill="${dark ? "#8FB4FF" : "#1553D1"}">${svgInner(CATEGORY_ICON[cat] || "map-pin", true)}</g></svg>`;
  markerCache[key] = { url: url(svg), width: 64, height: 76, anchorY: 74 };
  return markerCache[key];
}
// "You are here": the brand 8-point star on a blue disc; grey when the position is stale.
function meIcon(stale) {
  const key = `me-${stale}`;
  if (markerCache[key]) return markerCache[key];
  const c = stale ? "#7A8CA0" : "#1553D1";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72">
    <circle cx="36" cy="37.5" r="21" fill="rgba(8,17,27,0.25)"/><circle cx="36" cy="36" r="21" fill="#fff"/><circle cx="36" cy="36" r="16" fill="${c}"/>
    <g transform="translate(36 36)"><rect x="-7" y="-7" width="14" height="14" fill="#fff"/><rect x="-7" y="-7" width="14" height="14" fill="#fff" transform="rotate(45)"/></g></svg>`;
  markerCache[key] = { url: url(svg), width: 72, height: 72 };
  return markerCache[key];
}
const HEADING = { url: url(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
  <defs><linearGradient id="g" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#1553D1" stop-opacity=".45"/><stop offset="1" stop-color="#1553D1" stop-opacity="0"/></linearGradient></defs>
  <path d="M48 48 L24 6 A48 48 0 0 1 72 6 Z" fill="url(#g)"/><path d="M48 14 L58 30 L48 26 L38 30 Z" fill="#1553D1" stroke="#fff" stroke-width="3" stroke-linejoin="round"/></svg>`),
  width: 96, height: 96 };
const FLAG = { url: url(`<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="22" fill="#1553D1" stroke="#fff" stroke-width="4"/>
    <g transform="translate(18,18) scale(0.11)" fill="#fff">${svgInner("flag")}</g></svg>`), width: 64, height: 64 };
const PIN = { url: url(`<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="20" fill="#F2B61E" stroke="#fff" stroke-width="4"/>
    <g transform="translate(19,19) scale(0.1)" fill="#0B1B2B">${svgInner("crosshair-simple")}</g></svg>`), width: 64, height: 64 };

// deck.gl 9.4 + interleaved Google vector maps: deck creates its own 1x1 canvas instead of sharing
// Google's WebGL context, so nothing is drawn (verified in the browser, 2026-09-27). Non-interleaved
// mode draws deck on its own canvas above the map; we only lose buildings hiding our 3D shapes.
const INTERLEAVED = false;
const ON_TOP = { parameters: { depthCompare: "always", depthWriteEnabled: false } }; // markers/labels never hidden inside 3D volumes
const FLOOD_EXAGGERATION = 40; // 50 cm of water -> 20 m tall: readable from above
const SEV_ALPHA = { info: 110, warning: 160, danger: 210, critical: 240 };

function circle(lat, lon, r, n = 48) {
  const dLat = r / 111320, dLon = r / (111320 * Math.cos((lat * Math.PI) / 180));
  return Array.from({ length: n + 1 }, (_, i) => { const a = (2 * Math.PI * i) / n; return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]; });
}
const phase = (id) => [...id].reduce((s, c) => s + c.charCodeAt(0), 0) % 7;

// Map labels are language-neutral numbers (deck.gl text cannot shape Arabic script).
function label(e) {
  if (e.type === "flood" && e.data?.depth_cm != null) {
    const cm = `${isEstimated(e) ? "~" : ""}${Math.round(e.data.depth_cm)} cm`;
    return e.data?.trend_cm_per_h > 1 ? `${cm} ↑` : e.data?.trend_cm_per_h < -1 ? `${cm} ↓` : cm;
  }
  if (e.data?.value != null && e.data?.unit) return `${Math.round(e.data.value)} ${e.data.unit.split(" ")[0]}`;
  if (e.data?.magnitude) return `M${e.data.magnitude.toFixed(1)}`;
  return /[\u0600-\u06FF]/.test(e.title) ? "" : e.title.length > 26 ? e.title.slice(0, 25) + "…" : e.title;
}

function buildLayers({ events, routes, routeIndex, target, me, selectedId, dark, places, pickPoint, labels }, t, onPick, onPickPlace) {
  const obs = events.filter((e) => e.type === "flood" && !isEstimated(e));
  const est = events.filter(isEstimated);
  const fires = events.filter((e) => e.type === "fire");
  const domes = events.filter((e) => ["storm", "heat", "wind", "earthquake"].includes(e.type));
  const power = events.filter((e) => e.type === "power");
  const rings = events.filter((e) => ["water", "accident", "road", "health", "crowd", "other"].includes(e.type));
  const pins = obs.flatMap((e) => (e.data?.report_points || []).map(([lat, lon, cm]) => ({ lat, lon, cm, ev: e })));
  const pick = { pickable: true, onClick: (i) => i.object && onPick(i.object.ev || i.object) };
  const ripple = (e) => (t * 0.45 + phase(e.id) / 7) % 1;
  // one label per ~1.2 km, most severe first (keeps the map readable when reports cluster)
  const RANK = { info: 0, warning: 1, danger: 2, critical: 3 };
  const labelled = [];
  if (labels) for (const e of [...events].sort((a, b) => (b.id === selectedId) - (a.id === selectedId) || RANK[b.severity] - RANK[a.severity])) {
    if (e.severity === "info" && e.id !== selectedId) continue;
    if (labelled.every((l) => Math.hypot((l.lat - e.lat) * 111, (l.lon - e.lon) * 90) > 1.2)) labelled.push(e);
    if (labelled.length >= 12) break;
  }
  const alts = (routes || []).filter((_, i) => i !== routeIndex);
  const chosen = routes?.[routeIndex];
  const stale = me && me.at && Date.now() - me.at > 3 * 60000;   // no fix for 3 min: grey "last known" marker
  const moving = me && me.heading != null && (me.speed == null || me.speed > 0.6);
  const pulse = (t * 0.6) % 1;

  return [
    // routes (alternatives dashed grey, chosen solid brand with white casing)
    alts.length && new PathLayer({ ...ON_TOP, id: "alt-routes", data: alts, getPath: (r) => r.coords.map(([a, b]) => [b, a]),
      getColor: [129, 147, 166, 200], widthMinPixels: 4, getDashArray: [3, 2], dashJustified: true, extensions: [new PathStyleExtension({ dash: true })] }),
    chosen && new PathLayer({ ...ON_TOP, id: "route-casing", data: [chosen], getPath: (r) => r.coords.map(([a, b]) => [b, a]),
      getColor: [255, 255, 255, 255], widthMinPixels: 9, capRounded: true, jointRounded: true }),
    chosen && new PathLayer({ ...ON_TOP, id: "route", data: [chosen], getPath: (r) => r.coords.map(([a, b]) => [b, a]),
      getColor: chosen.safety === "avoid" ? [215, 38, 61] : chosen.safety === "caution" ? [201, 138, 0] : [21, 83, 209],
      widthMinPixels: 6, capRounded: true, jointRounded: true }),
    new PolygonLayer({ id: "domes", data: domes, ...pick, extruded: false, stroked: true, getPolygon: (e) => circle(e.lat, e.lon, e.radius_m),
      getFillColor: (e) => [...typeOf(e.type).rgb, Math.round(34 + 10 * Math.sin(t + phase(e.id)))], getLineColor: (e) => [...typeOf(e.type).rgb, 90],
      lineWidthMinPixels: 1, ...ON_TOP, updateTriggers: { getFillColor: Math.floor(t * 4) } }),
    new ScatterplotLayer({ id: "power-dark", data: power, getPosition: (e) => [e.lon, e.lat], getRadius: (e) => e.radius_m,
      getFillColor: dark ? [0, 0, 0, 90] : [8, 17, 27, 36], stroked: true, getLineColor: [245, 196, 0, 220], lineWidthMinPixels: 2.5 }),
    new PolygonLayer({ id: "flood-est", data: est, ...pick, extruded: false, stroked: true, getPolygon: (e) => circle(e.lat, e.lon, e.radius_m, 28),
      getFillColor: [156, 196, 255, 70], getLineColor: [42, 127, 255, 170], lineWidthMinPixels: 1.5,
      getDashArray: [4, 3], extensions: [new PathStyleExtension({ dash: true })] }),
    new PolygonLayer({ id: "flood-water", data: obs, ...pick, extruded: true, getPolygon: (e) => circle(e.lat, e.lon, e.radius_m),
      getElevation: (e) => ((e.data?.depth_cm || 20) / 100) * FLOOD_EXAGGERATION * (1 + 0.04 * Math.sin(t * 2 + phase(e.id))),
      getFillColor: (e) => [...(FLOOD_COLORS[e.data?.level] || FLOOD_COLORS.shin), 140],
      material: { ambient: 0.55, diffuse: 0.6, shininess: 90, specularColor: [210, 230, 255] }, updateTriggers: { getElevation: t } }),
    new ColumnLayer({ id: "flood-evidence", data: pins, ...pick, diskResolution: 8, radius: 5, extruded: true, getPosition: (p) => [p.lon, p.lat],
      getElevation: (p) => (p.cm / 100) * FLOOD_EXAGGERATION + 5, getFillColor: [255, 255, 255, 235] }),
    new ScatterplotLayer({ id: "flood-ripple", data: obs, stroked: true, filled: false, getPosition: (e) => [e.lon, e.lat],
      getRadius: (e) => e.radius_m * (1 + ripple(e) * 0.5), getLineColor: (e) => [42, 127, 255, 170 * (1 - ripple(e))],
      lineWidthMinPixels: 1.5, updateTriggers: { getRadius: t, getLineColor: t } }),
    new ScatterplotLayer({ id: "fire-glow", data: fires, getPosition: (e) => [e.lon, e.lat], getRadius: (e) => Math.max(400, e.radius_m * 0.6),
      getFillColor: [255, 106, 26, 45], stroked: false }),
    new ColumnLayer({ id: "fire-outer", data: fires, ...pick, diskResolution: 7, extruded: true, radius: 110, getPosition: (e) => [e.lon, e.lat],
      getElevation: (e) => 380 + 140 * Math.sin(t * 7 + phase(e.id)), getFillColor: (e) => [255, 106, 26, SEV_ALPHA[e.severity]], updateTriggers: { getElevation: t } }),
    new ColumnLayer({ id: "fire-core", data: fires, diskResolution: 6, extruded: true, radius: 55, getPosition: (e) => [e.lon, e.lat],
      getElevation: (e) => 250 + 90 * Math.sin(t * 9 + phase(e.id) + 1), getFillColor: [255, 212, 59, 240], updateTriggers: { getElevation: t } }),
    new ScatterplotLayer({ id: "rings", data: [...rings, ...power], ...pick, stroked: true, filled: false, getPosition: (e) => [e.lon, e.lat],
      getRadius: (e) => Math.max(120, e.radius_m) * (0.55 + ((t * 0.7 + phase(e.id) / 7) % 1) * 0.5),
      getLineColor: (e) => [...typeOf(e.type).rgb, SEV_ALPHA[e.severity]], lineWidthMinPixels: 2.5, updateTriggers: { getRadius: t } }),
    places?.length && new IconLayer({ ...ON_TOP, id: "places", data: places, pickable: true, onClick: (i) => i.object && onPickPlace?.(i.object),
      getPosition: (d) => [d.lon, d.lat], getIcon: (d) => placeIcon(d.category, d.status, dark), getSize: 34, updateTriggers: { getIcon: dark } }),
    me && new ScatterplotLayer({ ...ON_TOP, id: "me-halo", data: [me], getPosition: (p) => [p.lon, p.lat], getRadius: (p) => Math.max(15, p.accuracy || 30),
      radiusMinPixels: 18, getFillColor: stale ? [122, 140, 160, 40] : [21, 83, 209, 40], stroked: true,
      getLineColor: stale ? [122, 140, 160, 110] : [21, 83, 209, 110], lineWidthMinPixels: 1 }),
    me && !stale && new ScatterplotLayer({ ...ON_TOP, id: "me-pulse", data: [me], getPosition: (p) => [p.lon, p.lat], radiusUnits: "pixels",
      getRadius: 14 + pulse * 20, stroked: true, filled: false, getLineColor: [21, 83, 209, Math.round(200 * (1 - pulse))], lineWidthMinPixels: 2,
      updateTriggers: { getRadius: t, getLineColor: t } }),
    me && moving && new IconLayer({ ...ON_TOP, id: "me-heading", data: [me], getPosition: (p) => [p.lon, p.lat], getIcon: () => HEADING,
      getSize: 76, getAngle: (p) => -p.heading, updateTriggers: { getAngle: me.heading } }),
    target && new IconLayer({ ...ON_TOP, id: "target", data: [target], getPosition: (d) => [d.lon, d.lat], getIcon: () => FLAG, getSize: 38 }),
    pickPoint && new IconLayer({ ...ON_TOP, id: "pick", data: [pickPoint], getPosition: (d) => [d.lon, d.lat], getIcon: () => PIN, getSize: 34 }),
    new IconLayer({ ...ON_TOP, id: "markers", data: events, ...pick, getPosition: (e) => [e.lon, e.lat], getIcon: (e) => markerIcon(e.type, dark),
      getSize: (e) => (e.id === selectedId ? 50 : 40), updateTriggers: { getSize: selectedId } }),
    labels && new TextLayer({ ...ON_TOP, id: "labels", data: labelled, getPosition: (e) => [e.lon, e.lat], getText: label, getSize: 12, sizeUnits: "pixels",
      getColor: dark ? [234, 241, 248] : [11, 27, 43], background: true, getBackgroundColor: dark ? [15, 26, 38, 240] : [255, 255, 255, 245],
      backgroundPadding: [8, 5], backgroundBorderRadius: 8, getTextAnchor: "end", getPixelOffset: [-24, 0], fontFamily: "Inter, system-ui, sans-serif", fontWeight: 600,
      characterSet: "auto", getBorderColor: dark ? [34, 50, 68] : [220, 227, 234], getBorderWidth: 1 }),
    me && new IconLayer({ ...ON_TOP, id: "me", data: [me], getPosition: (p) => [p.lon, p.lat], getIcon: () => meIcon(!!stale), getSize: 40,
      updateTriggers: { getIcon: !!stale } }),
  ].filter(Boolean);
}

function loadGoogle(key) {
  if (window.google?.maps?.importLibrary) return Promise.resolve();
  return new Promise((resolve, reject) => {
    window.__gmReady = resolve;
    window.gm_authFailure = () => reject(new Error("google auth failure"));
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${key}&v=weekly&loading=async&callback=__gmReady`;
    s.async = true; s.onerror = reject;
    document.head.appendChild(s);
    setTimeout(() => reject(new Error("google timeout")), 12000);
  });
}

const HazardMap = forwardRef(function HazardMap({ config, onPick, onPickPlace, onMapClick, onUserPan, onReady, dark, ...data }, ref) {
  const el = useRef(null);
  const ctl = useRef(null);
  const props = useRef({});
  props.current = { ...data, dark };
  const cb = useRef({});
  cb.current = { onPick, onPickPlace, onMapClick, onUserPan };

  useImperativeHandle(ref, () => ({
    flyTo: (lat, lon, zoom = 13) => ctl.current?.flyTo(lat, lon, zoom),
    panTo: (lat, lon) => ctl.current?.panTo(lat, lon),
    setPitch: (p) => ctl.current?.setPitch(p),
    center: () => ctl.current?.center(),
    kind: () => ctl.current?.kind,
  }));

  useEffect(() => {
    if (!config) return;
    let raf, stop = false;
    const [lat, lon] = config.center || [36.8, 10.18];
    const init = async () => {
      if (ctl.current) return;   // already created (effect re-run, e.g. hot reload): just restart the loop
      try {
        if (!config.google_maps_key) throw new Error("no key");
        await loadGoogle(config.google_maps_key);
        const { Map, RenderingType } = await google.maps.importLibrary("maps");
        const map = new Map(el.current, { center: { lat, lng: lon }, zoom: 11, mapId: config.google_map_id,
          renderingType: RenderingType.VECTOR, tilt: 45, heading: 0, disableDefaultUI: true, clickableIcons: false,
          colorScheme: "FOLLOW_SYSTEM", gestureHandling: "greedy" });
        const overlay = new GoogleMapsOverlay({ interleaved: INTERLEAVED, layers: [] });
        overlay.setMap(map);
        if (import.meta.env.DEV) Object.assign(window, { __rafiqMap: map, __rafiqOverlay: overlay });
        map.addListener("dragstart", () => cb.current.onUserPan?.());
        map.addListener("click", (e) => e.latLng && cb.current.onMapClick?.({ lat: e.latLng.lat(), lon: e.latLng.lng() }));
        ctl.current = {
          kind: "google",
          setLayers: (l) => overlay.setProps({ layers: l }),
          flyTo: (la, lo, z) => { map.panTo({ lat: la, lng: lo }); map.setZoom(z); },
          panTo: (la, lo) => map.panTo({ lat: la, lng: lo }),
          setPitch: (p) => map.setTilt(p),
          center: () => { const c = map.getCenter(); return { lat: c.lat(), lon: c.lng() }; },
        };
      } catch {
        let view = { latitude: lat, longitude: lon, zoom: 11, pitch: 45, bearing: 0 };
        const tiles = (isDark) => new TileLayer({ id: `base-${isDark ? "d" : "l"}`, maxZoom: 19, tileSize: 256,
          data: `https://basemaps.cartocdn.com/${isDark ? "dark_all" : "light_all"}/{z}/{x}/{y}@2x.png`,
          renderSubLayers: (p) => { const [[w, s], [e, n]] = p.tile.boundingBox; return new BitmapLayer(p, { data: null, image: p.data, bounds: [w, s, e, n] }); } });
        const base = { l: tiles(false), d: tiles(true) };
        const deck = new Deck({ parent: el.current, controller: true, initialViewState: view,
          onClick: (info) => { if (!info.object && info.coordinate) cb.current.onMapClick?.({ lat: info.coordinate[1], lon: info.coordinate[0] }); },
          onViewStateChange: ({ viewState, interactionState }) => { if (interactionState?.isDragging) cb.current.onUserPan?.(); view = viewState; return viewState; } });
        ctl.current = {
          kind: "carto",
          setLayers: (l) => deck.setProps({ layers: [props.current.dark ? base.d : base.l, ...l] }),
          flyTo: (la, lo, z) => { view = { ...view, latitude: la, longitude: lo, zoom: z, transitionDuration: 900, transitionInterpolator: new FlyToInterpolator() }; deck.setProps({ initialViewState: view }); },
          panTo: (la, lo) => { view = { ...view, latitude: la, longitude: lo, transitionDuration: 500 }; deck.setProps({ initialViewState: view }); },
          setPitch: (p) => { view = { ...view, pitch: p, transitionDuration: 400 }; deck.setProps({ initialViewState: view }); },
          center: () => ({ lat: view.latitude, lon: view.longitude }),
        };
      }
      onReady?.(ctl.current.kind);
    };
    const tick = () => {
      if (stop) return;
      ctl.current?.setLayers(buildLayers(props.current, performance.now() / 1000, (x) => cb.current.onPick?.(x), (p) => cb.current.onPickPlace?.(p)));
      raf = requestAnimationFrame(tick);
    };
    init().then(tick);
    return () => { stop = true; cancelAnimationFrame(raf); };
  }, [config]);

  return (
    <>
      <div ref={el} className="map" />
      {config && !config.google_maps_key && <div style={{ position: "absolute", right: 6, bottom: 70, zIndex: 3, font: "400 10px/1 var(--font-ui)", color: "var(--ink-3)" }}>
        © OpenStreetMap contributors © CARTO</div>}
    </>
  );
});
export default HazardMap;
