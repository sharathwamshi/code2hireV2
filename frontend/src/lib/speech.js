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
export async function speak(text, { voice, rate, attId } = {}) {
  stopSpeaking();
  try {
    // V02.01.01: attId lets the server keep the line, with its time, for the interview video
    const res = await api.raw("POST", "/speech/tts", { text, voice, rate, attempt_id: attId || undefined });
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
 * Speech to text. Azure Speech when the server has a key (every browser, and it can listen to a chosen microphone or a
 * shared tab), otherwise the browser's own engine (Chrome and Edge; always the computer's default microphone).
 * onPartial(text) while speaking, onSentence(text) for each finished phrase. Returns { engine, stop() }; `engine` is
 * the engine listening right now.
 *
 * V02.00.07: captions never die quietly: Azure's key is renewed every 9 minutes, and a stopped engine restarts.
 * V02.01.05: no disruption when Azure drops.
 *  - A drop is retried quietly. If Azure drops twice within a minute, or isn't back within 5 seconds, listening moves
 *    to the browser's engine (when there is one and we're not listening to a shared tab), and goes back to Azure in
 *    the background once it works again (checked every 90 seconds).
 *  - The half-heard sentence at the moment of a drop is kept as a sentence, not lost.
 *  - No error messages while listening: onStatus("working" | "paused" | "off", engine) and onSwitch(from, to) report it,
 *    and onGap({ at, seconds }) reports any stretch over 10 seconds with no captions, so the page can mark it.
 *  - onError is only for "nothing can listen here" (no Azure and no browser engine) and the shared-tab notice.
 * source: "mic" (default) or "tab" (another meeting's tab: only Azure can listen to that).
 */
export async function listen({ language = "en-IN", onPartial, onSentence, onError, onStatus, onSwitch, onGap, stream, source = "mic" }) {
  let stopped = false;
  let engine = "none", cur = null, partial = "", lastOk = Date.now(), down = 0;
  const drops = [];
  let checkBack = null, upTimer = null;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canBrowser = !!SR && source !== "tab";
  const safe = (f) => (...a) => { try { f?.(...a); } catch { /* the page went away */ } };
  const status = safe(onStatus), sentence = safe(onSentence), part = safe(onPartial), err = safe(onError), sw = safe(onSwitch), gap = safe(onGap);
  const heard = (eng) => {   // captions came back: report the gap if it was long
    if (down && Date.now() - down > 10000) gap({ at: new Date(down).toISOString(), seconds: Math.round((Date.now() - down) / 1000) });
    down = 0; lastOk = Date.now();
    status("working", eng);
  };
  const flush = () => {   // keep the half-heard sentence
    const t = partial.trim();
    partial = "";
    if (t.split(/\s+/).length >= 3) sentence(t);
    part("");
  };

  // ---------------------------------------------------------------- Azure
  const tryAzure = async () => {
    const tok = await azureToken().catch(() => null);
    if (!tok) return null;
    const sdk = await loadSdk();
    let rec = null, renew = null, retry = null, region = tok.region, token = tok.token, dead = false;
    const h = { name: "azure" };
    const begin = async () => {
      const cfg = sdk.SpeechConfig.fromAuthorizationToken(token, region);
      cfg.speechRecognitionLanguage = language;
      const audio = stream ? sdk.AudioConfig.fromStreamInput(stream) : sdk.AudioConfig.fromDefaultMicrophoneInput();
      rec = new sdk.SpeechRecognizer(cfg, audio);
      rec.recognizing = (_, e) => { if (cur !== h) return; heard("azure"); partial = e.result.text || ""; part(partial); };
      rec.recognized = (_, e) => { if (cur !== h) return; if (e.result.reason === sdk.ResultReason.RecognizedSpeech && e.result.text) { partial = ""; heard("azure"); sentence(e.result.text); } };
      const lost = () => { if (!dead && cur === h) dropped(h); };
      rec.canceled = lost;
      rec.sessionStopped = lost;
      await new Promise((ok, bad) => rec.startContinuousRecognitionAsync(ok, bad));
    };
    h.restart = () => {
      clearTimeout(retry);
      try { rec?.close(); } catch { /* closed */ }
      retry = setTimeout(async () => {
        if (dead || stopped) return;
        const t = await azureToken().catch(() => null);
        if (t) { token = t.token; region = t.region; }
        try { await begin(); if (cur === h) heard("azure"); } catch { if (cur === h) dropped(h); }
      }, 1500);
    };
    h.stop = () => new Promise((ok) => {
      dead = true; clearInterval(renew); clearTimeout(retry);
      if (!rec) return ok();
      rec.stopContinuousRecognitionAsync(() => { try { rec.close(); } catch { /* closed */ } ok(); }, () => { try { rec.close(); } catch { /* closed */ } ok(); });
    });
    await begin();
    renew = setInterval(async () => {  // the key expires after 10 minutes
      const t = await azureToken().catch(() => null);
      if (t && rec) { token = t.token; region = t.region; try { rec.authorizationToken = t.token; } catch { /* restarted */ } }
    }, 9 * 60 * 1000);
    return h;
  };

  // ---------------------------------------------------------------- the browser's engine
  const startBrowser = () => {
    const r = new SR();
    r.lang = language; r.continuous = true; r.interimResults = true;
    let backoff = 300, dead = false;
    const h = { name: "browser" };
    r.onresult = (e) => {
      if (cur !== h) return;
      backoff = 300;
      heard("browser");
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript.trim();
        if (e.results[i].isFinal) { if (t) { partial = ""; sentence(t); } } else interim += t + " ";
      }
      partial = interim.trim();
      part(partial);
    };
    r.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") { status("off", "browser"); err("Captions need microphone permission."); dead = true; return; }
      status("paused", "browser");
    };
    r.onend = () => {  // Chrome ends a session every minute or so, and after errors: start again, a little slower each time
      if (stopped || dead) return;
      if (cur === h) flush();
      setTimeout(() => { if (!stopped && !dead) try { r.start(); } catch { /* already running */ } }, backoff);
      backoff = Math.min(backoff * 2, 5000);
    };
    r.onstart = () => { if (cur === h) status("working", "browser"); };
    r.start();
    h.stop = async () => { dead = true; try { r.stop(); } catch { /* stopped */ } };
    return h;
  };

  // ---------------------------------------------------------------- switching
  const use = (h) => { const from = engine; cur = h; engine = h.name; if (from !== "none" && from !== h.name) sw(from, h.name); };
  const toBrowser = async (old) => {
    use(startBrowser());
    old.stop();
    status("working", "browser");
    clearInterval(checkBack);
    checkBack = setInterval(async () => {   // Azure is better (any microphone, every browser): go back once it works
      if (stopped || engine !== "browser") return;
      try {
        const az = await tryAzure();
        if (!az || stopped) { az?.stop(); return; }
        const old2 = cur;
        flush();
        use(az);
        old2.stop();
        drops.length = 0;
        clearInterval(checkBack);
        heard("azure");
      } catch { /* still down: try again later */ }
    }, 90000);
  };
  function dropped(h) {
    if (stopped || cur !== h) return;
    flush();
    if (!down) down = Date.now();
    status("paused", h.name);
    const now = Date.now();
    drops.push(now);
    while (drops.length && now - drops[0] > 60000) drops.shift();
    if (canBrowser && drops.length >= 2) { toBrowser(h); return; }
    h.restart();
    clearTimeout(upTimer);
    upTimer = setTimeout(() => { if (!stopped && cur === h && down && canBrowser) toBrowser(h); }, 5000);
  }

  // ---------------------------------------------------------------- start
  try {
    const az = await tryAzure();
    if (az) use(az);
  } catch { /* Azure couldn't start: the browser's engine below */ }
  if (!cur) {
    if (stream && source === "tab") err("Listening to a shared tab needs Azure Speech. Using your microphone instead.");
    if (!SR) { err("This browser can't recognise speech. Type your answer instead."); status("off", "none"); return { engine: "none", stop: async () => {} }; }
    use(startBrowser());
  }
  status("working", engine);
  void lastOk;
  return {
    get engine() { return engine; },
    stop: async () => { stopped = true; clearInterval(checkBack); clearTimeout(upTimer); status("off", engine); await cur?.stop(); },
  };
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
