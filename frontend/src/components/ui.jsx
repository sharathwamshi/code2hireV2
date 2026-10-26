import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------- toasts
const ToastCtx = createContext(() => {});
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((msg, kind = "") => {
    const id = Math.random();
    setItems((x) => [...x, { id, msg, kind }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={"toast " + t.kind}>{t.msg}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

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

export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async (fn, okMsg) => {
    setBusy(true);
    try { const r = await fn(); if (okMsg) toast(okMsg, "good"); return r; }
    catch (e) { toast(e.message, "bad"); throw e; }
    finally { setBusy(false); }
  };
  return [run, busy];
}

// ---------------------------------------------------------------- primitives
export const Btn = ({ kind = "", size = "", children, busy, className = "", type = "button", ...p }) => (
  <button type={type} {...p} className={`btn ${kind} ${size} ${className}`} disabled={busy || p.disabled}>{busy && <span className="spin" style={{ width: 14, height: 14 }} />}{children}</button>
);
export const Chip = ({ kind = "", children, ...p }) => <span className={"chip " + kind} {...p}>{children}</span>;
export function Field({ label, hint, children, error }) {
  return <div className="field">{label && <label>{label}</label>}{children}{hint && <span className="hint">{hint}</span>}{error && <span className="small" style={{ color: "var(--bad)" }}>{error}</span>}</div>;
}
export const Input = (p) => <input className="input" {...p} />;
export const Textarea = (p) => <textarea className="textarea" {...p} />;
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

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose?.();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={"modal" + (wide ? " wide" : "")} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-h"><h3>{title}</h3><button className="btn ghost icon-btn right" aria-label="Close" onClick={onClose}>✕</button></div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
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
export function Score({ value, scale = 5 }) {
  if (value == null) return <span className="faint">—</span>;
  const pct = (100 * value) / scale;
  return <Chip kind={pct >= 70 ? "good" : pct >= 50 ? "warn" : "bad"}>{Number(value).toFixed(1)}/{scale}</Chip>;
}

const STAGE = {
  applied: ["Applied", ""], shortlisted: ["Shortlisted", "info"], in_round: ["In a round", "brand"], awaiting_review: ["To review", "warn"],
  decision: ["Decision", "gold"], offer: ["Offer", "good"], hired: ["Hired", "good"], rejected: ["Rejected", "bad"], on_hold: ["On hold", ""],
  withdrawn: ["Withdrawn", ""], live: ["Live", "good"], draft: ["Draft", ""], pending_approval: ["Awaiting approval", "warn"], closed: ["Closed", ""],
  invited: ["Invited", "info"], scheduled: ["Scheduled", "info"], in_progress: ["In progress", "brand"], paused: ["Paused", "bad"],
  completed: ["Completed", "good"], reviewed: ["Reviewed", "good"], expired: ["Expired", ""], awaiting: ["Awaiting", "warn"],
  shared: ["Shared", "good"], proceed: ["Proceed", "good"], hold: ["Hold", "warn"], reject: ["Reject", "bad"], pending: ["Pending", "warn"],
  approved: ["Approved", "good"], published: ["Published", "good"], review: ["In review", "warn"], retired: ["Retired", ""],
  active: ["Active", "good"], trial: ["Trial", "info"], suspended: ["Suspended", "bad"], revoked: ["Revoked", "bad"],
};
export function Status({ s }) {
  const [l, k] = STAGE[s] || [String(s || "—").replace(/_/g, " "), ""];
  return <Chip kind={k}><span className="dot" />{l}</Chip>;
}

export const ROUND_LABEL = { mcq: "MCQ screening", ai_interview: "AI interview · Hira", f2f_isha: "F2F with Isha", f2f_human: "Human F2F" };

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

export function Confirm({ title, text, onYes, onClose, yes = "Confirm", danger, children }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <Btn onClick={onClose}>Cancel</Btn>
      <Btn kind={danger ? "danger" : "primary"} busy={busy} onClick={async () => { setBusy(true); try { await onYes(); onClose(); } finally { setBusy(false); } }}>{yes}</Btn>
    </>}>
      {text && <p>{text}</p>}{children}
    </Modal>
  );
}

export function ListEditor({ value = [], onChange, placeholder = "Add and press Enter" }) {
  const [t, setT] = useState("");
  const ref = useRef();
  return (
    <div className="row wrap" style={{ border: "1px solid var(--line-2)", borderRadius: 9, padding: 6, minHeight: 38 }} onClick={() => ref.current?.focus()}>
      {value.map((v, i) => <Chip key={i} kind="brand">{String(v)}<button aria-label={"Remove " + v} onClick={() => onChange(value.filter((_, j) => j !== i))}>×</button></Chip>)}
      <input ref={ref} value={t} placeholder={placeholder} onChange={(e) => setT(e.target.value)} style={{ border: 0, outline: "none", flex: 1, minWidth: 120 }}
        onKeyDown={(e) => { if (e.key === "Enter" && t.trim()) { e.preventDefault(); onChange([...value, t.trim()]); setT(""); } }} />
    </div>
  );
}
