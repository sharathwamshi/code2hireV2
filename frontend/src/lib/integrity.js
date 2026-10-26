// Watches the candidate's environment during a proctored round and reports events to the server,
// which decides what counts as a warning and when to pause (all configurable per round).
import { useEffect, useRef } from "react";
import { api } from "../api";

export function useIntegrity({ attemptId, cfg = {}, active, questionIndex, onResult, videoRef }) {
  const last = useRef({});
  const qi = useRef(questionIndex);
  qi.current = questionIndex;

  useEffect(() => {
    if (!active) return;
    const send = async (type, note) => {
      const now = Date.now();
      if (last.current[type] && now - last.current[type] < 2500) return; // one event per burst
      if (type === "window_blur" && last.current.tab_switch && now - last.current.tab_switch < 1500) return;
      last.current[type] = now;
      try { onResult?.(await api.post(`/rounds/${attemptId}/integrity`, { type, note, question_index: qi.current })); } catch { /* offline: ignored */ }
    };
    const vis = () => { if (document.hidden) send("tab_switch", "Page hidden"); };
    const blur = () => setTimeout(() => { if (!document.hidden) send("window_blur", "Focus left the window"); }, 300);
    const fs = () => { if (cfg["integrity.fullscreen"] && !document.fullscreenElement) send("fullscreen_exit"); };
    const clip = (e) => {
      if (e.target?.dataset?.allowPaste) return;
      if (cfg["integrity.block_paste"]) e.preventDefault();
      send("copy_paste", e.type);
    };
    const keys = (e) => {
      const k = e.key?.toLowerCase();
      if (e.key === "F12" || ((e.ctrlKey || e.metaKey) && e.shiftKey && ["i", "j", "c"].includes(k))) { e.preventDefault(); send("devtools", "Shortcut"); }
    };
    const ctx = (e) => e.preventDefault();
    const off = () => send("disconnect");
    let devOpen = false;
    const devtools = setInterval(() => {
      const open = window.outerWidth - window.innerWidth > 200 || window.outerHeight - window.innerHeight > 240;
      if (open && !devOpen) send("devtools", "Window size suggests developer tools");
      devOpen = open;
    }, 2000);
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("blur", blur);
    document.addEventListener("fullscreenchange", fs);
    ["copy", "paste", "cut"].forEach((t) => document.addEventListener(t, clip));
    document.addEventListener("keydown", keys);
    document.addEventListener("contextmenu", ctx);
    window.addEventListener("offline", off);

    // Face presence: uses the browser FaceDetector where available.
    let faceTimer;
    if (cfg["integrity.face_check"] && "FaceDetector" in window && videoRef?.current) {
      const fd = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 3 });
      let none = 0;
      faceTimer = setInterval(async () => {
        const v = videoRef.current;
        if (!v || v.readyState < 2) return;
        try {
          const faces = await fd.detect(v);
          if (faces.length > 1) send("multi_face", `${faces.length} faces`);
          none = faces.length === 0 ? none + 1 : 0;
          if (none === 3) send("no_face", "No face for ~6 seconds");
        } catch { /* detector unavailable */ }
      }, 2000);
    }
    return () => {
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("blur", blur);
      document.removeEventListener("fullscreenchange", fs);
      ["copy", "paste", "cut"].forEach((t) => document.removeEventListener(t, clip));
      document.removeEventListener("keydown", keys);
      document.removeEventListener("contextmenu", ctx);
      window.removeEventListener("offline", off);
      clearInterval(devtools); clearInterval(faceTimer);
    };
  }, [active, attemptId, JSON.stringify(cfg)]); // eslint-disable-line react-hooks/exhaustive-deps
}

export async function enterFullscreen() {
  try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); return true; } catch { return false; }
}
