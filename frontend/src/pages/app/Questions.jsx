import QuestionBank from "../../components/QuestionBank";
import { PageHead } from "../../components/Shell";

export default function Questions() {
  return (
    <>
      <PageHead title="Question bank" sub="Organise questions in folders, track every version, preview what candidates see, and choose which folders each MCQ round draws from." />
      <QuestionBank />
    </>
  );
}
