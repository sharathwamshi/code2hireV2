# Code2Hire V02.01.02 · Interview with Isha: video space, selected questions only

**Version:** V02.01.02 (20 Nov 2026)

**Database:** **no migration.** Alembic stays at `0011_v12_data_fixes`.

**Deploy:** `bash c2h-deploy.sh deploy` after pushing to git.

**Tests:**
- All **250** backend tests pass on SQLite and on MariaDB 10.11.
- The `walk14` browser walkthrough passes 7 of 7.
- New test: `test_unanswered_selected_questions_need_a_decision_and_show_only_when_ticked`.
- Older tests now skip unanswered questions explicitly, using `tests/scorecard_helper.py`.

## 1. Interview room: the video uses its space
- **The problem:** when docked, the call box kept a fixed wide slot.
  - A normal camera picture left black bands on both sides.
  - The follow-ups panel was squeezed.
  - The area under the current question stayed blank.
- **Now:**
  - **The docked call is as wide as the candidate's picture** at the available height, with no black bands. The rest of the row goes to Isha's follow-ups. When chat is open, the box widens by the chat's width.
  - **The question card fills the height** under the topic cards. Its two sides scroll on their own.
  - **Before the call:** a compact card with the candidate's name and how to join, instead of a large empty box.
  - **Popped out:** a slim card, "Video is in its own window · Put it back here".
  - **Docked by default for every interview.** Popping out lasts for that interview only; before, the choice was remembered forever.
  - **The video restarts playing** after docking or popping out, and when the candidate's camera comes back. If the browser blocks it, the picture says "▶ Click to resume video" instead of staying frozen.
  - **The pop-out can be dragged at every size,** including the largest.

## 2. Scorecard and report: only the questions you selected
- **Selected questions with no answer:** a new panel on the scorecard lists every planned question Isha didn't find in the transcript. The Wrap-up and questions skipped during the interview aren't listed. For each one:
  - **It was asked: pick its answer.** Choose a quote from the transcript. It's filed under that question and scored.
  - **Skip:** with an optional reason, and a **Show on report** checkbox (off by default).
- **A decision is required for each one before submitting:** "Decision needed for: SQL · Hands-on, AWS · Basics. Pick its answer from the transcript, or press Skip." The rows are outlined. The server checks the same and returns `fields.undecided`.
- **Extra questions you asked** (not in the plan) are listed with a **Show on report** checkbox. They're left off the report unless ticked.
- **Skipped competencies** also have **Show on report**. They're shown only when it's ticked, and never counted.
- **The report:**
  - **Question by question** has only the selected questions that were answered, in plan order.
  - **Follow-ups fold into their question,** shown under its answer, with a "2 follow-ups" chip. They're no longer rows of their own, and their answers count in the question's "In brief".
  - **A skipped question you ticked** shows as "Skipped by the interviewer: not counted", with your reason. It has no score and no expected points.
  - **The "not asked: …" list is gone** from the header.
  - **Answer coverage and Isha's summary** count only answered questions.
  - **The candidate's view** never shows skipped questions.

## 3. Isha's review and her default questions (found while making the manual)
- **Greetings are small talk.** "Hi… can you hear me okay?" is no longer filed as a question "Not in the plan".
- **Short follow-ups** that point back ("What was your own part in that?") are filed under the question before them.
- **Extra questions get real good-answer points** instead of "A direct, correct answer about Not in the plan".
- **Default questions, built without Claude:**
  - each resume line is quoted once, so Python, SQL and AWS don't repeat the same line;
  - each skill's first question uses a different type;
  - the role scenario reads properly ("Part of this job is to design APIs…").

## Files
- **Backend:**
  - `backend/routes/isha.py`: unanswered and extras in the room state, decisions on submit, report questions, summaries
  - `backend/services/isha_review.py`: small talk, follow-ups
  - `backend/services/isha_prep.py`: resume lines, type variety, duty wording
  - `backend/services/ai.py`: good-answer points for extra questions
  - `backend/config.py`: the version
- **Frontend:**
  - `frontend/src/components/CallWindow.jsx`: fit-to-picture width, replay, drag
  - `frontend/src/pages/app/IshaRoom.jsx`: the call slot, the decisions panel, Show on report
  - `frontend/src/components/ReportView.jsx`: folded follow-ups, skipped and extra questions
  - `frontend/src/styles.css`
  - `frontend/src/version.js`, `frontend/package.json`
- **Tests:**
  - `backend/tests/scorecard_helper.py` (new)
  - `backend/tests/test_v02_01_01.py`
  - `test_v06`, `test_v13` and the other scorecard tests
