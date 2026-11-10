# Code2Hire V02.00.07 · bug fix and improvement report for the 10 Nov bug report

This release fixes all 8 bugs in `Code2Hire_Bug_Report-10-11.xlsx`, using your decisions on bugs 5, 6 and 7, and the 11
gaps found while checking them. The items on hold stay on hold:
- WhatsApp (BETACODE2-41)
- email and forgot password (BETACODE2-17)
- the landing page revamp (Udaan)
- the full UI redesign (BETACODE2-42)

**Version:** V02.00.07 is shown in the menu bar, the side menu, every footer, every interview room, public pages, PDFs and
`GET /api/health`.
**Database:** no change; a V02.00.05 or V02.00.06 database is already right. Deploy the code and rebuild the frontend.
**Tests:** `backend/tests/test_v07.py` names each bug and gap it covers.

## Bugs

| # | Bug (priority) | Cause | Fixed |
|---|---|---|---|
| **1** | Scrolling in the candidate's fullscreen call moves the interviewer panel (High) | The interview rooms only set a minimum height for the screen. Anything taller pushed the page down, mostly the chat as messages built up, and the whole page scrolled: the interviewer's video, the Leave, microphone and screen-share buttons, everything. | Every interview room (live call, AI interview, MCQ) is now locked to the screen. The interviewer's video stays put. The controls sit in a fixed bar at the bottom, always reachable. Only the chat messages, the instructions and side panels scroll, inside their own boxes. Checked with 30 chat messages at 1280×650: the page doesn't scroll and **Leave call** and **Send** stay on screen. |
| **2** | Chat messages not visible: a blank white box (High) | **Not reproducible on V02.00.06 in Chrome:** messages showed on both sides. The remaining cause was bug 1: as messages built up, the chat was pushed below the screen and looked like empty space. | The chat panel now has a fixed height, with messages scrolling inside and the typing box always at the bottom. Checked with 30 messages: they show on both sides, newest at the bottom. |
| **3** | Isha doesn't capture or show the candidate's answers correctly (Critical) | 1. Azure captions stopped for good after about 10 minutes, because the access key expired and was never renewed.<br>2. If captions stopped (network, the browser ending its session), nothing restarted them, and nobody was told.<br>3. The candidate's chosen microphone wasn't used for captions.<br>4. Without headphones, the interviewer's voice came back through the candidate's speakers and was saved as the candidate's answer.<br>5. Answers given before a question was selected went under "Opening".<br>6. The interviewer could only see the answer in the transcript column. | 1. The Azure key is renewed every 9 minutes.<br>2. Captions restart by themselves after any stop, waiting a little longer each time (up to 5 seconds). Both sides see the caption state: working, or "Captions paused, reconnecting…". The interviewer also sees "Last caption 3 s ago".<br>3. Azure captions use the microphone chosen in the system check.<br>4. A sentence that repeats what the interviewer said in the last 20 seconds is recognised as echo and left out, and the interviewer sees "N echoes ignored: the candidate may not be using headphones". The system check now asks "Are you using headphones?", and the answer shows to the interviewer.<br>5. An answer with no question selected goes to the next plan question, marked as assumed. **Move to** puts it under the right question with one click.<br>6. A **Live answer** box under the current question shows the candidate's words as they speak, with the points ticking as they're covered. |
| **4** | No message when the interviewer leaves; the candidate sees a blank screen (High) | Pressing **Leave call** worked. But when the interviewer closed the tab, the browser crashed or the internet dropped, the candidate kept a frozen or black picture with only a small chip in the corner. The server also counted the interviewer as present for 12 more seconds. | Whenever the call isn't connected, a clear message covers the video: **"The interviewer has left the meeting. Stay on this page. You'll be reconnected as soon as they come back. Your interview is still open."** Other states say "Connection lost. Reconnecting…" or "Waiting for the interviewer". After 10 minutes the message says what to do next. Closing the tab now sends a leave signal on the way out, and presence clears at once, so the message appears within about a second (checked). |
| **5** | The interviewer's spoken question isn't shown to the candidate (Medium) | Not built: the interviewer's speech was captioned only for Isha. | The interviewer's words go to the candidate as live subtitles: words appear as they speak, then the full sentence. As you decided, they show only after the candidate presses the new **CC** button in the call bar, which highlights while on. The choice is remembered for the next interview. Subtitles start as soon as the call connects, before Start interview too, and hide while the interviewer is away. |
| **6** | A cleared candidate still shows after Clear: all pages (Medium) | Each list kept one selection, but each action window (**Invite to next round**, **Add to a job**, **Move to folder**) kept its own copy of the selected names. The new selection bar also briefly showed "#id" before the name loaded. | One selection per list, used on every list page: job candidates, talent pool, question bank. The bar shows the selected names, each with × to unselect. **Clear**, an action finishing, or a change of page, filter or search empties the selection and closes any action window that still held the old names. Action windows show who they apply to ("Inviting Karan Shah"). Checked by selecting, opening Invite, cancelling, clearing and selecting someone else: only the new name shows. |
| **7** | Jobs page should show Live by default (Medium) | The Jobs page opened on all statuses. | The Jobs page opens on **Live** jobs. The Status filter shows Draft, Awaiting approval, Closed or all of them, and the page says so: "Live jobs first. Use the Status filter to see drafts, jobs awaiting approval, closed jobs, or all of them." |
| **8** | Scheduled interview shows in notifications but not on the candidate's home page (High) | The home page loaded once and never refreshed, and the date and time were a small grey line. The notification opened My applications, and only mentioned the deadline. | An **Upcoming interview** card at the top of the home page shows:<br>- the date and time in the candidate's time zone;<br>- a live countdown;<br>- the round and its length;<br>- the company and the interviewer;<br>- "Rescheduled" when the time changed;<br>- **Test my setup**, and **Join**, which turns on when the room opens.<br><br>The home page refreshes by itself when a notification arrives (checked about every 20 seconds and when the window comes back into focus) and every minute. The notification now says "Interview scheduled" and opens the card. |

