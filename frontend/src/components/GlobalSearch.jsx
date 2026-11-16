// CP-005 / GLB-01 (V02.00.10): one search box in the candidate header for jobs, skills and learning paths.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useOutside } from "./ui";

export default function GlobalSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const ref = useRef(null);
  useOutside(ref, () => setOpen(false));
  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return undefined; }
    const t = setTimeout(() => api.get("/me/search", { q: q.trim() }).then((r) => { setRes(r); setHi(0); }).catch(() => setRes(null)), 220);
    return () => clearTimeout(t);
  }, [q]);
  const items = !res ? [] : [
    ...res.jobs.map((j) => ({ group: "Jobs", label: j.title, sub: `${j.company || "Confidential"} · ${j.match}% match`, to: `/me/jobs/${j.id}` })),
    ...res.skills.map((s) => ({ group: "Skills", label: s.name, sub: s.mine ? "On your profile · take a skill check" : "Take a skill check", to: `/me/skills?skill=${encodeURIComponent(s.name)}` })),
    ...res.paths.map((p) => ({ group: "Learning paths", label: p.title, sub: "Your path", to: "/me/learning" })),
    { group: "More", label: `All jobs matching “${res.q}”`, sub: "Jobs for you", to: `/me/jobs?q=${encodeURIComponent(res.q)}` },
    { group: "More", label: `Build a learning path for “${res.q}”`, sub: "Learning paths", to: `/me/learning?skill=${encodeURIComponent(res.q)}` },
  ];
  const go = (it) => { setOpen(false); setQ(""); nav(it.to); };
  const key = (e) => {
    if (!open || !items.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setHi((hi + 1) % items.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((hi - 1 + items.length) % items.length); }
    else if (e.key === "Enter") { e.preventDefault(); go(items[hi]); }
    else if (e.key === "Escape") setOpen(false);
  };
  let last = "";
  return (
    <div className="gsearch" ref={ref} role="search">
      <span className="gs-icon" aria-hidden="true">⌕</span>
      <input className="input" value={q} placeholder="Search jobs, skills or learning paths" aria-label="Search jobs, skills or learning paths"
        aria-expanded={open && items.length > 0} aria-controls="gs-list" role="combobox" aria-autocomplete="list"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={key} />
      {open && items.length > 0 && (
        <div className="pop-menu gs-pop" id="gs-list" role="listbox">
          {items.map((it, i) => {
            const head = it.group !== last ? it.group : null;
            last = it.group;
            return (
              <div key={i}>
                {head && <div className="tiny muted gs-head">{head}</div>}
                <button type="button" role="option" aria-selected={i === hi} className={"gs-item" + (i === hi ? " on" : "")} onMouseEnter={() => setHi(i)} onClick={() => go(it)}>
                  <b className="small">{it.label}</b><span className="tiny muted">{it.sub}</span>
                </button>
              </div>);
          })}
        </div>
      )}
    </div>
  );
}
