import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { videoUrl } from "../lib/recorder";
import { Btn, Chip } from "./ui";

const mmss = (s) => `${String(Math.floor((s || 0) / 60)).padStart(2, "0")}:${String(Math.floor((s || 0) % 60)).padStart(2, "0")}`;

/** Ask any Recording player on the page to jump to a moment ("Click a transcript line to jump"). */
export const seekRecording = (seconds) => window.dispatchEvent(new CustomEvent("c2h:seek", { detail: seconds }));

/**
 * The interview video as one timeline: pieces play back to back; minutes the main copy is missing are played from the
 * other side's backup; what neither side has is shown as a gap. Markers show each question and integrity warning.
 */
export default function RecordingPlayer({ attId, video: initial }) {
  const [v, setV] = useState(initial);
  const [idx, setIdx] = useState(0);
  const [pos, setPos] = useState(0);
  const [rate, setRate] = useState(1);
  const el = useRef();
  const pendingSeek = useRef(null);
  useEffect(() => setV(initial), [initial]);
  // a video still being finished: check again every 20 seconds
  useEffect(() => {
    if (v?.status !== "processing") return undefined;
    const t = setInterval(() => api.get(`/recordings/${attId}`).then(setV).catch(() => {}), 20000);
    return () => clearInterval(t);
  }, [v?.status, attId]);
  const parts = useMemo(() => (v?.parts || []).filter((p) => p.status === "ready"), [v]);
  const total = parts.length ? parts[parts.length - 1].to : 0;
  const part = parts[idx];

  const seek = (t) => {
    const i = parts.findIndex((p) => t >= p.from && t < p.to);
    const j = i >= 0 ? i : parts.findIndex((p) => p.from >= t); // inside a gap: the next piece
    if (j < 0) return;
    const into = Math.max(0, t - parts[j].from) + (parts[j].skip || 0);
    if (j === idx && el.current) { el.current.currentTime = into; el.current.play().catch(() => {}); }
    else { pendingSeek.current = into; setIdx(j); }
    el.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  useEffect(() => {
    const h = (e) => seek(Number(e.detail) || 0);
    window.addEventListener("c2h:seek", h);
    return () => window.removeEventListener("c2h:seek", h);
  });
  useEffect(() => { if (el.current) el.current.playbackRate = rate; }, [rate, idx]);

  if (!v) return null;
  if (v.status === "none") return <div className="card pad row"><h3>Interview video</h3><span className="small muted">{v.reason || "No video for this round."}</span></div>;
  const markers = v.markers || [];
  return (
    <div className="card pad col" id="recording">
      <div className="row wrap"><h3>Interview video</h3>
        {v.status === "processing" && <Chip kind="warn">Finishing the video…</Chip>}
        {v.status === "failed" && <Chip kind="bad">The video couldn't be finished</Chip>}
        {total > 0 && <span className="small muted">{mmss(total)} · every view is logged</span>}
        <span className="right" />
        <label className="small row" style={{ gap: 6 }}>Speed<select className="input" style={{ height: 30, width: 80 }} value={rate} onChange={(e) => setRate(+e.target.value)} aria-label="Playback speed">{[1, 1.25, 1.5, 2].map((r) => <option key={r} value={r}>{r}x</option>)}</select></label>
      </div>
      {part ? (
        <video key={part.id} ref={el} controls preload="metadata" playsInline style={{ width: "100%", maxHeight: 460, background: "#000", borderRadius: 10 }} src={videoUrl(attId, part.id)}
          onLoadedMetadata={(e) => { const t = pendingSeek.current ?? (part.skip || 0); pendingSeek.current = null; if (t) e.currentTarget.currentTime = t; e.currentTarget.playbackRate = rate; if (idx > 0) e.currentTarget.play().catch(() => {}); }}
          onTimeUpdate={(e) => { const t = part.from + e.currentTarget.currentTime - (part.skip || 0); setPos(t); if (t >= part.to - 0.2 && idx < parts.length - 1) setIdx(idx + 1); }}
          onEnded={() => { if (idx < parts.length - 1) setIdx(idx + 1); }} />
      ) : <div className="note">{v.status === "processing" ? "The video is being finished. It will appear here in a minute or two." : "No playable video yet."}</div>}
      {total > 0 && (
        <div className="rec-bar" role="slider" aria-label="Interview timeline" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(pos)} tabIndex={0}
          onKeyDown={(e) => { if (e.key === "ArrowRight") seek(pos + 10); if (e.key === "ArrowLeft") seek(Math.max(0, pos - 10)); }}
          onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * total); }}>
          {parts.map((p) => <span key={p.id + "-" + p.from} className={"rec-part" + (p.backup ? " backup" : "")} style={{ left: `${(p.from / total) * 100}%`, width: `${((p.to - p.from) / total) * 100}%` }} title={p.backup ? "From the backup copy" : ""} />)}
          {(v.gaps || []).map((g, i) => <span key={"g" + i} className="rec-gap" style={{ left: `${(g.from / total) * 100}%`, width: `${((g.to - g.from) / total) * 100}%` }} title={`Missing ${mmss(g.from)} to ${mmss(g.to)}`} />)}
          {markers.map((m, i) => <span key={"m" + i} className={"rec-mark " + m.kind + (m.counted ? " counted" : "")} style={{ left: `${Math.min(100, (m.at / total) * 100)}%` }} title={`${mmss(m.at)} · ${m.label}`} />)}
          <span className="rec-head" style={{ left: `${Math.min(100, (pos / total) * 100)}%` }} />
        </div>
      )}
      {(v.gaps || []).length > 0 && <div className="small" style={{ color: "var(--warn)" }}>{v.gaps.map((g) => `Missing ${mmss(g.from)} to ${mmss(g.to)}`).join(" · ")} (the connection dropped on both sides)</div>}
      {parts.some((p) => p.backup) && <div className="tiny muted">Striped parts come from the candidate's backup copy, used where the interviewer's copy is missing.</div>}
      {markers.length > 0 && <div className="col" style={{ gap: 2, maxHeight: 220, overflow: "auto" }}>
        {markers.map((m, i) => <button key={i} type="button" className="rec-row" onClick={() => seek(m.at)}><span className="mono tiny">{mmss(m.at)}</span>
          <Chip kind={m.kind === "integrity" ? (m.counted ? "bad" : "") : "brand"}>{m.kind === "integrity" ? (m.counted ? "Warning" : "Noted") : "Question"}</Chip><span className="small grow">{m.label}</span></button>)}</div>}
      {v.can_download && <div className="row wrap small">{v.pieces.filter((p) => p.status === "ready").map((p, i) => <a key={p.id} className="btn sm ghost" href={videoUrl(attId, p.id, true)}>Download part {i + 1} ({p.side})</a>)}</div>}
      {v.pieces?.some((p) => p.note) && <div className="tiny muted">{[...new Set(v.pieces.map((p) => p.note).filter(Boolean))].join(" ")}</div>}
    </div>
  );
}

export function RecordingButton({ attId }) {
  return <Btn size="sm" kind="ghost" onClick={() => { window.location.href = `/app/reports/${attId}#recording`; }}>▶ Video</Btn>;
}
