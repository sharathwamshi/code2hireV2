# Code2Hire V02.00.08 · video calls that connect, the F2F and Superadmin bug reports, and a clean sign-in page

This release covers:
- the "stuck on Connecting…" calls;
- every item in `F2F_Interview_Bug_Report_Updated.xlsx` (F2F-001 to F2F-004, CD-005);
- every item in `Superadmin_Bug_Report_1.xlsx` (SA-001 to SA-010);
- the gaps found while checking them;
- making sure the saved Claude and Azure keys are really used;
- removing the demo-account buttons from the sign-in page;
- **added 12 Nov:** removing and re-adding candidates and team members, and **retaking a round after a technical
  problem**, with a limit the superadmin sets;
- **added 12 Nov:** **visual reports** with charts, colour and clearer tables, in every view and in the PDFs.

The items on hold stay on hold:
- WhatsApp (BETACODE2-41)
- email and forgot password (BETACODE2-17)
- the landing page revamp (Udaan)
- the full UI redesign (BETACODE2-42)

**Version:** V02.00.08 is shown in the menu bar, the side menu, every footer, every interview room, public pages, PDFs
and `GET /api/health`.
**Database:** migration **006** (or Alembic `0007_users_archive_cleanup`). It adds 2 columns to `users`, 3 to
`applications` and a new `pool_removals` table, and fixes some data (below). See `backend/migrations/README.md`.
**Tests:** `backend/tests/test_v08.py` (34 tests) names each item it covers.

## Deploy
1. Back up the database.
2. Run `mysql -u USER -p DBNAME < backend/migrations/sql/006_v08_users_archive_and_cleanup.up.sql`, or `alembic upgrade head`.
3. Deploy the code, rebuild the frontend (`npm ci && npm run build`) and restart.
4. **Recommended, for the relay:** switch coturn to per-call logins (see "Relay set-up" below), then fill in **AI, voice and
   defaults → Integrations → Video relay (TURN)**.

## Video calls stuck on "Connecting…"

| # | Problem | Cause | Fixed |
|---|---|---|---|
| C1 | Some candidates and interviewers saw a blank video, while chat and captions worked | 1. No relay server was configured, so networks that block direct video (strict Wi-Fi, mobile networks, VPNs) could never connect.<br>2. A code fault: the interviewer's network routes could arrive before the call offer, and the candidate's browser **threw them away** when the offer arrived. | 1. **Relay support:** several relay addresses (UDP, TCP and TLS on 5349), set once for the whole platform by the superadmin. A company's own relay still takes priority.<br>2. Network routes are numbered with their offer and kept until it arrives, and they leave in order, so none are lost. |
| C2 | A failed connection retried silently forever | Only a full "failed" state triggered a retry, and a stuck "connecting" state never did. | **Automatic retries:**<br>- If the video hasn't connected after 15 seconds, the interviewer's side starts again.<br>- The second retry goes **through the relay only**.<br>- After 3 retries, both sides see **"We couldn't connect the video"**, with steps to try and a **Try again** button. Retries continue every 30 seconds.<br>- A brief drop gets 8 seconds to recover by itself. |
| C3 | The candidate saw "Waiting for the interviewer" while the interviewer was in the call | One message covered "not here yet" and "here, but the video isn't through". | Both sides now say the right thing:<br>- **"The interviewer is here. Connecting the video…"**<br>- "This is taking longer than usual"<br>- "Trying again through the Code2Hire relay (attempt 3)"<br>- "We couldn't connect the video"<br>- "The interviewer has left the meeting" |
| C4 | Nothing checked the network before the interview | The system check tested camera, microphone and speed, but not a call. | A new **Video call connection** step in the system check, for live rounds, on both sides and on rejoining. It looks for a route through the relay or a direct one.<br>- If the network blocks both, the step fails, with steps to fix it (VPN off, switch to a hotspot).<br>- If only the relay is blocked, it passes with a note. |
| C5 | No record of how a call connected | Nothing was saved. | Each connection is saved: direct or through the relay, the retries, and failures.<br>- The interviewer sees **Video direct** or **Video via relay** in the room.<br>- The report has a **Video call** line, for example "Connected through the Code2Hire relay · 2 automatic retries", or "The video never connected". |
| C6 | Starting while the video wasn't connected gave the wrong warning | It said "The candidate hasn't joined yet" even when they were there. | When the candidate is there but the video isn't connected, Start says so: **Start without video** or **Keep trying**. The report records that the interview started without video. |
| C7 | Dock or Pop out reset every time | It wasn't remembered. | Each interviewer's choice is remembered. |

