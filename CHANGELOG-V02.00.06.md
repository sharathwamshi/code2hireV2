# Code2Hire V02.00.06 · fixes from the 6 Nov testing, and expected answers in reports

This release fixes everything found in the 6 Nov screenshots (missing buttons and breaks in the flow), and makes reports
show the expected answer next to the candidate's answer for every question. The items on hold stay on hold:
WhatsApp (BETACODE2-41), email and forgot password (BETACODE2-17), the landing page revamp (Udaan) and the full UI
redesign (BETACODE2-42).

Database: **no change**. A V02.00.05 database is already right; just deploy the code and rebuild the frontend.
Tests: `backend/tests/test_v06.py` names each item it covers.

## Bugs from the screenshots

| # | What you saw | Cause | Fixed |
|---|---|---|---|
| **B1** (Critical) | The candidate's live round (room/122) showed only "Please read the instructions and tick…", with no button. | The interviewer started the interview before the candidate arrived. The candidate's page treated a started round as a rejoin, so it skipped the instructions and the full check. The server then refused because the instructions were never read, and the page showed that as a dead end. | The page no longer decides; the server does. A re-check is allowed only after this person passed the full check and read the instructions. Otherwise they always get the instructions and the full check, even if the round has started. If the server still asks for the instructions or the check at Join, the candidate is taken straight back to them with a note, never to a dead end. While the interviewer is already waiting, the candidate sees "Your interviewer is ready and waiting". |
| **B2** (Critical) | MCQ check (room/121): **Face in view** said "✓ We can see you", but the step never passed and there was no **Next**. | The step waited for the face to be seen twice in a row. The second sighting gave the same answer ("1 face"), and the page only counted changes, so it never counted it. | One face held for about a second passes the step, and **Next** appears. While it waits, the box says "We can see you. Hold still for a second…", so the message and the result always agree. Once passed, the step stays passed. |
| **B3** (High) | Interviewer room: the call box shrank to a thin strip while waiting, and the interviewer's self-view hung over its edge. | The video area's fixed height was ignored while no video was playing. | The call box keeps its height (250 px of video) whether waiting, connected or with the camera off. The self-view stays inside it. |
| **B4** (High) | On a laptop about 1340 px wide (or with 125% display scaling), the interviewer page scrolled sideways: "YOU" showed as "OU", **Back** was cut off, and plan titles were cut. | The top bar couldn't shrink a long round name ("Live technical interview with Isha copilot (coding and debugging walkthrough)"). Below 1200 px the plan column was hidden completely. | The round name shortens with "…" (full name on hover), and the page never scrolls sideways. Plan titles wrap instead of being cut. At smaller widths the columns get narrower instead of hiding the plan, and below 980 px everything stacks. Checked at 1340, 1280 and 1093 px. |

## Breaks in the flow

| # | What happened | Fixed |
|---|---|---|
| **C1** | The interviewer could start before the candidate joined, and the "Live" timer counted from when the page was opened. | **Start interview** before the candidate is connected asks "The candidate hasn't joined yet. Start the interview anyway?", says where the candidate is right now, and offers **Wait for them**. The Live timer now counts from the moment the interview started, the same clock the report and video use, so a page reload doesn't reset it. |
| **C2** | The panel said "They passed the system check before joining" even when they hadn't. | A live **Candidate** panel shows where they really are, updated every 5 seconds: hasn't opened the round yet, reading the instructions, doing the system check (step 6 of 10, Microphone), asked for help, stuck on an error, check passed and joining, joined, connected. If the page went quiet it shows how long ago, and the latest system check result sits underneath. |
| **C3** (warn, as you decided) | The candidate could be in the MCQ while the live round was running. | The candidate sees "Your MCQ screening is still in progress. You can continue here, but finish it when you can." with **Open it**. The interviewer sees "Still in their MCQ screening (in progress)". Nothing is blocked. |
| **C4** | Error screens in the candidate rooms showed text only. | Every candidate error screen has **Try again**, **Back to home** and **Contact the hiring team**. The last one sends "I need help" with the error and their own note, and the interviewer's panel shows them as "Stuck". |

## Report: expected answers and candidate answers (R6)

- **Every question in "Question by question" is now open by default,** with **Expand all** and **Collapse all**.
- **Live rounds (F2F with Isha, human F2F):**
  - **A good answer covers:** the expected points from Isha's plan, marked covered ✓, partly ◐ or not ○, with "2 of 3 covered".
  - **Candidate's answer:** their own words, with Isha's tags.
  - **Interviewer also said:** the interviewer's remarks around that question.
  - The interviewer's own questions get expected points too, also shown live in the room.
- **AI interviews:**
  - The expected points fit each question. A debugging question, a design question, a "walk me through a project" question and a comparison each get their own points, even without an AI key; before, every question got the same three generic points.
  - The candidate's answer always comes from the transcript, never from the AI's retelling.
- **MCQ:**
  - **Correct answer** (with the explanation) beside **Candidate chose**, marked right or wrong.
  - All the options are listed below.
- **Older reports:** reports written before this release get their expected points filled in when opened. The stored report isn't changed.
- **PDF:** the report PDF now has each question with "A good answer covers" (covered or not covered), the candidate's answer and what the interviewer also said. For MCQ it has a table of the correct answer and the candidate's choice.
- **Who sees it:**
  - The hiring team and hiring manager see everything.
  - The client version keeps the expected points but hides the candidate's answers and the interviewer's remarks, as before.
  - Candidates see questions only if the company adds "questions" to **Sections candidates can see**. They then get each question, the expected points and their own answer, but no scores or tags.

## Checked
- **Tests:** 103 automated tests pass. Every suite also passes on MariaDB 10.11 (V02.00.06: 10, V02.00.05: 23, V02.00.04: 29, V02.00.03: 36, end to end: 4).
- **Database:** a fresh V02.00.06 database has exactly the same schema as a V02.00.05 database after migration 005, so no migration is needed.
- **Browser walkthrough** of the 6 Nov screenshots: 8 of 8 steps pass.
  - The face step passing in an MCQ round.
  - The long round name at 1340, 1280 and 1093 px with no sideways scroll.
  - The MCQ still running, seen by the interviewer.
  - **Start interview** asking first, then **Start anyway**.
  - The call box keeping its height while waiting.
  - The candidate opening the already-started round and getting the instructions and the full check, while the interviewer follows each step.
  - The report showing the expected answer beside the candidate's answer.
  - An error screen with its three buttons.
  - The face step used a stand-in detector that sees one face, because the test camera shows no face.
- **Earlier walkthrough:** the V02.00.05 walkthrough was run again and passes 18 of 18. Both runs had no page errors.
