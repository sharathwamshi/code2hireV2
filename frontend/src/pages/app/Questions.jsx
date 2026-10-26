import { useState } from "react";
import { api } from "../../api";
import { AgentNote } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, useAction } from "../../components/ui";
import { QuestionEdit, QuestionTable } from "../admin/Admin";

export default function Questions() {
  const [nw, setNw] = useState(false);
  const [k, setK] = useState(0);
  const [run] = useAction();
  return (
    <>
      <PageHead title="Question bank" sub="Your company's MCQ questions. Rounds pick from these first, then the global bank." actions={<Btn kind="primary" onClick={() => setNw(true)}>Add question</Btn>} />
      <AgentNote agent="hira">I can draft questions for any skill and level. Drafts stay “pending” until someone on your team approves them, so nothing unchecked reaches a candidate.</AgentNote>
      <QuestionTable key={k} endpoint="/company/questions" scopeToggle save={(id, p) => api.patch(`/company/questions/${id}`, p)} generatePath="/company/questions/generate" />
      {nw && <QuestionEdit q={{ text: "", options: ["", "", "", ""], answer: 0, skill: "", level: 3 }} onClose={() => setNw(false)} onSave={(p) => run(() => api.post("/company/questions", p), "Added").then(() => { setNw(false); setK(k + 1); })} />}
    </>
  );
}