### Relay set-up (coturn on the beta server)
The relay installed on 10 Nov works as it is: enter `turn:beta.code2hire.ai:3478` with username `c2hturn` and its
password in the new **Video relay (TURN)** card.

**Recommended:** per-call logins that expire after 8 hours, so no fixed password ever reaches a browser.
1. In `/etc/turnserver.conf`, replace the `lt-cred-mech` and `user=…` lines with these two:
   ```
   use-auth-secret
   static-auth-secret=<run: openssl rand -hex 32>
   ```
   Then run `systemctl restart coturn`.
2. In **Integrations → Video relay (TURN)**, fill in:
   - **Relay addresses:** `turn:beta.code2hire.ai:3478 turn:beta.code2hire.ai:3478?transport=tcp turns:beta.code2hire.ai:5349?transport=tcp`
   - **Shared secret:** the same secret as in the coturn file.
3. Press **Test saved relay from this browser**. It reports whether relay routes come back.

## F2F bug report

| # | Bug | Cause | Fixed |
|---|---|---|---|
| **F2F-004** + **SA-010** | Scorecard empty after the interview ends (High) | 1. Isha built the scorecard from her question-plan topics, not the job's competencies. Every real competency was then added as "Not covered" with no score, so it looked empty.<br>2. With no captured answers there was nothing to score, and no explanation.<br>3. The recommendation and summary were never pre-filled. | - Every plan question is now linked to one of the job's competencies when the plan is made.<br>- The scorecard has **one row per competency**. Each is scored from the answers to its questions (Claude when available), with the strongest quote and Isha's live score.<br>- A competency without answers says why: "Not asked in this interview", or "Asked, but no answer was captured (captions may have been off)".<br>- The **recommendation** and **summary** are pre-filled.<br>- **Re-draft** rebuilds the scorecard after answers are moved or corrected.<br>- **Open scorecard** always builds a fresh draft. |
| **F2F-003** | Repeated, template-like questions (High) | 1. Without Claude, the plan came from 5 sentence patterns with the skill swapped in, and every skill got the same first pattern.<br>2. Follow-ups were 3 fixed lines offered after every sentence. | **The plan:**<br>- Claude is told the job description, the competencies and the questions already asked. Every question must tie to a duty, a resume claim or a gap, with no two starting the same way.<br>- Without Claude, the plan is built from **the candidate's resume** ("Your resume says: 'Reduced deploy time from 40 to 8 minutes…'. Walk me through…") and **the job's duties**, and each skill gets a different kind of question.<br>- Questions from the candidate's earlier rounds are never asked again.<br><br>**Follow-ups:**<br>- They pick up the candidate's own words ("You mentioned Kafka. What exactly was your part in it?").<br>- A suggestion already shown or asked is **never offered again** in that interview. |
| **F2F-001** | Candidate answers not shown properly (High) | Mostly fixed in V02.00.07. What remained: a wrongly written caption, or a stray sentence ("Can you hear me?"), went straight into the scoring. | The interviewer can **Edit** any of the candidate's sentences, or **Remove** one that wasn't an answer. Corrected sentences are marked "(corrected)", and the scorecard and report use the corrected words. Typing an answer when captions fail is still there. |
| **F2F-002** | Chat message not shown after Enter (Medium) | Not reproducible on V02.00.07 (fixed with bug 2 there). Checking it found three gaps:<br>1. Pop out closed the chat.<br>2. A message that failed to send looked sent.<br>3. There was no way to write a second line. | - The chat **stays open** when the video is docked or popped out.<br>- Every message shows "Sending…", then nothing once delivered, or **"Not sent. Retry"**.<br>- **Shift+Enter** adds a new line; Enter sends. |
| **CD-005** | Superadmin questions missing from the candidate's practice quiz (High) | 1. Practice only used questions whose skill name matched **exactly** (a "python" practice missed "Python" questions) and whose level was within one of the practice level.<br>2. The rest were filled with generic filler questions, and **those were saved to the global bank as approved**: one test run added 18.<br>3. The Difficulty setting was ignored. | - Skill names match without regard to capitals or small differences ("python", "Python programming").<br>- Practice uses every level before writing anything new.<br>- Questions people wrote come before AI-written ones.<br>- Filler questions are **never saved to any bank**: they exist only in that one test. Questions Claude writes for practice are saved as **pending**, for the superadmin to review.<br>- Migration 006 moves the filler questions already saved back to pending.<br>- The practice form lists the **topics in the question bank**, with counts, as one-click choices. Difficulty now sets the level. |

