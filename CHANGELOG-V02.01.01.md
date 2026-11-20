# Code2Hire V02.01.01 · Isha reviews the whole interview

**Version:** V02.01.01 (20 Nov 2026).

**Database:** **no migration.** Alembic stays at `0011_v12_data_fixes`. Everything new lives in fields that already exist:
- the transcript (`turns`);
- the interview's state (`round_attempts.result`);
- the report (`reports.sections`).

**Deploy:** `bash c2h-deploy.sh deploy` after pushing to git. The script now **installs ffmpeg** if the server doesn't have it. ffmpeg is needed to mix Hira's voice into AI-interview videos.

**Tests:**
- New `backend/tests/test_v02_01_01.py` (14 tests).
- All **249** backend tests pass on SQLite and on MariaDB 10.11.
- Updated older tests for the new rules:
  - `test_v07`: moving an answer during the interview is only a hint.
  - `test_v13`: missing ratings are listed, and Skip is explicit.

**Browser walkthrough:** `walk14` passes 7 of 7 steps. The earlier walkthroughs were not re-run for this build (walk5 needs one line updated: the live rating card is gone by design).

## 1. Live interview: record everything, file nothing
**The problem:** answers were filed under whichever question was "current". If the interviewer didn't mark questions, everything piled under one question, and the others showed "Not asked".

**Now:**
- **The whole interview is recorded:** both speakers, in order.
- **Nothing is filed during the interview.** "Mark as asked" is still there, but it's **only a hint**. If the interviewer forgets to click, or clicks the wrong question, everything still counts.
- **The question cards show topic coverage only:**
  - **Not touched**;
  - **Touched**;
  - **Well covered**;
  - **Talking now**.

  It's worked out from the whole transcript so far. A skill's topic needs the skill to come up ("SQL", "AWS"): words every question shares ("explain", "example") don't count.
- **Beside the current topic:**
  - its good-answer points, marked **Heard / Partly / Not yet**;
  - a hint for which point to follow up on.
- **The right-hand panel:**
  - **Topic coverage** (well covered / touched / not touched);
  - the topics not touched yet;
  - the quick note.
- **Removed:** the per-question rating, and the "this answer sits under the next question" box with its Move menu.
- **Follow-ups** keep coming as before (panel and Ask Isha).

## 2. At the end: Isha reads the whole transcript
When the interview ends, Isha reviews the whole transcript and decides:
- which planned topics were covered, in any order;
- follow-ups;
- extra questions (shown as **Not in the plan**);
- small talk.

She does it with **Claude**. Without Claude, she matches by keywords, and the scorecard says **"Matched by keywords"** so the interviewer checks it.

