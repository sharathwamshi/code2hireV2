# Code2Hire V02.00.11 · candidate interview bug report (CAN-001 to CAN-022)

This release fixes every open item in `Candidate_AI_Voice_and_MCQ_Interview_Bug_Report_Updated.xlsx`, using the
decisions from the gap analysis:
- **CAN-021:** practice shows the integrity rules as a rehearsal.
- **CAN-015 / CAN-016:** MCQ questions are reviewed before the test. Whoever sets up the round chooses the paper.
- **CAN-004:** practice is deleted permanently.
- **CAN-018:** applicants are rescored when either the job's skills or a candidate's skills change.

CAN-011 to CAN-013 were ignored as asked. CAN-001 and CAN-003 were already fixed in V02.00.10.

**Version:** V02.00.11 (17 Nov 2026).
**Database:** migration **009**, or Alembic `0010_v11_resume_files`. It adds the table `resume_files` and the column `jobs.history`, with no data changes.
**Tests:** new `backend/tests/test_v11.py` (16 tests). All **201** backend tests pass on SQLite and on MariaDB 10.11.
Migration 009 (SQL and Alembic) matches a fresh install, survives down and up, and is safe to re-run.
**Browser walkthroughs:** the new `walk11` passes 14 of 14 steps, and the earlier walkthroughs (walk5 to walk10) still pass: 117 steps in all. Three older walkthroughs were updated for the new MCQ review step and the conversation panel.

## Deploy
1. Back up the database **and the `UPLOAD_DIR` folder**. Resume files are now kept on disk under `UPLOAD_DIR/resumes/`.
2. Run `mysql -u USER -p DBNAME < backend/migrations/sql/009_v11_resume_files_job_history.up.sql`, or `alembic upgrade head`.
3. Deploy the code, rebuild the frontend and restart.
4. Optional:
   - Install **LibreOffice** (`libreoffice-writer`) to read old Word `.doc` resumes.
   - Install **Tesseract** and **poppler-utils** (`tesseract-ocr poppler-utils`) to read scanned PDF resumes.

   Without them, candidates get a clear message asking for a DOCX or a text PDF.
5. **Behaviour change:** MCQ rounds now need someone to approve each candidate's questions before the candidate can start. This is on by default.
   - **To turn it off:** set **"Someone checks each candidate's questions before they can start"** to off in Settings (company, team, job or round). Candidates can then start straight away, as before.

## Fixes
| Id | What changed |
|---|---|
| CAN-019 | **The F2F chat box showed typed text white on white.** Every text box in the dark interview rooms now has dark text and a visible cursor. |
| CAN-020 | **The interview screen no longer scrolls**:<ul><li>MCQ: the question header is pinned at the top and Previous/Next at the bottom. Only a long question scrolls.</li><li>AI interview: Hira and the status are at the top, the conversation is in the middle, and the answer controls are pinned at the bottom.</li><li>Checked at 1366×768 and 1280×720.</li></ul> |
| CAN-021 | **Tab switching** (no website can block it, so switching is made useless instead):<ul><li>While the round isn't the window in front, the questions are covered.</li><li>When fullscreen is required, the round waits behind "Return to fullscreen".</li><li>The time away is recorded in the report.</li><li>**Practice** runs the same rules as a rehearsal: an "Integrity rehearsal" tag, and a notice for anything that would count, but nothing counts or pauses.</li><li>A skill check or certification section that goes past its warnings now **ends and is scored** instead of pausing forever, because it has no recruiter who could resume it.</li></ul> |
| CAN-022 | **The paused screen** explains what happens next and offers **Back to home** (continue later from home) and **Remind the hiring team**, limited to once every 10 minutes. |
| CAN-005 | **Certification progress no longer jumps from 0 to 1.** A section counts when the candidate finishes it. While Hira scores an AI-interview section it shows "Scoring…", and the page refreshes by itself. |
| CAN-004 | **Delete a practice session**: the bin button removes it permanently, including answers, transcript, report and recording files. Only a count stays in the audit log. Skill checks can't be deleted because they back badges. |
| CAN-017 | **One conversation**:<ul><li>The AI interview shows Hira's questions and your answers as a running chat. It reloads after a refresh.</li><li>In F2F, the candidate's captions show both people in one box, labelled Interviewer and You, in order.</li></ul> |
| CAN-014 | Before an AI interview, the start screen shows **"Resume Hira will use"** (file name and date), with **Replace** that opens the usual preview. It's locked once the interview starts. |
| CAN-002 | **Resumes from phone file managers:**<ul><li>The type is now judged by the file's content, so files with no extension work.</li><li>Old Word `.doc` files are accepted.</li><li>Scanned PDFs are read with OCR when the server has it.</li><li>**The original file is kept**: the candidate sees "📄 name · size · date" with Download on Profile. Staff see it in Edit candidate, with earlier versions. Every download by staff is logged.</li></ul> |
| CAN-015 / CAN-016 | **MCQ questions are checked before the test.** Details below. |
| CAN-018 | **Jobs can be edited, deleted and archived, and applicants are rescored.** Details below. |

