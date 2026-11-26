import { ConnectHelp, describeCall, useTick } from "./CallStatus";
import { useEffect, useRef, useState } from "react";

const STATE_TEXT = { waiting: "Waiting for the candidate to join…", connecting: "Connecting…", reconnecting: "Connection dropped. Reconnecting…", left: "The candidate left the call. They can rejoin while the interview is open.", self_left: "You left the call", ended: "Interview ended" };

export function Video({ stream, muted, mirror, style, onAspect }) {
  const v = useRef();
  const [blocked, setBlocked] = useState(false);
  // V02.01.02: start playing every time the stream is attached (also after docking or popping out); when the
  // browser blocks it, say so on the picture instead of leaving it frozen
  const play = () => { const el = v.current; if (!el || !el.srcObject) return; const p = el.play?.(); if (p?.catch) p.then(() => setBlocked(false)).catch(() => setBlocked(true)); };
  useEffect(() => { if (v.current && v.current.srcObject !== stream) v.current.srcObject = stream || null; play(); }, [stream]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = v.current;
    if (!el || !stream) return undefined;
    const tell = () => { if (el.videoWidth && el.videoHeight) onAspect?.(el.videoWidth / el.videoHeight); };
    const tracks = stream.getVideoTracks?.() || [];
    tracks.forEach((t) => t.addEventListener?.("unmute", play));
    el.addEventListener("loadedmetadata", tell); el.addEventListener("resize", tell);
    tell();
    return () => { el.removeEventListener("loadedmetadata", tell); el.removeEventListener("resize", tell); tracks.forEach((t) => t.removeEventListener?.("unmute", play)); };
  }, [stream, onAspect]); // eslint-disable-line react-hooks/exhaustive-deps
  return (<>
    <video ref={v} autoPlay playsInline muted={muted} style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000", transform: mirror ? "scaleX(-1)" : undefined, ...style }} />
    {blocked && <button type="button" className="video-resume" onClick={play}>▶ Click to resume video</button>}
  </>);
}

/**
 * onLeave: grey "Leave call" (only this person leaves; the other waits).
 * onEnd:   red "End interview" (interviewer only; ends it for both).
 */
/** V02.01.08: after any (re)connect, tell the other side whether my microphone and camera are on, so it never shows a
 * stale "muted" (or misses one). */
