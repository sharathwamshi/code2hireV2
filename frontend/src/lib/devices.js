// Camera and microphone during the interview (V02.00.05): notice when one stops or is unplugged, and repair the stream
// in place, so the call and the room keep the same MediaStream object.
import { useEffect, useRef, useState } from "react";

/** Returns null while both work, or { cam, mic } naming what stopped. A device that sends nothing for 4 s counts. */
export function useDeviceWatch(stream, on = true) {
  const [lost, setLost] = useState(null);
  const mutedSince = useRef({});
  useEffect(() => {
    if (!stream || !on) { setLost(null); return undefined; }
    const check = () => {
      const now = Date.now();
      const state = (t, k) => {
        if (!t) return false;
        if (t.readyState === "ended") return true;
        if (t.muted) { mutedSince.current[k] ||= now; return now - mutedSince.current[k] > 4000; }
        mutedSince.current[k] = 0;
        return false;
      };
      const cam = state(stream.getVideoTracks()[0], "cam");
      const mic = state(stream.getAudioTracks()[0], "mic");
      setLost((x) => (cam || mic ? (x && x.cam === cam && x.mic === mic ? x : { cam, mic }) : null));
    };
    const tracks = stream.getTracks();
    tracks.forEach((t) => { t.addEventListener("ended", check); t.addEventListener("mute", check); t.addEventListener("unmute", check); });
    navigator.mediaDevices?.addEventListener?.("devicechange", check);
    const iv = setInterval(check, 1500);
    check();
    return () => {
      clearInterval(iv);
      tracks.forEach((t) => { t.removeEventListener("ended", check); t.removeEventListener("mute", check); t.removeEventListener("unmute", check); });
      navigator.mediaDevices?.removeEventListener?.("devicechange", check);
    };
  }, [stream, on]);
  return lost;
}

/**
 * Gets new tracks for whatever stopped and swaps them into `stream` (same object). onTrack(kind, track) lets a call
 * replace what it sends. Returns true when everything works again.
 */
export async function repairStream(stream, onTrack) {
  const needV = stream.getVideoTracks().some((t) => t.readyState === "ended" || t.muted) || !stream.getVideoTracks().length;
  const needA = stream.getAudioTracks().some((t) => t.readyState === "ended" || t.muted) || !stream.getAudioTracks().length;
  if (!needV && !needA) return true;
  const fresh = await navigator.mediaDevices.getUserMedia({
    video: needV ? { width: { ideal: 1280 }, height: { ideal: 720 } } : false,
    audio: needA ? { echoCancellation: true, noiseSuppression: true, autoGainControl: true } : false,
  });
  for (const t of fresh.getTracks()) {
    stream.getTracks().filter((o) => o.kind === t.kind).forEach((o) => { stream.removeTrack(o); o.stop(); });
    stream.addTrack(t);
    await onTrack?.(t.kind, t);
  }
  return true;
}

/** The overlay shown while a device is missing. */
export function lostText(lost) {
  if (!lost) return "";
  const what = lost.cam && lost.mic ? "camera and microphone" : lost.cam ? "camera" : "microphone";
  return `Your ${what} stopped working. Plug it back in, or allow it in the browser bar, then press “Fix it”.`;
}
