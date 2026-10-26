import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Disha, Hira } from "../../components/Mascot";
import ReportView from "../../components/ReportView";
import CandidateCall from "./CandidateCall";
import { useVoices, VoicePreview } from "../../components/Settings";
import { Btn, Chip, Loading, ROUND_LABEL, useToast } from "../../components/ui";
import { enterFullscreen, useIntegrity } from "../../lib/integrity";
import { LANG_CODES, listen, micLevel, speak, stopSpeaking } from "../../lib/speech";

const EVENT_TEXT = { tab_switch: "Switching tabs or apps", fullscreen_exit: "Leaving fullscreen", copy_paste: "Copying or pasting", devtools: "Opening developer tools", multi_face: "Another person on camera", no_face: "Leaving the camera view" };

export default function Room() {
  const { id } = useParams();
  const nav = useNavigate();
  const { me } = useAuth();
  const [a, setA] = useState(null);
  const [err, setErr] = useState("");
  const [banner, setBanner] = useState(null);
  const [cam, setCam] = useState(null);
  const video = useRef();
  const load = () => api.get(`/rounds/${id}`).then(setA).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (video.current && cam) video.current.srcObject = cam; });
  useEffect(() => () => cam?.getTracks().forEach((t) => t.stop()), [cam]);
  // paused: poll until the recruiter lets the candidate continue
  useEffect(() => {
    if (a?.status !== "paused") return;
    const t = setInterval(async () => { const s = await api.get(`/rounds/${id}/status`).catch(() => null); if (s && s.status !== "paused") load(); }, 5000);
    return () => clearInterval(t);
  }, [a?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const cfg = a?.config || {};
  const onIntegrity = (r) => {
    if (!r.counted) return;
    setBanner({ level: r.paused ? 2 : 1, text: r.message });
    if (r.paused) setA((x) => ({ ...x, status: "paused", pause_reason: r.label }));
  };
  const curQ = useRef(0);
  useIntegrity({ attemptId: id, cfg, active: a?.status === "in_progress" && !String(a?.type).startsWith("f2f") && (!a?.practice || !!cfg.skill_check), questionIndex: curQ.current, onResult: onIntegrity, videoRef: video });

  if (err) return <div className="room"><div style={{ margin: "auto", textAlign: "center" }}><Hira size={90} /><h2 style={{ color: "#fff" }}>{err}</h2><Btn onClick={() => nav(me?.home || "/")}>Go back</Btn></div></div>;
  if (!a) return <div className="room"><Loading text="Opening your room…" /></div>;

  const finished = (outcome) => {
    document.fullscreenElement && document.exitFullscreen().catch(() => {});
    if (typeof outcome === "string" && outcome.startsWith("next_section:")) { nav(`/room/${outcome.split(":")[1]}`); return; }
    load().then(() => setA((x) => ({ ...x, outcome })));
  };

  return (
    <div className="room">
      <div className="rtop">
        <span className="logo" style={{ color: "#fff" }}>Code<b style={{ color: "var(--gold)" }}>2</b>Hire</span>
        <div className="col" style={{ gap: 0 }}><b>{a.name}</b><span className="tiny" style={{ opacity: .7 }}>{a.job}{a.company ? " · " + a.company : ""}{a.practice ? " · practice, private to you" : ""}</span></div>
        <div className="right row">
          {a.status === "in_progress" && !String(a.type).startsWith("f2f") && (!a.practice || cfg.skill_check) && <Chip kind={a.warnings ? "warn" : "good"}>Warnings {a.warnings} of {a.warnings_allowed}</Chip>}
          <Chip kind="dark">{ROUND_LABEL[a.type]}</Chip>
        </div>
      </div>
      {banner && a.status === "in_progress" && <div className={"warnbar w" + banner.level} role="alert"><b>!</b>{banner.text}. Please stay on this screen until you finish.<button className="btn sm ghost right" style={{ color: "inherit" }} onClick={() => setBanner(null)}>OK</button></div>}
      {["completed", "reviewed", "expired"].includes(a.status) ? <Done a={a} nav={nav} home={me?.home} />
        : String(a.type).startsWith("f2f") ? <CandidateCall a={a} nav={nav} home={me?.home || "/me"} />
        : a.status === "paused" ? <Paused a={a} />
        : !a.consented || a.status !== "in_progress" ? <Checks a={a} cfg={cfg} cam={cam} setCam={setCam} video={video} onStart={async (voice) => {
          await api.post(`/rounds/${id}/consent`, { voice, checks: { camera: !!cam } });
          if (cfg["integrity.fullscreen"] && (!a.practice || cfg.skill_check)) await enterFullscreen();
          setA(await api.post(`/rounds/${id}/start`));
        }} />
        : a.type === "mcq" ? <Mcq a={a} cam={cam} video={video} onQ={(i) => (curQ.current = i)} onDone={finished} />
        : <Voice a={a} cam={cam} video={video} onDone={finished} />}
    </div>
  );
}

function Rules({ a, cfg }) {
  const rules = [];
  if (a.type === "mcq") rules.push(`${cfg["mcq.questions"]} questions in ${cfg["mcq.minutes"]} minutes.${cfg["mcq.negative_marking"] ? " Wrong answers lose a quarter mark." : ""} You can flag questions and come back.`);
  else rules.push(`About ${cfg["interview.questions"]} questions in ${cfg["interview.minutes"]} minutes. Hira listens and may ask a follow-up. Speak naturally; there are no trick questions.`);
  if (!a.practice || cfg.skill_check) {
    if (cfg["integrity.fullscreen"]) rules.push("Stay in fullscreen and on this tab.");
    if (cfg["integrity.face_check"]) rules.push("Keep your face in the camera view, and be the only person in it.");
    if (cfg["integrity.block_paste"]) rules.push("Copying and pasting are switched off.");
    rules.push(`You get ${cfg["integrity.warnings_allowed"]} warnings that explain what happened. After that the round pauses until the recruiter checks. A dropped connection never counts.`);
    rules.push("This round is recorded and AI-assisted. A person reviews the result and makes every decision.");
  }
  return <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>{rules.map((r, i) => <li key={i}>{r}</li>)}</ul>;
}

function Checks({ a, cfg, cam, setCam, video, onStart }) {
  const [level, setLevel] = useState(0);
  const proctored = !a.practice || !!cfg.skill_check;
  const [agree, setAgree] = useState(!proctored);
  const [voice, setVoice] = useState(a.voice || cfg["voice.name"]);
  const [busy, setBusy] = useState(false);
  const [camErr, setCamErr] = useState("");
  const voices = useVoices();
  const isVoice = a.type === "ai_interview";
  const needCam = proctored && (cfg["integrity.face_check"] || isVoice);
  const allowed = (cfg["voice.allowed"] || []);
  const vlist = (voices?.voices || []).filter((v) => !allowed.length || allowed.includes(v.name));
  const turnOn = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: isVoice });
      setCam(s); setCamErr("");
      if (isVoice) micLevel(s, setLevel);
    } catch { setCamErr("We couldn't reach your camera or microphone. Allow access in the browser bar and try again."); }
  };
  const ready = agree && (!needCam || cam);
  return (
    <div className="rbody">
      <div className="rmain">
        <div className="q-card col" style={{ gap: 16 }}>
          <div className="row">{a.practice ? <Disha size={56} /> : <Hira size={56} />}<div><h2>Before you start</h2><div className="muted">{a.started_at ? "Welcome back. Your progress is saved." : "Two minutes of checks, then you're in."}</div></div></div>
          <Rules a={a} cfg={cfg} />
          {isVoice && cfg["voice.candidate_can_choose"] !== false && vlist.length > 0 && (
            <div className="col"><b>Choose Hira's voice</b>
              <div className="grid g2">{vlist.map((v) => (
                <label key={v.name} className="opt" style={{ alignItems: "center" }}>
                  <input type="radio" name="voice" checked={voice === v.name} onChange={() => setVoice(v.name)} />
                  <div className="grow"><b>{v.label}</b><div className="small muted">{v.gender} · {v.style || v.locale}</div></div>
                  <VoicePreview voice={v.name} rate={cfg["voice.rate"]} />
                </label>))}</div>
            </div>
          )}
          {proctored && <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />I understand the rules and agree to this round being recorded and AI-assisted.</label>}
          <div className="row"><Btn kind="primary" size="lg" busy={busy} disabled={!ready} onClick={async () => { setBusy(true); try { await onStart(voice); } catch (e) { alert(e.message); } finally { setBusy(false); } }}>{a.started_at ? "Continue" : "Start"}</Btn>
            {!ready && <span className="small muted">{needCam && !cam ? "Turn on your camera first." : "Tick the box to continue."}</span>}</div>
        </div>
      </div>
      <div className="rside">
        <div className="selfview">{cam ? <video ref={video} autoPlay playsInline muted /> : <div style={{ display: "grid", placeItems: "center", height: "100%", padding: 16, textAlign: "center" }}><Btn kind="gold" onClick={turnOn}>Turn on camera{isVoice ? " and mic" : ""}</Btn></div>}</div>
        {camErr && <div className="small" style={{ color: "#FFB4B4" }}>{camErr}</div>}
        {isVoice && cam && <div className="rpanel col"><b className="small">Say something</b><div className="levels">{Array.from({ length: 18 }).map((_, i) => <i key={i} style={{ height: Math.max(3, Math.min(28, level * 40 * (0.5 + Math.abs(Math.sin(i))))) }} />)}</div><span className="tiny" style={{ opacity: .7 }}>{level > .15 ? "We can hear you." : "Waiting for sound…"}</span></div>}
        <div className="rpanel small">Use Chrome or Edge on a laptop for the best experience. Close other apps that use the camera.</div>
      </div>
    </div>
  );
}

