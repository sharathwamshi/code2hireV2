# Code2Hire V02.00.12 · consolidated gap analysis (General UI, AI F2F, 17 Nov reports) and "every answer is B"

This release covers the consolidated gap analysis:
- the 23 unique issues A1–E6;
- the 14 foreseen bugs F1–F14;
- the finding that nearly every MCQ answer was option B.

It follows the decisions recorded in the gap-analysis doc:
- **A1:** paper review is always on.
- **C4:** MCQ rounds are recorded.
- **B5:** Today shows everything on your jobs.
- **E1:** Clear on all list pages.
- **E2:** the job visibility column is hidden.
- **E3:** candidates never see the name Isha, with no change in behaviour.

**Version:** V02.00.12 (18 Nov 2026).
**Database:** migration **010** / Alembic `0011_v12_data_fixes`. It **has no schema change**, only data fixes (see Deploy).
**Tests:**
- New `backend/tests/test_v12.py` (19 tests).
- All **220** backend tests pass on SQLite and on MariaDB 10.11.
- Alembic 0011 was run on MariaDB against a V02.00.11 database:
  - it reordered all 37 starter questions to 10 / 9 / 9 / 9 across A–D (was 33 of 37 at B);
  - it survives down and up;
  - a second run changes nothing.

**Browser walkthroughs:** the new `walk12` passes 15 of 15 steps. The earlier walkthroughs (walk5 to walk11) still pass, 132 steps in all. walk10 was updated because the job-search "Reset" button is now "Clear filters".

## Deploy
1. Back up the database **and the `UPLOAD_DIR` folder** (F12: resume files and recordings live there).
2. Deploy the code, rebuild the frontend and restart.
3. Run the data fixes once:
   - With Alembic: `alembic upgrade head`.
   - Without Alembic: `cd backend && DATABASE_URL=... python -m services.data_v12`.

   Both print what they changed and are safe to run again.
4. **Behaviour changes**
   - **MCQ papers:**
     - Every MCQ paper is reviewed before the candidate starts. The setting can no longer be switched off.
     - Papers are drawn from the question bank only when the invite is sent, so inviting many candidates is quick (F9).
     - When the bank is short, the reviewer presses **Ask Hira for N more**.
   - **Hiring MCQ rounds are now video recorded**, like the AI interview. The candidate is asked for camera and microphone, and the system check includes the recording test.
   - **AI interview settings:** the time limit must allow about 2 minutes per question. For example, 8 questions need at least 16 minutes.

## MCQ answers were nearly always B (A2, A3, A5, F2)
- **Root cause 1:** the 37 starter questions had the right answer at B 33 times, and options were never shuffled.
- **Root cause 2:** when Claude's reply could not be read, built-in filler questions (always B, generic wording) filled the paper.
- **Fixes:**
  - **Every paper shuffles each question's options**, and the answer moves with them.
    - "All of the above"-type options keep their place.
    - The reviewer, the candidate and the grading all use the same shuffled order.
  - **The bank is rebalanced once** by the data fix. Each question gets a new version, "Options reordered (V02.00.12)". Old attempts are frozen first, so their scores can't change.
  - **The starter bank is balanced** in new installs too.
  - **Hira's prompt** now asks for:
    - mixed question styles (concept, code output, debugging, scenario, best practice);
    - right answers spread across A–D;
    - believable wrong options.
  - **Built-in fillers are never used in hiring rounds** (practice only). Their own answers are spread too.
- **A5, reading Claude's replies:**
  - The JSON is read from the first `{` or `[`, so code fences inside a question no longer cut it in half ("Unterminated string").
  - A reply cut off at the length limit keeps every complete item instead of failing.
  - The interview plan has a larger reply limit.

