import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Chat, CallControls, useScreenShare, Video } from "../../components/CallWindow";
import { Hira } from "../../components/Mascot";
import { Btn, Chip, Loading, fmtDate, useConfirm } from "../../components/ui";
import { getMedia, useCall } from "../../lib/call";
import { LANG_CODES, listen, micLevel } from "../../lib/speech";

/** The candidate's side of a live F2F round: device check and consent, then the call. */
export default function CandidateCall({ a, nav, home }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  const [local, setLocal] = useState(null);
  const [level, setLevel] = useState(0);
  const [agree, setAgree] = useState(false);
  const [joined, setJoined] = useState(false);
  const [ended, setEnded] = useState(false);
  useEffect(() => { api.get(`/call/${a.id}`).then(setInfo).catch((e) => setErr(e.message)); }, [a.id]);
  useEffect(() => () => local?.getTracks().forEach((t) => t.stop()), [local]);
  // re-check the join window every 30 seconds while waiting
  useEffect(() => {
    if (!info || info.can_join) return;
    const t = setInterval(() => api.get(`/call/${a.id}`).then(setInfo).catch(() => {}), 30000);
    return () => clearInterval(t);
  }, [info, a.id]);

  if (err) return <Center><h2>{err}</h2></Center>;
  if (!info) return <Loading text="Getting your interview ready…" />;
  if (!info.enabled) return <Center><Hira size={100} /><h2>Your interviewer will send the meeting link</h2><p style={{ opacity: .8 }}>This round uses your company's own video tool.{info.scheduled_at ? ` It's scheduled for ${fmtDate(info.scheduled_at, true)}.` : ""}</p><Btn kind="gold" onClick={() => nav(home)}>Back</Btn></Center>;
  if (ended) return <Center><Hira size={110} mood="happy" /><h2>Thank you. The interview has ended.</h2><p style={{ opacity: .8 }}>The interviewer is writing up their notes. You'll hear back in your inbox.</p><Btn kind="gold" onClick={() => nav(home)}>Back to home</Btn></Center>;
  if (joined && local) return <InCall a={a} info={info} local={local} onLeave={() => setJoined(false)} onEnded={() => { setEnded(true); local.getTracks().forEach((t) => t.stop()); }} />;

  const turnOn = async () => {
    try { const s = await getMedia(); setLocal(s); micLevel(s, setLevel); }
    catch { setErr("We couldn't reach your camera or microphone. Allow access in the browser bar, then reload this page."); }
  };
  return (
    <div className="rbody">
      <div className="rmain">
        <div className="q-card col" style={{ gap: 14 }}>
          <div className="row"><Hira size={56} /><div><h2>{info.round}</h2><div className="muted">{info.job}{info.interviewer ? ` · with ${info.interviewer}` : ""}{info.scheduled_at ? ` · ${fmtDate(info.scheduled_at, true)}` : ""}</div></div></div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
            <li>This is a live video interview with a person from the hiring team.</li>
            {info.record && <li>The call is <b>recorded</b> so the hiring team can review it.</li>}
            <li>It is <b>AI-assisted</b>: {info.captions ? "live captions of what you say are sent to the interviewer's assistant, Isha, which helps them ask good follow-up questions." : "the interviewer uses an assistant to plan questions."} The interviewer makes every decision.</li>
            {info.watch_focus && <li>Please stay on this tab. The interviewer is told if you switch away.</li>}
            <li>Headphones help: they stop the interviewer's voice echoing into your captions.</li>
          </ul>
          <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />I agree to this interview being {info.record ? "recorded and " : ""}AI-assisted.</label>
          {!info.can_join && info.opens_at && <Chip kind="warn">You can join from {fmtDate(info.opens_at, true)}</Chip>}
          <div className="row"><Btn kind="primary" size="lg" disabled={!agree || !local || !info.can_join} onClick={async () => { await api.post(`/rounds/${a.id}/consent`, {}); setJoined(true); }}>Join interview</Btn>
            {!local ? <span className="small muted">Turn on your camera and microphone first.</span> : info.peer_online ? <Chip kind="good">Your interviewer is in the room</Chip> : <span className="small muted">Your interviewer hasn't joined yet. You can wait inside.</span>}</div>
        </div>
      </div>
      <div className="rside">
        <div className="selfview">{local ? <Video stream={local} muted mirror /> : <div style={{ display: "grid", placeItems: "center", height: "100%" }}><Btn kind="gold" onClick={turnOn}>Turn on camera and mic</Btn></div>}</div>
        {local && <div className="rpanel col"><b className="small">Say something</b><div className="levels">{Array.from({ length: 18 }).map((_, i) => <i key={i} style={{ height: Math.max(3, Math.min(28, level * 40 * (0.5 + Math.abs(Math.sin(i))))) }} />)}</div><span className="tiny" style={{ opacity: .7 }}>{level > .15 ? "We can hear you." : "Waiting for sound…"}</span></div>}
        <div className="rpanel small">Use Chrome or Edge on a laptop, with a steady connection. Close other apps that use the camera.</div>
      </div>
    </div>
  );
}

function InCall({ a, info, local, onLeave, onEnded }) {
  const askConfirm = useConfirm();
  const [chat, setChat] = useState([]);
  const [chatOn, setChatOn] = useState(false);
  const [seen, setSeen] = useState(0);
  const [caption, setCaption] = useState("");
  const [capOn, setCapOn] = useState(false);
  const rec = useRef(null);
  const call = useCall({ attId: a.id, role: "candidate", info, local, active: true, onMessage: (m) => {
    if (m.kind === "chat") setChat((c) => [...c, { from: "interviewer", text: m.payload.text }]);
    if (m.kind === "ended" || (m.kind === "bye" && m.payload?.ended)) onEnded();
  } });
  const [sharing, toggleShare] = useScreenShare(call, local);
  useEffect(() => { api.get(`/call/${a.id}/chat`).then(setChat).catch(() => {}); }, [a.id]);
  useEffect(() => { if (chatOn) setSeen(chat.length); }, [chatOn, chat.length]);
  // tell the interviewer when the candidate leaves the tab
  useEffect(() => {
    if (!info.watch_focus) return;
    const v = () => call.send("focus", { visible: !document.hidden });
    document.addEventListener("visibilitychange", v);
    return () => document.removeEventListener("visibilitychange", v);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // live captions for Isha, from the candidate's own microphone
  useEffect(() => {
    if (!info.captions) return;
    let stop = false;
    (async () => {
      rec.current = await listen({ language: LANG_CODES[info.language] || "en-IN",
        onPartial: (t) => setCaption(t),
        onSentence: (t) => { setCaption(t); if (local.getAudioTracks()[0]?.enabled !== false) call.send("caption", { text: t }); },
        onError: () => {} });
      if (stop) rec.current?.stop(); else setCapOn(rec.current?.engine !== "none");
    })();
    return () => { stop = true; rec.current?.stop(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const mutedSelf = local.getAudioTracks()[0]?.enabled === false;
  return (
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: chatOn ? "1fr 300px" : "1fr", minHeight: 0 }}>
      <div style={{ position: "relative", background: "#000", minHeight: 420 }}>
        {call.remote ? <Video stream={call.remote} style={{ objectFit: "contain" }} /> : (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center", padding: 20 }}>
            <div className="col" style={{ alignItems: "center" }}><Hira size={100} mood="idle" /><h2 style={{ color: "#fff" }}>{call.state === "left" ? "The interviewer stepped out" : call.state === "reconnecting" ? "Reconnecting…" : "Waiting for your interviewer"}</h2>
              <p style={{ opacity: .75 }}>{call.peerOnline ? "Connecting you now…" : "Stay on this page. You'll be connected as soon as they join."}</p></div>
          </div>
        )}
        {call.peerMedia.cam === false && call.remote && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: "#0B1026" }}>Interviewer's camera is off</div>}
        <div style={{ position: "absolute", right: 16, top: 16, width: 220, aspectRatio: "4/3", borderRadius: 12, overflow: "hidden", border: "2px solid rgba(255,255,255,.7)" }}><Video stream={sharing || local} muted mirror={!sharing} /></div>
        <div className="row" style={{ position: "absolute", left: 16, top: 16, gap: 6 }}>
          <Chip kind={call.state === "connected" ? "good" : "warn"}>{call.state === "connected" ? "● Connected" : "Connecting"}</Chip>
          {info.record && <Chip kind="bad">● Recorded</Chip>}
          {capOn && <Chip kind="dark">Captions on</Chip>}
          {sharing && <Chip kind="info">You're sharing your screen</Chip>}
        </div>
        {capOn && caption && !mutedSelf && <div style={{ position: "absolute", left: "50%", transform: "translateX(-50%)", bottom: 92, background: "rgba(0,0,0,.6)", padding: "6px 12px", borderRadius: 8, maxWidth: "70%", fontSize: 14 }}>{caption}</div>}
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 20 }}>
          <CallControls local={local} call={call} canShare={info.screen_share} onScreen={toggleShare} sharing={!!sharing}
            onChat={info.chat ? () => setChatOn(!chatOn) : null} chatOn={chatOn} unread={chatOn ? 0 : Math.max(0, chat.length - seen)}
            onHangup={async () => { if (await askConfirm({ title: "Leave the interview?", text: "You can rejoin from your home page while the interview is running.", yes: "Leave", no: "Stay", danger: true })) { call.hangup(false); onLeave(); } }} />
        </div>
      </div>
      {chatOn && <div style={{ background: "#0B1026", padding: 12, display: "flex", flexDirection: "column", minHeight: 0 }}><b style={{ marginBottom: 8 }}>Chat with the interviewer</b>
        <Chat items={chat} me="candidate" dark onSend={(t) => { call.send("chat", { text: t }); setChat((c) => [...c, { from: "candidate", text: t }]); }} /></div>}
    </div>
  );
}

function Center({ children }) {
  return <div style={{ margin: "auto", maxWidth: 560, textAlign: "center", padding: 24, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>{children}</div>;
}