## MCQ papers (CAN-015 / CAN-016)
- The questions are drawn **when the candidate is invited**, not when they press Start.
- The hiring team gets a notification **"Review an MCQ paper"**. The application page shows **Review questions**: every question with the correct answer and the explanation, plus "Draft by Hira" labels.
- Reviewers can **swap one question** (for another of the same skill) or **redraw all**. Then **Approve and let them start**.
- Until then, the candidate sees **"Being prepared"** on their home page and in the room. They get a notification when the test is ready.
- After the candidate starts, the paper is locked, and they get exactly the approved questions in the approved version.
- **Round setup** (Rounds and rules → Configure) has two new settings:
  - **Question paper:** "random" (each candidate gets their own draw; the default) or "same" (everyone gets the same paper).
  - **Someone checks each candidate's questions before they can start:** on by default.
- **Preview a sample paper** shows questions with answers from the pool the round draws from. With "same", **Use this paper for everyone** saves it. Every invite then gets that paper, already approved, because it was checked once in setup.
- Practice, skill checks and certification sections have no hiring team, so they still draw their questions at Start.

## Jobs (CAN-018)
- **Edit job** on the job page has three tabs:
  - **Details:** title, level, description, location, work mode, visibility, hires, salary, deadline, client.
  - **Skills:** add, remove, levels, must-have.
  - **History:** who changed what, from what to what, and how many applicants were rescored.
- **Changing the skills rescores every open application.** The recruiter is told how many before saving. Each application keeps its previous score, with why and when.
- When Hira had written shortlist notes, the application records that they predate the change. Run Shortlist again to refresh them.
- Candidates' skills drive rescoring too. Rescoring happens when a candidate:
  - edits their skills or saves a new resume;
  - gets a skill verified;
  - presses **"+ I have …"** on a job page, which adds the missing skill as self-reported. A new **"Already have one of these?"** card on the job page offers this.

  It also happens when staff edit the candidate's skills or resume.
- **Delete job:** only when nobody has applied (a draft or a mistake). Otherwise the job can only be **archived**.
- **Archive:** archived jobs leave the jobs list (Status filter "Archived" shows them) and stop taking applications. Candidates, reports and history stay. **Restore job** brings the job back as closed.

## Answers to the two questions
- **Is integrity in Settings now?** Yes. Company, team, job and round settings have an **Integrity** group:
  - warnings allowed before a pause;
  - require fullscreen;
  - face check;
  - block copy and paste;
  - "events that pause at once" (tab switch is one of the choices).
- **Is integrity checking happening in real interviews?** Yes, in every hiring MCQ and AI-interview round:
  - It records tab or app switches, leaving fullscreen, copy and paste, developer tools, and (with the face check) no face or more than one face.
  - Each counts as a warning, and after the allowed number the round pauses for the recruiter.
  - Live F2F interviews warn and tell the interviewer, but never pause by themselves.
  - New in this release: the screen cover, the fullscreen gate, and time away recorded.
  - It was **off in practice** before, which is likely why tab switching looked unrestricted. Practice now shows it as a rehearsal.

## Also fixed
- Tabs inside a scrolling dialog could collapse to zero height, which hid the Edit job tabs. Fixed for all dialogs.

## Files
- **New backend files:** `services/papers.py`, `services/resumes.py`, `tests/test_v11.py`, `tests/conftest.py`. The conftest switches paper review off for suites written before this release.
- **New frontend file:** `components/PaperReview.jsx`.
- **Rewritten parts:**
  - the room layouts in `pages/room/Room.jsx`;
  - the captions in `CandidateCall.jsx`;
  - `useCover` in `lib/integrity.js`;
  - Edit job / Archive / Delete in `pages/app/Jobs.jsx`;
  - the resume file line in `ResumeReview.jsx`.
- **Migrations:**
  - `backend/migrations/sql/009_*`
  - `backend/migrations/alembic/versions/0010_v11_resume_files.py`
  - an updated `migrations/README.md`
