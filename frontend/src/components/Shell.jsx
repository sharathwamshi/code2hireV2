import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api, getCompanyOverride, setCompanyOverride } from "../api";
import { useAuth } from "../auth";
import { Disha, Hira } from "./Mascot";
import { Avatar, Btn, ago, useOutside } from "./ui";

const I = {
  today: "M4 12h4l3-8 4 16 3-8h2", jobs: "M4 7h16v12H4z M9 7V4h6v3", people: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M2 20c0-3 3-5 6-5s6 2 6 5 M16 11a3 3 0 1 0 0-6 M22 20c0-3-2-5-5-5",
  mic: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z M5 11a7 7 0 0 0 14 0 M12 18v3", report: "M6 3h9l4 4v14H6z M9 12h7 M9 16h7 M9 8h3",
  chart: "M4 20V10 M10 20V4 M16 20v-7 M22 20H2", check: "M5 12l4 4L19 6", cert: "M12 15a5 5 0 1 0 0-10 5 5 0 0 0 0 10z M8.5 14 7 22l5-3 5 3-1.5-8",
  bank: "M4 6h16 M4 12h16 M4 18h10", cog: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  building: "M4 21V5l8-3 8 3v16 M9 9h1 M14 9h1 M9 13h1 M14 13h1 M10 21v-4h4v4", home: "M3 11l9-7 9 7v9H3z M9 20v-6h6v6",
  book: "M4 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4z M20 4h-6v16 M20 4v14h-6", star: "M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.3L12 17.5 6.5 20.4l1-6.3L3 9.7l6.2-.9z",
  practice: "M12 3a9 9 0 1 0 9 9 M12 7v5l3 3", user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21c0-4 4-6 8-6s8 2 8 6", shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  layers: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5", feedback: "M4 4h16v12H8l-4 4z",
};
const Icon = ({ d }) => <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;