## Gaps fixed with these

| # | Gap | Done |
|---|---|---|
| 1 | Caption health | The candidate sees "Captions on" or "Captions paused, reconnecting…". The interviewer sees the same state and "Last caption N s ago", so a silent failure never looks like Isha missing answers. |
| 2 | Headphones and echo | "Are you using headphones?" is in the system check, and the answer shows on the candidate's check line ("No headphones (echo possible)"). Echoed sentences are dropped and counted. |
| 3 | Captions follow the chosen microphone | Azure captions listen to the microphone picked in the check. The browser's own engine can only use the computer's default microphone, which is why Azure is recommended (gap 11). |
| 4 | Leaving without pressing Leave call | Closing the tab or the browser counts as leaving at once on both sides. |
| 5 | The candidate sees the interviewer's words | CC subtitles (bug 5). |
| 6 | Live answer | A Live answer box under the current question (bug 3). |
| 7 | No answer lost | Unassigned answers go to the next plan question as "assumed", with **Move to**. The report keeps the flag. |
| 8 | No page scroll in any interview room | The live call, AI interview and MCQ rooms all fit the screen (bug 1). |
| 9 | The home page updates live | New invites, schedules, changes and ended rounds appear without a reload. |
| 10 | Action windows read the current selection | On every list page (bug 6). |
| 11 | Azure Speech | `/api/health` reports `azure_speech`. Without it, the interviewer's room says "Captions: Chrome or Edge only (Azure Speech isn't set up)", and a candidate in a browser that can't write out speech is told to use Chrome or Edge. **Recommendation:** set `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` on beta, so captions work in every browser, including Safari on a Mac. |

## Things to know
- **CC is off by default.** Each candidate turns it on with **CC**, and their browser remembers the choice.
- **Echo detection** compares the candidate's sentence with what the interviewer said in the last 20 seconds; 70% of the words matching counts as echo. A candidate who repeats the question back word for word will have that sentence left out, which is usually right.
- **Without Azure Speech,** captions still depend on the browser's engine, which works only in Chrome and Edge and only with the default microphone. This is the biggest remaining risk to Isha's capture. Setting up Azure on the server removes it.

## Checked
- **Automated tests:** 110 pass on SQLite. Every suite also passes on MariaDB 10.11: V02.00.07 7, V02.00.06 10, V02.00.05 23, V02.00.04 29, V02.00.03 36, end to end 4.
- **Database:** a fresh V02.00.07 database has the same schema as a V02.00.05 database after migration 005, checked on MariaDB. No migration is needed.
- **Browser walkthrough of this report** (`walk7`), with real Chromium, a fake camera and microphone, and two browsers on a live call at 1280×650: 10 of 10 steps pass with no page errors.
  - the version label;
  - Jobs opening on Live;
  - selecting, Clear, and the invite window showing only the current names;
  - the Upcoming card appearing without a reload;
  - both system checks and joining;
  - the Azure notice;
  - 30 chat messages, with no page scroll and the controls on screen;
  - the CC subtitles showing only after CC;
  - an unassigned answer, the assumed notice and the Live answer box;
  - the interviewer closing the tab, and the candidate seeing "The interviewer has left the meeting".
- **Earlier walkthroughs:** V02.00.05 (18 of 18) and V02.00.06 (8 of 8) were run again on V02.00.07 and pass with no page errors. The V02.00.05 walkthrough now expects the new leave message.
