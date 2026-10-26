import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Btn, Chip, Empty, Select } from "./ui";

/**
 * The table standard used on every list: server-side search, sort, filters, pagination, page size,
 * column chooser, row selection with a bulk bar, density, saved views. Fits the screen (horizontal scroll inside).
 *
 * columns: [{key, label, sort?, render?(row), width?, hide?}]
 * endpoint: "/jobs" (expects {items,total,page,size,pages}) or rows: [...] for local data
 */
export default function DataTable({ endpoint, rows: localRows, columns, filters = [], params: extra = {}, defaultSort, onRow,
  selectable, bulk, searchPlaceholder = "Search…", toolbar, empty, viewKey, reloadKey, chips = [], onClearChip, pageSize = 25 }) {
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [sort, setSort] = useState(defaultSort || "");
  const [dir, setDir] = useState("desc");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(pageSize);
  const [f, setF] = useState({});
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [sel, setSel] = useState([]);
  const [hidden, setHidden] = useState(() => { try { return JSON.parse(localStorage.getItem("cols:" + (viewKey || endpoint)) || "[]"); } catch { return []; } });
  const [colMenu, setColMenu] = useState(false);
  const [dense, setDense] = useState(false);
  const t = useRef();

  useEffect(() => { clearTimeout(t.current); t.current = setTimeout(() => { setQd(q); setPage(1); }, 300); }, [q]);

  const load = useCallback(async () => {
    if (localRows) {
      let r = localRows.filter((x) => !qd || JSON.stringify(x).toLowerCase().includes(qd.toLowerCase()));
      Object.entries(f).forEach(([k, v]) => { if (v) r = r.filter((x) => String(x[k]) === String(v)); });
      if (sort) r = [...r].sort((a, b) => (a[sort] > b[sort] ? 1 : -1) * (dir === "asc" ? 1 : -1));
      setData({ items: r.slice((page - 1) * size, page * size), total: r.length, page, size, pages: Math.max(1, Math.ceil(r.length / size)) });
      return;
    }
    setErr(null);
    try { setData(await api.get(endpoint, { q: qd, sort, dir, page, size, ...f, ...extra })); }
    catch (e) { setErr(e.message); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, localRows, qd, sort, dir, page, size, JSON.stringify(f), JSON.stringify(extra), reloadKey]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSel([]); }, [qd, page, JSON.stringify(f), reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleSort = (c) => {
    if (!c.sort) return;
    if (sort === c.sort) setDir(dir === "asc" ? "desc" : "asc"); else { setSort(c.sort); setDir("asc"); }
    setPage(1);
  };
  const vis = columns.filter((c) => !hidden.includes(c.key));
  const items = data?.items || [];
  const allSel = items.length > 0 && items.every((r) => sel.includes(r.id));
  const saveHidden = (h) => { setHidden(h); try { localStorage.setItem("cols:" + (viewKey || endpoint), JSON.stringify(h)); } catch { /* ignore */ } };
  const pages = data?.pages || 1;
  const nums = [];
  for (let i = Math.max(1, page - 2); i <= Math.min(pages, page + 2); i++) nums.push(i);

  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div className="tbl-bar">
        <label className="search" style={{ flex: "1 1 240px", maxWidth: 380 }}>
          <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
          <input aria-label="Search" placeholder={searchPlaceholder} value={q} onChange={(e) => setQ(e.target.value)} />
          {q && <button className="btn ghost sm" style={{ height: 22, padding: "0 4px" }} onClick={() => setQ("")} aria-label="Clear search">✕</button>}
        </label>
        {filters.map((fl) => (
          <div key={fl.key} style={{ width: fl.width || 170 }}>
            <Select aria-label={fl.label} value={f[fl.key] || ""} onChange={(v) => { setF({ ...f, [fl.key]: v }); setPage(1); }}
              options={[{ value: "", label: fl.label + ": all" }, ...fl.options.map((o) => (typeof o === "object" ? o : { value: o, label: o }))]} />
          </div>
        ))}
        {toolbar}
        <div className="right row" style={{ position: "relative" }}>
          <Btn size="sm" kind="ghost" onClick={() => setDense(!dense)} title="Row density">{dense ? "Comfortable" : "Compact"}</Btn>
          <Btn size="sm" onClick={() => setColMenu(!colMenu)} aria-expanded={colMenu}>Columns</Btn>
          {colMenu && (
            <div className="pop-menu" style={{ minWidth: 220, padding: 8 }} onMouseLeave={() => setColMenu(false)}>
              {columns.map((c) => (
                <label key={c.key} className="check" style={{ display: "flex", padding: "6px 8px" }}>
                  <input type="checkbox" checked={!hidden.includes(c.key)} onChange={() => saveHidden(hidden.includes(c.key) ? hidden.filter((x) => x !== c.key) : [...hidden, c.key])} />{c.label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
      {chips.length > 0 && (
        <div className="tbl-bar" style={{ paddingTop: 8, paddingBottom: 8, background: "#FBFAFF" }}>
          <span className="small b" style={{ color: "var(--hira)" }}>Hira applied:</span>
          {chips.map((c, i) => <Chip key={i} kind="brand">{c.label}<button aria-label="Remove filter" onClick={() => onClearChip?.(i)}>×</button></Chip>)}
        </div>
      )}
      {selectable && sel.length > 0 && bulk && (
        <div className="bulkbar"><b>{sel.length} selected</b>{bulk(sel, () => { setSel([]); load(); })}<Btn size="sm" kind="ghost" style={{ color: "#fff" }} onClick={() => setSel([])}>Clear</Btn></div>
      )}
      {err && <div className="tbl-bar" style={{ color: "var(--bad)" }}>{err} <Btn size="sm" onClick={load}>Retry</Btn></div>}
      <div className="tbl-wrap">
        <table className="tbl" style={dense ? { fontSize: 13 } : undefined}>
          <thead><tr>
            {selectable && <th style={{ width: 36 }}><input type="checkbox" aria-label="Select all on this page" checked={allSel} onChange={() => setSel(allSel ? [] : items.map((r) => r.id))} /></th>}
            {vis.map((c) => (
              <th key={c.key} className={c.sort ? "sortable" : ""} style={{ width: c.width }} onClick={() => toggleSort(c)} aria-sort={sort === c.sort ? (dir === "asc" ? "ascending" : "descending") : undefined}>
                {c.label}{c.sort && <span style={{ opacity: sort === c.sort ? 1 : .3, marginLeft: 4 }}>{sort === c.sort && dir === "asc" ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {!data && !err && [0, 1, 2, 3].map((i) => <tr key={i}>{selectable && <td />}{vis.map((c) => <td key={c.key}><div className="skel" style={{ width: 40 + ((i * 17 + c.key.length * 9) % 50) + "%" }} /></td>)}</tr>)}
            {items.map((r) => (
              <tr key={r.id} className={(onRow ? "clickable " : "") + (sel.includes(r.id) ? "sel" : "")} onClick={() => onRow?.(r)}>
                {selectable && <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label="Select row" checked={sel.includes(r.id)} onChange={() => setSel(sel.includes(r.id) ? sel.filter((x) => x !== r.id) : [...sel, r.id])} /></td>}
                {vis.map((c) => <td key={c.key} style={dense ? { padding: "7px 12px" } : undefined}>{c.render ? c.render(r) : (r[c.key] ?? "—")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        {data && !items.length && (empty || <Empty title={qd || Object.values(f).some(Boolean) ? "Nothing matches" : "Nothing here yet"} text={qd ? "Try a different search or clear filters." : ""} />)}
      </div>
      {data && (
        <div className="tbl-foot">
          <span>{data.total ? `${(page - 1) * size + 1}–${Math.min(page * size, data.total)} of ${data.total}` : "0 results"}</span>
          <span style={{ width: 110 }}><Select aria-label="Rows per page" value={String(size)} onChange={(v) => { setSize(+v); setPage(1); }} options={["10", "25", "50", "100"].map((x) => ({ value: x, label: x + " / page" }))} /></span>
          <div className="pager">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">‹</button>
            {nums[0] > 1 && <><button onClick={() => setPage(1)}>1</button>{nums[0] > 2 && <span>…</span>}</>}
            {nums.map((n) => <button key={n} className={n === page ? "on" : ""} onClick={() => setPage(n)}>{n}</button>)}
            {nums[nums.length - 1] < pages && <>{nums[nums.length - 1] < pages - 1 && <span>…</span>}<button onClick={() => setPage(pages)}>{pages}</button></>}
            <button disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">›</button>
          </div>
        </div>
      )}
    </div>
  );
}
