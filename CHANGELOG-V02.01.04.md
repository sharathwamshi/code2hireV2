# Code2Hire V02.01.04 · Auto-start, live scores, File under, the candidate's thank-you, and a reviewed question bank

**Version:** V02.01.04 (24 Nov 2026)

**Migration: yes.** Alembic `0012_v020104_interview_questions`. Run `alembic upgrade head` before starting the new code.
- It adds `questions.kind` (`mcq` or `interview`, default `mcq`, indexed) and `questions.meta` (JSON).
- With the SQL files instead: `backend/migrations/sql/011_v020104_interview_questions.up.sql`. Rollback: `.down.sql`, or `alembic downgrade -1`.
- Existing questions all become `mcq`; nothing else changes. Both are safe to run twice.

**Deploy:** `alembic upgrade head`, then `bash c2h-deploy.sh deploy` after pushing to git.
- Transcribing the recording needs **ffmpeg** on the server and Azure Speech (already set up on beta).

**Tests:**
- All **266** backend tests pass, on SQLite and on MariaDB 10.11. That includes 16 new ones in `tests/test_v02_01_04.py`.
- Alembic on MariaDB: 0012 applies to a V02.01.03 database, rolls back, and applies again.
- Browser checks (Chromium):
  - the room's layout; the live score and your rating; File under in the live transcript and the scorecard;
  - the candidate's thank-you and Contact the hiring team;
  - Move answer on the report; the question paper's review with a Claude draft.
- **Not checked in a browser:** the auto-start countdown on a live two-person call. A headless browser can't pass the candidate's device check, which asks them to read a sentence aloud. The server side is tested: Start runs once, keeps what was said before it, and refuses after End.

## 1. The interview starts itself
- **Built-in call:** when you and the candidate are both connected, a 5-second countdown appears.
  - "Start now" starts at once; "Not yet" holds it.
  - Then it starts like Start does: recording, Isha and the timer.
- **Outside meeting:** when the candidate opens the round, you hear a sound and see "The candidate is here: Start interview".
- What either of you said after the call connected, before the start, is kept at the top of the transcript ("Before the start").
- It never restarts an ended interview, and it doesn't fire again on reload. Pressing Start in two tabs starts it once.

## 2. Asked, captured, rated, with no clicks
- **Talking about X:** Isha follows the topic being discussed, and the live answer shows under its question.
- **Isha's score, live:** when an answer ends (the topic changes, or 20 seconds of quiet), Isha suggests a 1–5 score with a reason.
  - With Claude, she judges the answer against the good-answer points.
  - Without Claude, the score comes from the points covered, labelled "from the points covered · please check".
- **Your rating:** one optional click on 1–5 beside Isha's. Yours wins. Click it again to clear it.
- **At End:** the review uses these scores. Every answered question gets a score, and the competency ratings are drafted from them.
- **Capture line:** how many of the candidate's sentences were heard. It turns red after about 45 seconds of the interview with no candidate speech.
- **Transcribe the recording:** when the captions missed the answers, the scorecard offers to transcribe the video with Azure Speech.
  - A side's live captions are replaced only when the recording heard more words.
  - Then Isha reviews the interview again.

## 3. The room's layout
- **Right:** Isha's follow-ups, at full height. "How this works" sits there until the first follow-up arrives.
- **Left:** the video, then the current question with its live answer, points and Isha's score, then your tools (topic coverage, quick note, the next question, the capture line).
- **Bottom:** the question chips, wrapping onto a second line.
- Fixed in the browser check: the left column no longer stops at 300 px with an empty gap beside it.
- The header says "Ended · scorecard to submit" after End, instead of still saying Live.

