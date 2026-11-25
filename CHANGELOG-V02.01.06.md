# Code2Hire V02.01.06 · Isha decides, End never freezes, better follow-ups, Leave call

**Version:** V02.01.06 (25 Nov 2026)

**Migration: none.** Everything new is kept in the interview's existing result data. Deploy as usual: `bash c2h-deploy.sh deploy` after pushing to git.

**Tests:**
- All **284** backend tests pass, on SQLite and on MariaDB 10.11. That includes 11 new ones in `tests/test_v02_01_06.py`.
- Browser check (Chromium, dark room): End opens the "Wrapping up" window at once; the scorecard opens by itself with Isha's decision (1.8 s without Claude); "Agree with Isha and submit" → the report shows Isha's assessment; the candidate sees the thank-you.
- Older tests were updated where behaviour changed on purpose:
  - changing Isha's score now needs a reason;
  - the old "Clarify" follow-up is now the "Check" purpose.

**Your two decisions, as recommended:**
- An unsubmitted review reaches the hiring team after **24 hours**, marked "not yet confirmed".
- Changing Isha's decision **needs a one-line reason**.

## 1. End interview: the call is cut first, and nothing freezes
- **The call ends at once for both of you** when you confirm End. The candidate sees the thank-you screen, and your camera and microphone turn off.
- **Then, in order:** the captions stop (the last half-heard sentence is kept), and the recording saves its last minutes.
- **The server answers in under a second.** Isha's full review and the candidate's thank-you run in the background.
- **A "Wrapping up the interview" window** shows every step as it happens:
  - Call ended · Captions stopped (with how many sentences were heard) · Saving the recording;
  - Isha is reading the transcript ("3 of 7 planned questions were asked");
  - Isha is scoring each answer (each score appears);
  - Isha is going through the whole conversation;
  - Isha is rating the competencies; Isha is deciding (the recommendation and why);
  - Thank-you to the candidate.
- **When the steps finish, the scorecard opens by itself.**
- **If Claude is slow (over 45 seconds):** "Open scorecard now" uses Isha's quick scores, which update when she's done.
- **A failed step says why,** and **Retry** runs the steps again.
- **Closing the window doesn't stop anything.** The header shows "Isha is reviewing… 60%", and reloading picks up where it was. While the recording is still saving, closing the tab asks first.
- "Open scorecard" now opens **Isha's review as she left it**. Before, it rebuilt the draft without Claude.

## 2. Leave call is back, first on the bottom bar
- A red **Leave call** button sits first on the left of the bottom bar.
  - It means *you* step out: the interview stays open, the candidate waits, and **Rejoin** is in the video area.
- **End interview** stays at the far right.

## 3. Isha reviews the whole conversation and decides
- **The whole conversation, not only the planned questions.** Isha lists every topic the candidate really talked about, planned or not (skills, projects, situations), each with:
  - a 1–5 score;
  - the candidate's own words as evidence;
  - what the answer showed, and what was missing.
  - Topics that weren't in your plan are marked "Not in the plan".
- **A competency's score counts what was said about it anywhere** in the interview, not only under its planned question.
- **Isha's decision:**
  - **Proceed / Hold / Do not proceed**, with **confidence** (high, medium or low) and a **one-line reason**;
  - **strengths**, **concerns** and **red flags** (contradictions with the resume, vague claims, important things never covered);
  - **where the candidate stands among this job's candidates** ("2 of 5 · same questions" when they had the job's question set).
- **Fixed score descriptions** (what a 2, a 3 or a 4 looks like), so every candidate is judged the same way.
- **"Not enough evidence":** with fewer than 6 sentences heard, Isha says so instead of guessing. She points to transcribing the video, and "Agree" isn't offered.
- **Low confidence never leads to "Do not proceed":** Isha says Hold instead, and explains why.

## 4. The interviewer confirms instead of filling in a form
- The scorecard opens with **Isha's decision at the top** and her scores already filled in. Competencies she couldn't assess start as Skip.
- **Agree with Isha and submit:** one click.
- **Change anything** (a score or the recommendation) and a **one-line reason is required.** The button then says "Submit with my 2 changes".
- **On the report: "Isha's assessment" first**, then the interviewer's view:
  - "Priya agreed with Isha", or each change, e.g. "Python: Isha 4 → 2 · 'No real project behind it'".
- **After 24 hours with no scorecard,** Isha's review goes to the report as "Not yet confirmed by the interviewer", and the round's team is notified. The interviewer can still confirm it afterwards.
- A person still makes the hiring decision, as before.

## 5. Follow-ups: varied, and only when an answer pauses
- **Isha writes follow-ups when the candidate pauses for 3 seconds,** not after every sentence. The list stays still while they talk.
- **Every follow-up has a purpose,** chosen from what the answer is missing:
  - Missing point · Proof (numbers, results) · Your part · Why · What went wrong · Trade-off · Scale;
  - Check (doesn't match the resume, or contradicts something said earlier) · Link (to the resume or the job) · Challenge.
- **Rules:**
  - at most 3 at a time, each with a different purpose;
  - unused purposes come first;
  - a purpose never comes twice in a row;
  - "Your part" at most once per topic;
  - no wording is ever repeated.
- **When the answer is complete,** Isha stops probing: "Strong answer: move on to X", or one Challenge.
- **When Claude is down,** there are 4–5 phrasings per purpose, built around the candidate's own topic. That replaces the three fixed templates, which made every follow-up sound the same.
- **Prepared follow-ups** show only for a point that's still missing, and stay until it's covered or asked.
- **Each card shows its purpose and reason,** e.g. "Proof · No numbers, results or example yet".

## Files
**Backend**
- `services/wrapup.py` (new): the background steps after End
- `services/isha_review.py`: `consolidate()` (the whole conversation); topics kept across Review again
- `services/scorecard.py`: Isha's decision (`decide()`), `rank()`, topic-blended scores, "not enough evidence"
- `services/ai.py`: follow-up purposes, phrasings, the new rules for Claude
- `services/housekeeping.py`: publishes unconfirmed reviews after 24 hours
- `routes/isha.py`:
  - a fast `end`, and `wrapup` (Retry);
  - `scorecard` with `agree`, required reasons, and `publish()`;
  - `publish_unconfirmed()`;
  - per-answer follow-ups (`defer`), and purpose tracking.

**Frontend**
- `pages/app/IshaRoom.jsx`: End cuts the call first, the "Wrapping up" window, Leave call, Isha's decision on the scorecard, Agree and submit, required reasons, per-answer follow-ups
- `components/ReportView.jsx`: Isha's assessment and the interviewer's view
- `styles.css`, `version.js`, `package.json`
