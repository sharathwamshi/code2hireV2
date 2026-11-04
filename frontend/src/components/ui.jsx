import { cloneElement, createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------- toasts
// The same message again only refreshes its timer, at most 3 show at once, and each can be closed.
const ToastCtx = createContext(() => {});
const ConfirmCtx = createContext(async () => false);
const TOAST_MS = 3800, TOAST_MAX = 3;
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const timers = useRef({});
  const drop = useCallback((key) => { clearTimeout(timers.current[key]); delete timers.current[key]; setItems((x) => x.filter((i) => i.key !== key)); }, []);
  const push = useCallback((msg, kind = "") => {
    const text = typeof msg === "string" ? msg : String(msg ?? "");
    if (!text) return;
    const key = kind + "|" + text;
    clearTimeout(timers.current[key]);
    timers.current[key] = setTimeout(() => drop(key), kind === "bad" ? TOAST_MS + 2200 : TOAST_MS);
    setItems((x) => {
      const rest = x.filter((i) => i.key !== key);
      const next = [...rest, { key, msg: text, kind, n: Date.now() }];
      while (next.length > TOAST_MAX) { const old = next.shift(); clearTimeout(timers.current[old.key]); delete timers.current[old.key]; }
      return next;
    });
  }, [drop]);
  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), []);
  // in-app confirm: const ok = await confirm({ title, text, yes, danger })
  // in-app prompt:  const v = await confirm({ title, input: { label, value, required, match, placeholder } }) -> string | null
  const [ask, setAsk] = useState(null);
  const [val, setVal] = useState("");
  const confirm = useCallback((o) => new Promise((resolve) => {
    const a = typeof o === "string" ? { text: o } : o;
    setVal(a.input?.value ?? "");
    setAsk({ ...a, resolve });
  }), []);
  const answer = (v) => { ask?.resolve(ask.input ? (v ? val.trim() : null) : v); setAsk(null); };
  const inputBad = ask?.input && ((ask.input.required && !val.trim()) || (ask.input.match && val.trim() !== ask.input.match));
  return (
    <ToastCtx.Provider value={push}>
      <ConfirmCtx.Provider value={confirm}>
        {children}
        {ask && (
          <Modal title={ask.title || "Are you sure?"} onClose={() => answer(false)} footer={<>
            <Btn onClick={() => answer(false)}>{ask.no || "Cancel"}</Btn>
            <Btn kind={ask.danger ? "danger" : "primary"} disabled={inputBad} onClick={() => answer(true)} autoFocus={!ask.input}>{ask.yes || "Confirm"}</Btn>
          </>}>
            {ask.text && <p style={{ margin: 0 }}>{ask.text}</p>}
            {ask.input && (
              <form onSubmit={(e) => { e.preventDefault(); if (!inputBad) answer(true); }}>
                <Field label={ask.input.label} required={ask.input.required} hint={ask.input.hint}>
                  {ask.input.multiline
                    ? <Textarea value={val} onChange={(e) => setVal(e.target.value)} placeholder={ask.input.placeholder} autoFocus maxLength={ask.input.max || 2000} />
                    : <Input value={val} onChange={(e) => setVal(e.target.value)} placeholder={ask.input.placeholder} autoFocus maxLength={ask.input.max || 200} type={ask.input.type || "text"} min={ask.input.min} max={ask.input.maxValue} />}
                </Field>
              </form>
            )}
          </Modal>
        )}
        <div className="toasts" role="status" aria-live="polite">
          {items.map((t) => (
            <div key={t.key + t.n} className={"toast " + t.kind}>
              <span>{t.msg}</span>
              <button className="toast-x" aria-label="Dismiss" onClick={() => drop(t.key)}>✕</button>
            </div>
          ))}
        </div>
      </ConfirmCtx.Provider>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
/** Promise-based in-app confirm. Never use window.confirm: it leaves fullscreen and looks out of place. */
export const useConfirm = () => useContext(ConfirmCtx);

// ---------------------------------------------------------------- async helpers
export function useAsync(fn, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  const run = useCallback(async () => {
    set((s) => ({ ...s, loading: true }));
    try { const data = await fn(); set({ data, error: null, loading: false }); return data; }
    catch (e) { set({ data: null, error: e.message, loading: false }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run, setData: (d) => set((s) => ({ ...s, data: typeof d === "function" ? d(s.data) : d })) };
}

/** Runs one action at a time: clicks while it is running are ignored, so a fast double click can't save twice. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const run = async (fn, okMsg) => {
    if (running.current) return new Promise(() => {});
    running.current = true; setBusy(true);
    try { const r = await fn(); if (okMsg) toast(okMsg, "good"); return r; }
    catch (e) { toast(e.message, "bad"); throw e; }
    finally { running.current = false; setBusy(false); }
  };
  return [run, busy];
}

// ---------------------------------------------------------------- primitives
export const Btn = ({ kind = "", size = "", children, busy, className = "", type = "button", ...p }) => (
  <button type={type} {...p} className={`btn ${kind} ${size} ${className}`} disabled={busy || p.disabled}>{busy && <span className="spin" style={{ width: 14, height: 14 }} />}{children}</button>
);
export const Chip = ({ kind = "", children, ...p }) => <span className={"chip " + kind} {...p}>{children}</span>;
let fieldSeq = 0;
/** Label, control, hint and error in one. `required` adds the * and links the error to the control for screen readers. */
export function Field({ label, hint, children, error, required, id }) {
  const [auto] = useState(() => "f" + (++fieldSeq));
  const fid = id || auto;
  const kid = Array.isArray(children) || !children?.type ? children
    : cloneElement(children, { id: children.props.id || fid, "aria-invalid": error ? true : undefined, "aria-describedby": error ? fid + "-e" : undefined, "aria-required": required || undefined });
  return (
    <div className={"field" + (error ? " has-error" : "")}>
      {label && <label htmlFor={fid}>{label}{required && <span className="req" aria-hidden="true"> *</span>}</label>}
      {kid}
      {error ? <span className="field-err" id={fid + "-e"} role="alert">{error}</span> : hint && <span className="hint">{hint}</span>}
    </div>
  );
}
export const Input = ({ className = "", ...p }) => <input className={"input " + className} {...p} />;
export const Textarea = ({ className = "", ...p }) => <textarea className={"textarea " + className} {...p} />;
/** Password box with a show/hide eye and a Caps Lock warning. */
export function PasswordInput({ value, onChange, ...p }) {
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const capsCheck = (e) => setCaps(!!e.getModifierState?.("CapsLock"));
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="pw-wrap">
        <input className="input" type={show ? "text" : "password"} value={value} onChange={onChange} onKeyUp={capsCheck} onKeyDown={capsCheck} onBlur={() => setCaps(false)} {...p} />
        <button type="button" className="pw-eye" aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} onClick={() => setShow(!show)}>
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />{show && <path d="M4 4l16 16" />}
          </svg>
        </button>
      </div>
      {caps && <span className="tiny" style={{ color: "var(--warn)" }}>Caps Lock is on.</span>}
    </div>
  );
}
export function Select({ options, value, onChange, ...p }) {
  return (
    <select className="select" value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...p}>
      {options.map((o) => typeof o === "object" ? <option key={o.value} value={o.value}>{o.label}</option> : <option key={o} value={o}>{o}</option>)}
    </select>
  );
}
export const Switch = ({ on, onChange, label, disabled }) => (
  <button type="button" role="switch" aria-checked={!!on} aria-label={label} disabled={disabled} className={"switch" + (on ? " on" : "")} onClick={() => onChange(!on)} />
);
export const Spinner = () => <span className="spin" />;
export function Loading({ text = "Loading…" }) { return <div className="empty"><Spinner /><span>{text}</span></div>; }
export function Empty({ title, text, action, mascot }) {
  return <div className="empty">{mascot}<h3 style={{ color: "var(--ink)" }}>{title}</h3>{text && <p style={{ maxWidth: 420 }}>{text}</p>}{action}</div>;
}
export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return <div className="card pad row" style={{ borderColor: "#F1B9C1", background: "var(--bad-soft)" }}><b style={{ color: "var(--bad)" }}>{error}</b>{onRetry && <Btn size="sm" onClick={onRetry} className="right">Try again</Btn>}</div>;
}

