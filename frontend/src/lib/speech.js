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

/** C2 (V02.00.12): fetch the speech token and SDK before the first answer, so listening starts without a pause. */
export function warmUpListening() { azureToken().then((t) => { if (t) loadSdk(); }).catch(() => {}); }

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
/**
 * Speech to text. Azure Speech when the server has a key (every browser, and it can listen to a chosen microphone or a
 * shared tab), otherwise the browser's own engine (Chrome and Edge; always the computer's default microphone).
 *
 * V02.00.07 (bug 3): captions no longer die quietly.
 *  - Azure's access key lasts 10 minutes: it is renewed every 9 minutes while listening.
 *  - If either engine stops (network, a cancelled session, the browser ending it), it restarts by itself.
 *  - onStatus("working" | "paused" | "off", engine) reports the state, so both sides can show it.
 * source: "mic" (default) or "tab" (another meeting's tab: only Azure can listen to that).
 */
export async function listen({ language = "en-IN", onPartial, onSentence, onError, onStatus, stream, source = "mic" }) {
  let stopped = false;
  const status = (st, engine) => { try { onStatus?.(st, engine); } catch { /* the page went away */ } };
  const tok = await azureToken().catch(() => null);
  if (tok) {
    try {
      const sdk = await loadSdk();
      let rec = null, renew = null, restartTimer = null, region = tok.region, token = tok.token;
      const start = async () => {
        if (stopped) return;
        const cfg = sdk.SpeechConfig.fromAuthorizationToken(token, region);
        cfg.speechRecognitionLanguage = language;
        const audio = stream ? sdk.AudioConfig.fromStreamInput(stream) : sdk.AudioConfig.fromDefaultMicrophoneInput();
        rec = new sdk.SpeechRecognizer(cfg, audio);
        rec.recognizing = (_, e) => { status("working", "azure"); onPartial?.(e.result.text); };
        rec.recognized = (_, e) => { if (e.result.reason === sdk.ResultReason.RecognizedSpeech && e.result.text) { status("working", "azure"); onSentence?.(e.result.text); } };
        const again = (why) => {
          if (stopped) return;
          status("paused", "azure");
          onError?.(why || "Captions paused. Reconnecting…");
          try { rec?.close(); } catch { /* closed */ }
          clearTimeout(restartTimer);
          restartTimer = setTimeout(async () => { const t = await azureToken().catch(() => null); if (t) { token = t.token; region = t.region; } start(); }, 2000);
        };
        rec.canceled = (_, e) => again(e.errorDetails ? `Captions paused (${e.errorDetails}). Reconnecting…` : "");
        rec.sessionStopped = () => again("");
        await new Promise((ok, bad) => rec.startContinuousRecognitionAsync(ok, bad));
        status("working", "azure");
      };
      await start();
      renew = setInterval(async () => {  // the key expires after 10 minutes
        const t = await azureToken().catch(() => null);
        if (t && rec) { token = t.token; region = t.region; try { rec.authorizationToken = t.token; } catch { /* restarted */ } }
      }, 9 * 60 * 1000);
      return { engine: "azure", stop: () => new Promise((ok) => { stopped = true; clearInterval(renew); clearTimeout(restartTimer); status("off", "azure");
        if (!rec) return ok(); rec.stopContinuousRecognitionAsync(() => { try { rec.close(); } catch { /* closed */ } ok(); }, ok); }) };
    } catch (e) { onError?.("Azure Speech couldn't start, using the browser instead."); }
  }
  if (stream && source === "tab") onError?.("Listening to a shared tab needs Azure Speech. Using your microphone instead.");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { onError?.("This browser can't recognise speech. Type your answer instead."); status("off", "none"); return { engine: "none", stop: async () => {} }; }
  const r = new SR();
  r.lang = language; r.continuous = true; r.interimResults = true;
  let backoff = 300;
  r.onresult = (e) => {
    backoff = 300;
    status("working", "browser");
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript.trim();
      if (e.results[i].isFinal) { if (t) onSentence?.(t); } else interim += t + " ";
    }
    onPartial?.(interim.trim());
  };
  r.onerror = (e) => {
    if (e.error === "no-speech" || e.error === "aborted") return;
    status("paused", "browser");
    onError?.("Microphone: " + e.error);
  };
  r.onend = () => {  // Chrome ends a session every minute or so, and after errors: start again, a little slower each time
    if (stopped) return;
    setTimeout(() => { if (!stopped) try { r.start(); } catch { /* already running */ } }, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };
  r.onstart = () => status("working", "browser");
  r.start();
  return { engine: "browser", stop: async () => { stopped = true; status("off", "browser"); r.stop(); } };
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
