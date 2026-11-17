// CAN-015 / CAN-016 (V02.00.11): the hiring team checks a candidate's MCQ questions, with the answers, before the test.
// Swap a single question, redraw the whole paper, then approve; the candidate can start only after approval.
// RoundSample is the same view in round setup, from the pool the round draws from (with "same paper for everyone"
// the reviewer keeps that sample as the paper).
import { useState } from "react";
import { api } from "../api";
import { Btn, Chip, Loading, Modal, useAction, useAsync, useToast } from "./ui";

function QList({ qs, onSwap, busyId, locked }) {
  return (
    <ol className="paper-list">{qs.map((q, i) => (
      <li key={q.id + "-" + i} className="paper-q">
        <div className="row wrap" style={{ gap: 6 }}><b className="small">Q{i + 1}</b><Chip>{q.skill || "General"} · L{q.level}</Chip>
          {q.draft && <Chip kind="warn" title="Written by Hira and not yet approved in the question bank">Draft by Hira</Chip>}
          {q.source === "ai" && !q.draft && <Chip>By Hira</Chip>}
          {onSwap && !locked && <Btn size="sm" kind="ghost" className="right" busy={busyId === q.id} onClick={() => onSwap(q)}>Swap question</Btn>}</div>
        <div className="paper-text">{q.text}</div>
        {q.code && <pre className="code small">{q.code}</pre>}
        <ul className="paper-opts">{(q.options || []).map((o, k) => <li key={k} className={k === q.answer ? "is-answer" : ""}><span className="k">{String.fromCharCode(65 + k)}</span>{o}{k === q.answer && <b className="tiny"> ✓ correct</b>}</li>)}</ul>
        {q.explanation && <div className="tiny muted">Why: {q.explanation}</div>}
      </li>))}</ol>
  );
}

export default function PaperReview({ attemptId, name, onClose, onChanged }) {
  const toast = useToast();
  const { data, setData, error } = useAsync(() => api.get(`/rounds/${attemptId}/paper`), [attemptId]);
  const [run, busy] = useAction();
  const [swapping, setSwapping] = useState(null);
  const act = (action, body) => run(() => api.post(`/rounds/${attemptId}/paper/${action}`, body)).then((r) => { setData(r); onChanged?.(); return r; });
  const swap = (q) => { setSwapping(q.id); act("swap", { question_id: q.id }).then(() => toast("Question swapped", "good")).catch((e) => toast(e.message, "bad")).finally(() => setSwapping(null)); };
  const approved = data?.state === "approved";
  return (
    <Modal wide title={`Questions for ${name || "this candidate"}`} onClose={onClose}
      footer={data && !data.locked ? <><Btn onClick={() => act("redraw").then(() => toast("New paper drawn", "good")).catch((e) => toast(e.message, "bad"))}>Redraw all</Btn>
        <Btn onClick={onClose}>Close</Btn>
        <Btn kind="primary" busy={busy} disabled={approved || !data.questions.length} onClick={() => act("approve").then(() => { toast("Approved. The candidate can start now.", "good"); onClose(); }).catch((e) => toast(e.message, "bad"))}>{approved ? "Approved" : "Approve and let them start"}</Btn></>
        : <Btn onClick={onClose}>Close</Btn>}>
      {error ? <p role="alert">{String(error)}</p> : !data ? <Loading /> : <>
        <div className="row wrap" style={{ gap: 8 }}>
          <Chip kind={approved ? "good" : data.locked ? "" : "warn"}>{data.locked ? "Locked: the candidate has started" : approved ? "Approved" : "Waiting for your review"}</Chip>
          <span className="small muted">{data.questions.length} of {data.wanted} questions · {data.mode === "same" ? "the same paper for everyone" : "drawn for this candidate"}</span></div>
        {data.questions.length < data.wanted && <div className="sc-note warn small">The bank has fewer questions than this round asks for. Add or approve questions in the question bank, then redraw.</div>}
        <p className="small muted" style={{ margin: 0 }}>Only the hiring team sees this. The candidate never sees the answers. {data.locked ? "" : "Swap any question you don't want; approving lets the candidate start."}</p>
        <QList qs={data.questions} onSwap={swap} busyId={swapping} locked={data.locked} />
        {data.history.length > 0 && <details className="small"><summary>History</summary>{data.history.map((h, i) => <div key={i} className="tiny muted">{new Date(h.at).toLocaleString()} · {h.note}</div>)}</details>}
      </>}
    </Modal>
  );
}

export function RoundSample({ job, round, n, folders, same, fixed, onUse, onClose }) {
  const [fresh, setFresh] = useState(0);
  const { data, error } = useAsync(() => api.get(`/jobs/${job.id}/rounds/${round.index}/sample`, { questions: n, folders, fresh: fresh || "" }), [fresh]);
  return (
    <Modal wide title={`Sample paper: ${round.name}`} onClose={onClose}
      footer={<><Btn onClick={() => setFresh(fresh + 1)}>Draw another sample</Btn><Btn onClick={onClose}>Close</Btn>
        {same && data?.questions?.length > 0 && <Btn kind="primary" onClick={() => onUse(data.questions.map((q) => q.id))}>{fixed && !fresh ? "Keep this paper" : "Use this paper for everyone"}</Btn>}</>}>
      {error ? <p role="alert">{String(error)}</p> : !data ? <Loading /> : <>
        <p className="small muted" style={{ margin: 0 }}>{data.fixed && !fresh ? "This is the paper everyone gets." : same ? `A sample of ${data.questions.length} from ${data.available} approved questions. Keep it and every candidate gets exactly these questions.` : `A sample of ${data.questions.length} from ${data.available} approved questions. Each candidate gets their own draw like this, and you review it before they start.`}</p>
        {!data.questions.length ? <div className="sc-note warn">No approved questions match this round yet. Add questions to the question bank or choose folders.</div> : <QList qs={data.questions} />}
      </>}
    </Modal>
  );
}