## Superadmin bug report

| # | Bug | Fixed |
|---|---|---|
| **SA-001** | A deleted template didn't appear under Show archived (High) | **Delete now moves a template to Archived.** Show archived lists only archived templates, each with **Restore** and **Delete permanently**. Before, Delete erased the template, so it could never be in the archive. |
| **SA-002** | All users: no checkboxes and no Delete (Medium) | A checkbox on every row and **Delete** at the end of the selection bar. Deleting archives the user:<br>- they can't sign in and disappear from lists;<br>- their jobs, interviews and reports stay.<br><br>You can't delete yourself or the last superadmin. |
| **SA-003** | An "Archived" button before the user type (Medium) | **Current / Archived** sits in front of the Type filter. Archived lists deleted users with when they were deleted, and **Restore** in the bar. The list also gains Company and Last sign-in columns, and a Superadmin type. |
| **SA-004** | "Platform" next to the bell (Low) | It was the superadmin account's name, "Platform Superadmin".<br>- The account is now "Superadmin" (migration 006 renames it).<br>- The repeated "Superadmin" role chip is hidden.<br>- Clicking your name lets you change it. |
| **SA-005** | Audit log shows raw JSON (High) | Every row is in plain words:<br>- **Action:** "Invited to a round"<br>- **Target:** "Application: Arjun Mehta · Senior Python Developer"<br>- **Company**<br>- **Details:** "Round: 2 · Type: AI interview"<br><br>Click a row for all its details. |
| **SA-006** | Audit search didn't work for numbers or letters (High) | Search covers the person, the action (also in plain words, so "invited" works), the company, the target's number and name, and the details. **Action** and **Company** filters were added. |
| **SA-007** | Sign out position (Medium) | **Sign out** is the last item of the Platform menu, with an icon, and no longer sits at the top right. |
| **SA-008** | Overview number cards don't open anything (High) | All 12 cards open their list, already filtered. Three new superadmin lists sit behind them: **Jobs**, **Rounds** (MCQ, AI interview, Isha, practice) and **Reports** (with "AI and person disagree" for the AI–human agreement card). They're also in the Platform menu. |
| **SA-009** | Odd characters before "Waiting for you" items (Low) | They were 0 counts. A count now shows only when something is waiting ("3 waiting"). When nothing is waiting: "All clear. Nothing is waiting for you." |
| **SA-010** | Scorecard empty | Same fix as F2F-004 above. |

## Remove and re-add (added 12 Nov)

| # | Where | What it does |
|---|---|---|
| A1 | **Job → candidates**: tick → **Remove from job**; or **Remove from job** on a candidate's page | They leave the pipeline and the job's counts.<br>- Open invites are **cancelled and their credits come back**.<br>- Reports and videos stay.<br>- You can't remove someone in the middle of a round: wait for it to end, or retake it.<br>- The candidate sees the job as "Closed". |
| A2 | **Stage filter → Removed → Bring back**; or add the same email again | Two choices:<br>- **Restore:** back to the same stage, rounds and reports.<br>- **Start fresh:** back to round 1. Earlier rounds stay as history ("Voided"), left out of scores and decisions, with their videos kept.<br><br>Adding a removed person's email on the Add candidate form shows **Bring back…** instead of "already on this job". |
| A3 | **Talent pool**: tick → **Remove from pool**; **Talent pool / Removed** switch → **Restore to pool** | They leave your talent pool and your Add candidate search. Their Code2Hire account and any jobs they're in stay (use Remove from job for those). Adding them again by email brings them back. |
| A4 | **Company admin → People and roles**: open a person → **Remove from team**; **Team / Removed** switch → **Restore** | They can't sign in and leave every list and picker. Their past work stays under their name.<br>- You can't remove yourself or the last company admin.<br>- Inviting a removed person's email again offers **Restore them**, which gives back their access and roles. |
| A5 | **Superadmin → All users → Archived**: tick → **Delete permanently** | For erasure requests. Name, email, phone and resume are removed, and interview videos deleted. Reports stay for employers without personal data. This can't be undone.<br>A company adding a deleted (archived) person's email is told to ask the superadmin to restore them. |