// Open dialogs, top-most last: only the top one reacts to Escape, and the page behind can't scroll while any is open.
const modalStack = [];
/**
 * Dialog with a header, a scrolling body and a footer that always stays visible.
 * dirty: true asks "Discard changes?" before closing by Escape, ✕, Cancel (via requestClose) or a click outside.
 */
export function Modal({ title, onClose, children, footer, wide, dirty, size }) {
  const me = useRef({});
  const [asking, setAsking] = useState(false);
  const tryClose = useCallback(() => { if (dirty) setAsking(true); else onClose?.(); }, [dirty, onClose]);
  me.current.tryClose = tryClose;
  useEffect(() => {
    const entry = me.current;
    modalStack.push(entry);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const k = (e) => { if (e.key === "Escape" && modalStack[modalStack.length - 1] === entry) { e.stopPropagation(); entry.tryClose?.(); } };
    window.addEventListener("keydown", k);
    return () => {
      window.removeEventListener("keydown", k);
      modalStack.splice(modalStack.indexOf(entry), 1);
      if (!modalStack.length) document.body.style.overflow = prev === "hidden" ? "" : prev;
    };
  }, []);
  const down = useRef(false);
  return (
    <div className="modal-bg" onMouseDown={(e) => { down.current = e.target === e.currentTarget; }} onMouseUp={(e) => { if (down.current && e.target === e.currentTarget) tryClose(); down.current = false; }}>
      <div className={"modal" + (wide ? " wide" : "") + (size ? " " + size : "")} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <div className="modal-h"><h3>{title}</h3><button type="button" className="btn ghost icon-btn right" aria-label="Close" onClick={tryClose}>✕</button></div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{typeof footer === "function" ? footer(tryClose) : footer}</div>}
        {asking && (
          <div className="modal-discard" role="alertdialog" aria-label="Discard changes?">
            <div className="card pad col" style={{ gap: 10, maxWidth: 360 }}>
              <b>Discard changes?</b><span className="small muted">What you typed here will be lost.</span>
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <Btn onClick={() => setAsking(false)} autoFocus>Keep editing</Btn>
                <Btn kind="danger" onClick={() => { setAsking(false); onClose?.(); }}>Discard</Btn>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return <div className="tabs" role="tablist">{tabs.map((t) => {
    const [k, l] = Array.isArray(t) ? t : [t, t];
    return <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>;
  })}</div>;
}
export function Seg({ options, value, onChange }) {
  return <div className="seg">{options.map((o) => {
    const [k, l] = Array.isArray(o) ? o : [o, o];
    return <button key={k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>;
  })}</div>;
}

export function Avatar({ name = "?", color }) {
  const ini = name.split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase();
  const colors = ["#2F6FED", "#5B3FFF", "#0E9F8E", "#E0672E", "#B5338A", "#12805C"];
  const c = color || colors[(name.charCodeAt(0) + name.length) % colors.length];
  return <span className="avatar" style={{ background: c }}>{ini}</span>;
}

export function Bar({ value, max = 100, tone }) {
  const pct = Math.max(0, Math.min(100, (100 * (value || 0)) / max));
  const t = tone || (pct >= 70 ? "good" : pct >= 45 ? "warn" : "bad");
  return <div className={"bar " + t}><i style={{ width: pct + "%" }} /></div>;
}
export function Ring({ value, max = 100, label }) {
  const p = Math.round((100 * (value || 0)) / max);
  const c = p >= 70 ? "var(--good)" : p >= 45 ? "#E08A1E" : "var(--bad)";
  return <div className="ring" style={{ "--p": p, "--c": c }}><span>{label ?? p}</span></div>;
}
/**
 * One score format for the whole app: "3.0 / 5 · 60%".
 * Interview and scorecard scores are stored out of 5; MCQ scores are stored as a percentage (pass type "mcq").
 * scale is the company's display scale (report.scale: 5, 10 or 100); the stored value is converted to it.
 */
export function toBase5(value, type) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) return null;
  return type === "mcq" ? Number(value) / 20 : Number(value);
}
export function scorePct(v5) {
  if (v5 == null || !Number.isFinite(Number(v5))) return null;
  return Math.max(0, Math.min(100, Math.round(Number(v5) * 20)));
}
export function fmtScore(v5, scale = 5, { pct = true } = {}) {
  const s = [5, 10, 100].includes(Number(scale)) ? Number(scale) : 5;
  if (v5 == null || !Number.isFinite(Number(v5))) return "—";
  const shown = (Number(v5) * s) / 5;
  const txt = `${s === 100 ? Math.round(shown) : shown.toFixed(1)} / ${s}`;
  return pct ? `${txt} · ${scorePct(v5)}%` : txt;
}
export const scoreTone = (p) => (p == null ? "" : p >= 70 ? "good" : p >= 50 ? "warn" : "bad");
export function Score({ value, scale = 5, pct = false, type }) {
  const v5 = toBase5(value, type);
  if (v5 == null) return <span className="faint">—</span>;
  return <Chip kind={scoreTone(scorePct(v5))}>{fmtScore(v5, scale, { pct })}</Chip>;
}
/** Integrity: "Clean", or "1 warning" / "3 warnings". */
export function Integrity({ count, onClick }) {
  const n = Number(count) || 0;
  const label = n === 0 ? "Clean" : `${n} warning${n === 1 ? "" : "s"}`;
  const c = <Chip kind={n === 0 ? "good" : n === 1 ? "warn" : "bad"}>{label}</Chip>;
  return onClick && n ? <button type="button" className="linklike" onClick={onClick} aria-label={`${label}: show details`}>{c}</button> : c;
}

const STAGE = {
  applied: ["Applied", ""], shortlisted: ["Shortlisted", "info"], in_round: ["In a round", "brand"], awaiting_review: ["To review", "warn"],
  decision: ["Decision", "gold"], offer: ["Offer", "good"], hired: ["Hired", "good"], rejected: ["Rejected", "bad"], on_hold: ["On hold", ""],
  withdrawn: ["Withdrawn", ""], live: ["Live", "good"], draft: ["Draft", ""], pending_approval: ["Awaiting approval", "warn"], closed: ["Closed", ""],
  invited: ["Invited", "info"], scheduled: ["Scheduled", "info"], in_progress: ["In progress", "brand"], paused: ["Paused", "bad"],
  completed: ["Completed", "good"], reviewed: ["Reviewed", "good"], expired: ["Expired", ""], awaiting: ["Awaiting", "warn"],
  shared: ["Shared", "good"], proceed: ["Proceed", "good"], hold: ["Hold", "warn"], reject: ["Reject", "bad"], pending: ["Pending", "warn"],
  approved: ["Approved", "good"], published: ["Published", "good"], review: ["In review", "warn"], retired: ["Retired", ""],
  active: ["Active", "good"], trial: ["Trial", "info"], suspended: ["Suspended", "bad"], revoked: ["Revoked", "bad"], cancelled: ["Cancelled", ""],
};
export function Status({ s }) {
  const [l, k] = STAGE[s] || [String(s || "—").replace(/_/g, " "), ""];
  return <Chip kind={k}><span className="dot" />{l}</Chip>;
}

export const ROUND_LABEL = { mcq: "MCQ screening", ai_interview: "AI interview · Hira", f2f_isha: "F2F with Isha", f2f_human: "Human F2F" };

/** <input type="datetime-local"> value -> ISO with timezone (what the API needs), and back. */
export function localInputToISO(v) {
  if (!v) return "";
  const d = new Date(v); // a datetime-local string is read as the viewer's local time
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}
export function isoToLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function fmtTime(d) { return d ? new Date(d).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }) : ""; }
export function fmtDate(d, withTime) {
  if (!d) return "—";
  const x = new Date(d);
  return x.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: withTime ? undefined : "numeric", ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}) });
}
export function ago(d) {
  if (!d) return "";
  const s = (Date.now() - new Date(d).getTime()) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + "m ago"; if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}
