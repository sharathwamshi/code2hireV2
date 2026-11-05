# Code2Hire V02.00.04 · interview bug fixes and interview videos

This release fixes the bug report BUG-001 to BUG-007 and adds NEW-001: every interview's video is saved, and the
recruiter can watch it. It also covers the 13 related gap fixes and the usability changes in the agreed plan, and shows
the version number in the menu bar and on every page.

Database: migration 004 / Alembic 0005 (see `backend/migrations/README.md`).
Server: `pip install -r backend/requirements.txt` (adds reportlab and azure-storage-blob) and `apt install ffmpeg`.
Tests: `backend/tests/test_v04.py` names each bug it covers.

## Bugs

| Bug | What was wrong | Fixed |
|---|---|---|
| BUG-001 · Only 7 of 20 F2F questions | F2F rounds had no question count. Isha always planned "5 to 7 areas" (5 skills plus a wrap-up without AI). | New round settings: **Questions in the interview plan** (1 to 30, default 7) and **Your own questions**, typed in or picked from the question bank. The plan always has exactly that many questions: your own first, in your order, then Isha's, then more from the job's skills, with Wrap-up last. No question or area name appears twice. |
| BUG-002 · Red button drops the candidate | The interviewer's red phone button sent "bye" and closed the candidate's call. There was no difference between stepping out and ending. | Two buttons. **Leave call** (grey): only the interviewer leaves, the interview stays open, and the candidate sees "The interviewer stepped out. Stay here, they'll be back." **Rejoin call** reconnects. **End interview** (red, with a confirm): ends it for both, and the candidate's room closes and opens the scorecard. A candidate can't end it for both. |
| BUG-003 · Tab switching allowed in live interviews | Tab switches in live calls were saved as "not counted". Fullscreen, paste and face checks didn't run in live calls. | Live calls use the same watcher as the AI interview. Tab switch, paste, copy, leaving fullscreen, a second face and no face are counted warnings, following the round's integrity settings. The candidate sees a warning banner. The interviewer gets an alert and an **Integrity** panel with each event and its time, and the warnings appear as markers on the video. As agreed, live calls warn and count but never pause on their own; the interviewer decides. |
| BUG-004 · Hira repeats MCQ questions | (1) Without AI, the fallback wrote one template question per skill, so the same text repeated in one test. (2) Each run saved those copies to the bank. (3) Questions from earlier attempts were never avoided. | No question twice in one test, compared by text (case, spacing and punctuation ignored), not just by id. Questions the candidate saw before come last. New AI questions are told which ones to avoid, a text already in the bank is never saved, and the fallback now writes different questions. If the bank is still short, the test gets shorter instead of padding with copies, and the recruiter is told (at most once a day per job). This applies to job rounds, certifications and practice. The migration archives copies already in the bank. |
| BUG-005 · No report download | Not built. | **Download PDF** for staff on every report, in the audience being previewed (internal, hiring manager, client or candidate). Candidates get **Download PDF** on Feedback for shared reports, with "You cleared this round" and the next step at the top, and their score on the company's scale. There is a company setting to turn candidate downloads off. Certificates and badges download as a one-page PDF with the verification ID. |
| BUG-006 · Settings accept negative numbers | Number settings had no limits, at any level. | Every number setting has a range and unit. The server refuses values outside it at the platform, company, team, job and round levels, and the box shows "2 to 6 options" and refuses bad values as you type. Choice settings accept only their options, text settings have length limits, and colours and voices are checked. Cross-checks: auto-reject can't be above auto-advance; MCQ needs at least 30 seconds per question; you can't list more own questions than the plan has. Old bad values are read back inside the limits, and the migration corrects the saved ones. |
| BUG-007 · Options shown at once accepts 5 to 6 digits | Same cause as BUG-006. | Limited to 2 to 6, which is what the room can show. Covered by the same fix. The room itself also never uses a value outside 2 to 6. |

## New: every interview video saved (NEW-001)

| Area | What it does |
|---|---|
| Always on | Every AI interview and every live interview on the built-in call is recorded. "Record the call" is no longer a setting. Practice interviews are not recorded. |
| Consent | The candidate is told the interview is recorded (video and sound), who can watch it and that it's deleted after the retention period, and must agree. **I don't agree to recording** stops the interview from starting and tells the recruiter and the interviewer. |
| AI interviews | The candidate's browser records their camera and microphone, with Hira's spoken questions mixed in. |
| Live interviews | Both sides record. The interviewer's copy shows the candidate large with the interviewer in the corner, and both voices. The candidate's copy is a backup, used for any minutes the main copy is missing (for example while the interviewer had stepped out). |
| Nothing lost | Video is uploaded in 10-second chunks while recording. A crash or dropped connection loses at most the last 10 seconds. A chunk that fails to upload is kept in the browser and retried, and a retried chunk is never stored twice. Rejoining starts a new piece of the same recording. End interview waits for the last chunk. |
| Every browser | webm where supported, MP4 on Safari and iPhone. |
| Finishing | The server remuxes each piece with ffmpeg so it can be scrubbed (duration and seek index), in the background. A piece whose browser closed mid-way is finished automatically after 3 quiet minutes. |
| Watching | The report has an **Interview video** player: the pieces play back to back on one timeline. Striped parts come from the backup, and real gaps show as "Missing 12:30 to 12:42". Markers show each question and each integrity warning; click one to jump there. "▶ 03:12" links in the question list and transcript jump to that moment. Speeds 1x to 2x. A **▶ Video** button sits on the candidate's application page. The video also shows before the report is ready, for example while the scorecard is still being written. |
| Who can watch | Staff who can read the job's reports (recruiter, hiring manager, the round's interviewer), and the platform team for support and disputes. Never candidates or client share links. Every viewing and download goes in the audit log. Downloading is a separate permission, **Download interview videos**: on for company admins, off for everyone else unless granted. |
| Storage | With `C2H_AZURE_STORAGE_CONNECTION_STRING` set, finished videos go to a private Azure Blob container and play through 15-minute read-only links. Otherwise they are kept on the server's disk. |
| Retention | Kept for 180 days by default (company setting **Keep interview videos for**, 30 to 730 days), then deleted automatically. Deleted too when a candidate erases their account. |
| Interviewer feedback | The room shows "● Saved up to 12:41". A warning appears at once if the recording stops, uploads fall behind, or there is no sound. |
| Outside meetings | When a round uses an outside meeting tool, the report says "Not recorded: this round used an outside meeting tool", so it isn't mistaken for a lost video. |