function useCountdown(a, minutesKey, onEnd) {
  const total = (a.config?.[minutesKey] || 0) * 60;
  const startedAt = a.started_at ? new Date(a.started_at).getTime() : Date.now();
  const [left, setLeft] = useState(() => Math.max(0, total - Math.floor((Date.now() - startedAt) / 1000)));
  const fired = useRef(false);
  useEffect(() => {
    if (!total) return;
    const t = setInterval(() => {
      const l = Math.max(0, total - Math.floor((Date.now() - startedAt) / 1000));
      setLeft(l);
      if (l === 0 && !fired.current) { fired.current = true; onEnd(); }
    }, 1000);
    return () => clearInterval(t);
  }, [total, startedAt]); // eslint-disable-line react-hooks/exhaustive-deps
  return total ? `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}` : null;
}

function Mcq({ a, cam, video, onQ, onDone }) {
  const toast = useToast();
  const qs = a.questions || [];
  const [i, setI] = useState(0);
  const [ans, setAns] = useState(a.answers || {});
  const [flag, setFlag] = useState(new Set(a.flagged || []));
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const submit = async (reason = "submitted") => {
    setBusy(true);
    try { const r = await api.post(`/rounds/${a.id}/submit`, { reason }); onDone(r.outcome); }
    catch (e) { toast(e.message, "bad"); setBusy(false); }
  };
  const timer = useCountdown(a, "mcq.minutes", () => { toast("Time's up. Submitting your answers."); submit("time"); });
  useEffect(() => { onQ(i); }, [i]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = qs[i];
  const choose = (k) => { setAns({ ...ans, [q.id]: k }); api.post(`/rounds/${a.id}/answer`, { qid: q.id, choice: k }).catch((e) => toast(e.message, "bad")); };
  const toggleFlag = () => { const f = new Set(flag); const on = !f.has(q.id); on ? f.add(q.id) : f.delete(q.id); setFlag(f); api.post(`/rounds/${a.id}/answer`, { qid: q.id, flagged: on }); };
  useEffect(() => {
    const k = (e) => { if (e.target.tagName === "INPUT") return; const n = "1234".indexOf(e.key); if (n >= 0 && q?.options[n] !== undefined) choose(n); if (e.key === "ArrowRight") setI(Math.min(qs.length - 1, i + 1)); if (e.key === "ArrowLeft") setI(Math.max(0, i - 1)); };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  });
  if (!q) return <Loading />;
  const answered = Object.keys(ans).length;
  return (
    <div className="rbody">
      <div className="rmain">
        <div className="q-card col" style={{ gap: 14 }}>
          <div className="row"><Chip kind="brand">Question {i + 1} of {qs.length}</Chip><Chip>{q.skill} · L{q.level}</Chip>
            <Btn size="sm" kind={flag.has(q.id) ? "gold" : "ghost"} className="right" onClick={toggleFlag}>{flag.has(q.id) ? "★ Flagged" : "☆ Flag for review"}</Btn></div>
          <h2 style={{ fontSize: 20, lineHeight: 1.4 }}>{q.text}</h2>
          {q.code && <pre className="code">{q.code}</pre>}
          <div className="col">{q.options.map((o, k) => <button key={k} className={"opt" + (ans[q.id] === k ? " on" : "")} onClick={() => choose(k)}><span className="k">{String.fromCharCode(65 + k)}</span><span>{o}</span></button>)}</div>
          <div className="row"><Btn disabled={i === 0} onClick={() => setI(i - 1)}>← Previous</Btn>
            {i < qs.length - 1 ? <Btn kind="primary" className="right" onClick={() => setI(i + 1)}>Next →</Btn> : <Btn kind="primary" className="right" onClick={() => setConfirm(true)}>Review and submit</Btn>}</div>
          <span className="tiny muted">Keys 1–4 choose an answer, arrows move between questions. Answers save as you go.</span>
        </div>
      </div>
      <div className="rside">
        {timer && <div className="rpanel" style={{ textAlign: "center" }}><div className="tiny" style={{ opacity: .7 }}>Time left</div><div style={{ fontSize: 30, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>{timer}</div></div>}
        <div className="selfview" style={{ aspectRatio: "16/10" }}>{cam ? <video ref={video} autoPlay playsInline muted /> : <div className="tiny" style={{ padding: 10, opacity: .6 }}>Camera off</div>}</div>
        <div className="rpanel col"><div className="row small"><b>{answered} of {qs.length} answered</b><span className="right">{flag.size} flagged</span></div>
          <div className="qnav">{qs.map((x, k) => <button key={x.id} className={(ans[x.id] !== undefined ? "ans " : "") + (k === i ? "cur " : "") + (flag.has(x.id) ? "flag" : "")} onClick={() => setI(k)} aria-label={`Question ${k + 1}`}>{k + 1}</button>)}</div></div>
        <Btn kind="gold" onClick={() => setConfirm(true)}>Submit</Btn>
      </div>
      {confirm && <div className="modal-bg"><div className="modal" style={{ color: "var(--ink)" }}><div className="modal-b">
        <h3>Submit your answers?</h3>
        <p>{answered} of {qs.length} answered{flag.size ? `, ${flag.size} flagged for review` : ""}. You can't change answers after submitting.</p>
        <div className="row"><Btn onClick={() => setConfirm(false)}>Keep working</Btn><Btn kind="primary" busy={busy} className="right" onClick={() => submit()}>Submit</Btn></div></div></div></div>}
    </div>
  );
}

function Voice({ a, cam, video, onDone }) {
  const toast = useToast();
  const cfg = a.config || {};
  const [cur, setCur] = useState(a.current);
  const [progress, setProgress] = useState(a.progress || { done: 0, total: cfg["interview.questions"] });
  const [phase, setPhase] = useState("idle"); // speaking | listening | thinking | idle
  const [answer, setAnswer] = useState("");
  const [partial, setPartial] = useState("");
  const [typeMode, setTypeMode] = useState(cfg["voice.enabled"] === false);
  const [silentFor, setSilentFor] = useState(0);
  const rec = useRef(null);
  const lastSpeech = useRef(Date.now());
  const voice = a.voice || cfg["voice.name"];
  const rate = cfg["voice.rate"];
  const lang = LANG_CODES[cfg["ai.language"]] || (voice || "en-IN").split("-").slice(0, 2).join("-");

  const stopRec = async () => { if (rec.current) { await rec.current.stop(); rec.current = null; } };
  const ask = async (q) => {
    await stopRec();
    setAnswer(""); setPartial("");
    if (!typeMode) { setPhase("speaking"); await speak(q.q, { voice, rate }); }
    setPhase("listening"); lastSpeech.current = Date.now();
    if (!typeMode) {
      rec.current = await listen({ language: lang, onPartial: (t) => { setPartial(t); lastSpeech.current = Date.now(); },
        onSentence: (t) => { setAnswer((x) => (x ? x + " " : "") + t); setPartial(""); lastSpeech.current = Date.now(); },
        onError: (m) => { toast(m); if (/can't recognise|Type/.test(m)) setTypeMode(true); } });
    }
  };
  useEffect(() => { if (cur) ask(cur); return () => { stopRec(); stopSpeaking(); }; }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setInterval(() => setSilentFor(Math.floor((Date.now() - lastSpeech.current) / 1000)), 1000); return () => clearInterval(t); }, []);

  const send = async (skip = false) => {
    await stopRec(); stopSpeaking();
    setPhase("thinking");
    try {
      const r = await api.post(`/rounds/${a.id}/turn`, { answer: (answer + " " + partial).trim(), skip });
      if (r.done) { onDone(r.outcome); return; }
      setProgress(r.progress); setCur(r.next); ask(r.next);
    } catch (e) { toast(e.message, "bad"); setPhase("listening"); }
  };
  const finishEarly = async () => { if (!confirm("End the interview now? Your answers so far will be scored.")) return; await stopRec(); const r = await api.post(`/rounds/${a.id}/finish`, { reason: "ended_early" }); onDone(r.outcome); };
  const timer = useCountdown(a, "interview.minutes", () => { toast("Time's up. Hira is wrapping up."); send(); });
  const silence = cfg["voice.silence_seconds"] || 6;
  const said = (answer + " " + partial).trim();

  return (
    <div className="rbody">
      <div className="rmain" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 }}>
        <div className="row" style={{ alignSelf: "stretch" }}><Chip kind="brand">Question {Math.min(progress.done + 1, progress.total)} of {progress.total}</Chip>{cur?.kind === "followup" && <Chip kind="gold">Follow-up</Chip>}{cur?.topic && <Chip>{cur.topic}</Chip>}</div>
        <div className={"orb " + (phase === "speaking" ? "speaking" : phase === "listening" ? "listening" : "")}><Hira size={120} mood={phase === "speaking" ? "talk" : phase === "thinking" ? "think" : "idle"} /></div>
        <div className="tiny" style={{ opacity: .7 }}>{phase === "speaking" ? "Hira is asking…" : phase === "listening" ? (typeMode ? "Type your answer" : "Listening. Take your time.") : phase === "thinking" ? "Hira is thinking…" : ""}</div>
        <div className="q-card" style={{ width: "100%" }}>
          <h2 style={{ fontSize: 20, lineHeight: 1.45 }}>{cur?.q}</h2>
          <div className="row" style={{ marginTop: 8 }}><Btn size="sm" kind="ghost" onClick={() => speak(cur.q, { voice, rate })}>🔁 Repeat question</Btn>
            <Btn size="sm" kind="ghost" onClick={() => { setTypeMode(!typeMode); stopRec(); if (typeMode) ask(cur); }}>{typeMode ? "🎙 Answer by voice" : "⌨ Type instead"}</Btn></div>
        </div>
        <div className="q-card col" style={{ width: "100%", gap: 10 }}>
          <b className="small muted">YOUR ANSWER</b>
          {typeMode ? <textarea className="textarea" data-allow-paste="0" style={{ minHeight: 140 }} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Type your answer…" />
            : <div style={{ minHeight: 90, fontSize: 16 }}>{answer}<span style={{ opacity: .5 }}> {partial}</span>{!said && <span className="muted">Start speaking. Your words appear here.</span>}</div>}
          {!typeMode && said && silentFor >= silence && phase === "listening" && <div className="chip gold" style={{ alignSelf: "flex-start" }}>Finished? Press “Done answering”, or keep talking.</div>}
          <div className="row"><Btn kind="ghost" onClick={() => send(true)} disabled={phase === "thinking"}>Skip question</Btn>
            <Btn kind="primary" size="lg" className="right" busy={phase === "thinking"} disabled={phase === "speaking"} onClick={() => send(false)}>Done answering →</Btn></div>
        </div>
      </div>
      <div className="rside">
        {timer && <div className="rpanel" style={{ textAlign: "center" }}><div className="tiny" style={{ opacity: .7 }}>Time left</div><div style={{ fontSize: 30, fontWeight: 800 }}>{timer}</div></div>}
        <div className="selfview">{cam ? <video ref={video} autoPlay playsInline muted /> : <div className="tiny" style={{ padding: 10, opacity: .6 }}>Camera off</div>}</div>
        <div className="rpanel small col"><b>Tips</b><span>Use a real example: what happened, what you did, why, and the result.</span><span>It's fine to pause and think. Hira waits.</span></div>
        <Btn kind="ghost" style={{ color: "#fff" }} onClick={finishEarly}>End interview early</Btn>
      </div>
    </div>
  );
}

function Paused({ a }) {
  return (
    <div style={{ margin: "auto", maxWidth: 520, textAlign: "center", padding: 24 }} className="col">
      <div style={{ margin: "0 auto" }}><Hira size={110} mood="think" /></div>
      <h2 style={{ color: "#fff" }}>Your round is paused</h2>
      <p style={{ opacity: .8 }}>Reason: {a.pause_reason}. The recruiter has been told and will check. Your answers so far are saved. Keep this page open; it continues automatically when they let you.</p>
      <span className="spin" style={{ margin: "0 auto" }} />
    </div>
  );
}

function Done({ a, nav, home }) {
  return (
    <div style={{ margin: "auto", maxWidth: 820, padding: 24, width: "100%" }} className="col">
      <div style={{ textAlign: "center" }} className="col">
        <div style={{ margin: "0 auto" }}>{a.practice ? <Disha size={110} mood="happy" /> : <Hira size={110} mood="happy" />}</div>
        <h2 style={{ color: "#fff" }}>{a.status === "expired" ? "This link has expired" : a.outcome === "badge" ? "You earned a verified badge!" : a.outcome === "not_yet" ? "Not this time" : a.outcome === "certified" ? "You're certified!" : "Thank you. You're done."}</h2>
        <p style={{ opacity: .8 }}>{a.status === "expired" ? "Ask the recruiter to send a new invite." : a.practice ? (a.outcome === "not_yet" ? "You need 70% for the badge. Try a learning path, then take it again." : "Here's your private feedback.") : "Your answers are with the hiring team. A person reviews every result, and you'll hear back in your inbox."}</p>
        {a.practice && a.score != null && <div style={{ fontSize: 34, fontWeight: 900, color: "var(--gold)" }}>{a.type === "mcq" ? a.score + "%" : a.score + " / 5"}</div>}
      </div>
      {a.practice_report && a.type === "ai_interview" && <div style={{ background: "#fff", color: "var(--ink)", borderRadius: 16, padding: 16 }}><ReportView r={{ sections: a.practice_report, overall: a.score, round: a.name, type: a.type, version: 1, scale: 5, candidate: { name: "You" }, job: { title: "Practice" } }} /></div>}
      <div className="row" style={{ justifyContent: "center" }}><Btn kind="gold" onClick={() => nav(home || "/me")}>Back to home</Btn>{a.practice && <Btn onClick={() => nav("/me/learning")}>Open learning paths</Btn>}</div>
    </div>
  );
}
