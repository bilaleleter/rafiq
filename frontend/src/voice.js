// Read text aloud: Google Cloud Text-to-Speech through the backend (clear Arabic and French voices on
// every phone), falling back to the phone's own voice (speechSynthesis) when the cloud voice is off.
import { api } from "./api.js";

const BCP47 = { ar: ["ar-SA", "ar-EG", "ar-TN", "ar"], fr: ["fr-FR", "fr-CA", "fr"], en: ["en-GB", "en-US", "en"],
  de: ["de-DE", "de"], it: ["it-IT", "it"], es: ["es-ES", "es"] };
let audio = null;
let cloudOff = false;

export function stopSpeaking() {
  try { audio?.pause(); } catch {}
  audio = null;
  try { speechSynthesis.cancel(); } catch {}
}

function deviceVoice(lang) {
  const voices = typeof speechSynthesis !== "undefined" ? speechSynthesis.getVoices() : [];
  for (const tag of BCP47[lang] || [lang]) {
    const v = voices.find((x) => x.lang?.toLowerCase().startsWith(tag.toLowerCase()));
    if (v) return v;
  }
  return null;
}

export const hasDeviceVoice = (lang) => !!deviceVoice(lang);

/**
 * speak(text, lang, {cloud, onEnd, onBoundary, rate}) -> "cloud" | "device" | "none"
 * cloud=false skips the server call (public-config says the cloud voice is not enabled).
 */
export async function speak(text, lang = "en", { cloud = true, onEnd, onBoundary, rate = 0.92 } = {}) {
  stopSpeaking();
  if (cloud && !cloudOff) {
    try {
      const blob = await api.tts(text, lang);
      const a = new Audio(URL.createObjectURL(blob));
      a.onended = () => { if (audio === a) audio = null; onEnd?.(); };
      audio = a;
      await a.play();
      return "cloud";
    } catch (e) {
      if (String(e.message) === "503") cloudOff = true;   // don't ask again this session
    }
  }
  if (typeof speechSynthesis === "undefined") { onEnd?.(); return "none"; }
  const u = new SpeechSynthesisUtterance(text);
  const v = deviceVoice(lang);
  u.lang = v?.lang || (BCP47[lang] || [lang])[0];
  if (v) u.voice = v;
  u.rate = rate; u.volume = 1;
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  if (onBoundary) u.onboundary = (ev) => onBoundary(ev.charIndex);
  speechSynthesis.speak(u);
  return v ? "device" : "none";
}

// Voices load asynchronously in some browsers.
try { speechSynthesis.getVoices(); speechSynthesis.onvoiceschanged = () => speechSynthesis.getVoices(); } catch {}