## 4. File under… on every candidate sentence
- **Where:** the live transcript, the scorecard (where each answer was found is now open by default), and the report.
- **Groups:**
  - your selected questions;
  - from the job description, and from the resume (skills that aren't already a selected question);
  - Small talk; Not in the plan.
- During the interview, filing a sentence shows "You filed it: X". At End, Isha puts it there.
- **Review again keeps your filings.**
- An answer filed under a job-description or resume topic becomes its own question on the report, marked "From the resume" or "From the job description".
- **On the report:** a reviewer can move an answer under another question (it's scored again with that question), or remove it from the report.
  - A reason is required.
  - Each change is a new report version.

## 5. The candidate's thank-you and next steps
- **Every end:** when the interviewer ends or closes the interview, on reload, when the link is opened later, or after a dropped connection.
  - The call page checks every 10 seconds, so the candidate is never left on a dead call.
- **No AI character:** the interview was with a person.
- **What it says:**
  - what happens next: the interviewer submits their notes, the hiring team reviews them, and a person makes every decision;
  - the next round, if there is one;
  - that their camera and microphone are off, and that they can close the page.
- **Closed early:** "Your interview was stopped before the end", and the hiring team will contact them.
- **Contact the hiring team:** a short message from the end screen goes to the round's team.
- **Inbox and email:** the same message goes to their Code2Hire inbox and by email, once per interview.

## 6. MCQ tests and the question bank
- **No filler questions, ever.** When the bank has nothing for a skill, the test says so instead of adding unrelated questions.
- **Strict skill matching:**
  - "SQL databases" matches SQL; "JS" matches JavaScript.
  - "React Native" isn't React, and "Java" isn't JavaScript.
  - A job with no skills never draws from the whole bank.
- **When Claude is down:** "Claude is unavailable: questions are taken from the question bank", on the paper and in practice tests.
- **Everything Claude writes goes into the bank, by topic:**
  - MCQs;
  - Isha's interview questions, with the good-answer points, a model answer and follow-ups (shown as "Interview question" in the bank, with a Type filter).
- **Reviewed before a candidate sees them:**
  - Claude's questions are drafts until approved.
  - A hiring test can't be released with unapproved questions.
  - The paper shows "Written by Claude · needs review" on each draft, with "Approve this question".
  - "Approve all" on one paper approves its drafts with it, after a confirm. Bulk approval on a job skips papers that have drafts, and says so.
- **Correct answers spread over A–D:** no letter is correct in more than a quarter of the paper, plus one. The paper shows the split.
- **Isha uses the bank first when Claude is down:** approved interview questions, then pending ones, before her built-in ones ("From the question bank").
- Demo data: one Acme question about SQL isolation levels was labelled Python; it's now SQL (new installs only).

## Files
**Backend**
- `migrations/alembic/versions/0012_v020104_interview_questions.py`, `migrations/sql/011_v020104_interview_questions.{up,down}.sql`, `migrations/README.md`
- `models.py`: `Question.kind`, `Question.meta`
- `services/mcq.py`: strict matching, no fillers, answer balancing
- `services/papers.py`: drafts, per-question approval, the answer split
- `services/ibank.py` (new): interview questions in the bank
- `services/isha_prep.py`: saves Claude's questions; uses the bank when Claude is down
- `services/isha_review.py`: live segments and scores, your ratings, File under topics, kept filings
- `services/transcribe.py` (new): Azure Speech transcription of the recording
- `services/candidate_end.py` (new): the thank-you, inbox and email
- `services/syscheck.py`: the candidate's stage
- `routes/isha.py`:
  - Start with `pre` and `auto`;
  - `score-topic`, `topic-rating`, `file-sentence`, `transcribe`;
  - the thank-you on End and Close.
- `routes/call.py`: `end` details for the candidate; `message-team`
- `routes/reports.py`: `refile`
- `routes/rounds.py`, `routes/jobs.py`, `routes/qbank.py`
- `seed.py`

**Frontend**
- `pages/app/IshaRoom.jsx`: auto-start, live scores, capture line, layout, File under, transcription
- `components/FileUnder.jsx` (new)
- `components/ReportView.jsx`, `pages/app/Reports.jsx`: Move answer
- `pages/room/CandidateCall.jsx`: the thank-you screen, and checking for the end
- `components/PaperReview.jsx`, `pages/app/Approvals.jsx`, `components/QuestionBank.jsx`, `components/PrepareQuestions.jsx`, `pages/room/Room.jsx`
- `styles.css`
