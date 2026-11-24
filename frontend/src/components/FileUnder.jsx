// V02.01.04: "File under…": one grouped list of every topic an answer can go under: the selected questions, skills
// from the job description and from the resume that aren't in the plan, then Small talk / Not in the plan.
export const TOPIC_JD = "From the job description: ";
export const TOPIC_RESUME = "From the resume: ";

/** The same "normal form" the server uses to recognise a sentence (case, punctuation and spacing ignored). */
export const normSentence = (t) => (t || "").toLowerCase().replace(/[^\p{L}\p{N}\s_]/gu, " ").split(/\s+/).filter(Boolean).join(" ");

export default function FileUnder({ topics, current, onPick, disabled, label = "File under…", ariaLabel = "File this sentence under a topic" }) {
  const t = topics || { selected: [], jd: [], resume: [], other: ["Small talk", "Not in the plan"] };
  const not = (x) => x !== current;
  return (
    <select className="select file-under" value="" disabled={disabled} aria-label={ariaLabel} onChange={(e) => { if (e.target.value) onPick(e.target.value); }}>
      <option value="">{label}</option>
      {t.selected?.length > 0 && <optgroup label="Your selected questions">{t.selected.filter(not).map((x) => <option key={"s" + x} value={x}>{x}</option>)}</optgroup>}
      {t.jd?.length > 0 && <optgroup label="From the job description">{t.jd.map((x) => <option key={"j" + x} value={TOPIC_JD + x}>{x}</option>)}</optgroup>}
      {t.resume?.length > 0 && <optgroup label="From the resume">{t.resume.map((x) => <option key={"r" + x} value={TOPIC_RESUME + x}>{x}</option>)}</optgroup>}
      <optgroup label="Other">{(t.other || ["Small talk", "Not in the plan"]).filter(not).map((x) => <option key={"o" + x} value={x}>{x}</option>)}</optgroup>
    </select>
  );
}
