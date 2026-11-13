# Code2Hire V02.00.09 · the Candidate / Manager / Company Admin bug report, Ask Disha, and clearer F2F wrap-up

This release covers:
- the items in `Candidate_Manager_Company_Admin_Bug_Report.xlsx` (BUG-001 to BUG-011; BUG-012 dropped at your request);
- the gaps found while checking them (manager analytics, slow AI calls, the clipped Columns menu);
- **N1** Ask Disha, a chat assistant for candidates;
- **N2** finishing an F2F interview: the scorecard opens at once, Wrap-up answers count, and a clear 1–5 rating;
- **N3** a bigger live rating card, with full marks when every point is covered;
- **N4** closing an interview that was done but is still open;
- **N5** no time limits on joining;
- **N6** one "Interview again" action for putting a candidate back into the same round.

**Still on hold:** WhatsApp (BETACODE2-41), email and forgot password (BETACODE2-17), the landing page revamp (Udaan),
the full UI redesign (BETACODE2-42).
**Still open:** BUG-007 / BUG-008 (an unwanted icon on Manager Analytics and Company Admin). The handwritten mark
wasn't in the spreadsheet; a screenshot of the icon is needed.

**Version:** V02.00.09, shown in the menu bar, side menu, footers, rooms, PDFs and `GET /api/health`.
**Database:** migration **007** (or Alembic `0008_v09_no_time_limits`). No new tables or columns, data only (below).
**Tests:** `backend/tests/test_v09.py` (18 tests); all 162 backend tests pass on SQLite and the V08/V09 suites on
MariaDB. Browser walkthrough: 10 of 10 steps pass, and the V05–V08 walkthroughs still pass.

## Deploy
1. Back up the database.
2. `mysql -u USER -p DBNAME < backend/migrations/sql/007_v09_no_time_limits.up.sql`, or `alembic upgrade head`.
3. Deploy the code, rebuild the frontend (`npm ci && npm run build`) and restart.

## Bug report

| # | Problem | Cause | Fixed |
|---|---|---|---|
| BUG-001 | Practice quiz shows superadmin questions, not AI ones | V08 used bank questions first and only asked the AI when the bank ran short. | A practice quiz is now **mostly written fresh by Hira: 80% by default**, the rest from the question bank. New superadmin-only setting **"Share of a practice quiz Hira writes fresh"** (0–100%). If the AI is down, the bank fills the gap before any built-in filler. Skill checks and hiring rounds still use the bank first. |
| BUG-002 | Reports slow to generate | The AI-interview report was written while the candidate's screen waited, and every answer waited for an AI follow-up. | The interview closes at once and **Hira writes the report in the background**. The Done screen says "Hira is writing your report" and updates by itself. A report still writing after 3 minutes (a stuck AI call or a restarted server) is finished with the built-in fallback. Follow-up questions wait at most **8 s** and Isha's live analysis at most **10 s**, then the standard question is used. |
| BUG-005 | Camera light stays on after practice with Hira | The camera was only released when the page closed, and the page was stuck waiting for the report. | The camera and microphone are **turned off the moment the round ends**, and fullscreen is left. |
| BUG-006 | Report screen not responding after practice | Same blocking wait. | The Done screen shows the writing state, then the report. |
| BUG-004 | No download for the practice report | Candidates could only download PDFs of hiring rounds. | **Download report (PDF)** on the practice Done screen and in the practice Feedback window. New `GET /api/me/practice/<id>/pdf`, private to the candidate. |
| BUG-003 | Share link accepted negative days | No check on the screen or the server. | **1 to 90 whole days**, checked on the screen (message and Share disabled) and on the server. The practice "Questions" box is checked too (1–10 for interviews, 1–30 for quizzes). |
| BUG-009 | "+12 more" on Today couldn't be clicked | It was plain text. | **Show all (12)** expands the card in place; **Show less** folds it back. |
| BUG-010 | Talent pool "Clear" | It cleared the ticked rows, not the people. | Renamed **Clear selection** in every table. Removing people stays under **Remove from pool**. |
| BUG-011 | My interviews: the Action column showed a checkbox | The Columns menu listed the column with no name as a blank checkbox, and the menu was cut off by the card edge. | The column is called **Actions**; columns without a name aren't listed; the menu is drawn above the page so nothing cuts it off. The same fix covers every table. |
| BUG-012 | F2F PDF too colourful | | Dropped at your request. The colourful report stays. |
| BUG-007 / 008 | Unwanted icon on Manager Analytics / Company Admin | | Open: send a screenshot of the icon. |
| Gap | Manager Analytics loaded forever | A hiring manager named on a job (not at company level) was refused by the server, and the page had no error state. | Managers now see **Analytics for the jobs they're on**, and the menu shows it. Any analytics page that can't load says why. |

## N1 · Ask Disha, for candidates
- An **Ask Disha** button on every candidate page (hidden during a round).
- It answers from the candidate's **own** record: profile, applications and where each stands, upcoming rounds (when,
  what kind, with whom, how to join), practice and skill-check results, badges, and the best matching open jobs.
  Plus how-to help: joining a video interview, the system check, rejoining, retakes, password, privacy.
- **Never shown:** other candidates, the hiring team's notes, scores or recommendations the company hasn't shared,
  the questions of rounds still to come.
- With Claude it writes a natural answer from that data only; links in an answer can only point to the candidate's own
  pages. Without Claude, a keyword reader answers the common questions from the same data.
