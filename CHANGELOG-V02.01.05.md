# Code2Hire V02.01.05 · A new interview room (dark or light), quiet caption fallback, job question sets, short questions

**Version:** V02.01.05 (24 Nov 2026)

**Migration: yes.** Alembic `0013_v020105_job_question_sets`. Run `alembic upgrade head` before starting the new code.
- It adds `questions.job_id` (indexed): the job an interview question was kept for.
- With the SQL files instead: `backend/migrations/sql/012_v020105_job_question_sets.up.sql`. Rollback: `.down.sql`, or `alembic downgrade -1`.
- Both are safe to run twice.

**Deploy:** `alembic upgrade head`, then `bash c2h-deploy.sh deploy` after pushing to git.

**Tests:**
- All **273** backend tests pass, on SQLite and on MariaDB 10.11. That includes 7 new ones in `tests/test_v02_01_05.py`.
- Alembic on MariaDB: 0013 applies to a V02.01.04 database, rolls back, and applies again.
- Browser checks (Chromium) of the room, in dark and light, at 1440×860 and 1360×700:
  - before the start, running, and after End;
  - the status and Questions popovers, the side panel (transcript with File under, resume), Isha on/off and folding;
  - the scorecard over the dark room;
  - Prepare questions for a second candidate, and the job's Interview questions tab.
- Two older tests checked exact question wording that changed on purpose ("Your resume mentions…", "Payments are failing…"); they were updated.

