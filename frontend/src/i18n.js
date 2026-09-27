// UI language. Source strings are written in English inside t("...") calls.
//  - fr / ar: built-in dictionaries (i18n.dict.js), instant and offline.
//  - de / it / es: the English strings are translated once by the backend (Google Cloud Translation,
//    else the AI model) and cached on the phone.
//  - Live text written by the server in English (hazard titles, descriptions) goes through useTx(),
//    which batches it to /api/translate and caches the result.
// Arabic switches the whole layout to right-to-left.
import { createContext, createElement, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { FR, AR } from "./i18n.dict.js";

export const LANGS = [["English", "English", "en"], ["Français", "French", "fr"], ["العربية", "Arabic", "ar"],
  ["Deutsch", "German", "de"], ["Italiano", "Italian", "it"], ["Español", "Spanish", "es"]];
export const LANG_NAME = Object.fromEntries(LANGS.map(([, en, c]) => [c, en]));
const BUILTIN = { fr: FR, ar: AR };
const DICT_VERSION = 3;
const RTL = new Set(["ar"]);
export const ALL_KEYS = Object.keys(FR);

let current = { lang: "en", dict: {} };
const fill = (s, vars) => (vars ? s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m)) : s);
/** Translate outside React components (helpers in hazardStyle.js use it). */
export const tr = (key, vars) => fill(current.dict[key] ?? key, vars);

const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
const dictKey = (lang) => `rafiq_i18n_${lang}_v${DICT_VERSION}`;

async function fetchDict(lang) {
  const out = {};
  for (let i = 0; i < ALL_KEYS.length; i += 150) {
    const chunk = ALL_KEYS.slice(i, i + 150);
    const r = await api.translate(chunk, lang);
    if (r.provider === "none") throw new Error("no translator");
    chunk.forEach((k, n) => { out[k] = r.texts[n]; });
  }
  return out;
}

const Ctx = createContext({ lang: "en", dir: "ltr", t: tr, loading: false });

export function I18nProvider({ lang = "en", children }) {
  const [dicts, setDicts] = useState(() => ({ [lang]: BUILTIN[lang] || store.get(dictKey(lang)) || null }));
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const dict = lang === "en" ? {} : (BUILTIN[lang] || dicts[lang] || {});
  current = { lang, dict };

  useEffect(() => {
    const dir = RTL.has(lang) ? "rtl" : "ltr";
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
    if (lang === "en" || BUILTIN[lang] || dicts[lang]) { setFailed(false); return; }
    const cached = store.get(dictKey(lang));
    if (cached) { setDicts((d) => ({ ...d, [lang]: cached })); return; }
    let stop = false;
    setLoading(true); setFailed(false);
    fetchDict(lang).then((d) => { if (!stop) { store.set(dictKey(lang), d); setDicts((x) => ({ ...x, [lang]: d })); } })
      .catch(() => !stop && setFailed(true)).finally(() => !stop && setLoading(false));
    return () => { stop = true; };
  }, [lang]);

  const value = useMemo(() => ({
    lang, dir: RTL.has(lang) ? "rtl" : "ltr", loading, failed,
    t: (k, vars) => fill(dict[k] ?? k, vars),
  }), [lang, dict, loading, failed]);
  return createElement(Ctx.Provider, { value }, children);
}

export const useT = () => useContext(Ctx);

// ── live server text ─────────────────────────────────────────────────────
const LIVE_KEY = "rafiq_live_tx_v1";
const live = new Map(Object.entries(store.get(LIVE_KEY) || {}));
const pending = new Map();      // lang -> Set(text)
const listeners = new Set();
let timer = null;

function flush() {
  timer = null;
  for (const [lang, set] of pending) {
    const texts = [...set];
    pending.delete(lang);
    api.translate(texts, lang).then((r) => {
      if (r.provider === "none") return;
      texts.forEach((src, i) => live.set(`${lang}|${src}`, r.texts[i]));
      if (live.size > 3000) [...live.keys()].slice(0, 500).forEach((k) => live.delete(k));
      store.set(LIVE_KEY, Object.fromEntries(live));
      listeners.forEach((f) => f());
    }).catch(() => {});
  }
}

/** Translate a server-written English string into the UI language (original shown until ready). */
export function useTx(text) {
  const { lang } = useT();
  const [, force] = useState(0);
  const k = `${lang}|${text}`;
  const done = !text || lang === "en" || live.has(k);
  useEffect(() => {
    if (done) return;
    const f = () => live.has(k) && force((x) => x + 1);
    listeners.add(f);
    if (!pending.has(lang)) pending.set(lang, new Set());
    pending.get(lang).add(text);
    timer = timer || setTimeout(flush, 80);
    return () => listeners.delete(f);
  }, [k, done]);
  return !text || lang === "en" ? text : live.get(k) ?? text;
}

export function Tx({ children }) {
  return useTx(typeof children === "string" ? children : "");
}