function navFor(me, can, override) {
  if (me.user.is_superadmin && !override) {
    return [["Platform", [["/admin", "Overview", I.today, true], ["/admin/companies", "Companies", I.building], ["/admin/settings", "AI, voice and defaults", I.cog],
      ["/admin/questions", "Global question bank", I.bank], ["/admin/templates", "Hiring templates", I.layers], ["/admin/certifications", "Certification review", I.cert],
      ["/admin/users", "All users", I.people], ["/admin/audit", "Audit log", I.shield]]]];
  }
  if (me.user.kind === "candidate") {
    return [["Disha", [["/me", "Home", I.home, true], ["/me/jobs", "Jobs for you", I.jobs], ["/me/applications", "My applications", I.report],
      ["/me/practice", "Practice interviews", I.practice], ["/me/skills", "Skill checks and badges", I.star], ["/me/learning", "Learning paths", I.book],
      ["/me/certifications", "Certifications", I.cert], ["/me/feedback", "Feedback", I.feedback], ["/me/profile", "Profile and privacy", I.user]]]];
  }
  const work = [["/app/today", "Today", I.today, true], ["/app/jobs", "Jobs", I.jobs]];
  if (can("candidates.view")) work.push(["/app/talent", "Talent pool", I.people]);
  if (can("interviews.join") || can("interviews.run")) work.push(["/app/interviews", "My interviews", I.mic]);
  if (can("reports.view")) work.push(["/app/reports", "Reports", I.report]);
  const insight = [];
  if (can("analytics.view")) insight.push(["/app/analytics", "Analytics", I.chart]);
  if (can("approvals.decide")) insight.push(["/app/approvals", "Approvals", I.check]);
  const build = [];
  if (can("certs.manage")) build.push(["/app/certifications", "Certifications", I.cert]);
  if (can("questions.manage")) build.push(["/app/questions", "Question bank", I.bank]);
  if (can("users.manage") || can("settings.manage") || can("policies.manage")) build.push(["/app/admin", "Company admin", I.cog]);
  return [["Hiring", work], ...(insight.length ? [["Insight", insight]] : []), ...(build.length ? [["Set up", build]] : [])];
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef();
  const nav = useNavigate();
  useOutside(ref, () => setOpen(false));
  const load = async () => {
    try { const n = await api.get("/inbox/notifications"); setItems(n); setUnread(n.filter((x) => !x.read).length); } catch { /* signed out */ }
  };
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="btn icon-btn" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} onClick={() => { setOpen(!open); if (!open && unread) api.post("/inbox/notifications/read").then(load); }}>
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z M10 20h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
        {unread > 0 && <span style={{ position: "absolute", top: -4, right: -4, background: "var(--bad)", color: "#fff", borderRadius: 999, fontSize: 10, padding: "0 5px", fontWeight: 700 }}>{unread}</span>}
      </button>
      {open && (
        <div className="pop-menu">
          <div className="row" style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}><b>Notifications</b></div>
          {!items.length && <div className="empty small">You're all caught up.</div>}
          {items.map((n) => (
            <button key={n.id} className="list-row" style={{ width: "100%", border: 0, background: n.read ? "#fff" : "#FAF9FF", textAlign: "left", cursor: "pointer" }}
              onClick={() => { setOpen(false); if (n.link) nav(n.link); }}>
              <div className="grow"><div className="b">{n.title}</div><div className="small muted">{n.body}</div></div>
              <span className="tiny faint">{ago(n.created_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Shell({ children }) {
  const { me, can, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [side, setSide] = useState(false);
  const override = getCompanyOverride();
  useEffect(() => setSide(false), [loc.pathname]);
  if (!me) return null;
  const groups = navFor(me, can, override);
  const roleText = me.user.is_superadmin ? (override ? "Superadmin · support access" : "Superadmin")
    : me.user.kind === "candidate" ? "Candidate" : [...new Set((me.roles || []).map((r) => r.label))].join(" · ") || "Team member";
  return (
    <div className="shell">
      <aside className={"side" + (side ? " open" : "")} aria-label="Main navigation">
        <div style={{ padding: "4px 10px 10px" }}>
          <div className="logo">Code<b>2</b>Hire</div>
          <div className="powered">Powered by AcknowledgerFirst</div>
        </div>
        {me.company && <div className="chip" style={{ margin: "0 10px", justifyContent: "flex-start" }}>{me.company.name}</div>}
        {groups.map(([g, links]) => (
          <nav className="nav" key={g}>
            <div className="nav-sec">{g}</div>
            {links.map(([to, label, icon, end]) => <NavLink key={to} to={to} end={end}><Icon d={icon} />{label}</NavLink>)}
          </nav>
        ))}
        <div style={{ marginTop: "auto", padding: 10 }}>
          {me.user.kind === "candidate"
            ? <div className="agent disha" style={{ padding: 10 }}><Disha size={36} /><span className="small">Disha is here to help you grow. Click me.</span></div>
            : <div className="agent hira" style={{ padding: 10 }}><Hira size={36} /><span className="small">Hira works across your jobs. Ask from any table.</span></div>}
        </div>
      </aside>
      <div className="main">
        <header className="top">
          <button className="btn icon-btn burger" aria-label="Open menu" onClick={() => setSide(!side)}>☰</button>
          {override && (
            <div className="chip warn">Support access: company #{override}
              <button onClick={() => { setCompanyOverride(null); nav("/admin"); window.location.reload(); }} aria-label="Exit support access">×</button>
            </div>
          )}
          <div className="right row">
            <span className="chip brand" title="Your roles">{roleText}</span>
            <Notifications />
            <div className="row" style={{ gap: 8 }}>
              <Avatar name={me.user.name} />
              <div className="col" style={{ gap: 0 }}><b className="small">{me.user.name}</b><span className="tiny muted">{me.user.email}</span></div>
            </div>
            <Btn size="sm" kind="ghost" onClick={() => { logout(); nav("/"); }}>Sign out</Btn>
          </div>
        </header>
        <main className="page" id="main">{children}</main>
      </div>
    </div>
  );
}

export function PageHead({ title, sub, actions, back }) {
  const nav = useNavigate();
  return (
    <div className="page-head">
      <div>
        {back && <button className="btn ghost sm" style={{ marginLeft: -10, marginBottom: 4 }} onClick={() => nav(back)}>← Back</button>}
        <h1>{title}</h1>{sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
