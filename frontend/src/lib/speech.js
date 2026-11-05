// Voice for interviews. Azure Speech when configured (TTS from the server, STT in the browser with a short-lived token);
// the browser's own speech engines otherwise, so every flow still works without keys.
import { api } from "../api";

let sdkPromise = null;
const loadSdk = () => (sdkPromise ||= import("microsoft-cognitiveservices-speech-sdk"));
let tokenCache = null;

async function azureToken() {
  if (tokenCache && tokenCache.until > Date.now()) return tokenCache;
  const t = await api.get("/speech/token");
  if (!t.configured) return null;
  tokenCache = { ...t, until: Date.now() + (t.expires_in - 30) * 1000 };
  return tokenCache;
}

let currentAudio = null;
// While an AI interview is being recorded, Hira's voice is mixed into the recording through this tap.
let tap = null;
export function setSpeechTap(t) { tap = t; }
export function stopSpeaking() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

/** Speak text in the chosen Azure voice. Resolves when finished. */
export async function speak(text, { voice, rate } = {}) {
  stopSpeaking();
  try {
    const res = await api.raw("POST", "/speech/tts", { text, voice, rate });
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("audio")) {
      const url = URL.createObjectURL(await res.blob());
      const a = new Audio(url);
      currentAudio = a;
      if (tap) { try { const src = tap.ctx.createMediaElementSource(a); src.connect(tap.ctx.destination); src.connect(tap.node); } catch { /* plays without the tap */ } }
      await new Promise((resolve) => { a.onended = resolve; a.onerror = resolve; a.play().catch(resolve); });
      URL.revokeObjectURL(url);
      return "azure";
    }
  } catch { /* fall through to the browser voice */ }
  if (!window.speechSynthesis) return "none";
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    const locale = (voice || "en-IN").split("-").slice(0, 2).join("-");
    const v = window.speechSynthesis.getVoices().find((x) => x.lang === locale) || window.speechSynthesis.getVoices().find((x) => x.lang.startsWith("en"));
    if (v) u.voice = v;
    u.lang = locale;
    const r = parseInt(rate || "0", 10);
    u.rate = 1 + (isNaN(r) ? 0 : r / 100);
    u.onend = () => resolve("browser"); u.onerror = () => resolve("browser");
    window.speechSynthesis.speak(u);
  });
}

/**
 * Continuous recogniser. onPartial(text) while speaking, onSentence(text) for each finished phrase.
 * Returns { stop(), engine }.
 */
export async function listen({ language = "en-IN", onPartial, onSentence, onError, stream }) {
  const tok = await azureToken().catch(() => null);
  if (tok) {
    try {
      const sdk = await loadSdk();
      const cfg = sdk.SpeechConfig.fromAuthorizationToken(tok.token, tok.region);
      cfg.speechRecognitionLanguage = language;
      const audio = stream ? sdk.AudioConfig.fromStreamInput(stream) : sdk.AudioConfig.fromDefaultMicrophoneInput();
      const rec = new sdk.SpeechRecognizer(cfg, audio);
      rec.recognizing = (_, e) => onPartial?.(e.result.text);
      rec.recognized = (_, e) => { if (e.result.reason === sdk.ResultReason.RecognizedSpeech && e.result.text) onSentence?.(e.result.text); };
      rec.canceled = (_, e) => onError?.(e.errorDetails || "Speech recognition stopped.");
      await new Promise((ok, bad) => rec.startContinuousRecognitionAsync(ok, bad));
      return { engine: "azure", stop: () => new Promise((ok) => rec.stopContinuousRecognitionAsync(() => { rec.close(); ok(); }, ok)) };
    } catch (e) { onError?.("Azure Speech couldn't start, using the browser instead."); }
  }
  if (stream) onError?.("Listening to a shared tab needs Azure Speech. Using your microphone instead.");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { onError?.("This browser can't recognise speech. Type your answer instead."); return { engine: "none", stop: async () => {} }; }
  const r = new SR();
  r.lang = language; r.continuous = true; r.interimResults = true;
  let stopped = false;
  r.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript.trim();
      if (e.results[i].isFinal) { if (t) onSentence?.(t); } else interim += t + " ";
    }
    onPartial?.(interim.trim());
  };
  r.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") onError?.("Microphone: " + e.error); };
  r.onend = () => { if (!stopped) try { r.start(); } catch { /* already running */ } };
  r.start();
  return { engine: "browser", stop: async () => { stopped = true; r.stop(); } };
}

/** Microphone level meter for the 'we can hear you' check. */
export async function micLevel(stream, cb) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume().catch(() => {}); // a suspended context reads silence
  const src = ctx.createMediaStreamSource(stream);
  const an = ctx.createAnalyser(); an.fftSize = 256; src.connect(an);
  const buf = new Uint8Array(an.frequencyBinCount);
  let on = true;
  const tick = () => { if (!on) return; an.getByteFrequencyData(buf); cb(buf.reduce((a, b) => a + b, 0) / buf.length / 128); requestAnimationFrame(tick); };
  tick();
  return () => { on = false; ctx.close(); };
}

export const LANG_CODES = { English: "en-IN", Hindi: "hi-IN", Hinglish: "en-IN", Tamil: "ta-IN", Telugu: "te-IN" };
