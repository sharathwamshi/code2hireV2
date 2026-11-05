import { useEffect, useRef, useState } from "react";

const STATE_TEXT = { waiting: "Waiting for the candidate to join…", connecting: "Connecting…", reconnecting: "Connection dropped. Reconnecting…", left: "The candidate left the call. They can rejoin while the interview is open.", self_left: "You left the call", ended: "Interview ended" };

export function Video({ stream, muted, mirror, style }) {
  const v = useRef();
  useEffect(() => { if (v.current && v.current.srcObject !== stream) v.current.srcObject = stream || null; }, [stream]);
  return <video ref={v} autoPlay playsInline muted={muted} style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000", transform: mirror ? "scaleX(-1)" : undefined, ...style }} />;
}

/**
 * onLeave: grey "Leave call" (only this person leaves; the other waits).
 * onEnd:   red "End interview" (interviewer only; ends it for both).
 */
export function CallControls({ local, call, canShare, onScreen, sharing, chatOn, onChat, unread, onLeave, onEnd, light }) {
  const [mic, setMic] = useState(true);
  const [cam, setCam] = useState(true);
  const toggle = (kind, on, set) => { local?.getTracks().filter((t) => t.kind === kind).forEach((t) => (t.enabled = on)); set(on); call?.send("media", kind === "audio" ? { mic: on } : { cam: on }); };
  const b = (on) => ({ width: 42, height: 42, borderRadius: "50%", border: 0, cursor: "pointer", fontSize: 17, background: on ? (light ? "#EEF0F5" : "rgba(255,255,255,.16)") : "#C5283D", color: on && light ? "#14213D" : "#fff" });
  return (
    <div className="row" style={{ gap: 10, justifyContent: "center" }}>
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

export function Chat({ items, onSend, me, dark }) {
  const [t, setT] = useState("");
  const box = useRef();
  useEffect(() => { box.current?.scrollTo({ top: 1e6 }); }, [items.length]);
  return (
    <div className="col" style={{ gap: 6, height: "100%", minHeight: 0 }}>
      <div ref={box} className="col" style={{ gap: 6, overflow: "auto", flex: 1, fontSize: 13 }}>
        {!items.length && <span style={{ opacity: .6 }}>Messages appear here. Use chat to share a link or a snippet.</span>}
        {items.map((m, i) => <div key={i} style={{ alignSelf: m.from === me ? "flex-end" : "flex-start", background: m.from === me ? "#5B3FFF" : dark ? "rgba(255,255,255,.1)" : "#F1F3F8", color: m.from === me ? "#fff" : "inherit", borderRadius: 10, padding: "6px 10px", maxWidth: "85%", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{m.text}</div>)}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (t.trim()) { onSend(t.trim()); setT(""); } }}>
        <input className="input" value={t} onChange={(e) => setT(e.target.value)} placeholder="Message" aria-label="Chat message" style={{ height: 34 }} />
        <button className="btn sm primary" type="submit">Send</button>
      </form>
    </div>
  );
}

/** The interviewer's floating, draggable, resizable call window. Candidate large, interviewer picture-in-picture. */
export default function CallWindow({ call, local, info, recording, recNote, chat, onChat, candidateName, focusAway, onLeave, onEnd }) {
  const ref = useRef();
  const drag = useRef(null);
  const [size, setSize] = useState("normal");
  const [pos, setPos] = useState({ x: window.innerWidth - 470, y: Math.max(70, window.innerHeight - 330) });
  const [chatOn, setChatOn] = useState(false);
  const [seen, setSeen] = useState(0);
  const [sharing, toggleShare] = useScreenShare(call, local);
  useEffect(() => {
    const mv = (e) => { if (!drag.current) return; setPos({ x: Math.max(0, Math.min(window.innerWidth - 160, e.clientX - drag.current.dx)), y: Math.max(56, Math.min(window.innerHeight - 80, e.clientY - drag.current.dy)) }); };
    const up = () => (drag.current = null);
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
  }, []);
  useEffect(() => { if (chatOn) setSeen(chat.length); }, [chatOn, chat.length]);
  const dims = size === "big" ? { width: Math.min(900, window.innerWidth - 40), height: Math.min(560, window.innerHeight - 120) } : size === "mini" ? { width: 260, height: 170 } : { width: 440, height: 300 };
  const placed = size === "big" ? { left: 20, top: 70 } : { left: pos.x, top: pos.y };
  const theirs = call.peerMedia;
  return (
    <div ref={ref} className="float-video" style={{ ...placed, ...dims, display: "flex", flexDirection: "column", background: "#0B1026" }} aria-label="Video call">
      <div className="fv-h" style={{ position: "relative", background: "#0B1026", height: 34 }} onPointerDown={(e) => { if (size === "big" || e.target.tagName === "BUTTON") return; const r = ref.current.getBoundingClientRect(); drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top }; }}>
        <span className="dot" style={{ color: call.state === "connected" ? "#3DDC84" : "#FFC94A" }} /> {candidateName}
        {recording && <span style={{ color: "#FF6B6B", fontWeight: 700 }} title={recNote || ""}>● REC</span>}
        {focusAway && <span style={{ color: "#FFC94A" }}>· left the call tab</span>}
        <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {["mini", "normal", "big"].map((s) => <button key={s} onClick={() => setSize(s)} style={{ background: size === s ? "rgba(255,255,255,.2)" : "none", border: 0, color: "#fff", cursor: "pointer", borderRadius: 6, fontSize: 11, padding: "2px 6px" }}>{s === "mini" ? "▁" : s === "normal" ? "▢" : "⛶"}</button>)}
        </span>
      </div>
      <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex" }}>
        <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
          {call.remote ? <Video stream={call.remote} /> : <div style={{ color: "#C9CDDA", display: "grid", placeItems: "center", height: "100%", fontSize: 13, padding: 16, textAlign: "center" }}>{STATE_TEXT[call.state] || "Connecting…"}{info?.scheduled_at && call.state === "waiting" && <div className="tiny" style={{ opacity: .7 }}>The candidate gets a “Join” button in their account.</div>}</div>}
          {call.remote && call.state !== "connected" && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: "rgba(0,0,0,.45)", color: "#fff", fontSize: 13 }}>{STATE_TEXT[call.state]}</div>}
          {call.remote && theirs.cam === false && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: "#0B1026", color: "#C9CDDA", fontSize: 13 }}>{candidateName} turned their camera off</div>}
          {theirs.mic === false && <span className="chip bad" style={{ position: "absolute", left: 8, top: 8 }}>Candidate muted</span>}
          {theirs.screen && <span className="chip info" style={{ position: "absolute", left: 8, top: 8 }}>Candidate is sharing their screen</span>}
          {size !== "mini" && <div style={{ position: "absolute", right: 8, bottom: 62, width: size === "big" ? 200 : 120, aspectRatio: "4/3", borderRadius: 8, overflow: "hidden", border: "2px solid rgba(255,255,255,.7)" }}><Video stream={sharing || local} muted mirror={!sharing} /></div>}
          {size !== "mini" && <div style={{ position: "absolute", left: 0, right: 0, bottom: 8 }}><CallControls local={local} call={call} canShare={info?.screen_share} onScreen={toggleShare} sharing={!!sharing}
            onChat={info?.chat ? () => setChatOn(!chatOn) : null} chatOn={chatOn} unread={chatOn ? 0 : chat.length - seen} onLeave={onLeave} onEnd={onEnd} /></div>}
        </div>
        {chatOn && size !== "mini" && <div style={{ width: 220, borderLeft: "1px solid rgba(255,255,255,.1)", padding: 8, color: "#fff" }}><Chat items={chat} onSend={onChat} me="interviewer" dark /></div>}
      </div>
    </div>
  );
}