export const inr = (n) => n == null ? "—" : "₹" + (n >= 100000 ? (n / 100000).toFixed(n % 100000 ? 1 : 0) + " L" : Number(n).toLocaleString("en-IN"));

export function useOutside(ref, fn) {
  useEffect(() => {
    const h = (e) => ref.current && !ref.current.contains(e.target) && fn();
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, fn]);
}

export function Confirm({ title, text, onYes, onClose, yes = "Confirm", danger, children, disabled }) {
  const [run, busy] = useAction();
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <Btn onClick={onClose}>Cancel</Btn>
      <Btn kind={danger ? "danger" : "primary"} busy={busy} disabled={disabled} onClick={() => run(onYes).then(() => onClose()).catch(() => {})}>{yes}</Btn>
    </>}>
      {text && <p>{text}</p>}{children}
    </Modal>
  );
}

/** Chips editor: Enter or comma adds, duplicates (any case) are skipped, at most `max` items, Backspace removes the last. */
export function ListEditor({ value = [], onChange, placeholder = "Add and press Enter", max = 50, id, ...aria }) {
  const [t, setT] = useState("");
  const [note, setNote] = useState("");
  const ref = useRef();
  const add = (raw) => {
    const parts = raw.split(/[,;]/).map((x) => x.trim().replace(/\s+/g, " ").slice(0, 60)).filter(Boolean);
    let next = [...value], msg = "";
    for (const p of parts) {
      if (next.some((v) => String(v).toLowerCase() === p.toLowerCase())) { msg = `“${p}” is already added.`; continue; }
      if (next.length >= max) { msg = `You can add at most ${max}.`; break; }
      next.push(p);
    }
    if (next.length !== value.length) onChange(next);
    setNote(msg); setT("");
  };
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="chips-box" onClick={() => ref.current?.focus()}>
        {value.map((v, i) => <Chip key={v + i} kind="brand">{String(v)}<button type="button" aria-label={"Remove " + v} onClick={() => onChange(value.filter((_, j) => j !== i))}>×</button></Chip>)}
        <input ref={ref} id={id} {...aria} value={t} placeholder={value.length >= max ? "" : placeholder} disabled={value.length >= max} onChange={(e) => { setNote(""); if (/[,;]/.test(e.target.value)) add(e.target.value); else setT(e.target.value); }}
          onBlur={() => t.trim() && add(t)}
          onKeyDown={(e) => { if (e.key === "Enter" && t.trim()) { e.preventDefault(); add(t); } else if (e.key === "Backspace" && !t && value.length) onChange(value.slice(0, -1)); }} />
      </div>
      {note && <span className="tiny muted">{note}</span>}
    </div>
  );
}
