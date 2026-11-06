// The system check before every interview (V02.00.05), for candidates and, shorter, for interviewers.
//
// One step at a time: device, browser, permissions, camera, face, microphone, speaker, a test recording, fullscreen,
// internet and the room checklist. Every step except the internet test must pass before the round can start; the
// server checks the result again and refuses consent without it. "I need help" tells the recruiter which step failed.
import { useEffect, useRef, useState } from "react";
import { api, download } from "../api";
import { enterFullscreen, useFaceCount } from "../lib/integrity";
import { recordingType, setUploadSpeed } from "../lib/recorder";
import { listen, micLevel, LANG_CODES } from "../lib/speech";
import { Btn, Chip, Loading, Select, Textarea, fmtDate, useToast } from "./ui";

// ---------------------------------------------------------------- device and browser

export function isMobileDevice() {
  const ua = navigator.userAgent || "";
  if (/Mobi|Android|iPhone|iPad|iPod|Windows Phone|webOS|BlackBerry|Opera Mini|IEMobile/i.test(ua)) return true;
  return /Macintosh/.test(ua) && navigator.maxTouchPoints > 1; // iPadOS says it is a Mac
}

export function browserInfo() {
  const ua = navigator.userAgent || "";
  const num = (re) => parseInt((ua.match(re) || [])[1] || "0", 10);
  let name = "Unknown browser", version = 0, ok = false;
  if (/Edg\//.test(ua)) { name = "Microsoft Edge"; version = num(/Edg\/(\d+)/); ok = version >= 100; }
  else if (/OPR\//.test(ua)) { name = "Opera"; version = num(/OPR\/(\d+)/); ok = version >= 86; }
  else if (/Firefox\//.test(ua)) { name = "Firefox"; version = num(/Firefox\/(\d+)/); ok = false; }
  else if (/Chrome\//.test(ua)) { name = "Google Chrome"; version = num(/Chrome\/(\d+)/); ok = version >= 100; }
  else if (/Safari\//.test(ua) && /Version\//.test(ua)) { name = "Safari"; version = num(/Version\/(\d+)/); ok = version >= 15; }
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS X|Macintosh/.test(ua) ? "macOS" : /CrOS/.test(ua) ? "ChromeOS" : /Linux/.test(ua) ? "Linux" : "Other";
  return { name, version, ok, os };
}

const PERMISSION_HELP = {
  chrome: "Click the camera icon at the right of the address bar, choose “Always allow”, then press Try again.",
  edge: "Click the camera icon at the right of the address bar, choose “Always allow”, then press Try again.",
  safari: "Open the Safari menu → Settings for this website, set Camera and Microphone to Allow, then press Try again.",
  other: "Allow the camera and microphone for this site in your browser's settings, then press Try again.",
};
const helpFor = (b) => PERMISSION_HELP[/Edge/.test(b.name) ? "edge" : /Chrome|Opera/.test(b.name) ? "chrome" : /Safari/.test(b.name) ? "safari" : "other"];

const PHRASE = "I am ready for my interview today";
const words = (t) => (t || "").toLowerCase().replace(/[^a-zऀ-෿\s]/g, " ").split(/\s+/).filter((w) => w.length > 1);

async function getStream(n, cam, mic) {
  return navigator.mediaDevices.getUserMedia({
    video: n.camera ? { deviceId: cam ? { exact: cam } : undefined, width: { ideal: 1280 }, height: { ideal: 720 } } : false,
    audio: n.mic ? { deviceId: mic ? { exact: mic } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true } : false,
  });
}

/** Phones and tablets: a full stop, with a way to get the link onto a laptop. */
export function UseLaptop({ message }) {
  const toast = useToast();
  const url = window.location.href;
  return (
    <div className="sc-block" role="alert">
      <div className="sc-big">💻</div>
      <h2>Please join from a laptop or desktop</h2>
      <p>{message || "Interviews on Code2Hire can't be taken on a phone or tablet, because the camera, microphone and screen checks need a computer."}</p>
      <div className="linkbox"><code>{url}</code></div>
      <div className="row wrap" style={{ justifyContent: "center", gap: 8 }}>
        <Btn kind="primary" onClick={async () => { try { await navigator.clipboard.writeText(url); toast("Link copied. Open it on your laptop.", "good"); } catch { toast("Select the link and copy it.", "bad"); } }}>Copy link</Btn>
        {navigator.share && <Btn onClick={() => navigator.share({ title: "My Code2Hire interview", text: "Open this on my laptop", url }).catch(() => {})}>Send me the link</Btn>}
      </div>
      <p className="tiny" style={{ opacity: .75 }}>Send it to yourself (for example by chat), then open it on a laptop or desktop with Chrome or Edge. You can also sign in on the laptop and open the round from your home page.</p>
    </div>
  );
}

// ---------------------------------------------------------------- the check

/**
 * props:
 *   attemptId   the round (empty for "Test my setup")
 *   role        "candidate" | "interviewer"
 *   mode        "full" | "recheck" (rejoining: devices only)
 *   language    for the speech test
 *   onPassed({ stream, result })  every blocking step passed and the server agreed
 *   final       what to show once passed (the Start / Join panel); gets { stream }
 *   dark        dark room styling
 */
export default function SystemCheck({ attemptId, role = "candidate", mode = "full", language = "English", onPassed, final, dark }) {
  const toast = useToast();
  const [req, setReq] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [read, setRead] = useState(false);
  const [readDone, setReadDone] = useState(false);
  const [i, setI] = useState(0);
  const [res, setRes] = useState({});
  const [stream, setStream] = useState(null);
  const [devs, setDevs] = useState({ cam: "", mic: "", spk: "" });
  const [info, setInfo] = useState({});
  const [saving, setSaving] = useState(false);
  const [passed, setPassed] = useState(null);
  const [help, setHelp] = useState(null);
  const streamRef = useRef(null);
  const handed = useRef(false); // once passed, the stream belongs to the room
  streamRef.current = stream;
  useEffect(() => () => { if (!handed.current) streamRef.current?.getTracks().forEach((t) => t.stop()); }, []);

  useEffect(() => {
    api.get("/syscheck/requirements", { attempt: attemptId || undefined, role, mode }).then((r) => {
      setReq(r);
      if (r.instructions?.read_at || role !== "candidate" || mode === "recheck" || !r.instructions) setReadDone(true);
      setRead(!!r.instructions?.read_at);
    }).catch((e) => setLoadErr(e.message));
  }, [attemptId, role, mode]);

  if (loadErr) return <div className="sc-block"><h2>{loadErr}</h2></div>;
  if (!req) return <Loading text="Getting the system check ready…" />;
  const steps = req.steps;
  const n = req.needs || {};
  if (isMobileDevice() || req.mobile) return <UseLaptop message={req.mobile_message} />;

  if (!readDone && req.instructions) {
    return <Instructions ins={req.instructions} attemptId={attemptId} read={read} setRead={setRead} onNext={() => setReadDone(true)} dark={dark} />;
  }

  const step = steps[i];
  const set = (key, status, detail = "") => setRes((r) => ({ ...r, [key]: { status, detail } }));
  const next = () => setI((x) => Math.min(steps.length, x + 1));
  const ok = (k) => res[k]?.status === "pass" || (res[k]?.status === "warn" && !steps.find((s) => s.key === k)?.blocking);
  const allDone = steps.every((s) => ok(s.key));

  const finish = async () => {
    setSaving(true);
    try {
      const b = browserInfo();
      const r = await api.post("/syscheck", { attempt_id: attemptId || undefined, role, mode, steps: res, instructions_read: read,
        device: { browser: `${b.name} ${b.version}`, os: b.os, ...info } });
      if (r.passed) { handed.current = true; setPassed(r); onPassed?.({ stream, result: r }); }
      else toast(`These steps still need to pass: ${r.failed.join(", ")}.`, "bad");
    } catch (e) { toast(e.message, "bad"); } finally { setSaving(false); }
  };

  const askHelp = async (note) => {
    try {
      const r = await api.post("/syscheck/help", { attempt_id: attemptId || undefined, role, step: step?.key, note, steps: res });
      setHelp({ sent: true, text: r.message });
    } catch (e) { toast(e.message, "bad"); }
  };

  if (passed && final) return final({ stream, result: passed });

  const ctx = { n, stream, setStream, devs, setDevs, set, next, info, setInfo, language, role, mode, attemptId, dark };
  return (
    <div className={"sc " + (dark ? "dark" : "")}>
      <ol className="sc-steps" aria-label="System check steps">
        {steps.map((s, k) => {
          const st = res[s.key]?.status;
          return (
            <li key={s.key} className={(k === i ? "on " : "") + (st || "")}>
              <button type="button" disabled={k > i && !steps.slice(0, k).every((x) => ok(x.key))} onClick={() => setI(k)}>
                <span className="sc-dot" aria-hidden="true">{st === "pass" ? "✓" : st === "warn" ? "!" : st === "fail" ? "✕" : k + 1}</span>
                <span className="grow">{s.label}{!s.blocking && <span className="tiny muted"> · warning only</span>}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="sc-main">
        {req.guide && <details className="sc-note"><summary className="b">How the live interview room works</summary>
          {req.guide.map((g) => <div key={g.heading} style={{ marginTop: 6 }}><b className="small">{g.heading}</b><ul style={{ margin: "2px 0 0", paddingLeft: 18 }}>{g.items.map((t, k) => <li key={k} className="small">{t}</li>)}</ul></div>)}
        </details>}
        {req.instructions?.scheduled_at && new Date(req.instructions.scheduled_at) > new Date() && <Countdown at={req.instructions.scheduled_at} />}
        {step ? (
          <div className="sc-card" key={step.key}>
            <div className="row"><h3 className="grow">{i + 1}. {step.label}</h3>{res[step.key] && <Chip kind={res[step.key].status === "pass" ? "good" : res[step.key].status === "warn" ? "warn" : "bad"}>{res[step.key].status === "pass" ? "Passed" : res[step.key].status === "warn" ? "Warning" : "Not passed"}</Chip>}</div>
            <p className="small muted" style={{ margin: 0 }}>{step.about}</p>
            <StepBody k={step.key} ctx={ctx} />
            <div className="row wrap sc-actions">
              {ok(step.key) ? <Btn kind="primary" onClick={next}>{i === steps.length - 1 ? "Finish" : "Next"}</Btn> : <span className="small muted">{step.blocking ? "This step must pass to continue." : ""}</span>}
              {res[step.key]?.status === "fail" && step.key !== "device" && role === "candidate" && attemptId && !help && <Btn kind="ghost" onClick={() => setHelp({ open: true })}>I need help</Btn>}
            </div>
            {help?.open && !help.sent && <HelpForm onSend={askHelp} onCancel={() => setHelp(null)} />}
            {help?.sent && <div className="sc-note good" role="status">{help.text}</div>}
          </div>
        ) : (
          <div className="sc-card">
            <h3>{allDone ? "All checks passed" : "Some checks haven't passed"}</h3>
            <ul className="sc-sum">{steps.map((s) => <li key={s.key}><span className={"sc-dot " + (res[s.key]?.status || "")}>{res[s.key]?.status === "pass" ? "✓" : res[s.key]?.status === "warn" ? "!" : "✕"}</span>{s.label}{res[s.key]?.detail ? <span className="muted"> · {res[s.key].detail}</span> : null}</li>)}</ul>
            {res.internet?.status === "warn" && <div className="sc-note warn">Your internet is weak, so the video will be recorded at a lower quality. Close other apps and downloads if you can.</div>}
            <div className="row"><Btn kind="primary" size="lg" busy={saving} disabled={!allDone} onClick={finish}>{role === "interviewer" ? "Done: join the call" : "Continue"}</Btn>
              {!allDone && <Btn onClick={() => setI(steps.findIndex((s) => !ok(s.key)))}>Go to the step that failed</Btn>}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function Countdown({ at }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const left = Math.max(0, new Date(at).getTime() - now);
  if (!left) return null;
  const h = Math.floor(left / 3600000), m = Math.floor((left % 3600000) / 60000), s = Math.floor((left % 60000) / 1000);
  return <div className="sc-note info" role="status">Your round starts in <b>{h ? `${h} h ` : ""}{String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}</b> ({fmtDate(at, true)}). Test your setup meanwhile.</div>;
}

function HelpForm({ onSend, onCancel }) {
  const [t, setT] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="sc-note col" style={{ gap: 6 }}>
      <b className="small">Tell the hiring team what's wrong (optional)</b>
      <Textarea value={t} maxLength={500} onChange={(e) => setT(e.target.value)} placeholder="e.g. My laptop has no camera" style={{ minHeight: 60 }} />
      <div className="row"><Btn kind="primary" size="sm" busy={busy} onClick={async () => { setBusy(true); await onSend(t); setBusy(false); }}>Send to the hiring team</Btn><Btn size="sm" kind="ghost" onClick={onCancel}>Cancel</Btn></div>
      <span className="tiny muted">Your invite stays valid. You can come back and try again any time.</span>
    </div>
  );
}

export function Instructions({ ins, attemptId, read, setRead, onNext, dark, compact }) {
  const toast = useToast();
  return (
    <div className={"sc-ins " + (dark ? "dark" : "")}>
      <h2 style={{ marginTop: 0 }}>Before your round: {ins.title}</h2>
      <div className="small muted">{ins.job} · {ins.kind}{ins.minutes ? ` · about ${ins.minutes} minutes` : ""}{ins.scheduled_at ? ` · ${fmtDate(ins.scheduled_at, true)}` : ""}</div>
      {ins.sections.map((s) => (
        <section key={s.heading}><h4>{s.heading}</h4><ul>{s.items.map((t, k) => <li key={k}>{t}</li>)}</ul></section>
      ))}
      {ins.extra && <section><h4>From the hiring team</h4><p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ins.extra}</p></section>}
      {!compact && <>
        <label className="check"><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />I've read the instructions</label>
        <div className="row wrap">
          <Btn kind="primary" size="lg" disabled={!read} onClick={onNext}>Start the system check</Btn>
          {attemptId && <Btn kind="ghost" onClick={() => download(`/syscheck/instructions/${attemptId}/pdf`, "Code2Hire-instructions.pdf").catch((e) => toast(e.message, "bad"))}>Download PDF</Btn>}
        </div>
      </>}
    </div>
  );
}

// ---------------------------------------------------------------- steps

function StepBody({ k, ctx }) {
  if (k === "device") return <DeviceStep ctx={ctx} />;
  if (k === "browser") return <BrowserStep ctx={ctx} />;
  if (k === "permissions") return <PermissionStep ctx={ctx} />;
  if (k === "camera") return <CameraStep ctx={ctx} />;
  if (k === "face") return <FaceStep ctx={ctx} />;
  if (k === "mic") return <MicStep ctx={ctx} />;
  if (k === "speaker") return <SpeakerStep ctx={ctx} />;
  if (k === "recording") return <RecordingStep ctx={ctx} />;
  if (k === "fullscreen") return <FullscreenStep ctx={ctx} />;
  if (k === "internet") return <InternetStep ctx={ctx} />;
  if (k === "room") return <RoomStep ctx={ctx} />;
  return null;
}

function DeviceStep({ ctx }) {
  useEffect(() => { if (isMobileDevice()) ctx.set("device", "fail", "Phone or tablet"); else { ctx.set("device", "pass", browserInfo().os); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="sc-note good">✓ You're on a computer ({browserInfo().os}).</div>;
}

function BrowserStep({ ctx }) {
  const b = browserInfo();
  const needRec = ctx.n.recording, live = ctx.role === "interviewer" || (ctx.n.speaker && ctx.n.camera);
  const missing = [];
  if ((ctx.n.camera || ctx.n.mic) && !navigator.mediaDevices?.getUserMedia) missing.push("camera access");
  if (needRec && !recordingType()) missing.push("video recording");
  if (live && !window.RTCPeerConnection) missing.push("video calls");
  const good = b.ok && !missing.length;
  useEffect(() => { ctx.set("browser", good ? "pass" : "fail", `${b.name} ${b.version || ""}`.trim()); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return good ? <div className="sc-note good">✓ {b.name} {b.version} works.</div>
    : <div className="sc-note bad">{b.name === "Firefox" ? "Firefox can't run every part of the interview." : !b.ok ? `${b.name}${b.version ? " " + b.version : ""} isn't supported.` : `This browser can't do ${missing.join(", ")}.`} Please open this page in <b>Google Chrome</b> or <b>Microsoft Edge</b> (Safari 15 or newer on a Mac), updated to the latest version.</div>;
}

function PermissionStep({ ctx }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const b = browserInfo();
  const ask = async () => {
    setBusy(true); setErr("");
    try {
      ctx.stream?.getTracks().forEach((t) => t.stop());
      const s = await getStream(ctx.n, ctx.devs.cam, ctx.devs.mic);
      ctx.setStream(s); ctx.set("permissions", "pass", "Allowed");
    } catch (e) {
      const name = e?.name || "";
      const msg = name === "NotAllowedError" || name === "SecurityError" ? `The browser blocked the camera or microphone. ${helpFor(b)}`
        : name === "NotFoundError" || name === "OverconstrainedError" ? "No camera or microphone was found. Plug one in (or turn it on), then press Try again."
        : name === "NotReadableError" ? "Another app is using your camera or microphone. Close Zoom, Teams, Meet or other camera apps, then press Try again."
        : "We couldn't start the camera or microphone. Restart the browser and try again.";
      setErr(msg); ctx.set("permissions", "fail", name || "Blocked");
    } finally { setBusy(false); }
  };
  useEffect(() => {
    if (ctx.stream) { ctx.set("permissions", "pass", "Allowed"); return; }
    // already allowed before: no need to click
    navigator.permissions?.query({ name: "camera" }).then((p) => { if (p.state === "granted") ask(); }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="col" style={{ gap: 8 }}>
      <p className="small" style={{ margin: 0 }}>When the browser asks, choose <b>Allow</b>{ctx.n.camera && ctx.n.mic ? " for both the camera and the microphone" : ""}.</p>
      {err && <div className="sc-note bad" role="alert">{err}</div>}
      {!ctx.stream && <div><Btn kind="primary" busy={busy} onClick={ask}>{err ? "Try again" : `Allow ${ctx.n.camera ? "camera" : ""}${ctx.n.camera && ctx.n.mic ? " and " : ""}${ctx.n.mic ? "microphone" : ""}`}</Btn></div>}
      {ctx.stream && <div className="sc-note good">✓ Allowed.</div>}
    </div>
  );
}

function useDeviceList(kind) {
  const [list, setList] = useState([]);
  useEffect(() => {
    const load = () => navigator.mediaDevices?.enumerateDevices().then((d) => setList(d.filter((x) => x.kind === kind))).catch(() => {});
    load();
    navigator.mediaDevices?.addEventListener?.("devicechange", load);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", load);
  }, [kind]);
  return list;
}

async function switchDevice(ctx, which, id) {
  const devs = { ...ctx.devs, [which]: id };
  ctx.setDevs(devs);
  try {
    const s = await getStream(ctx.n, devs.cam, devs.mic);
    ctx.stream?.getTracks().forEach((t) => t.stop());
    ctx.setStream(s);
  } catch { /* keep the old stream */ }
}

function NeedStream({ ctx }) {
  return <div className="sc-note bad">The camera and microphone aren't allowed yet. Go back to “Camera and microphone allowed”.</div>;
}

function CameraStep({ ctx }) {
  const v = useRef();
  const list = useDeviceList("videoinput");
  const [light, setLight] = useState(null);
  const good = useRef(0);
  const track = ctx.stream?.getVideoTracks()[0];
  useEffect(() => { if (v.current && ctx.stream) v.current.srcObject = ctx.stream; }, [ctx.stream]);
  useEffect(() => {
    if (!ctx.stream) return undefined;
    const c = document.createElement("canvas"); c.width = 64; c.height = 36;
    const g = c.getContext("2d", { willReadFrequently: true });
    good.current = 0;
    const t = setInterval(() => {
      const el = v.current;
      if (!el || el.readyState < 2) return;
      g.drawImage(el, 0, 0, 64, 36);
      const px = g.getImageData(0, 0, 64, 36).data;
      let sum = 0, sq = 0;
      for (let i = 0; i < px.length; i += 4) { const y = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]; sum += y; sq += y * y; }
      const cnt = px.length / 4, mean = sum / cnt, sd = Math.sqrt(Math.max(0, sq / cnt - mean * mean));
      const state = mean < 35 ? "dark" : sd < 6 ? "covered" : "ok";
      setLight(state);
      good.current = state === "ok" ? good.current + 1 : 0;
      if (good.current >= 3) ctx.set("camera", "pass", track?.label || "Camera");
      else if (state !== "ok") ctx.set("camera", "fail", state === "dark" ? "Too dark" : "Picture is blank or covered");
    }, 500);
    return () => clearInterval(t);
  }, [ctx.stream]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ctx.stream) return <NeedStream ctx={ctx} />;
  return (
    <div className="sc-media">
      <div className="sc-video"><video ref={v} autoPlay playsInline muted /></div>
      <div className="col grow" style={{ gap: 8 }}>
        <label className="small b">Camera</label>
        <Select value={ctx.devs.cam || track?.getSettings?.().deviceId || ""} onChange={(id) => switchDevice(ctx, "cam", id)}
          options={(list.length ? list : [{ deviceId: "", label: track?.label || "Default camera" }]).map((d, k) => ({ value: d.deviceId, label: d.label || `Camera ${k + 1}` }))} aria-label="Choose camera" />
        <span className="tiny muted">Default: {track?.label || "your system's camera"}</span>
        {light === "dark" && <div className="sc-note bad">The picture is too dark. Turn on a light in front of you, or face a window.</div>}
        {light === "covered" && <div className="sc-note bad">The picture is blank. Check the camera isn't covered, or pick another camera above.</div>}
        {light === "ok" && <div className="sc-note good">✓ The picture looks clear.</div>}
      </div>
    </div>
  );
}

function FaceStep({ ctx }) {
  const v = useRef();
  useEffect(() => { if (v.current && ctx.stream) { v.current.srcObject = ctx.stream; v.current.play?.().catch(() => {}); } }, [ctx.stream]);
  const faces = useFaceCount(v, !!ctx.stream);
  const seen = useRef(0);
  useEffect(() => {
    if (faces === "unavailable") { ctx.set("face", "pass", "Face check unavailable in this browser"); return; }
    if (faces === 1) { seen.current += 1; if (seen.current >= 2) ctx.set("face", "pass", "One face"); }
    else if (faces != null) { seen.current = 0; ctx.set("face", "fail", faces === 0 ? "No face" : `${faces} faces`); }
  }, [faces]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ctx.stream) return <NeedStream ctx={ctx} />;
  return (
    <div className="sc-media">
      <div className="sc-video"><video ref={v} autoPlay playsInline muted /></div>
      <div className="col grow" style={{ gap: 8 }}>
        {faces == null && <div className="sc-note">Looking for your face…</div>}
        {faces === 1 && <div className="sc-note good">✓ We can see you.</div>}
        {faces === 0 && <div className="sc-note bad">We can't see your face. Sit facing the camera, about an arm's length away, with light in front of you.</div>}
        {typeof faces === "number" && faces > 1 && <div className="sc-note bad">We can see {faces} people. Only you should be in view.</div>}
        {faces === "unavailable" && <div className="sc-note warn">This browser can't run the face check. A reviewer will see that. You can continue.</div>}
      </div>
    </div>
  );
}

function Meter({ level }) {
  return <div className="levels" aria-hidden="true">{Array.from({ length: 18 }).map((_, i) => <i key={i} style={{ height: Math.max(3, Math.min(28, level * 40 * (0.5 + Math.abs(Math.sin(i))))) }} />)}</div>;
}

function MicStep({ ctx }) {
  const list = useDeviceList("audioinput");
  const [level, setLevel] = useState(0);
  const loud = useRef(0);
  const [heard, setHeard] = useState(false);
  const [phase, setPhase] = useState("level"); // level | say | done
  const [said, setSaid] = useState("");
  const [msg, setMsg] = useState("");
  const tries = useRef(0);
  const rec = useRef(null);
  const [testing, setTesting] = useState(false);
  const track = ctx.stream?.getAudioTracks()[0];
  const wordTest = ctx.mode !== "recheck";
  useEffect(() => {
    if (!ctx.stream?.getAudioTracks().length) return undefined;
    let stop = null;
    micLevel(ctx.stream, (l) => {
      setLevel(l);
      if (l > 0.15) { loud.current += 1; if (loud.current > 20) setHeard(true); }
    }).then((s) => { stop = s; });
    return () => stop?.();
  }, [ctx.stream]);
  useEffect(() => {
    if (!heard) return;
    if (!wordTest) { ctx.set("mic", "pass", track?.label || "Microphone"); ctx.setInfo((x) => ({ ...x, mic: track?.label })); setPhase("done"); }
    else if (phase === "level") setPhase("say");
  }, [heard]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { rec.current?.stop(); }, []);
  const sayTest = async () => {
    if (testing) return;
    setSaid(""); setMsg(""); setTesting(true); tries.current += 1;
    const target = words(PHRASE);
    let finished = false;
    const done = (status, detail, text) => {
      if (finished) return; finished = true;
      rec.current?.stop(); rec.current = null; setTesting(false);
      ctx.set("mic", status, detail); ctx.setInfo((x) => ({ ...x, mic: track?.label, captions: detail }));
      if (status === "pass") setPhase("done"); else setMsg(text);
    };
    const timer = setTimeout(() => {
      if (tries.current >= 2) done("pass", "Sound OK; words not recognised", "");
      else done("fail", "Words not recognised", "We heard sound but couldn't make out the words. Move closer to the microphone, speak clearly, and press Try again.");
    }, 12000);
    rec.current = await listen({ language: LANG_CODES[ctx.language] || "en-IN", stream: ctx.devs.mic ? new MediaStream(ctx.stream.getAudioTracks()) : null,
      onPartial: (t) => setSaid(t),
      onSentence: (t) => {
        setSaid(t);
        const got = words(t).filter((w) => target.includes(w)).length;
        if (got >= 3) { clearTimeout(timer); done("pass", `${track?.label || "Microphone"} · captions work`, ""); }
      },
      // the speech service itself isn't reachable (not the candidate's fault): the level test already proved the mic works
      onError: (m) => { if (/network|not-allowed|audio-capture/i.test(m || "")) { clearTimeout(timer); done("pass", "Sound OK; speech service unavailable", ""); } } });
    if (rec.current?.engine === "none") { clearTimeout(timer); done("pass", "Sound OK; this browser can't write out speech", ""); }
  };
  if (!ctx.stream?.getAudioTracks().length) return <NeedStream ctx={ctx} />;
  return (
    <div className="col" style={{ gap: 10 }}>
      <label className="small b">Microphone</label>
      <Select value={ctx.devs.mic || track?.getSettings?.().deviceId || ""} onChange={(id) => { loud.current = 0; setHeard(false); setPhase("level"); switchDevice(ctx, "mic", id); }}
        options={(list.length ? list : [{ deviceId: "", label: track?.label || "Default microphone" }]).map((d, k) => ({ value: d.deviceId, label: d.label || `Microphone ${k + 1}` }))} aria-label="Choose microphone" />
      <span className="tiny muted">Default: {track?.label || "your system's microphone"}</span>
      <div className="sc-meter"><Meter level={level} /><span className="small">{heard ? "✓ We can hear you." : "Say something: the bars should move."}</span></div>
      {phase === "say" && <div className="sc-note col" style={{ gap: 6 }}>
        <span className="small">Now read this sentence out loud. It tests that captions can write out what you say:</span>
        <b style={{ fontSize: 18 }}>“{PHRASE}.”</b>
        <div className="sc-caption" aria-live="polite">{said || <span className="muted">What we hear appears here…</span>}</div>
        <div><Btn kind="primary" onClick={sayTest} busy={testing}>{msg ? "Try again" : "Start the test"}</Btn></div>
      </div>}
      {msg && <div className="sc-note bad">{msg}</div>}
      {phase === "done" && <div className="sc-note good">✓ Your microphone works{said ? " and we understood you" : ""}.</div>}
    </div>
  );
}

function SpeakerStep({ ctx }) {
  const list = useDeviceList("audiooutput");
  const canPick = typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype;
  const [played, setPlayed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [no, setNo] = useState(false);
  const dflt = list.find((d) => d.deviceId === "default") || list[0];
  const label = (list.find((d) => d.deviceId === ctx.devs.spk) || dflt)?.label || "Your system's speaker";
  const play = async () => {
    setPlaying(true); setNo(false);
    const text = "Hello, this is Hira. If you can hear me, press I heard it.";
    try {
      let a = null;
      try {
        const r = await api.raw("POST", "/speech/tts", { text });
        if ((r.headers.get("content-type") || "").includes("audio")) a = new Audio(URL.createObjectURL(await r.blob()));
      } catch { /* browser voice below */ }
      if (a) {
        if (canPick && ctx.devs.spk) await a.setSinkId(ctx.devs.spk).catch(() => {});
        await new Promise((ok) => { a.onended = ok; a.onerror = ok; a.play().catch(ok); });
      } else if (window.speechSynthesis) {
        await new Promise((ok) => { const u = new SpeechSynthesisUtterance(text); u.onend = ok; u.onerror = ok; window.speechSynthesis.speak(u); setTimeout(ok, 6000); });
      } else {
        const AC = window.AudioContext || window.webkitAudioContext; const c = new AC(); const o = c.createOscillator(); o.frequency.value = 660; o.connect(c.destination); o.start(); await new Promise((ok) => setTimeout(ok, 800)); o.stop(); c.close();
      }
    } finally { setPlaying(false); setPlayed(true); }
  };
  return (
    <div className="col" style={{ gap: 10 }}>
      {canPick && list.length > 0 && <>
        <label className="small b">Speaker</label>
        <Select value={ctx.devs.spk || dflt?.deviceId || ""} onChange={(id) => { ctx.setDevs({ ...ctx.devs, spk: id }); setPlayed(false); }}
          options={list.map((d, k) => ({ value: d.deviceId, label: d.label || `Speaker ${k + 1}` }))} aria-label="Choose speaker" />
      </>}
      <span className="tiny muted">{canPick ? `Default: ${dflt?.label || "your system's speaker"}` : "This browser plays through your system's default speaker. Change it in your computer's sound settings."}</span>
      <div className="row wrap"><Btn kind="primary" busy={playing} onClick={play}>{played ? "▶ Play again" : "▶ Play test sound"}</Btn>
        {played && <><Btn kind="gold" onClick={() => { ctx.set("speaker", "pass", label); ctx.setInfo((x) => ({ ...x, speaker: label })); }}>I heard it</Btn>
          <Btn kind="ghost" onClick={() => { setNo(true); ctx.set("speaker", "fail", "Not heard"); }}>I didn't hear it</Btn></>}</div>
      {no && <div className="sc-note bad">Turn the volume up and check it isn't muted. If you use headphones, check they're plugged in{canPick ? ", or pick another speaker above" : ""}. Then play it again.</div>}
    </div>
  );
}

function RecordingStep({ ctx }) {
  const [state, setState] = useState("idle");
  const [msg, setMsg] = useState("");
  const run = async () => {
    const type = recordingType();
    if (!type || !ctx.stream) { setState("fail"); setMsg("This browser can't record video. Use Chrome or Edge."); ctx.set("recording", "fail", "Not supported"); return; }
    setState("recording"); setMsg("");
    try {
      const chunks = [];
      const r = new MediaRecorder(ctx.stream, { mimeType: type, videoBitsPerSecond: 600_000 });
      r.ondataavailable = (e) => e.data?.size && chunks.push(e.data);
      await new Promise((ok) => { r.onstop = ok; r.start(); setTimeout(() => r.stop(), 3000); });
      setState("uploading");
      const fd = new FormData(); fd.append("file", new Blob(chunks, { type }), "test." + (type.startsWith("video/mp4") ? "mp4" : "webm"));
      const res = await api.post("/syscheck/upload-test", fd);
      setState("pass"); ctx.set("recording", "pass", `${Math.round(res.bytes / 1024)} KB ${res.format}`);
    } catch (e) { setState("fail"); setMsg(e.message || "The test video didn't reach us. Check your internet and try again."); ctx.set("recording", "fail", "Upload failed"); }
  };
  useEffect(() => { if (ctx.stream) run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ctx.stream) return <NeedStream ctx={ctx} />;
  return (
    <div className="col" style={{ gap: 8 }}>
      {state === "recording" && <div className="sc-note">● Recording 3 seconds…</div>}
      {state === "uploading" && <div className="sc-note">Sending the test video…</div>}
      {state === "pass" && <div className="sc-note good">✓ The test video reached us. Your interview can be recorded.</div>}
      {state === "fail" && <><div className="sc-note bad">{msg}</div><div><Btn kind="primary" onClick={run}>Try again</Btn></div></>}
    </div>
  );
}

function FullscreenStep({ ctx }) {
  const [msg, setMsg] = useState("");
  const go = async () => {
    const okk = await enterFullscreen();
    if (okk && document.fullscreenElement) { ctx.set("fullscreen", "pass", "Works"); setMsg(""); }
    else { ctx.set("fullscreen", "fail", "Blocked"); setMsg("The browser didn't allow fullscreen. Press the button again, or press F11."); }
  };
  useEffect(() => { if (document.fullscreenElement) ctx.set("fullscreen", "pass", "Works"); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="col" style={{ gap: 8 }}>
      <p className="small" style={{ margin: 0 }}>The round runs in fullscreen. Leaving fullscreen during the round counts as a warning.</p>
      <div><Btn kind="primary" onClick={go}>Enter fullscreen</Btn></div>
      {msg && <div className="sc-note bad">{msg}</div>}
      {document.fullscreenElement && <div className="sc-note good">✓ Fullscreen works.</div>}
    </div>
  );
}

async function measure() {
  const t0 = performance.now();
  for (let k = 0; k < 3; k++) await api.raw("GET", `/syscheck/ping?bytes=0&r=${Math.random()}`);
  const rtt = (performance.now() - t0) / 3;
  const d0 = performance.now();
  const blob = await (await api.raw("GET", `/syscheck/ping?bytes=1000000&r=${Math.random()}`)).blob();
  const down = (blob.size * 8) / ((performance.now() - d0) / 1000) / 1e6;
  const payload = new Blob([new Uint8Array(500000)]);
  const fd = new FormData(); fd.append("file", payload, "ping.bin");
  const u0 = performance.now();
  await api.raw("POST", "/syscheck/ping", fd);
  const up = (payload.size * 8) / ((performance.now() - u0) / 1000) / 1e6;
  return { rtt: Math.round(rtt), down: Math.round(down * 10) / 10, up: Math.round(up * 10) / 10 };
}

function InternetStep({ ctx }) {
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const m = await measure();
      setR(m); setUploadSpeed(m.up); ctx.setInfo((x) => ({ ...x, down_mbps: m.down, up_mbps: m.up, rtt_ms: m.rtt }));
      const weak = m.down < 2 || m.up < 1 || m.rtt > 500;
      ctx.set("internet", weak ? "warn" : "pass", `${weak ? "weak · " : ""}${m.down} Mbps down · ${m.up} up · ${m.rtt} ms`);
    } catch { setR({ failed: true }); ctx.set("internet", "warn", "couldn't measure"); }
    finally { setBusy(false); }
  };
  useEffect(() => { run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="col" style={{ gap: 8 }}>
      {busy && <div className="sc-note">Measuring your connection…</div>}
      {r && !r.failed && <div className={"sc-note " + (r.down < 2 || r.up < 1 || r.rtt > 500 ? "warn" : "good")}>
        Download {r.down} Mbps · Upload {r.up} Mbps · Delay {r.rtt} ms.
        {(r.down < 2 || r.up < 1 || r.rtt > 500) ? " Your internet is weak or unsteady. You can still continue: the video is recorded at a lower quality so it reaches us. Close other apps and downloads if you can." : " ✓ Good."}</div>}
      {r?.failed && <div className="sc-note warn">We couldn't measure your connection. You can still continue.</div>}
      {!busy && <div><Btn size="sm" onClick={run}>Test again</Btn></div>}
    </div>
  );
}

const ROOM = ["I'm in a quiet room", "I'm alone in the room", "My phone is away and silent", "My charger is plugged in"];
function RoomStep({ ctx }) {
  const [t, setT] = useState(ROOM.map(() => false));
  useEffect(() => { ctx.set("room", t.every(Boolean) ? "pass" : "fail", t.every(Boolean) ? "All ticked" : "Not all ticked"); }, [t]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="col" style={{ gap: 6 }}>
      {ROOM.map((r, k) => <label key={r} className="check"><input type="checkbox" checked={t[k]} onChange={(e) => setT(t.map((x, j) => (j === k ? e.target.checked : x)))} />{r}</label>)}
    </div>
  );
}
