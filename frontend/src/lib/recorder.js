// Interview video recorder (V02.00.04). Every AI and live interview is recorded.
//
// - A chunk is cut every 10 seconds and uploaded straight away, so a crash or a dropped connection loses at most the
//   last 10 seconds. Chunks that fail to upload stay in memory and are retried, in order, until the server has them.
// - Each continuous piece has its own id ("segment"); every chunk is numbered, so a retry is never stored twice.
// - webm where the browser supports it, MP4 on Safari / iPhone.
// - Voices are mixed through one AudioContext. Hira's spoken questions are tapped into the mix (see speech.js).
import { api, getToken } from "../api";
import { setSpeechTap } from "./speech";

const CHUNK_MS = 10_000;
const TYPES = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4;codecs=avc1,mp4a", "video/mp4"];

/** The format this browser records in, or null. */
export function recordingType() {
  if (!window.MediaRecorder) return null;
  return TYPES.find((t) => window.MediaRecorder.isTypeSupported?.(t)) || null;
}

// Weak internet (V02.00.05): the system check measures the upload speed and new recordings use a lower bitrate,
// so the video still reaches the server instead of falling behind.
const QUALITY_KEY = "c2h_upload_mbps";
export function setUploadSpeed(mbps) { try { sessionStorage.setItem(QUALITY_KEY, String(mbps)); } catch { /* private mode */ } }
export function videoBitrate() {
  let up = NaN;
  try { up = parseFloat(sessionStorage.getItem(QUALITY_KEY)); } catch { /* private mode */ }
  if (!isFinite(up)) return 900_000;
  if (up < 0.8) return 250_000;
  if (up < 1.5) return 450_000;
  return 900_000;
}

export function recorderSupported() {
  return !!(window.MediaRecorder && (window.AudioContext || window.webkitAudioContext) && TYPES.some((t) => window.MediaRecorder.isTypeSupported?.(t)));
}

/** Draws two videos into one canvas: the main one full size, the other picture-in-picture. 15 frames a second. */
function compose(mainStream, pipStream) {
  const canvas = document.createElement("canvas");
  canvas.width = 1280; canvas.height = 720;
  const g = canvas.getContext("2d");
  const mk = (s) => { const v = document.createElement("video"); v.muted = true; v.playsInline = true; v.srcObject = s; v.play().catch(() => {}); return v; };
  const a = mk(mainStream), b = pipStream ? mk(pipStream) : null;
  const fit = (v, x, y, w, h) => {
    if (!v || v.readyState < 2 || !v.videoWidth) return false;
    const r = Math.min(w / v.videoWidth, h / v.videoHeight), vw = v.videoWidth * r, vh = v.videoHeight * r;
    g.drawImage(v, x + (w - vw) / 2, y + (h - vh) / 2, vw, vh); return true;
  };
  const t = setInterval(() => {
    g.fillStyle = "#0B1026"; g.fillRect(0, 0, 1280, 720);
    if (!fit(a, 0, 0, 1280, 720)) { g.fillStyle = "#C9CDDA"; g.font = "28px sans-serif"; g.fillText("Video paused", 540, 360); }
    if (b && b.readyState >= 2) { g.fillStyle = "#000"; g.fillRect(1280 - 340, 720 - 200, 320, 180); fit(b, 1280 - 340, 720 - 200, 320, 180); }
  }, 66);
  const out = canvas.captureStream(15);
  return { track: out.getVideoTracks()[0], stop: () => { clearInterval(t); out.getTracks().forEach((x) => x.stop()); a.srcObject = null; if (b) b.srcObject = null; } };
}

/**
 * startRecording({ attId, video, pip, audio: [streams], tapSpeech, onStatus })
 *   video: the main picture (the candidate's camera for AI interviews, the other person for live calls)
 *   pip:   an optional second picture drawn in the corner (the recorder's own camera in live calls)
 * Returns { stop(), health(), resume(), status() } or null when this browser can't record.
 */
