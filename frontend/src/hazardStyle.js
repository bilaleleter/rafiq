// Visual + language meta for hazards, sources and statuses (shared by map, cards and alerts).
// Labels are getters so they follow the UI language (tr() reads the current dictionary).
import { tr } from "./i18n.js";

const T = (icon, color, rgb, label) => ({ icon, color, rgb, get label() { return tr(label); } });
export const TYPE = {
  flood: T("waves", "--water", [42, 127, 255], "Flood"),
  storm: T("cloud-rain", "--sky", [110, 107, 216], "Heavy rain"),
  wind: T("wind", "--sky", [110, 107, 216], "Strong wind"),
  heat: T("thermometer-hot", "--heat", [232, 85, 61], "Heat"),
  fire: T("fire", "--fire", [255, 106, 26], "Fire"),
  power: T("lightning-slash", "--power", [245, 196, 0], "Power cut"),
  water: T("drop-slash", "--cyan", [15, 163, 184], "Water cut"),
  earthquake: T("wave-sine", "--ink-2", [74, 91, 109], "Earthquake"),
  accident: T("car-profile", "--avoid", [215, 38, 61], "Accident"),
  road: T("barricade", "--caution", [201, 138, 0], "Road blocked"),
  health: T("first-aid", "--avoid", [215, 38, 61], "Health"),
  crowd: T("users-three", "--sky", [110, 107, 216], "Crowd"),
  other: T("warning", "--unknown", [122, 140, 160], "Other"),
};
export const typeOf = (t) => TYPE[t] || TYPE.other;
export const cssVar = (name) => `var(${name})`;

const S = (icon, label, color) => ({ icon, color, get label() { return tr(label); } });
export const STATUS = {
  clear: S("check-circle", "No reported issues", "--clear"),
  caution: S("warning", "Caution", "--caution"),
  avoid: S("prohibit", "Avoid for now", "--avoid"),
  unknown: S("question", "Limited data", "--unknown"),
};

export function sourceOf(e) {
  const n = e.reports_count || 1;
  if (e.is_simulated && ["demo", "replay"].includes(e.source)) return { icon: "flask", name: tr("Simulated") };
  switch (e.source) {
    case "open-meteo": return { icon: "cloud-rain", name: tr("Weather forecast") };
    case "open-meteo-flood": return { icon: "waves", name: tr("River forecast") };
    case "firms": return { icon: "satellite", name: tr("NASA satellite") };
    case "usgs": return { icon: "wave-sine", name: tr("Earthquake feed") };
    case "news": return { icon: "newspaper", name: tr("News") };
    case "crowd": return { icon: "users-three", name: tr(n > 1 ? "{n} travellers" : "{n} traveller", { n }) };
    case "web": return { icon: "video-camera", name: tr("Web video") };
    case "model": return { icon: "mountains", name: tr("Terrain model + rain") };
    case "sos": return { icon: "siren", name: tr("SOS alert") };
    case "demo": case "replay": case "sim": return { icon: "flask", name: tr("Simulated") };
    default: return { icon: "info", name: e.source || tr("Report") };
  }
}

export const isEstimated = (e) => e?.data?.kind === "estimated";
export function confWord(conf, estimated) {
  if (estimated) return tr("estimated");
  const p = Math.round(conf * 100);
  return `${p}% ${tr(p >= 70 ? "confirmed" : p >= 50 ? "likely" : "unconfirmed")}`;
}

export function ago(iso) {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m <= 0) return tr("just now");
  if (m < 60) return tr("{n} min ago", { n: m });
  const h = Math.round(m / 60);
  return h < 24 ? tr("{n} h ago", { n: h }) : tr("{n} d ago", { n: Math.round(h / 24) });
}
export const hhmm = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export const dist = (m) => (m == null ? "" : m < 950 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(m < 10000 ? 1 : 0)} km`);
export function haversine(a, b) {
  const R = 6371000, r = Math.PI / 180;
  const dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
export function bearing(a, b) {
  const r = Math.PI / 180;
  const y = Math.sin((b.lon - a.lon) * r) * Math.cos(b.lat * r);
  const x = Math.cos(a.lat * r) * Math.sin(b.lat * r) - Math.sin(a.lat * r) * Math.cos(b.lat * r) * Math.cos((b.lon - a.lon) * r);
  return (Math.atan2(y, x) / r + 360) % 360;
}
const L = (label) => ({ get text() { return tr(label); } });
const LEVELS = { ankle: L("Ankle-deep"), shin: L("Shin-deep"), knee_car: L("Knee-deep"), deadly: L("Life-threatening") };
export const FLOOD_LEVEL_TEXT = new Proxy({}, { get: (_, k) => LEVELS[k]?.text });
export const FLOOD_COLORS = { ankle: [120, 200, 255], shin: [60, 150, 255], knee_car: [42, 110, 240], deadly: [95, 60, 210] };

// Interests / place categories (keys match backend destinations.CATEGORIES)
export const CATEGORY_ICON = { beach: "umbrella-simple", history: "scroll", medina: "mosque", nature: "tree", desert: "sun-horizon",
  museum: "bank", food: "fork-knife", cafe: "coffee", shopping: "shopping-bag", family: "balloon", nightlife: "martini", sight: "map-pin",
  hospital: "hospital", pharmacy: "pill", police: "police-car", fuel: "gas-pump", atm: "money", hotel: "bed" };
const CAT = { beach: "Beach", history: "History", medina: "Medina", nature: "Nature", desert: "Desert", museum: "Museum", food: "Food",
  cafe: "Café", shopping: "Shopping", family: "Family", nightlife: "Nightlife", sight: "Sight", hospital: "Hospital",
  pharmacy: "Pharmacy", police: "Police", fuel: "Fuel", atm: "Cash", hotel: "Hotel" };
export const CATEGORY_LABEL = new Proxy({}, { get: (_, k) => (CAT[k] ? tr(CAT[k]) : undefined) });
const CAT_PLURAL = { beach: "Beaches", history: "History", medina: "Medinas", nature: "Nature", desert: "Desert", museum: "Museums",
  food: "Food", cafe: "Cafés", shopping: "Shopping", family: "Family", nightlife: "Nightlife", sight: "Sights" };
export const categoryPlural = (k) => tr(CAT_PLURAL[k] || "Sights");
export const INTERESTS = ["beach", "history", "medina", "nature", "desert", "museum", "food", "cafe", "shopping", "family", "nightlife"];
export const statusOfEvent = (e) => (["danger", "critical"].includes(e.severity) && e.confidence >= 0.5 ? "avoid" : e.severity !== "info" ? "caution" : "unknown");