## Fixes
| Id | What changed |
|---|---|
| A1 | **Papers are easy to find and approve:**<ul><li>**Approvals → MCQ papers** lists every waiting paper by job, with **Approve all** and **Review questions**.</li><li>Today shows a **"Check … questions"** card that opens the review directly.</li><li>Interviewers and people assigned to the job can review too, and the Approvals menu item shows for them.</li></ul> |
| A4 | **Short banks and short interviews are explained:**<ul><li>Round setup says how many questions each paper will start with when the bank is short.</li><li>An AI interview's time limit is checked against its number of questions.</li></ul> |
| B1 | **Isha's plan stays on the job:**<ul><li>At least two in three questions name a job skill or duty.</li><li>Resume items are only used when they relate to the job. Education lines are never used.</li><li>Built-in questions are worded for any field, not only software.</li><li>The "built-in questions" chip now reflects **this** plan, not some other AI call that failed.</li></ul> |
| B2, F7 | **Text boxes in dark panels are readable:** typed text is dark on white in every dark panel (call window, chat, side panel, bulk bars). One shared rule covers them all. |
| B3 | **Calls hold up better on weak networks:** video is capped at about 500 kbps, and the voice is sent with high priority. On a weak line the picture drops resolution first, then the sound. |
| B4, F3 | **The right people hear about a pause:**<ul><li>Pause and "candidate is waiting" alerts go to everyone on that job: the creator, whoever sent the invite, people assigned to the job, the interviewer, and the company's recruiters, managers and admins.</li><li>The link opens the round's report page, where **Let them continue** is.</li></ul> |
| B5 | **Today shows all interviews on your jobs:** every upcoming interview on jobs you created or are assigned to, as well as interviews you run yourself. Each invite also records who sent it, and the data fix fills this in for old invites from the audit log. |
| C1 | **The camera no longer blinks:** the camera picture is no longer reset every 1.5 s. The away-cover waits 2 s, so a browser prompt doesn't flash it (F4). |
| C2, C3 | **Captions keep up:** the AI interview keeps **one** listening connection for the whole interview, instead of reconnecting for every question. While Hira speaks, what the microphone hears is ignored. The speech token is fetched before the first answer. |
| C4 | **Hiring MCQ rounds are video recorded.** The recording shows on the report page like an AI interview. |
| D1, F5 | **Candidate feedback is written once:**<ul><li>It is written when the report is made (or on first view) and saved, so the candidate page opens at once.</li><li>It no longer changes between views or between the screen and the PDF.</li><li>It is rewritten only when the report itself changes.</li></ul> |
| D2 | **Numbers open what's behind them:**<ul><li>**Analytics** numbers open the interviews or reports lists already filtered, or the report builder already run.</li><li>On a **job page**, a stage number opens Candidates filtered to that stage.</li><li>Links like `/app/reports?status=awaiting_review` open the list filtered.</li></ul> |
| D3, F14 | **The date range applies everywhere on Analytics:**<ul><li>It now applies to Interviewer calibration, Question quality and "Reports to review".</li><li>The page says "Showing the last N days".</li><li>"Avg hours to complete" is measured from pressing Start, not from the invite.</li></ul> |
| D4 | **No more arrows on the tabs:** tabs no longer show a scrollbar with up/down arrows. |
| E1 | **Clear filters on every list:** every list page shows **Clear filters** as soon as a search or filter changes, and it puts the list back as it opened. On the candidate's job search, "Reset" is renamed to the same. |
| E2 | **No Visibility on the jobs list:** the jobs list and job header no longer show Visibility. It is still set in Create and Edit job. |
| E3 | **Candidates never see the name Isha:**<ul><li>Covers round names ("Live interview"), consent text, notifications, Disha's replies and feedback.</li><li>Only phrases like "with Isha" are changed, so a person called Isha keeps their name.</li><li>Staff screens and behaviour are unchanged.</li></ul> |
| E4 | **Sidebar:** the first sidebar group is called **Menu** instead of "Hiring". |
| E5, F8 | **Ghost buttons on dark bars are readable** (Remove from pool, Clear selection and the rest). |
| E6 | **Forgot password:** "Forgot password?" sits on the Password label row, so it no longer overlaps the button. |
| F1 | **No Start button too early:** the candidate's home page shows **Being prepared** on an MCQ whose paper is still waiting, instead of Start. The room opens the test by itself once it's approved. |
| F6 | **Single names count:** a single name such as "Snehagr" counts for profile strength. The email's first part doesn't count as a name. |
| F10 | **Big jobs rescore quickly:** rescoring loads jobs and profiles in two queries, so a job with thousands of applicants rescores within the save. |
| F11 | **Closed jobs stay readable:** a job you applied to can still be opened after it closes or is archived. It shows "no longer taking applications". |
| F12 | **Resume backup:** resume files are kept under `UPLOAD_DIR/resumes/`. Back that folder up with the database (see Deploy). |
| F13 | **Interview again explains the review step:** for an MCQ, the message says the new paper waits for review, and where to approve it. |

## Files
- **New backend files:**
  - `services/data_v12.py`
  - `tests/test_v12.py`
  - `migrations/alembic/versions/0011_v12_data_fixes.py`
  - `migrations/sql/010_v12_data_fixes.README.txt`
- **Main backend changes:**
  - `services/ai.py`: parser, prompts, plan
  - `services/mcq.py`: shuffle, no fillers, bank-only draw
  - `services/papers.py`: fill, can_review, waiting
  - `services/audit.py`: job-team alerts, candidate wording
  - `services/settings.py`: locked review, AI-interview time check
  - `routes/inbox.py`: Today cards
  - `routes/jobs.py`: papers waiting and approve-all
  - `routes/reports.py`: date range, feedback saved
  - `routes/recordings.py`: MCQ recorded
  - `routes/candidate.py`: closed jobs
  - `app.py`: candidate wording on every response
- **Main frontend changes:**
  - `pages/app/Approvals.jsx`: MCQ papers tab
  - `pages/app/Analytics.jsx`, `pages/app/Jobs.jsx`: clickable numbers, no Visibility
  - `components/DataTable.jsx`: Clear filters, filters from the URL
  - `pages/room/Room.jsx`: camera, MCQ recording, one listening connection
  - `lib/call.js`: bitrate
  - `lib/integrity.js`: cover debounce
  - `components/PaperReview.jsx`: Ask Hira for more
  - `styles.css`: dark panels, tabs, ghost buttons
  - `pages/public/Auth.jsx`: Forgot link
- **Older tests updated for the decided behaviour:**
  - `test_v04`: hiring MCQ no longer pads with fillers.
  - `test_v05`: hiring MCQ now needs the camera because it is recorded.
  - `test_v11`: the version check.
