# Code2Hire V02.00.05 · system check, instructions, Ask Hira, candidate picker, F2F fixes

This release adds the five requests from 6 Nov (R1 to R5) and fixes the F2F bug report (F2F-001 to F2F-008). It also
covers the gaps listed in the plan. The items on hold are untouched: WhatsApp (BETACODE2-41), email and forgot password
(BETACODE2-17), the landing page revamp (Udaan) and the full UI redesign (BETACODE2-42).

Database: migration 005 / Alembic 0006 (see `backend/migrations/README.md`). There are no new packages.
Tests: `backend/tests/test_v05.py` names each item it covers.

## Your requests

| # | What | Done |
|---|---|---|
| **R1** | **System check before every interview** | <ul><li>**Steps, one at a time:** laptop or desktop, supported browser, camera and microphone allowed, camera, face in view, microphone, speaker, a test recording, fullscreen, internet, and the room checklist.</li><li>**Camera:** finds the default camera and names it, lets the candidate pick another, shows a preview, and fails a dark or covered picture.</li><li>**Microphone:** a level bar, then the candidate reads one sentence, which is written back on screen. This also tests captions.</li><li>**Speaker:** names the default speaker, lets the candidate pick another (Chrome and Edge), and plays a test sound in Hira's voice. The candidate presses "I heard it".</li><li>**Recording:** a 3-second test video must reach the server.</li><li>**Internet:** download, upload and delay are measured. This is the only step that warns instead of blocking.</li><li>**Blocking:** every other step must pass before **Start** or **Join** appears. The server checks it again and refuses consent and start without a passing check.</li><li>**When a step fails:** it says how to fix it and shows **Try again**. **I need help** tells the recruiter, the hiring manager and the interviewer which step failed, and the invite stays valid.</li><li>**Results** are saved and shown on the report: "Camera OK · Microphone OK · Speaker OK · Internet weak (0.8 Mbps up)", with the device names and browser.</li><li>**Pipeline:** shows "Setup tested ✓", "Needs help" or "Setup check failed".</li><li>**Rejoining** re-checks camera, microphone and speaker only.</li><li>**MCQ rounds** run only the steps they need.</li><li>**Practice rounds** run the check to help the candidate, but don't require it.</li></ul> |
| **R2** | **No phones or tablets** | A phone or tablet (including an iPad, which reports itself as a Mac) sees "Please join from a laptop or desktop" with **Copy link** and **Send me the link** (the phone's share menu). The server also refuses the system check, consent and start from a phone or tablet. |
| **R3** | **Full instructions** | <ul><li>**Instructions page before the check.** It is built from the round's real settings and covers:<ul><li>what the round is, how long it takes and how many questions it has;</li><li>what you need;</li><li>the rules and what counts as a warning;</li><li>recording and AI (with the company's retention days);</li><li>what to do if something goes wrong;</li><li>what happens after.</li></ul></li><li>**"I've read the instructions"** must be ticked. The time is saved.</li><li>**Download PDF** of the instructions.</li><li>**Company text:** a new setting, **Your own instructions for candidates** (company, team, job or round, up to 2,000 characters), shows under "From the hiring team".</li><li>**Candidate home page:** a short version next to each round, with **Test my setup**.</li><li>**Interviewers** get a short "How the live interview room works" guide in their check.</li></ul> |
| **R4** | **Ask Hira** | <ul><li>A chat panel on every hiring-team page (**Ask Hira**, bottom right) that knows the job or application page you're on.</li><li>**Questions it answers:**<ul><li>open jobs;</li><li>a job's status (stages, rounds, hires, deadline);</li><li>jobs with no candidates;</li><li>jobs closing this week;</li><li>who is at a stage;</li><li>who is in the final round;</li><li>reports waiting for review;</li><li>who scored above N%;</li><li>a candidate's results;</li><li>**"Which candidates should I add to this job?"**: your pool plus open Disha profiles, ranked by skill match with the reasons. Clicking one opens Add candidate with them already chosen;</li><li>**"What needs my attention today?"**: reports to review, today's interviews, candidates stuck on the system check, declined recordings, and MCQ rounds short of questions.</li></ul></li><li>**Each answer links to the record.** Every answer comes from a database lookup made as you, so it only shows what your role can see and never another company's data. When it doesn't know, it says so and offers example questions.</li><li>**With an AI key,** Claude only works out what is being asked; the answer still comes from the data. Without a key, a keyword reader handles the common questions.</li><li>**History and audit:** the chat history is kept per person (Clear empties it), and every question is in the audit log.</li><li>**Answers only:** as planned, Hira doesn't add, move or invite anyone yet.</li></ul> |
| **R5** | **Existing candidates in a dropdown** | <ul><li>**Matching:** typing 2 letters of a name or email in **Add candidate** lists matching people. Your company's candidates come first, then Disha candidates.</li><li>**Each match shows:** name, email, headline, city, skills, and their jobs and stages with you.</li><li>**Picking one** uses their existing profile, with no new account. Someone already on this job is greyed out with their stage and an "Open their application" link.</li><li>**New people:** a name with no match is marked "New candidate". The same name with a different email shows **Possible duplicate** with **Use this person**.</li><li>**Results say what happened.** "Already on this job" is never silent any more, and the CSV preview marks each row as new, already in your pool, an existing Code2Hire account, or already on this job.</li><li>**Disha candidates** who aren't yours show only name, headline, city and skills (no email or phone) until they're on the job. They're told they were added and can withdraw. Their profile isn't taken over by your company.</li></ul> |