## 1. The interview room, redesigned
Laid out like the reference screen you shared.
- **Header, one row:**
  - the job title, with the round and the candidate under it;
  - **Candidate resume**; **● Recording**;
  - one **status** button: "All good", or "2 to check" in amber or red;
  - **time remaining** (from the round's planned length) and **time elapsed**;
  - the **light/dark switch** (☀/☾);
  - Join / Start / Open scorecard when they apply, and **⋯** for the rest.
- **The status button** holds everything that used to be a row of chips:
  - your camera and microphone, and the call connection (Try again, Ring again);
  - recording and caption problems;
  - which speech engine is listening;
  - the caption source (Call captions, My microphone, Other meeting tab) and "Isha reads captions";
  - Claude and Azure set-up notes, echoes, and the capture line.
- **⋯** holds: Leave the call, Check camera and microphone, Keep these questions for this job, Technical problem, Close interview, and the theme.
- **The video is the main thing.**
  - The candidate is large, with their name and "candidate" at the bottom left, plus "muted" or "left the tab" when it applies.
  - A green **Speaking** badge appears when they talk.
  - **You** are a picture-in-picture at the top right, labelled "Me". Its border turns green when you speak.
  - Before the call: the candidate card, their status and Join. The auto-start countdown, "Not yet" and "The candidate is here" now sit over the video.
- **Under the video, two strips:**
  - **What the candidate is saying now**, one line. Click it for the whole transcript.
  - **The question in play:** your name, what Isha hears you talking about, and the question.
    - On the right: Isha's score for that answer, your 1–5 rating, and **Points** (the good-answer points, folded away until you need them).
    - "Good time to move on" appears here with the next question.
- **Bottom bar:**
  - microphone and camera;
  - **Switch device:** camera, microphone and speaker;
  - **Enable blur:** uses the camera's own background blur where the browser offers it (Chrome on recent Windows and Mac cameras). Elsewhere the button is greyed out and says why;
  - **Share screen**;
  - **Questions:** your plan as a list with status dots and scores, Asked / Skip, and Keep for this job;
  - **Transcript**, **Chat**, and **End interview** in red.
- **Isha's panel, on the right:**
  - **Fold** it with ›.
  - **Ask Isha**; **↻** for new follow-ups now; **⏻** to pause her suggestions (everything is still recorded and reviewed at the end).
  - **Follow-ups grouped by what they pick up on:** From the conversation, From the resume, From the job description, From your plan.
    - Each has its evidence above it, for example *Conversation evidence: "At my last company I led…"* or *Not covered yet: A case where it's the wrong choice*.
    - Pin and Asked appear under each one.
  - "Asked something else? Type it here" stays at the bottom.
- **Side panel** (resume, candidate, plan, rounds, notes, integrity, transcript, chat) opens over the left side, with tabs. The transcript keeps File under on every candidate sentence.
- **Dark is the default.** The choice is remembered on this computer. Dialogs (scorecard, Prepare questions, system check) stay light in both themes, so they're easy to read.
- Small screens: at 1360×700 everything fits without scrolling. Below 860 px wide, the panels stack.

## 2. No disruption when Azure drops
- A drop is retried quietly.
- If Azure drops **twice within a minute**, or isn't back **within 5 seconds**, captions carry on with the browser's speech engine (Chrome and Edge).
- They switch back to Azure in the background once it works again (checked every 90 seconds). Listening to another meeting's tab can only use Azure, so there it keeps retrying.
- **The half-heard sentence is kept** when a drop happens, instead of being lost.
- **No pop-up messages while listening.** The status button shows which engine is listening. On the candidate's side, the switch is reported to the interviewer too.
- **Gaps are recorded.** Any stretch over 10 seconds with no captions, on either side, is saved. The status button shows "Captions missed about 40 s".
  - When the gaps add up to 30 seconds or more, the scorecard offers **Transcribe the video** (when Azure Speech and ffmpeg are set up on the server).

## 3. Keep questions for the job, for the next candidates
- **In Prepare questions:**
  - each question gets **Keep for this job**;
  - **Save as this job's set** keeps all your chosen questions at once;
  - the same option is in the room's Questions list and the ⋯ menu.
- **The next candidate for the same job** gets the kept questions first ("This job's set"), already selected. Claude only writes what they don't cover, plus questions about that candidate's own resume. When the set covers everything, Claude isn't called at all.
- **Questions about one candidate are never kept.** Anything quoting or naming their resume is marked "About this candidate only".
- **The job page has a new Interview questions tab:**
  - see the set, edit a question's wording (a new version in the bank), or remove it from the set (it stays in the bank);
  - editing and removing need "edit job" permission.
- Keeping a question counts as the hiring team's review, so kept questions are approved in the bank, with a note of who kept them for which job.

## 4. Short questions, realistic to ask aloud
- **Claude's instructions now ask for one sentence of at most 25 words**, read out in one breath. For example: "How would you speed up a slow page that lists 10,000 orders?"
  - The twist, the constraint, the scale and "when is it the wrong choice" become the **follow-ups**.
  - Follow-ups are short too (under 18 words).
- **Every question is checked, whatever wrote it** (Claude, the bank, the job's set or the built-in templates):
  - at most one short lead-in and the question;
  - the other sentences become follow-ups ("You have two weeks and can't stop new features. How does that change your answer?");
  - instructions like "say it out loud" are dropped.
  - If a question is still long, it's marked "Long to say" in Prepare questions.
  - Your own questions are never changed.
- **The built-in questions were rewritten** as single short questions. For example:
  - before: "Explain Python the way you would to a new teammate, in about a minute. Then give one case where using it is the wrong choice."
  - now: "How would you explain Python to a new teammate?", with "When is Python the wrong choice?" as a follow-up.
- Follow-ups from the conversation quote at most 10 of the candidate's words.

## Files
**Backend**
- `migrations/alembic/versions/0013_v020105_job_question_sets.py`, `migrations/sql/012_v020105_job_question_sets.{up,down}.sql`, `migrations/README.md`
- `models.py`: `Question.job_id`
- `services/isha_prep.py`: `speakable()`, the shorter prompt, rewritten built-in questions, the job's set first
- `services/ibank.py`: `personal()`, `job_set()`, `keep()`, `match_set()`
- `services/ai.py`: follow-ups name their evidence and stay short
- `routes/isha.py`: `keep`, `followups` (refresh), `caption-gap`, evidence on every follow-up, personal flags in Prepare questions
- `routes/call.py`: the candidate's `caption-gap`
- `routes/jobs.py`: `jobs/<id>/interview-set` (list, edit, remove)
- `config.py`: version

**Frontend**
- `pages/app/IshaRoom.jsx`: the new room, the theme switch, devices, blur, popovers, Isha's panel
- `lib/speech.js`: the quiet Azure ⇄ browser fallback, kept sentences, gaps
- `pages/room/CandidateCall.jsx`: engine switches and gaps from the candidate's side
- `components/PrepareQuestions.jsx`: Keep for this job, Save as this job's set, "About this candidate only", "Long to say"
- `pages/app/Jobs.jsx`: the Interview questions tab
- `styles.css`: the room in dark and light
- `version.js`, `package.json`
