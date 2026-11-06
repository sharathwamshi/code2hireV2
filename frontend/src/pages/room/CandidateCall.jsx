import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Chat, CallControls, useScreenShare, Video } from "../../components/CallWindow";
import { Hira } from "../../components/Mascot";
import { Btn, Chip, Loading, fmtDate, useConfirm } from "../../components/ui";
import { useCall } from "../../lib/call";
import { allowFullscreenExit, enterFullscreen, useFaceCount, useIntegrity } from "../../lib/integrity";
import { declineRecording, startRecording } from "../../lib/recorder";
import { LANG_CODES, listen } from "../../lib/speech";
import SystemCheck from "../../components/SystemCheck";
import { lostText, repairStream, useDeviceWatch } from "../../lib/devices";

/** The candidate's side of a live F2F round: device check and consent, then the call. */
export default function CandidateCall({ a, nav, home }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  const [local, setLocal] = useState(null);
  const [agree, setAgree] = useState(false);
  const [joined, setJoined] = useState(false);
  const [ended, setEnded] = useState(false);
  const [declined, setDeclined] = useState(false);
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
  if (declined || info.recording_declined) return <Center><Hira size={100} /><h2>The interview hasn't started</h2><p style={{ opacity: .8 }}>You chose not to be recorded. Every interview on Code2Hire is recorded, so this one can't go ahead as it is. The hiring team has been told and will contact you about what happens next.</p><Btn kind="gold" onClick={() => nav(home)}>Back to home</Btn></Center>;
  if (ended || info.ended) return <Center><Hira size={110} mood="happy" /><h2>Thank you. The interview has ended.</h2><p style={{ opacity: .8 }}>The interviewer is writing up their notes. You'll hear back in your inbox.</p><Btn kind="gold" onClick={() => nav(home)}>Back to home</Btn></Center>;
  if (joined && local) return <InCall a={a} info={info} local={local} onLeave={() => setJoined(false)} onEnded={() => { setEnded(true); local.getTracks().forEach((t) => t.stop()); }} />;

  const again = a.status === "in_progress" || a.consented;
  return (
    <div className="rbody sc-room">
      <SystemCheck dark attemptId={a.id} role="candidate" mode={again ? "recheck" : "full"} language={info.language}
        onPassed={({ stream }) => setLocal(stream)}
        final={({ stream }) => (
          <div className="rbody" style={{ width: "100%" }}>
            <div className="rmain">
              <div className="q-card col" style={{ gap: 14 }}>
                <div className="row"><Hira size={56} /><div><h2>{info.round}</h2><div className="muted">{info.job}{info.interviewer ? ` · with ${info.interviewer}` : ""}{info.scheduled_at ? ` · ${fmtDate(info.scheduled_at, true)}` : ""}</div></div></div>
                <div className="sc-note good">✓ Every check passed.{again ? " Join again when you're ready." : ""}</div>
                <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                  <li>This is a live video interview with a person from the hiring team.</li>
                  {info.record && <li>The call is <b>recorded</b> (video and sound) so the hiring team can review it. Only the hiring team can watch it, every viewing is logged, and it is deleted after the company's retention period.</li>}
                  <li>It is <b>AI-assisted</b>: {info.captions ? "live captions of what you say are sent to the interviewer's assistant, Isha, which helps them ask good follow-up questions." : "the interviewer uses an assistant to plan questions."} The interviewer makes every decision.</li>
                  {info.watch_focus && <li>Please stay on this tab. Switching tabs or apps{info.integrity?.["integrity.block_paste"] ? ", pasting" : ""}{info.integrity?.["integrity.fullscreen"] ? ", leaving fullscreen" : ""}{info.integrity?.["integrity.face_check"] ? " or someone else appearing on camera" : ""} counts as a warning, and the interviewer sees it at once.</li>}
                </ul>
                {!again && <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />I agree to this interview being {info.record ? "recorded and " : ""}AI-assisted.</label>}
                {!info.can_join && info.opens_at && <Chip kind="warn">You can join from {fmtDate(info.opens_at, true)}</Chip>}
                {!info.can_join && info.opens_at && <JoinCountdown at={info.opens_at} />}
                <div className="row"><Btn kind="primary" size="lg" disabled={(!agree && !again) || !(stream || local) || !info.can_join} onClick={async () => {
                  try { await api.post(`/rounds/${a.id}/consent`, { checks: { system_check: true } }); } catch (e) { setErr(e.message); return; }
                  if (info.integrity?.["integrity.fullscreen"]) await enterFullscreen(); setJoined(true); }}>{again ? "Rejoin interview" : "Join interview"}</Btn>
                  {info.record && !again && <Btn kind="ghost" onClick={async () => { try { await declineRecording(a.id); setDeclined(true); } catch (e) { setErr(e.message); } }}>I don't agree to recording</Btn>}
                  {info.peer_online ? <Chip kind="good">Your interviewer is in the room</Chip> : <span className="small muted">Your interviewer hasn't joined yet. You can wait inside.</span>}</div>
              </div>
            </div>
            <div className="rside">
              <div className="selfview">{(stream || local) && <Video stream={stream || local} muted mirror />}</div>
              <div className="rpanel small">Headphones help: they stop the interviewer's voice echoing into your captions.</div>
            </div>
          </div>
        )} />
    </div>
  );
}

function JoinCountdown({ at }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const left = Math.max(0, new Date(at).getTime() - now);
  if (!left) return null;
  const m = Math.floor(left / 60000), sec = Math.floor((left % 60000) / 1000);
  return <span className="small">The room opens in <b>{m}:{String(sec).padStart(2, "0")}</b>. Test your setup meanwhile.</span>;
}

function InCall({ a, info, local, onLeave, onEnded }) {
  const askConfirm = useConfirm();
  const selfRef = useRef(null);
  const recRef = useRef(null);
  const recFor = useRef(null);
  const [warn, setWarn] = useState("");
  const [fsOut, setFsOut] = useState(false);
  const [chat, setChat] = useState([]);
  const [chatOn, setChatOn] = useState(false);
  const [seen, setSeen] = useState(0);
  const [caption, setCaption] = useState("");
  const [capOn, setCapOn] = useState(false);
  const [fixed, setFixed] = useState(0); // bumps when a stopped camera or microphone is repaired
  const rec = useRef(null);
  const call = useCall({ attId: a.id, role: "candidate", info, local, active: true, onMessage: (m) => {
    if (m.kind === "chat") setChat((c) => [...c, { from: "interviewer", text: m.payload.text }]);
    if (m.kind === "ended" || (m.kind === "bye" && m.payload?.ended)) finish();
  } });
  const finish = async () => { allowFullscreenExit(); await recRef.current?.stop(); recRef.current = null; if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); onEnded(); };
  const running = call.roundStatus === "in_progress";
  // integrity: the same watcher as the AI interview; live calls warn and count, the interviewer decides what to do
  useIntegrity({ attemptId: a.id, cfg: { ...(info.integrity || {}), "integrity.face_check": !!info.integrity?.["integrity.face_check"] }, active: running && info.watch_focus,
    videoRef: selfRef, onResult: (r) => { if (r.counted) { setWarn(r.message); setTimeout(() => setWarn(""), 8000); } } });
  useEffect(() => {
    if (!info.integrity?.["integrity.fullscreen"]) return undefined;
    const f = () => setFsOut(!document.fullscreenElement);
    document.addEventListener("fullscreenchange", f); f();
    return () => document.removeEventListener("fullscreenchange", f);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // the device check the interviewer sees before starting
  const faces = useFaceCount(selfRef, !!info.integrity?.["integrity.face_check"] && !running);
  useEffect(() => {
    if (call.state !== "connected" || running) return undefined;
    const tell = () => call.send("device", { cam: local.getVideoTracks()[0]?.enabled !== false && local.getVideoTracks()[0]?.readyState === "live", mic: local.getAudioTracks()[0]?.enabled !== false && local.getAudioTracks()[0]?.readyState === "live", faces });
    tell();
    const t = setInterval(tell, 5000);
    return () => clearInterval(t);
  }, [call.state, running, faces]); // eslint-disable-line react-hooks/exhaustive-deps
  // backup recording from the candidate's side: their camera large, the interviewer in the corner, both voices
  useEffect(() => {
    if (!info.record || !running || call.state !== "connected" || !call.remote || recFor.current === call.remote) return;
    (async () => {
      if (recRef.current) await recRef.current.stop();
      recRef.current = startRecording({ attId: a.id, video: local, pip: call.remote, audio: [local, call.remote] });
      recFor.current = call.remote;
    })();
  }, [running, call.state, call.remote, fixed]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { recRef.current?.stop(4000); }, []);
  // V02.00.05: the camera or microphone stopped mid-interview: tell the candidate and the interviewer, and repair in place
  const lost = useDeviceWatch(local, true);
  const [fixing, setFixing] = useState(false);
  useEffect(() => { if (lost) call.send("devlost", lost); }, [lost]); // eslint-disable-line react-hooks/exhaustive-deps
  const fix = async () => {
    setFixing(true);
    try {
      await repairStream(local, (kind, t) => call.replaceTrack(kind, t));
      if (recRef.current) { await recRef.current.stop(); recRef.current = null; recFor.current = null; }
      call.send("device", { cam: true, mic: true });
      setFixed((n) => n + 1);
    } catch { setWarn("We still can't reach your camera or microphone. Allow them in the browser bar and press Fix it again."); }
    finally { setFixing(false); }
  };
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
    // F2F-007: Azure Speech when configured (every browser), else the browser's own engine. Words still being spoken go
    // to the interviewer about once a second as "partial", then the finished sentence as "caption".
    let lastPartial = 0;
    (async () => {
      rec.current = await listen({ language: LANG_CODES[info.language] || "en-IN",
        onPartial: (t) => {
          setCaption(t);
          const muted = local.getAudioTracks()[0]?.enabled === false;
          if (!muted && t && Date.now() - lastPartial > 900) { lastPartial = Date.now(); call.send("partial", { text: t }); }
        },
        onSentence: (t) => { setCaption(t); if (local.getAudioTracks()[0]?.enabled !== false) call.send("caption", { text: t }); },
        onError: () => {} });
      if (stop) { rec.current?.stop(); return; }
      const engine = rec.current?.engine || "none";
      setCapOn(engine !== "none");
      call.send("device", { captions: engine });
    })();
    return () => { stop = true; rec.current?.stop(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const mutedSelf = local.getAudioTracks()[0]?.enabled === false;
  return (
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: chatOn ? "1fr 300px" : "1fr", minHeight: 0 }}>
      <div style={{ position: "relative", background: "#000", minHeight: 420 }}>
        {call.remote ? <Video stream={call.remote} style={{ objectFit: "contain" }} /> : (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center", padding: 20 }}>
            <div className="col" style={{ alignItems: "center" }}><Hira size={100} mood="idle" /><h2 style={{ color: "#fff" }}>{call.state === "left" ? "The interviewer stepped out" : call.state === "reconnecting" ? "Reconnecting…" : "Waiting for the interviewer"}</h2>
              <p style={{ opacity: .75 }}>{call.peerOnline ? "Connecting you now…" : call.state === "left" ? "Stay here, they'll be back. You'll be reconnected as soon as they return." : "Stay on this page. You'll be connected as soon as they join."}</p>
              {call.peerAwaySince && Date.now() - call.peerAwaySince > 10 * 60000 && <p style={{ opacity: .9, maxWidth: 460 }}>Your interviewer hasn't come back yet. Keep this page open, or leave and rejoin from your home page while the interview is open.</p>}</div>
          </div>
        )}
        {call.peerMedia.cam === false && call.remote && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: "#0B1026" }}>Interviewer's camera is off</div>}
        <div style={{ position: "absolute", right: 16, top: 16, width: 220, aspectRatio: "4/3", borderRadius: 12, overflow: "hidden", border: "2px solid rgba(255,255,255,.7)" }}><Video stream={sharing || local} muted mirror={!sharing} /></div>
        <video ref={(v) => { selfRef.current = v; if (v && v.srcObject !== local) { v.srcObject = local; v.play().catch(() => {}); } }} muted playsInline style={{ position: "absolute", width: 2, height: 2, opacity: 0, pointerEvents: "none" }} aria-hidden="true" />
        {warn && <div className="warnbar w2" role="alert" style={{ position: "absolute", left: 16, right: 16, top: 60, zIndex: 3 }}><b>!</b>{warn}</div>}
        {fsOut && running && <div className="warnbar w1" role="alert" style={{ position: "absolute", left: 16, right: 16, top: warn ? 110 : 60, zIndex: 3 }}><b>!</b>Please stay in fullscreen during the interview.<button className="btn sm right" onClick={() => enterFullscreen()}>Back to fullscreen</button></div>}
        <div className="row" style={{ position: "absolute", left: 16, top: 16, gap: 6 }}>
          <Chip kind={call.state === "connected" ? "good" : "warn"}>{call.state === "connected" ? "● Connected" : call.state === "reconnecting" ? "Reconnecting" : call.state === "left" ? "Interviewer stepped out" : "Waiting for the interviewer"}</Chip>
          {info.record && <Chip kind="bad">● Recorded</Chip>}
          {capOn && <Chip kind="dark">Captions on</Chip>}
          {sharing && <Chip kind="info">You're sharing your screen</Chip>}
        </div>
        {capOn && caption && !mutedSelf && <div style={{ position: "absolute", left: "50%", transform: "translateX(-50%)", bottom: 92, background: "rgba(0,0,0,.6)", padding: "6px 12px", borderRadius: 8, maxWidth: "70%", fontSize: 14 }}>{caption}</div>}
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 20 }}>
          <CallControls local={local} call={call} canShare={info.screen_share} onScreen={toggleShare} sharing={!!sharing}
            onChat={info.chat ? () => setChatOn(!chatOn) : null} chatOn={chatOn} unread={chatOn ? 0 : Math.max(0, chat.length - seen)}
            onLeave={async () => { if (await askConfirm({ title: "Leave the call?", text: "You can rejoin from your home page while the interview is open.", yes: "Leave", no: "Stay", danger: true })) { await recRef.current?.stop(); recRef.current = null; recFor.current = null; call.hangup(false); onLeave(); } }} />
        </div>
      </div>
      {lost && <div className="devlost" role="alertdialog" aria-label="Device stopped"><div className="devlost-card">
        <h2>Your {lost.cam && lost.mic ? "camera and microphone" : lost.cam ? "camera" : "microphone"} stopped</h2><p>{lostText(lost)}</p>
        <p className="small" style={{ opacity: .8 }}>The interviewer has been told and is waiting.</p>
        <Btn kind="gold" size="lg" busy={fixing} onClick={fix}>Fix it</Btn></div></div>}
      {chatOn && <div style={{ background: "#0B1026", padding: 12, display: "flex", flexDirection: "column", minHeight: 0 }}><b style={{ marginBottom: 8 }}>Chat with the interviewer</b>
        <Chat items={chat} me="candidate" dark onSend={(t) => { call.send("chat", { text: t }); setChat((c) => [...c, { from: "candidate", text: t }]); }} /></div>}
    </div>
  );
}

function Center({ children }) {
  return <div style={{ margin: "auto", maxWidth: 560, textAlign: "center", padding: 24, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>{children}</div>;
}