The keyword method:
- An answer that clearly belongs to another planned topic (it names that topic's skill) goes there, even under a question that was clicked.
- The candidate's opening words, before any question, go to the **Introduction**.
- Greetings and short chat are small talk.
- Anything else stays as **Not in the plan**. **No answer is dropped.**
- Interviewer remarks inside an answer ("Nice, go on") stay with that answer in the report.

## 3. Scorecard
- **Move a quote:** under "Show where each answer was found", every quote has **Move to…**. Choices: any topic, Small talk, or Not in the plan. Both topics are scored again, and the draft scores are rebuilt.
- **Review again**, **Match by keywords** and **Undo** work as before.
- **Every competency needs a rating 1–5 or an explicit Skip.**
  - Skip is a button of its own. Isha's draft no longer leaves scores blank as a silent "skip".
  - **The skip reason is optional:** a "Why skip? (optional)" field appears under a skipped competency.
- **Missing ratings get a clear message, not "Something went wrong":** "Rating not received for: Django, AWS. Rate each from 1 to 5, or press Skip if you didn't assess it."
  - The rows are outlined and the screen scrolls to the first one.
  - The server checks the same and returns the list (`fields.missing`).
- **In the report:** a skipped competency shows **"Skipped by the interviewer: not counted"**, with the reason if one was given. It's left out of every score.

## 4. Summaries in the report
- **Generated on submit** for both live F2F interviews and AI interviews with Hira:
  - **"In brief":** a 2–3 line summary of each question or topic;
  - **Isha's summary:** an overall summary, with strengths, gaps and claims to check.
- Written by Claude. Without Claude, they're built from the answers' key sentences, and labelled so.
- **Share with the candidate:** off by default. On the report, two switches:
  - **Overall summary**;
  - **Summary of each question**.

  The overall text can be edited before sharing. The candidate sees it with their feedback, never the scores, quotes or notes. Endpoint: `POST /api/reports/<id>/share-summaries`. The change is logged.
- **Not in the report:** the Ask Isha chat and the candidate chat.

## 5. Hira's voice in the AI-interview video
**The problem:** the video was silent while Hira spoke when:
- the browser's own voice was used (Azure not set up, or a request failed): no website can record it;
- her opening lines played before the recording started.

**Now:**
- **The server keeps every line Hira says,** with the time she said it.
  - With Azure, it keeps the audio itself.
  - With the browser voice, it keeps the text.
- **When a recorded piece is finished,** ffmpeg mixes her voice into the candidate's video at the right moments.
  - The video picture isn't re-encoded.
  - Lines the browser spoke itself are made again on the server (Azure, or espeak-ng if installed).
- **The browser no longer mixes Hira's voice into the recording** when the server can do it, so she isn't heard twice.
- **Captions:** the player has a **"Hira's questions"** caption track (`captions.vtt`). It's on by default when her voice couldn't be mixed in.
- **The piece's note says what happened,** e.g. "Hira's voice included (12 of 12 lines)".
- **Without ffmpeg** the video saves as before, and the captions still work.

## 6. Ask Isha: a full assistant for the interview
The interviewer shouldn't need any other AI tool. Ask Isha now:
- **Finds questions on any skill and level.** "Get me 5 simple SQL questions" returns 5 questions, each with:
  - its level;
  - what a good answer covers;
  - a **model answer**.
- **Uses the question bank:**
  - **Offline (no Claude),** she still finds the questions in the bank (matched by skill and easy / medium / hard) and in the plan.
  - **With Claude,** she reuses the bank questions when they fit.
- **Also:** checks whether an answer is correct, explains concepts, writes harder follow-ups, suggests what to ask about a resume claim, and helps with the plan and time ("12 of 45 minutes used").
- **Stays on topic:** she answers only about hiring and Code2Hire, and politely declines anything else.
- **Each suggested question can be:** opened (**Show good answer**), pinned, added to the plan, or copied.
- **Starter prompts** show when the chat is empty.
- **The chat stays private.** It is never added to the report.

## Files
- **New:**
  - `backend/services/isha_review.py`
  - `backend/services/hira_audio.py`
  - `backend/tests/test_v02_01_01.py`
- **Changed:**
  - **Backend:**
    - `backend/routes/isha.py`: review at End, move-quote, Skip and missing ratings, summaries, live topics, Ask Isha context
    - `backend/routes/reports.py`: share-summaries, the candidate view
    - `backend/routes/rounds.py`: AI-interview summaries, the `hira_merge` flag
    - `backend/routes/speech.py`: keeps Hira's lines
    - `backend/routes/recordings.py`: merge, the captions endpoint, `hira_voice`
    - `backend/services/ai.py`: `answer_summaries`, `bank_questions`, the Ask Isha upgrade
  - **Frontend:**
    - `frontend/src/pages/app/IshaRoom.jsx`
    - `frontend/src/components/ReportView.jsx`
    - `frontend/src/components/RecordingPlayer.jsx`
    - `frontend/src/lib/speech.js`
    - `frontend/src/lib/recorder.js`
    - `frontend/src/pages/room/Room.jsx`
    - `frontend/src/styles.css`
  - **Deploy:** `deploy/c2h-deploy.sh` installs ffmpeg