## Gap fixes

| Gap | From | Fixed |
|---|---|---|
| The AI interview plan could have fewer main questions than configured | BUG-001 | Always exactly the configured number, filled with different questions. |
| Interviewers couldn't add their own question to the plan | BUG-001 | Add a question to the plan during the interview, and use the existing **Ask your own question** box. Both are kept in the report. |
| The candidate's call ended for good if the interviewer's browser crashed or their internet dropped | BUG-002 | Both sides show "Reconnecting" or "The interviewer stepped out" and reconnect when the other side returns. After 10 minutes away, each side sees a note with what to do. |
| Nobody ended a call both people had left, so the round stayed "in progress" | BUG-002 | After 30 minutes with both away, the round closes as **Not finished**, and the interviewer and recruiters are told. The interviewer can still submit the scorecard, or the candidate can be invited again. |
| Paste and fullscreen weren't recorded in live calls | BUG-003 | Recorded, following the round's settings. Pasting into the call chat is covered too. |
| Face check didn't run in live calls | BUG-003 | Runs on the candidate's side when the round turns it on. |
| The interviewer saw integrity events only after the call | BUG-003 | A live Integrity panel, which survives a page reload. |
| Practice tests and certification sections repeated questions | BUG-004 | Same question picking as job rounds. |
| MCQ setup didn't say whether the bank had enough questions | BUG-004 | Round setup shows "10 questions per test from 34 available (Python 18, SQL 16)", and warns when retakes will repeat or the bank is short. |
| AI-written questions went live without review | BUG-004 | Saved as drafts for review (company setting, on by default). When the bank is short they're used in that one test, and the recruiter is told they're waiting. |
| Settings that conflict | BUG-006 | Cross-checks, listed under BUG-006 above. |
| Choice and text settings accepted anything through the API | BUG-006 | Checked on the server. |
| Candidates couldn't keep proof of a certification | BUG-005 | Certificate PDF. |

## Usability

- **Live interview room (interviewer):** "7 of 20 asked" with a progress bar. Skip and Un-skip, ↑ ↓ to reorder, and a "Yours" tag on your own questions. Before starting, the candidate's check shows: camera on, microphone on, "We can see them". The buttons are **Join video call**, **Rejoin call**, **Ring again**, **Leave call** and **End interview**, and only End is red.
- **Live interview room (candidate):** a status line ("Waiting for the interviewer", "Interviewer stepped out", "Reconnecting", "Connected"), the same warning banner as the AI interview, and a "Back to fullscreen" bar when the round needs fullscreen.
- **Round setup:** settings grouped and named in plain words (not raw keys). Each one shows its limits and inline errors, and Save stays off until they're fixed. A one-line preview of what the round will do, such as "20 questions in the plan: your 1, plus 19 from Isha", or the MCQ bank coverage. Closing with unsaved changes asks first.
- **Settings screens:** each number shows its range and unit, a bad value can't be saved, and the default is shown. "Set here" vs inherited, and **Reset to inherited**.
- **Candidate results:** "You cleared this round" with the next step, the score, and Download PDF.

## Version shown everywhere

- **Menu bar:** the version chip at the top of every signed-in page, and under the logo in the side menu.
- **Footer:** "Code2Hire V02.00.04 · Powered by AcknowledgerFirst" at the bottom of every signed-in page.
- **Interview rooms:** next to the logo in the AI interview, candidate live call and Isha rooms.
- **Public pages** (landing, sign-in, verify, jobs): a small "Code2Hire V02.00.04" in the corner, and in the landing footer.
- **PDFs:** in the footer of every PDF.
- **API:** `GET /api/health` returns the version.
- **Where to change it:** `frontend/src/version.js` and `APP_VERSION` in `backend/config.py`.

## Also fixed while testing

- **Isha room state:** skipping or reordering a plan question could be overwritten by the room's earlier state. Live integrity events were also wiped when the plan changed.
- **AI interview fallback:** with one skill, the plan repeated a question.
- **Video timeline:** the first piece of a video was dated from its first upload rather than from when recording began, which showed a false gap at the start.

## Checked

- **Tests:** 70 tests pass on SQLite. The V02.00.04 suite (29) and the V02.00.03 suite (36) also pass on MariaDB 10.11.
- **Migrations:** 004 and Alembic 0005 were checked on MariaDB against a V02.00.03 copy with planted data. Up, down and re-up all work. The schema matches a fresh install, the data fixes are verified, and running it a second time changes nothing.
- **Browser walkthrough:** two real Chromium browsers on a live call, with a fake camera and microphone. 13 of 13 steps pass with no page errors:
  - the settings limits;
  - round setup and MCQ coverage;
  - the 20-question plan with skip and add;
  - join, and the device check reaching the interviewer;
  - recording from both sides;
  - Leave call and Rejoin;
  - a pasted-text warning reaching the interviewer's panel;
  - End interview and the scorecard;
  - the video player;
  - the report PDF;
  - candidate feedback with Download PDF;
  - AI interview recording;
  - the version label.
