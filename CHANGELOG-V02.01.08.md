# Code2Hire V02.01.08 · Teams (interviewer activity), mute that works, the interview's IST time on reports

**Version:** V02.01.08 (26 Nov 2026)

**Migration: none.** Deploy as usual: `bash c2h-deploy.sh deploy` after pushing to git.

**Tests:**
- All **290** backend tests pass, on SQLite and on MariaDB 10.11, including 4 new ones in `tests/test_v02_01_08.py`.
- Browser checks (Chromium):
  - Teams and a person's page as the company admin; no Teams for a recruiter;
  - a report's "Taken on · Time · Length";
  - mute and unmute in a real call: through the full device check, then mute, unmute, mute and camera off. Each click flips the button and the "Me" label, and the other side is sent each change.

**Not in this version:** anything about interviewers' own question style or scoring, as you asked.

## 1. Teams: how many interviews each person has taken
A new **Teams** item in the menu, for **company admins only**. Others don't see it, and the pages and the export refuse them.

**The Teams page**, laid out like your PDF:
- **Period:** This month, Last month, Last 3 months or custom dates. **Export CSV.**
- **Tiles:** Interviewers, Interviews taken, Upcoming, Cancelled, Feedback pending.
- **Panels:**
  - Top interviewers (by completed, with a bar);
  - Interviews taken by week;
  - Upcoming interviews (the next 5, with the date and time in IST, linked to the candidate).
- **Interviews by person:** Total, Completed, Upcoming, Cancelled, Feedback pending (in amber), Avg. duration, Last interview, and **View**.

**One person's page** (from View or from Top interviewers):
- **The header:** name, roles, email, account status, last interview, next interview (IST).
- **Tiles:** Total, Completed, Upcoming, Cancelled, Feedback pending, Avg. duration, Time spent.
- **All interviews:** Date, Time (IST), Duration ("45 min planned" for upcoming ones), Candidate (opens the report, or the application before there is one), Job role, Round, Status, Result.
- **Export CSV** for just that person.

**What's counted**

| Column | Counted as |
|---|---|
| Interview | Live rounds with an interviewer assigned: Technical F2F with Isha, and live interviews |
| Completed | The interview ended. "Closed early" shows as its own status and counts as completed |
| Upcoming | Invited or scheduled |
| Cancelled | Cancelled, replaced by a retake, or expired |
| Feedback pending | Ended, and the interviewer hasn't submitted a scorecard (including when Isha published on her own after 24 hours) |
| Duration | The real call time, from Start to End |
| Time spent | The sum of those durations |
| Result | The interviewer's recommendation: Proceed, Hold or Reject |

- **The period and its weeks** follow the company's time zone (IST unless set otherwise in Company admin), and the period stays in the address bar, so Back and shared links keep it.
- **The CSV** has one row per interview (Interviewer, Date, Time (IST), Duration, Candidate, Job role, Round, Status, Result) and opens in Excel with names intact.
- **When there's nothing yet,** an empty state replaces the charts.

## 2. Mute and unmute work
- **The bug:** clicking mute turned the microphone off, but the screen didn't redraw. The button kept saying "Mute", so the next click turned it back on, and mute looked broken. The camera button had the same problem.
- **Now in the interview room:**
  - the button flips at once and turns red, and "Me" shows "muted";
  - the candidate sees "The interviewer is muted";
  - you see "[Name] is muted" when they are.
- **After every reconnect,** each side tells the other again whether its microphone and camera are on, so nobody sees a stale "muted".
- **"You're muted"**: if you talk for about a second while muted, a red banner says so, with **Unmute**. The candidate gets the same reminder on their side.
- **On the candidate's side,** the page now redraws when they mute, so their captions and the reminder follow at once.

## 3. Reports: when the interview was taken, in IST, and how long
- **Under the candidate's name:** **Taken on** (e.g. Wed, 25 Nov 2026) · **Time** (10:00 AM – 10:42 AM IST) · **Length** (42 min).
- **The length** is the real call time: from Start to End interview, not when the scorecard was submitted.
- **In every report view and in the PDF** ("taken Wed, 25 Nov 2026, 10:00 AM – 10:42 AM IST · 42 min").
- **The time zone** is the company's (IST, Asia/Kolkata, by default). Another zone shows its own name instead of IST.

## Files
**Backend**
- `services/activity.py` (new): interviews by person, statuses, durations, weeks, IST times
- `routes/teams.py` (new): `GET /api/teams`, `GET /api/teams/<user>`, `GET /api/teams/export.csv` (company admins only)
- `routes/reports.py`: `taken` on every report
- `services/pdf.py`: the time and length in the PDF header
- `app.py`, `config.py`, `tests/test_v02_01_08.py`

**Frontend**
- `pages/app/Teams.jsx` (new): the Teams page and a person's page
- `components/Shell.jsx`, `App.jsx`: the Teams menu item and routes
- `pages/app/IshaRoom.jsx`, `components/CallWindow.jsx`, `pages/room/CandidateCall.jsx`: mute and camera fixes, re-sending after reconnects, "You're muted"
- `components/ReportView.jsx`: Taken on · Time · Length
- `styles.css`, `version.js`, `package.json`