## Retake after a technical problem (added 12 Nov)

| What | How it works |
|---|---|
| Where | A **Retake** button:<br>- on each round on the **candidate's page**;<br>- in **My interviews**;<br>- **Technical problem?** in Isha's live room. |
| Who | **Anyone on the hiring team who can see the job.** No approval step. |
| Which rounds | Any MCQ, AI interview or live interview that has **started**: in progress, paused, finished, not finished or expired. A round that hasn't started is rescheduled instead. |
| What you give | **What went wrong** (required): the video didn't connect, audio problems, the candidate's device failed, the interviewer's device failed, the internet dropped, a Code2Hire error, or something else (details required).<br>An optional note, and a new time for live rounds. |
| Evidence | The Retake window shows what Code2Hire recorded:<br>- the round's status and time spent;<br>- how the video call connected (directly, through the relay, or never), and the reconnects;<br>- both system checks;<br>- integrity warnings;<br>- whether a video was recorded.<br><br>All of it is saved with the retake. |
| The old round | It becomes **"Voided: retaken"**, showing the reason and who did it. It's kept for the record **with its video**, but left out of scores, comparisons, the hiring packet, analytics, the review queue and Isha's earlier-round context. Its report says it was voided. Anyone still in the room is told the session ended. The candidate's old link says "This round will be retaken", with **Open the new session**. |
| The new round | The same round, with the same interviewer unless you pick another, and a fresh set of questions for MCQ and AI interviews. The candidate gets the usual invite, and the round is marked **Retake**. |
| Cost | **Charged like a re-interview:** MCQ 1 credit, AI interview 5, live interview with Isha 3. |
| Limit | **5 per candidate per round** by default.<br>- Only the superadmin changes it: **AI, voice and defaults → All defaults → Policies → "Retakes for a technical problem…"** (0–20).<br>- Companies see it but can't change it.<br>- When the limit is reached, Retake explains that the limit is set by Code2Hire.<br>- It's separate from the company's re-interview limit. |

## Visual reports (added 12 Nov)

Every report is now laid out to be read at a glance. This covers the hiring team's view, the hiring manager and client views, the candidate's feedback, shared links, practice results and the PDFs. Each view still shows only what that audience is allowed to see.

| Part | What it shows |
|---|---|
| Header | A **score gauge** coloured by result (green 70%+, amber 45–69%, red below), with the candidate, round, job, date and interviewer. A coloured **recommendation** badge and the decision. A band across the top in the recommendation's colour. |
| Key figures | Coloured tiles:<br>- Overall score.<br>- MCQ: correct out of total, and skipped.<br>- Interviews: strong, meets and weak competencies, and how many of a good answer's points were covered.<br>- Integrity, as clean or the number of warnings.<br>- Recommendation and decision. |
| Interviews | **Scores by competency:**<br>- Bars on a 0–5 scale, coloured by level (strong, meets, weak).<br>- A diamond for Isha's live score.<br>- A **radar** of the candidate's profile against the "meets" line.<br><br>**Answer quality by question:** a bar per question showing the share of a good answer's points covered, or the score when no points were matched. Click a bar to jump to that answer. |
| MCQ rounds | A **donut** of correct, wrong and skipped answers. An **answer map** with one coloured square per question; click one to jump to it. **Bars by skill**, split into correct, wrong and skipped. |
| Tables | Competency details with a coloured level stripe and badge. Resume vs reality with a count of each kind of result. Integrity events with a **timeline** and colour by severity. |
| Lists | Strengths and gaps in green and red boxes with counts. The candidate gets three coloured boxes: what went well, what to work on, and next steps. |
| Coverage | A donut of planned topics tested, and a meter showing how closely the interviewer and Isha agreed. |
| Candidate | A score gauge, green when they cleared the round. MCQ answers at a glance. Their own answers question by question, when the company shares them; before, these weren't shown on screen. |
| PDF | The same in print, drawn as vector graphics on the server:<br>- a coloured band at the top of the first page;<br>- a gauge, coloured key-figure tiles and competency bars with a radar;<br>- for MCQ, a donut, the answer map and skill bars;<br>- the per-question chart;<br>- colour-coded tables, and question cards with green "covered" markers. |