export function useMediaResend(call, local, tick) {
  useEffect(() => {
    if (call?.state !== "connected" || !local) return;
    call.send("media", { mic: local.getAudioTracks()[0]?.enabled !== false, cam: local.getVideoTracks()[0]?.enabled !== false });
  }, [call?.state, local, tick]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** V02.01.08: true while you talk with your microphone muted (heard on a copy of the muted track), so the page can say
 * "You're muted". */
export function useMutedTalk(local, muted) {
  const [talking, setTalking] = useState(false);
  useEffect(() => {
    const t = local?.getAudioTracks()[0];
    if (!muted || !t || t.readyState !== "live") { setTalking(false); return undefined; }
    let stop = null, loud = 0, gone = false;
    const copy = t.clone();
    copy.enabled = true;
    import("../lib/speech").then(({ micLevel }) => micLevel(new MediaStream([copy]), (l) => {
      loud = l > 0.14 ? loud + 1 : Math.max(0, loud - 1);
      if (loud > 6) setTalking(true);   // about a second of speech
    })).then((s2) => { if (gone) s2?.(); else stop = s2; }).catch(() => {});
    return () => { gone = true; stop?.(); copy.stop(); setTalking(false); };
  }, [local, muted]);
  return talking;
}

export function CallControls({ local, call, canShare, onScreen, sharing, chatOn, onChat, unread, onLeave, onEnd, light, onMedia }) {
  const [mic, setMic] = useState(() => local?.getAudioTracks()[0]?.enabled !== false);
  const [cam, setCam] = useState(() => local?.getVideoTracks()[0]?.enabled !== false);
  useMediaResend(call, local, `${mic}${cam}`);
  const toggle = (kind, on, set) => {
    local?.getTracks().filter((t) => t.kind === kind).forEach((t) => (t.enabled = on)); set(on);
    call?.send("media", kind === "audio" ? { mic: on } : { cam: on });
    onMedia?.(kind, on);   // so the page shows it at once ("You're muted", captions)
  };
  const b = (on) => ({ width: 42, height: 42, borderRadius: "50%", border: 0, cursor: "pointer", fontSize: 17, background: on ? (light ? "#EEF0F5" : "rgba(255,255,255,.16)") : "#C5283D", color: on && light ? "#14213D" : "#fff" });
  return (
    <div className="row call-controls" style={{ gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
      <button style={b(mic)} onClick={() => toggle("audio", !mic, setMic)} aria-label={mic ? "Mute microphone" : "Unmute microphone"} title={mic ? "Mute" : "Unmute"}>{mic ? "🎙" : "🔇"}</button>
      <button style={b(cam)} onClick={() => toggle("video", !cam, setCam)} aria-label={cam ? "Turn camera off" : "Turn camera on"} title={cam ? "Camera off" : "Camera on"}>{cam ? "📷" : "🚫"}</button>
      {canShare && <button style={{ ...b(true), background: sharing ? "#5B3FFF" : b(true).background, color: sharing ? "#fff" : b(true).color }} onClick={onScreen} aria-label={sharing ? "Stop sharing screen" : "Share screen"} title="Share screen">🖥</button>}
      {onChat && <button style={{ ...b(true), background: chatOn ? "#5B3FFF" : b(true).background, color: chatOn ? "#fff" : b(true).color, position: "relative" }} onClick={onChat} aria-label="Chat" title="Chat">💬{unread > 0 && <span style={{ position: "absolute", top: -2, right: -2, background: "#FFC94A", color: "#14213D", borderRadius: 99, fontSize: 10, padding: "0 5px", fontWeight: 800 }}>{unread}</span>}</button>}
      {onLeave && <button style={{ ...b(true), width: "auto", padding: "0 14px", borderRadius: 22, fontSize: 13, fontWeight: 700 }} onClick={onLeave} aria-label="Leave call" title="Leave the call. The interview stays open and you can rejoin.">Leave call</button>}
      {onEnd && <button style={{ ...b(false), width: "auto", padding: "0 14px", borderRadius: 22, fontSize: 13, fontWeight: 700 }} onClick={onEnd} aria-label="End interview" title="End the interview for both of you">End interview</button>}
    </div>
  );
}

export function useScreenShare(call, local) {
  const [sharing, setSharing] = useState(null);
  const toggle = async () => {
    if (sharing) { sharing.getTracks().forEach((t) => t.stop()); await call.replaceVideo(local.getVideoTracks()[0]); setSharing(null); call.send("media", { screen: false }); return; }
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const t = s.getVideoTracks()[0];
      t.onended = async () => { await call.replaceVideo(local.getVideoTracks()[0]); setSharing(null); call.send("media", { screen: false }); };
      await call.replaceVideo(t); setSharing(s); call.send("media", { screen: true });
    } catch { /* cancelled */ }
  };
  return [sharing, toggle];
}

/** F2F-002 (V02.00.08): a chat message shows "Sending…", then nothing when it arrived, or "Not sent · Retry". */
export function useChatSend(call, setChat, me) {
  const post = (key, text) => call.sendStrict("chat", { text })
    .then(() => setChat((c) => c.map((m) => (m.key === key ? { ...m, status: "sent" } : m))))
    .catch(() => setChat((c) => c.map((m) => (m.key === key ? { ...m, status: "failed" } : m))));
  const send = (text) => { const key = Math.random().toString(36).slice(2); setChat((c) => [...c, { from: me, text, key, status: "sending" }]); post(key, text); };
  const retry = (m) => { setChat((c) => c.map((x) => (x.key === m.key ? { ...x, status: "sending" } : x))); post(m.key, m.text); };
  return [send, retry];
}

export function Chat({ items, onSend, onRetry, me, dark }) {
  const [t, setT] = useState("");
  const box = useRef();
  useEffect(() => { box.current?.scrollTo({ top: 1e6 }); }, [items.length]);
  const submit = () => { if (t.trim()) { onSend(t.trim()); setT(""); } };
  return (
    <div className="col" style={{ gap: 6, height: "100%", minHeight: 0 }}>
      <div ref={box} className="col" style={{ gap: 6, overflow: "auto", flex: 1, fontSize: 13 }}>
        {!items.length && <span style={{ opacity: .6 }}>Messages appear here. Use chat to share a link or a snippet.</span>}
        {items.map((m, i) => <div key={m.key || i} className="col" style={{ gap: 2, alignSelf: m.from === me ? "flex-end" : "flex-start", maxWidth: "85%", alignItems: m.from === me ? "flex-end" : "flex-start" }}>
          <div style={{ background: m.from === me ? (m.status === "failed" ? "#9B2C2C" : "#5B3FFF") : dark ? "rgba(255,255,255,.1)" : "#F1F3F8", color: m.from === me ? "#fff" : "inherit", borderRadius: 10, padding: "6px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word", opacity: m.status === "sending" ? .7 : 1 }}>{m.text}</div>
          {m.status === "sending" && <span className="tiny" style={{ opacity: .6 }}>Sending…</span>}
          {m.status === "failed" && <span className="tiny" style={{ color: "#FF8A8A" }}>Not sent. {onRetry && <button className="linkbtn" onClick={() => onRetry(m)}>Retry</button>}</span>}
        </div>)}
      </div>
      <form className="row chat-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <textarea className="input" rows={1} value={t} onChange={(e) => setT(e.target.value)} placeholder="Message" aria-label="Chat message" title="Enter sends. Shift+Enter adds a new line."
          style={{ minHeight: 34, maxHeight: 90, resize: "none", padding: "7px 10px", lineHeight: 1.35 }}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
        <button className="btn sm primary" type="submit">Send</button>
      </form>
    </div>
  );
}

/**
 * The interviewer's call (V02.00.05). Docked in the room by default, so it never covers the plan or Isha's suggestions
 * (F2F-005); "Pop out" floats it. The controls sit in their own strip under the video and chat opens as a side panel
 * with the typing box at the bottom, so nothing overlaps (F2F-004). End interview lives only in the room's top bar.
 */
export default function CallWindow({ call, local, info, recording, recNote, chat, onChat, onChatRetry, candidateName, focusAway, onLeave, docked, onDock, level }) {
  const ref = useRef();
  const drag = useRef(null);
  const [size, setSize] = useState("normal");
  const [pos, setPos] = useState({ x: window.innerWidth - 560, y: Math.max(70, window.innerHeight - 420) });
  // F2F-002 (V02.00.08): docking or popping out the video keeps the chat open
  const [chatOn, setChatOnRaw] = useState(() => { try { return sessionStorage.getItem("c2h_chat_on") === "1"; } catch { return false; } });
  const setChatOn = (v) => { setChatOnRaw(v); try { sessionStorage.setItem("c2h_chat_on", v ? "1" : "0"); } catch { /* private mode */ } };
  const [seen, setSeen] = useState(() => chat.length);
  const everConnected = useRef(false);
  if (call.state === "connected") everConnected.current = true;
  useTick(call.state !== "connected");
  const st = describeCall(call, "candidate", everConnected.current);
  const [sharing, toggleShare] = useScreenShare(call, local);
  useEffect(() => {
    const mv = (e) => { if (!drag.current) return; setPos({ moved: true, x: Math.max(0, Math.min(window.innerWidth - 200, e.clientX - drag.current.dx)), y: Math.max(56, Math.min(window.innerHeight - 120, e.clientY - drag.current.dy)) }); };
    const up = () => (drag.current = null);
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
  }, []);
  useEffect(() => { if (chatOn) setSeen(chat.length); }, [chatOn, chat.length]);
  const theirs = call.peerMedia;
  const chatW = 260;
  const floatDims = size === "big" ? { width: Math.min(1000, window.innerWidth - 40), height: Math.min(620, window.innerHeight - 120) }
    : size === "mini" ? { width: 280, height: 210 } : { width: 480 + (chatOn ? chatW : 0), height: 380 };
  // V02.01.02: docked, the box is as wide as the candidate's picture at the available height (no black bands, no
  // blank space): the rest of the row goes to Isha's follow-ups
  const [ar, setAr] = useState(16 / 9);
  const [stageH, setStageH] = useState(0);
  const stageRef = useRef();
  useEffect(() => {
    if (!docked || !stageRef.current || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([e]) => setStageH(e.contentRect.height));
    ro.observe(stageRef.current);
    return () => ro.disconnect();
  }, [docked]);
  const onAspect = (x) => { if (x > 0.5 && x < 3 && Math.abs(x - ar) > 0.01) setAr(x); };
  const dockW = stageH ? Math.round(stageH * ar + (chatOn ? chatW : 0)) : undefined;
  const placed = docked ? (dockW ? { width: dockW } : {}) : size === "big" && !pos.moved ? { left: 20, top: 70, ...floatDims }
    : { left: Math.max(0, Math.min(pos.x, window.innerWidth - floatDims.width - 8)), top: Math.max(56, Math.min(pos.y, window.innerHeight - floatDims.height - 8)), ...floatDims };
  const mini = !docked && size === "mini";
  return (
    <div ref={ref} className={docked ? "call-dock" : "float-video call-float"} style={placed} aria-label="Video call">
      <div className="fv-h" onPointerDown={(e) => { if (docked || e.target.closest("button")) return; const r = ref.current.getBoundingClientRect(); drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top }; }}>
        <span className="dot" style={{ color: call.state === "connected" ? "#3DDC84" : "#FFC94A" }} /> <span className="grow ell">{candidateName}</span>
        {recording && <span className="rec-dot" title={recNote || ""}>● REC</span>}
        {focusAway && <span style={{ color: "#FFC94A" }}>left the tab</span>}
        <span className="row" style={{ gap: 4 }}>
          {!docked && ["mini", "normal", "big"].map((s) => <button key={s} className={"fv-btn" + (size === s ? " on" : "")} onClick={() => setSize(s)} aria-label={s === "mini" ? "Small" : s === "normal" ? "Medium" : "Large"}>{s === "mini" ? "▁" : s === "normal" ? "▢" : "⛶"}</button>)}
          <button className="fv-btn" onClick={onDock} title={docked ? "Float the video over the room" : "Put the video back in the room"}>{docked ? "Pop out ↗" : "Dock ↙"}</button>
        </span>
      </div>
      <div className="call-body">
        <div className="call-stage" ref={stageRef}>
          {call.remote && <Video stream={call.remote} style={{ objectFit: "contain" }} onAspect={onAspect} />}
          {(!call.remote || call.state !== "connected") && (
            <div className={"call-msg" + (call.remote ? " over" : "")}>
              <b>{call.state === "self_left" ? STATE_TEXT.self_left : call.state === "connected" ? "Connecting the video…" : st.title}</b>
              {!mini && call.state !== "self_left" && !st.failed && <div className="tiny" style={{ opacity: .8 }}>{call.state === "connected" ? "" : st.text}</div>}
              {info?.scheduled_at && st.key === "waiting" && <div className="tiny" style={{ opacity: .7 }}>The candidate gets a “Join” button in their account.</div>}
              {!mini && (st.failed || (st.slow && call.attempt > 0)) && <ConnectHelp dark compact onRetry={call.reconnect} />}
            </div>
          )}
          {call.remote && theirs.cam === false && <div className="call-msg over solid">{candidateName} turned their camera off</div>}
          <div className="call-tags">
            {theirs.mic === false && <span className="chip bad">Candidate muted</span>}
            {theirs.screen && <span className="chip info">Candidate is sharing their screen</span>}
          </div>
          {!mini && <div className="call-pip"><Video stream={sharing || local} muted mirror={!sharing} /></div>}
        </div>
        {chatOn && !mini && <div className="call-chat" style={{ width: chatW }}><b className="small">Chat</b><Chat items={chat} onSend={onChat} onRetry={onChatRetry} me="interviewer" dark /></div>}
      </div>
      {!mini && <div className="call-strip">
        <CallControls local={local} call={call} canShare={info?.screen_share} onScreen={toggleShare} sharing={!!sharing}
          onChat={info?.chat ? () => setChatOn(!chatOn) : null} chatOn={chatOn} unread={chatOn ? 0 : chat.length - seen} onLeave={onLeave} />
        <span className="call-level" title="Sound from the call"><span className="tiny">🔊</span><i style={{ width: `${Math.min(100, Math.round((level || 0) * 160))}%` }} /></span>
      </div>}
    </div>
  );
}