## F2F bug report

| Bug | Cause found in the code | Fixed |
|---|---|---|
| **F2F-001** Interviewer's camera prompt easy to miss (High) | Camera access was only asked when **Join video call** was pressed, among about 10 buttons, and a block showed only a short toast. | **Join video call** opens the interviewer's own check (camera, microphone, speaker, test recording, internet) with a guide. The call starts only after it passes. A bar under the top bar always shows "Camera and microphone not checked yet" or ✓ Camera, ✓ Microphone and ✓ Speaker checked. If a device stops during the call, a red bar shows **Fix it**. |
| **F2F-002** Speaker indicator blinks (Medium) | The recording sound warning showed after 20 seconds of silence and hid on the next word, so normal pauses made it blink, with its "Turn on sound" button. | The warning needs 60 seconds without sound, and any change must hold for 4 seconds before it shows or hides, so it can't flicker. "Turn on sound" appears only when that is the fix. The call strip has a steady sound level bar. |
| **F2F-003** Default camera and speaker not checked (High) | No device check existed for the interviewer, and the candidate's check never tested the microphone or speaker. | Both sides find the default camera, microphone and speaker, name them, let the person switch, and test each one (R1). |
| **F2F-004** Chat white space; End Interview covers the text box (High) | The call window was 440 px wide. Opening chat left 220 px for the video, and the control row (with Leave and End) was wider than that, so it ran over the chat's typing box. The chat had no layout of its own. | The controls sit in their own strip under the video and chat. Chat is a proper side panel with the messages filling it and the typing box at the bottom. **End interview** is only in the top bar. |
| **F2F-005** Isha's questions overlap; answers not detected (Critical) | **Overlap:** the call floated over the bottom right of the room, covering the plan and Isha's suggestions, and long plan notes wrapped into the next rows. **Detection:** an answer was tied to a question only after "Ask this" was clicked, and it depended on captions that weren't arriving (F2F-007). | **Layout:** the call is now docked at the top of the centre column (**Pop out** floats it), and each plan row is laid out cleanly: title, question in full, note on its own line. Checked at 1366×768 with nothing overlapping. **Detection:** the interviewer's speech is captioned too. When they read out a plan question (filler words and order don't matter), Isha moves to it by herself, with **Undo**. The candidate's answer goes to that question. The card shows "Isha heard 4 sentences, covering 2 of 3 points". |
| **F2F-006** No next question suggested (High) | Suggestions were made only after a caption arrived, so with no captions nothing appeared, and nothing ever pointed to the next plan question. | A **Next question** card is always shown: the next plan question not yet asked or skipped, with **Ask this** and **Skip**. It glows with "Good time to move on" when the answer covers every expected point, or the candidate has been quiet for 20 seconds. Isha's follow-ups stay below it. It works without captions. |
| **F2F-007** Live captions miss the candidate (High) | Only finished sentences were sent, and the browser can take a long time to finish one, so nothing appeared. The words still being spoken were shown only to the candidate. Captions before "Start interview" were thrown away. | The words still being spoken reach the interviewer about once a second (grey), then the finished sentence. Captions work from the moment both join and are kept under "Before the interview started". Azure Speech is used when it's set up (every browser). Both sides see "Captions: working (Azure / browser)" or "not available in the candidate's browser". Captions are tested in the system check. The transcript labels both voices. |
| **F2F-008** No clear (✕) option (Medium) | The text boxes had no clear button. | Every text box, search box and text area across the app shows a ✕ once it has text, and **Esc** clears it too. Lists of chips (skills, topics) get **Clear all** next to each chip's ×. Check this one when you test: the sheet asked whether you meant Clear, Close or ✕. |

## Gaps fixed with these
- **Hira's subtitles:** Hira's spoken question appears as a subtitle in AI interviews, and stays long enough to read.
- **Weak internet:** when the internet test finds a slow upload, new recordings use a lower video bitrate (450 or 250 kbps instead of 900) so they keep reaching the server. The interviewer's "Saved up to" chip says "lower quality".
- **Pipeline:** shows each candidate's system check status.
- **Opening early:** a countdown ("Your round starts in 12:30. Test your setup meanwhile.") on the check, and "The room opens in 4:10" in live rounds.
- **A device stops mid-interview:**
  - *AI interview:* a screen "Hira is waiting for you" with **Fix it**. It repairs the camera or microphone in place, restarts the recording piece and resumes listening.
  - *Live call:* the candidate gets the same screen, and the interviewer gets an alert.
- **Test my setup:** the full check, any time, from the candidate's home page. Nothing is recorded, and a passing test shows "✓ Setup tested" next to their rounds.
- **Long text settings** (like the instructions) get a larger box with a character count.

## Things to know
- **Microphone sentence test:** if a microphone clearly picks up sound but the speech engine can't make out the words twice in a row, or the speech service can't be reached, the step passes and the report says "Sound OK; words not recognised". That way a working microphone doesn't lock someone out because of the speech service.
- **Speaker test:** the candidate confirms it themselves ("I heard it"). A browser can't tell whether a person heard a sound.
- **Face step:** it is part of the check when the round's **Face presence check** setting is on (the default).
- **Interviewer's check:** the browser enforces it (the call starts only after it), and the server saves it. The candidate's check is enforced by the server too.
- **Timer during "Hira is waiting":** the AI interview's timer keeps running while a device is being fixed, because the time limit is kept on the server.
- **Disha candidates** appear in the dropdown and in Hira's suggestions only if their profile is set to **everyone**. Those who chose "only companies I applied to" are never shown to other companies.
- **"Send me the link"** on a phone uses the phone's share menu or copies the link, because email is on hold.
- **Headphones:** the interviewer's captions come from their own microphone. Headphones stop the candidate's voice from being captioned as the interviewer's.

## Version
V02.00.05 in the menu bar, side menu, footer, rooms, public pages and PDFs (`frontend/src/version.js`, `APP_VERSION` in `backend/config.py`).

## Checked
- **Tests:** 93 pass on SQLite. Every suite also passes on MariaDB 10.11 (V02.00.05: 23, V02.00.04: 29, V02.00.03: 36, end to end: 4).
- **Migrations:** 005 and Alembic 0006 were checked on MariaDB against a V02.00.04 copy.
  - The schema after the update matches a fresh install exactly.
  - Running the update twice, rolling it back, and updating again all work.
- **Browser walkthrough:** real Chromium with a fake camera and microphone, two browsers in a live call at 1366×768. 18 of 18 steps passed with no page errors. The steps were:
  - the version label;
  - a phone being blocked;
  - instructions with the PDF;
  - the full candidate check;
  - the AI interview with subtitles and recording;
  - a camera stopping, then **Fix it**;
  - "Setup tested ✓" in the pipeline;
  - the live candidate's check;
  - the interviewer's check and status bar;
  - the docked layout with no overlaps (call, plan, suggestions, chat box and controls);
  - captions before the start and words in progress;
  - the Next question card;
  - ✕ and Esc clearing;
  - leaving and rejoining with a device re-check;
  - ending, the scorecard, and the report's system check line;
  - the candidate dropdown (greyed out when already on the job, then picking and adding);
  - Ask Hira (open jobs, attention, job status, suggestions that open Add candidate);
  - the face step blocking in **Test my setup**.