- Chat history is kept per candidate (last 200 messages); **Clear** empties it. Uses the existing `assistant_messages` table.
- API: `POST /api/disha/ask`, `GET /api/disha/history`, `DELETE /api/disha/history` (candidates only).

## N2 · Finishing an F2F interview and the scorecard
| Cause found | Fixed |
|---|---|
| Ending the interview waited for Claude to draft the scorecard, and could time out with a red error. | **End interview** opens the scorecard at once from Isha's own scores. Claude then improves it in the background ("Isha is improving the draft…"); if you've already changed something, your changes are kept. |
| Answers given while the current question was Wrap-up were thrown away, so those skills showed "Not covered" with no score. | Wrap-up (and Opening) answers now count towards the skill they talk about (matched by name, e.g. "SQL" for "SQL (joins, window functions…)"). A skill with no answers of its own gets a suggested score from anything said about it elsewhere, marked "Not asked directly". |
| The score was a small dropdown that started on "Skip". | Each skill has a row of **1 2 3 4 5 Skip** buttons with a level word (Weak → Excellent). **Isha's suggestion has a dashed outline.** Pick a different number and a **"Why do you disagree with Isha's N?"** box opens; the reason is saved in the report. "Not covered" is a calm grey note, not a warning. |
| Re-draft failed silently. | It shows a message if it fails. A scorecard can't be submitted twice. |

## N3 · The live rating card
- The one-line "Answer so far" bar is now a **full card**: a big score, the level word, a bar, sentences heard and
  points covered, and every "good answer covers" point with **Covered / Partly / Not yet**.
- **Full-marks rule:** when every point is covered, the answer scores **5 / 5**, even if Isha's own reading scored
  it lower or couldn't read it.
- **Mark covered:** the interviewer can tick a point Isha missed (for example when captions dropped). Ticking the last
  one gives full marks; **Untick** goes back to Isha's own score. Ticks survive later sentences.
- API: `POST /api/isha/<id>/tick {index, point, on}`.

## N4 · Close an interview that's still open
- **Close interview** (in the room, the Interviews list, the application page and Superadmin → Rounds) shows what was
  captured (sentences, video) and offers:
  - **Submit the scorecard** from what was captured;
  - **Close without a scorecard**, with a required reason. It becomes **Not finished**; transcript and video stay, and
    the scorecard can still be submitted later;
  - **Interview again** (N6).
- In the room, **Start interview** reads **Continue interview** once answers exist, and **Open scorecard** shows for
  a Not finished interview.
- Today shows **Needs closing** for interviews still open 2 hours after they started, or closed as Not finished.
- Interviewers, recruiters, company admins and the superadmin can use it; every close is in the audit log.
- API: `GET/POST /api/isha/<id>/close`.

## N5 · No time limits on joining
| Limit | Was | Now |
|---|---|---|
| Round invite (MCQ, AI interview, F2F, practice, skill check) | 5 days (2–7 for practice) | **No deadline.** A company can still set "Days a candidate has to finish an invited round" (0 = none). Invites say "Take it whenever you're ready". |
| Candidate's personal portal link | 7 days | **Works until the candidate sets up their account**, or until the team makes a new link (which cancels it). |
| F2F join window | 15 minutes before the scheduled time | **Join any time** (default 0). Uses the live setting, so open invites change too. |

Kept on purpose: report share links (1–90 days) and the retake limit.

## N6 · One "Interview again" action
Five overlapping ways (Retake, Request a re-interview, dispute grant, re-inviting, remove and bring back) are now one
**Interview again** window, the same on the application page, the Interviews list, the interview room ("Technical
problem?"), the job pipeline's Current round column and Superadmin → Rounds. It shows the round's state and only the
options that fit, with the reason for any that are greyed out:

| Option | When | Old attempt | Limit | Credits |
|---|---|---|---|---|
| Change time or interviewer | Not started | Kept, updated | No | Free |
| Re-send the invite | The candidate missed it (expired, or closed without them) | Kept, marked "Missed · re-sent" | No | Free |
| Retake: technical problem | Started but went wrong | Voided (kept, with video) | Retake limit (5) | Charged |
| Re-interview: second assessment | Finished and scored | Kept; both reports; the earlier one is marked "Earlier attempt" | Re-interview limit | Charged |
| Grant a re-interview (dispute) | Superadmin, open dispute | Kept | No | Free |

- An expired invite is no longer re-sent through Retake, so it doesn't use up the technical-retake limit.
- The application page lists every attempt in order, with **Retake**, **Missed · re-sent**, **Re-interview** and
  **Earlier attempt** labels.
- API: `GET/POST /api/attempts/<id>/again {action: reschedule | resend | retake | reinterview | dispute}`. The old
  `/retake` and `/reinterview` routes still work.

## Database (migration 007 / Alembic 0008)
No schema change. Data only: open invites lose their deadline; unused, still-valid portal links stop expiring
(stored as 2099-12-31). Expired invites aren't reopened automatically; use Interview again → Re-send. Safe to run twice.

## Settings added or changed
| Setting | Default | Who |
|---|---|---|
| `practice.ai_share`: share of a practice quiz Hira writes fresh | 80% | Superadmin only |
| `round.deadline_days`: days to finish an invited round | 0 (none) | Platform, company, team, job |
| `call.join_early_minutes` | 15 → **0** (any time) | as before |
| `invite.link_days` | 7 → **0** (until used) | as before |
