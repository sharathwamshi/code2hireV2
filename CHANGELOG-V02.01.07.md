# Code2Hire V02.01.07 · Isha assesses, the interviewer recommends, simpler reports, Regenerate

**Version:** V02.01.07 (25 Nov 2026)

**Migration: none.** Deploy as usual: `bash c2h-deploy.sh deploy` after pushing to git.

**Tests:**
- All **286** backend tests pass, on SQLite and on MariaDB 10.11.
- The V02.01.06 tests were rewritten for the new rules, plus new ones for Regenerate.
- Three older tests checked behaviour that changed on purpose (a pre-filled recommendation, a disagreement reason kept on the report); they were updated.
- Browser check, in a real browser on a test copy of the app:
  - the scorecard has no recommendation pre-selected and no reason fields, and asks for your recommendation when you submit without one;
  - the report has no change log and no "Claude";
  - a report written the old way was rebuilt from its **Regenerate** button, in the background, and the page updated by itself.

## 1. Isha assesses; the interviewer recommends
- **Isha no longer says Proceed, Hold or Do not proceed:**
  - not on the scorecard;
  - not in the "Wrapping up" window ("Isha is deciding" is now "Isha is summarising");
  - not on the report;
  - not in what Claude is asked for.
- **Isha still gives:**
  - every answer's and competency's score, and the overall score;
  - how sure she is, and a one-line summary of the evidence;
  - strengths, concerns and red flags;
  - where the candidate stands for this job, and everything discussed;
  - "Not enough evidence" when too little was heard.
- **On the scorecard, nothing is pre-selected.** "Your recommendation (required)": submitting without one says "Choose Proceed, Hold or Do not proceed".
- **Submit with Isha's scores** is one click once you've picked a recommendation. Change a score and the button becomes "Submit with my N changes".
- **After 24 hours with no scorecard,** Isha's scores go to the report. The recommendation shows **"Awaiting the hiring team"**.
- **The report PDF's footer for these interviews** now says: "Isha scores the interview; the interviewer recommends; a named person reviews and decides."

## 2. No reason needed to change a score
- **On the scorecard,** the "Why did you change Isha's score?" field and the recommendation reason are gone.
- **On the report's Review,** a reason for changing a score is now optional.
- What changed from Isha's scores is still kept in the audit log ("changed": name, Isha's score, the final score), for audit only.

## 3. Reports: one assessment, no change log, no "Claude"
On interviews with Isha, the report (internal, hiring manager and client views, and the PDF) no longer shows:
- the "agreed with Isha" / "changed Isha's 4 → 2" box;
- the "Interviewer vs Isha" agreement panel;
- "Isha's live score" next to each competency, in the chart's key, and in the evidence window;
- "Written by Claude", "Key sentences · Claude was unavailable", and "filed by … (Claude)" / "(matched by keywords)". It now just says "filed by Isha reading the whole transcript".

The competency scores are the final ones, as submitted. "Isha's assessment" shows her summary, confidence, strengths, concerns, red flags, the job ranking and everything discussed. "Not yet confirmed by the interviewer" still shows when Isha published on her own after 24 hours.

## 4. Regenerate: old reports, the new way
- Isha interview reports have a **Regenerate** button, next to Download PDF.
- **It runs in the background:** "Regenerating…" shows, the page updates by itself when it's done, and "Couldn't regenerate" says why if it fails.
- **What happens:**
  - Isha reviews the whole interview again: she reads the transcript, scores every answer, goes through the whole conversation and writes her assessment;
  - the report is rebuilt the current way.
- **What stays as it was:** the interviewer's submitted scores, notes and recommendation, skipped questions, the report's status, the hiring decision, and its sharing.
- It's saved as a **new version** ("Regenerated: Isha reviewed the interview again") in the report's history.
- The candidate is **never sent the thank-you again**, and the team isn't notified of a "new" report.
- Who can use it: the interviewer, or anyone who can record a recommendation for the job. Other kinds of reports (MCQ, coding, AI interviews) can't be regenerated.

## Files
**Backend**
- `services/scorecard.py`: Isha's assessment with no recommendation
- `services/wrapup.py`: "Isha is summarising"
- `routes/isha.py`: no required reasons; the interviewer's recommendation; a report with no change log; `publish(regen=True)`; changes kept in the audit log
- `routes/reports.py`: `POST /reports/<id>/regenerate`; an optional reason on Review
- `services/pipeline.py`: `make_report(notify=False)` for Regenerate
- `services/pdf.py`: the footer for Isha interviews
- `config.py`, tests

**Frontend**
- `pages/app/IshaRoom.jsx`: the scorecard (no pre-selected recommendation, no reason fields, Submit with Isha's scores), Isha's assessment panel, the wrap-up text
- `components/ReportView.jsx`: one assessment; no comparison with Isha's scores and no "Claude" on Isha reports
- `pages/app/Reports.jsx`: Regenerate, with background progress
- `styles.css`, `version.js`, `package.json`
