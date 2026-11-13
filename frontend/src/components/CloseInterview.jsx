// N4 (V02.00.09): close an interview that was done (or abandoned) but is still open. Offers what fits: submit the
// scorecard from what was captured, close without a scorecard (with a reason), or interview again.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Btn, Chip, Field, Loading, Modal, Status, Textarea, useAction, useAsync } from "./ui";

export default function CloseInterview({ attemptId, onClose, onDone, onAgain, inRoom, onScorecard }) {
  const nav = useNavigate();
  const { data, error } = useAsync(() => api.get(`/isha/${attemptId}/close`), [attemptId]);
  const [reason, setReason] = useState("");
  const [run, busy] = useAction();
  const cap = data?.captured;
  const close = () => run(() => api.post(`/isha/${attemptId}/close`, { reason }), "Interview closed").then((r) => onDone?.(r));
  const score = () => { if (inRoom) onScorecard?.(); else nav(`/app/isha/${attemptId}?scorecard=1`); };
  return (
    <Modal title="Close interview" onClose={onClose} footer={<Btn onClick={onClose}>Cancel</Btn>}>
      {error ? <div className="sc-note bad">{String(error)}</div> : !data ? <Loading /> : (
        <div className="col" style={{ gap: 14 }}>
          <div className="row wrap" style={{ gap: 8 }}><Status s={data.status} />
            <Chip kind={cap.sentences ? "good" : ""}>{cap.sentences} sentence{cap.sentences === 1 ? "" : "s"} captured</Chip>
            <Chip kind={cap.videos ? "good" : ""}>{cap.videos ? `${cap.videos} video piece${cap.videos > 1 ? "s" : ""}` : "No video"}</Chip></div>
          {data.closed && <div className="sc-note calm">Closed by {data.closed.by || "Code2Hire"}{data.closed.note ? `: ${data.closed.note}` : data.closed.reason === "both_left" ? ": both people left the call." : "."}</div>}
          {data.can_score && <div className="again-opt on" style={{ cursor: "default" }}><div className="grow"><b>Submit the scorecard</b>
            <div className="small muted">{cap.sentences ? "Opens the scorecard drafted from what was captured. Change anything you disagree with." : "Nothing was captured, so you score it from your notes or the video."}</div></div>
            <Btn kind="primary" onClick={score}>Open scorecard</Btn></div>}
          {data.can_close && <div className="again-opt" style={{ cursor: "default", flexDirection: "column", alignItems: "stretch" }}>
            <div><b>Close without a scorecard</b><div className="small muted">It's marked “Not finished” with your reason. The transcript and video stay, and anyone can still submit the scorecard later.</div></div>
            <Field label="Why are you closing it?"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="For example: the interview was done outside Code2Hire." /></Field>
            <div><Btn kind="danger" busy={busy} disabled={!reason.trim()} onClick={close}>Close interview</Btn></div></div>}
          {onAgain && <div className="again-opt" style={{ cursor: "default" }}><div className="grow"><b>Interview again</b><div className="small muted">Retake after a technical problem, or re-send if the candidate missed it.</div></div>
            <Btn onClick={onAgain}>Interview again…</Btn></div>}
        </div>
      )}
    </Modal>
  );
}
