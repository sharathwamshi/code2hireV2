// Watches the candidate's environment during a proctored round and reports events to the server,
// which decides what counts as a warning and when to pause (all configurable per round).
import { useEffect, useRef, useState as useStateSafe } from "react";
import { api } from "../api";
import { loadFaceCounter, snapshot } from "./faces";

const FACE_EVERY_MS = 1500;
const MULTI_HITS = 2;   // 2 checks in a row with 2+ faces (about 3 s) -> warning
const NONE_HITS = 4;    // 4 checks in a row with no face (about 6 s) -> warning
const FACE_COOLDOWN_MS = 20000; // after a face warning, wait before raising another

/**
 * Our own dialogs never count as leaving fullscreen. Call allowFullscreenExit() right before code that is
 * expected to leave fullscreen (finishing the round, for example).
 */
let fullscreenGraceUntil = 0;
export function allowFullscreenExit(ms = 3000) { fullscreenGraceUntil = Date.now() + ms; }

export function useIntegrity({ attemptId, cfg = {}, active, questionIndex, onResult, videoRef }) {
  const last = useRef({});
  const qi = useRef(questionIndex);
  qi.current = questionIndex;

  useEffect(() => {
    if (!active) return undefined;
    let alive = true;
    const send = async (type, note, extra = {}) => {
      const now = Date.now();
      if (last.current[type] && now - last.current[type] < 2500) return; // one event per burst
      if (type === "window_blur" && last.current.tab_switch && now - last.current.tab_switch < 1500) return;
      last.current[type] = now;
      try { const r = await api.post(`/rounds/${attemptId}/integrity`, { type, note, question_index: qi.current, ...extra }); if (alive) onResult?.(r); } catch { /* offline: ignored */ }
    };
    const vis = () => { if (document.hidden) send("tab_switch", "Page hidden"); };
    const blur = () => setTimeout(() => { if (!document.hidden && !document.hasFocus()) send("window_blur", "Focus left the window"); }, 300);
    const fs = () => {
      if (!cfg["integrity.fullscreen"] || document.fullscreenElement) return;
      if (Date.now() < fullscreenGraceUntil) return; // we closed it ourselves
      send("fullscreen_exit");
    };
    const clip = (e) => {
      if (e.target?.dataset?.allowPaste) return;
      if (cfg["integrity.block_paste"]) e.preventDefault();
      send("copy_paste", e.type);
    };
    // Developer tools: only the keyboard shortcuts. Window-size guessing was removed because browser side panels,
    // vertical tabs and display scaling made innocent candidates look guilty.
    const keys = (e) => {
      const k = e.key?.toLowerCase();
      if (e.key === "F12" || ((e.ctrlKey || e.metaKey) && e.shiftKey && ["i", "j", "c"].includes(k)) || (e.metaKey && e.altKey && ["i", "j", "c"].includes(k))) {
        e.preventDefault(); send("devtools", "Shortcut");
      }
    };
    const ctx = (e) => { if (!e.target?.dataset?.allowContext) e.preventDefault(); };
    const off = () => send("disconnect");
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("blur", blur);
    document.addEventListener("fullscreenchange", fs);
    ["copy", "paste", "cut"].forEach((t) => document.addEventListener(t, clip));
    document.addEventListener("keydown", keys);
    document.addEventListener("contextmenu", ctx);
    window.addEventListener("offline", off);

    // Face presence: counts faces on-device every 1.5 s.
    let faceTimer = null;
    if (cfg["integrity.face_check"]) {
      let multi = 0, none = 0, quietUntil = 0, busy = false;
      loadFaceCounter().then((count) => {
        if (!alive) return;
        if (!count) { send("face_check_unavailable", "This browser can't run the face check"); return; }
        faceTimer = setInterval(async () => {
          const v = videoRef?.current;
          if (busy || !v || v.readyState < 2 || document.hidden) return;
          busy = true;
          try {
            const n = await count(v);
            if (Date.now() < quietUntil) return;
            multi = n >= 2 ? multi + 1 : 0;
            none = n === 0 ? none + 1 : 0;
            if (multi >= MULTI_HITS) { multi = 0; quietUntil = Date.now() + FACE_COOLDOWN_MS; send("multi_face", `${n} people on camera`, { snapshot: snapshot(v) }); }
            else if (none >= NONE_HITS) { none = 0; quietUntil = Date.now() + FACE_COOLDOWN_MS; send("no_face", "No face for about 6 seconds", { snapshot: snapshot(v) }); }
          } catch { /* a frame that failed to read: try the next one */ } finally { busy = false; }
        }, FACE_EVERY_MS);
      });
    }
    return () => {
      alive = false;
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("blur", blur);
      document.removeEventListener("fullscreenchange", fs);
      ["copy", "paste", "cut"].forEach((t) => document.removeEventListener(t, clip));
      document.removeEventListener("keydown", keys);
      document.removeEventListener("contextmenu", ctx);
      window.removeEventListener("offline", off);
      if (faceTimer) clearInterval(faceTimer);
    };
  }, [active, attemptId, JSON.stringify(cfg)]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** Live face count for the pre-start check: "we can see you" before the round begins. */
export function useFaceCount(videoRef, on) {
  const [n, setN] = useStateSafe(null);
  useEffect(() => {
    if (!on) { setN(null); return undefined; }
    let alive = true, t = null, busy = false;
    loadFaceCounter().then((count) => {
      if (!alive) return;
      if (!count) { setN("unavailable"); return; }
      t = setInterval(async () => {
        const v = videoRef?.current;
        if (busy || !v || v.readyState < 2) return;
        busy = true;
        try { const c = await count(v); if (alive) setN(c); } catch { /* skip frame */ } finally { busy = false; }
      }, 1200);
    });
    return () => { alive = false; if (t) clearInterval(t); };
  }, [on]); // eslint-disable-line react-hooks/exhaustive-deps
  return n;
}

export async function enterFullscreen() {
  try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); return true; } catch { return false; }
}
export async function leaveFullscreen() {
  allowFullscreenExit();
  try { if (document.fullscreenElement) await document.exitFullscreen(); } catch { /* already out */ }
}