export function startRecording({ attId, video, pip, audio = [], tapSpeech = false, onStatus }) {
  if (!recorderSupported() || !video) return null;
  const AC = window.AudioContext || window.webkitAudioContext;
  const ctx = new AC();
  const dest = ctx.createMediaStreamDestination();
  const meter = ctx.createAnalyser(); meter.fftSize = 512;
  const sources = [];
  audio.filter(Boolean).forEach((s) => {
    if (s.getAudioTracks().length) {
      const src = ctx.createMediaStreamSource(new MediaStream(s.getAudioTracks()));
      src.connect(dest); src.connect(meter); sources.push(src);
    }
  });
  if (tapSpeech) setSpeechTap({ ctx, node: dest });
  const wake = () => { if (ctx.state === "suspended") ctx.resume().catch(() => {}); };
  wake();
  const onGesture = () => { wake(); if (ctx.state === "running") { window.removeEventListener("pointerdown", onGesture, true); window.removeEventListener("keydown", onGesture, true); } };
  window.addEventListener("pointerdown", onGesture, true);
  window.addEventListener("keydown", onGesture, true);

  let comp = null;
  let vtrack = video.getVideoTracks()[0];
  if (pip) { try { comp = compose(video, pip); vtrack = comp.track; } catch { comp = null; } }
  const tracks = [...(vtrack ? [vtrack] : []), ...dest.stream.getAudioTracks()];
  const type = TYPES.find((t) => window.MediaRecorder.isTypeSupported(t));
  let rec;
  const bitrate = videoBitrate();
  try { rec = new MediaRecorder(new MediaStream(tracks), { mimeType: type, videoBitsPerSecond: bitrate }); }
  catch { comp?.stop(); ctx.close().catch(() => {}); return null; }
  const mime = type.startsWith("video/mp4") ? "video/mp4" : "video/webm";

  const segment = (Date.now().toString(36) + Math.random().toString(36).slice(2, 6)).slice(0, 20);
  const queue = [];       // [{ seq, blob, seconds }] not yet confirmed by the server
  let seq = 0, saved = 0, sending = false, stopped = false, failing = 0, lastError = "";
  const started = Date.now();
  const status = () => ({ segment, pending: queue.length, savedSeconds: saved, failing, lastError, stopped, lowQuality: bitrate < 900_000 });
  const emit = () => onStatus?.(status());

  const pump = async () => {
    if (sending) return;
    sending = true;
    while (queue.length) {
      const c = queue[0];
      const fd = new FormData();
      fd.append("segment", segment); fd.append("seq", String(c.seq)); fd.append("mime", mime); fd.append("seconds", String(c.seconds));
      fd.append("file", c.blob, `${segment}-${c.seq}.${mime === "video/mp4" ? "mp4" : "webm"}`);
      try {
        await api.post(`/recordings/${attId}/chunk`, fd);
        queue.shift(); saved = c.seconds; failing = 0; lastError = ""; emit();
      } catch (e) {
        const expected = e.data?.fields?.expected;
        if (e.status === 409 && Number.isInteger(expected) && expected > c.seq) { queue.shift(); continue; } // server already has it
        if (e.status === 403 || e.status === 404) { lastError = e.message; queue.length = 0; emit(); break; } // not allowed: stop trying
        failing += 1; lastError = e.message || "Upload failed"; emit();
        await new Promise((ok) => setTimeout(ok, Math.min(15000, 1500 * failing)));
      }
    }
    sending = false;
  };
  rec.ondataavailable = (e) => {
    if (!e.data?.size) return;
    queue.push({ seq: seq++, blob: e.data, seconds: Math.round((Date.now() - started) / 100) / 10 });
    emit(); pump();
  };
  rec.start(CHUNK_MS);
  emit();

  const buf = new Uint8Array(meter.frequencyBinCount);
  let heard = 0;
  const cleanup = () => {
    window.removeEventListener("pointerdown", onGesture, true); window.removeEventListener("keydown", onGesture, true);
    if (tapSpeech) setSpeechTap(null);
    comp?.stop(); ctx.close().catch(() => {});
  };
  return {
    segment, mime,
    status,
    seconds: () => Math.round((Date.now() - started) / 1000),
    health: () => {
      meter.getByteTimeDomainData(buf);
      let peak = 0; for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128));
      const level = peak / 128;
      if (level > 0.02) heard = Date.now();
      return { running: ctx.state === "running", recording: rec.state === "recording", hasAudioTracks: sources.length > 0 || tapSpeech, level,
        silentFor: heard ? (Date.now() - heard) / 1000 : (Date.now() - started) / 1000, behind: queue.length > 2, ...status() };
    },
    resume: wake,
    /** Stops recording, waits (up to maxWaitMs) for every chunk to reach the server, then asks the server to finish. */
    stop: (maxWaitMs = 60000) => new Promise((resolve) => {
      if (stopped) { resolve(status()); return; }
      stopped = true;
      const done = async () => {
        cleanup();
        const until = Date.now() + maxWaitMs;
        pump();
        while ((queue.length || sending) && Date.now() < until) await new Promise((ok) => setTimeout(ok, 300));
        if (!queue.length) { try { await api.post(`/recordings/${attId}/finish`, { segment }); } catch { /* housekeeping finishes it */ } }
        emit(); resolve(status());
      };
      rec.onstop = done;
      try { if (rec.state !== "inactive") rec.stop(); else done(); } catch { done(); }
    }),
  };
}

/** Tell the server the candidate said no to recording. */
export const declineRecording = (attId) => api.post(`/recordings/${attId}/declined`, {});

export const videoUrl = (attId, pieceId, download = false) =>
  `/api/recordings/${attId}/${pieceId}/video?token=${encodeURIComponent(getToken() || "")}${download ? "&download=1" : ""}`;