## Claude and Azure keys
The keys saved under Integrations were already used ahead of the server's environment settings. What was missing: when a
saved key **failed**, everything fell back to templates and voices without telling anyone. That is the most likely
reason beta still showed template questions with a key in place.
- Every Claude and Azure call now records whether it worked.
- **Overview:** a red bar says "Claude's key is saved but the last call failed: <reason>".
- **Integrations:** shows the same under each key, or "Working · last call used <model>".
- **Isha's room:** says "Claude isn't responding (<reason>): Isha uses built-in questions".
- `GET /api/health` adds `anthropic_working`, `anthropic_error`, `azure_speech_working` and `azure_speech_error`.
- If the saved AI model no longer exists, calls switch to the default model instead of failing.
- **Test saved key** now tests the model the platform actually uses.

**After deploying, check:** open the Overview. If there's no red bar after an interview, Claude and Azure are working.
`/api/health` shows `"anthropic_working": true` after the first AI call.

## Sign-in page
The demo-account buttons and the shared password are gone. The page has only email, password and "Create a free profile".

## Also fixed
- Choosing **Quiz** on the practice form **started a practice** at once: buttons in a two-way switch submitted the
  form. That affected every such switch inside a form; all now only switch.
- Practice instructions said "The hiring team reviews your round". They now say practice is private, and that the score
  and feedback show as soon as the candidate finishes.

## Checked
- **Automated tests:** 144 pass on SQLite. Every suite also passes on MariaDB 10.11: V02.00.08 34, V02.00.07 7,
  V02.00.06 10, V02.00.05 23, V02.00.04 29, V02.00.03 36, end to end 4.
- **Migration 006** on MariaDB, from a V02.00.07 schema with planted rows:
  - The schema then matches a fresh V02.00.08 install exactly.
  - Only the filler questions move to pending, and only the superadmin is renamed.
  - Running it again changes nothing. Down and up both work.
  - Alembic `upgrade head`, `downgrade -1` and `upgrade head` give the same result.
- **Browser walkthroughs** with real Chromium and a fake camera and microphone:
  - `walk8` (12 of 12 pass): sign-in page, header and menu, overview cards and Waiting for you, templates archive, users delete and restore, readable and searchable audit log, relay card, practice topics, both system checks with the connection step, a connected call showing the route, chat (Enter, Shift+Enter, Pop out), correcting a caption, and the pre-filled scorecard.
  - `walk8d` (12 of 12 pass): an MCQ report and a live-interview report in the hiring team, hiring manager, client and candidate views, both PDFs, a shared client link and the candidate's feedback page, each checked for its charts.
  - `walk8c` (7 of 7 pass): the retake limit in the superadmin's settings; Retake from the candidate's page (limit, cost, evidence, voided and retake marks); the candidate's old link; Remove from job and Bring back; adding a removed email again (Start fresh); talent pool remove and restore; team member remove and restore.
  - `walk8b` (8 of 8 pass): a candidate whose network blocks the video. Both sides say "is here, connecting"; retries show their number; Start warns that the video isn't connected; after the retries both sides show "We couldn't connect the video" with steps; chat still works; Try again restarts; the report says the video never connected.
  - Earlier walkthroughs V02.00.05 (18 of 18), V02.00.06 (8 of 8) and V02.00.07 (10 of 10) were run again on
    V02.00.08. The V02.00.05 rejoin step now expects the connection test.
  - No page errors in any walkthrough.
