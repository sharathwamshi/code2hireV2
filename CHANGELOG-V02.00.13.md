# Code2Hire V02.00.13 · Isha interview redesign

This release redesigns the live (F2F) interview with Isha. The interviewer picks the questions before the interview. Isha proposes them in **sections**, one per skill or topic from the job description and the resume. Each section mixes **question types**, weighted by the **candidate's level**.

During the interview:
- Isha **hears** which question was asked, so there's no "Ask this" button to press.
- Follow-ups stay specific even when Claude is down.
- The screen follows layout **Option A** from the design canvas.
- The scorecard no longer fails with "Something went wrong".

**Version:** V02.00.13 (19 Nov 2026).

**Database:** **no migration.** Everything new lives in fields that already exist:
- the interview plan (`round_attempts.brief`);
- the interview's live state (`round_attempts.result`).

Interviews already started or finished keep their old plan and open as before. One new optional setting: **"Interview length (minutes)"** (`f2f.minutes`, default 45). It needs no database change.

**Tests:** new `backend/tests/test_v13.py` (15 tests). All **235** backend tests pass on SQLite and on MariaDB 10.11.

**Browser walkthroughs:** the new `walk13` passes 10 of 10 steps.

## Deploy
`bash c2h-deploy.sh deploy` after pushing to git. There's nothing to migrate. Alembic stays at `0011_v12_data_fixes`.

## The scorecard error
**"Something went wrong" when a competency was left unrated.**
- **Cause:** leaving any competency on **Skip** made the server crash while building the report.
- **Now:**
  - A skipped competency shows as **"Not rated"**.
  - With nothing rated, Submit stays off and says **"Rate at least one competency from 1 to 5 to submit."**
  - With some skipped, it says how many will show as Not rated.
  - A score that isn't 1–5, or a missing recommendation, gets a plain message.
- The same check was added when someone edits scores on a report.

## Prepare questions (before the interview)
- **Opens by itself** the first time an interviewer opens a not-yet-started interview with Isha. It's also under **Prepare questions / Change questions** in the room.
- **Sections:**
  - **Introduction:** "Tell me about yourself…". It always opens the interview, and its prepared follow-ups pick up on what the candidate says.
  - **Core:** in the job description *and* on the resume. Goes deep and checks the claims.
  - **Gap:** needed for the job but not on the resume. Starts basic.
  - **Resume claim:** on the resume but not needed for the job. One quick check that it's true.
  - **The role:** the job's own duties and business.
  - **Working style:** how they work with others and under pressure.
  - **Your questions:** questions you add.
- **How skills are grouped:** related skills share a section (Django under Python, PostgreSQL under SQL). Must-have skills come first, and at most 5 skill sections are proposed.
- **What the section header shows:** must-have, the years on the resume, and "Already proven" when an earlier round or a verified skill already shows it. Proven skills skip the basics.
- **Question types:**

  | Type | What it is |
  |---|---|
  | Basics | Applied: explain it and say when it's the wrong choice. Never a bare definition. |
  | Hands-on | What it prints, read a log, say the query |
  | Scenario | A situation with a constraint |
  | Real situation | On-call or production pressure: what to check, in order |
  | Own experience | Their own project, quoted from the resume |
  | Design / trade-off | Architecture and trade-offs, for experienced candidates |

- **Candidate level:** Fresher, Mid-level, Senior or Lead. It's guessed from the resume's years, then the job's level, and the interviewer can change it. Changing it rewrites the questions.
- **"How Isha mixes questions"** is an info card with one row of bars per level. You can press a row to use that level.

  | Level | Basics | Hands-on | Scenario | Real situation | Own experience | Design |
  |---|---|---|---|---|---|---|
  | Fresher (0-2 yrs) | 35% | 30% | 10% | 10% | 15% | – |
  | Mid-level (3-6) | 15% | 25% | 15% | 15% | 30% | – |
  | Senior (7+) | 5% | 10% | 10% | 15% | 30% | 30% |
  | Lead / manager | – | – | 10% | 15% | 35% | 40% |

- **Every question shows:**
  - its type, about how many minutes it takes, and the points a good answer covers;
  - where it came from: **Written by Claude**, **Built-in · Claude was unavailable**, or **Yours**;
  - its prepared follow-ups (3 each).
- **Built-in questions** are written from the job and the resume when Claude is unavailable: the job's business, real-sounding numbers, a line from the resume. **Rewrite** (per section, or "Rewrite unticked") writes them again.
- **Your questions:**
  - Tick, reorder and remove them.
  - **Use Isha's picks** restores Isha's choice.
  - Add your own, into any section.
  - A time bar shows "≈ 32 of 45 min" against the interview length.
- **Checks:** every must-have skill has a question; the time fits; several types are used; how many are built-in; follow-ups are ready.
- **When Isha decides:** before anyone saves, the plan keeps the round's question count. After you save, your choice is kept as it is. Once the interview starts, the choice is locked; questions can still be added or skipped from the room.

## The interview room (Option A)
- **Layout:**
  - **The call is on top**, with **Isha's follow-ups** beside it.
  - **The questions are at the bottom centre:** a row of cards with each question's status (Not asked, Asking, Answered, Partly, No answer heard, Skipped) and your score.
  - **Under them, the current question:** its type and source, the live answer, and the points a good answer covers.
  - **Your rating sits beside the current question:** 1–5, with Isha's suggestion dashed, and a quick note.
- **No "Ask this":**
  - Isha hears the interviewer's own voice (call or microphone) and files the answer under the question that was asked, in any order.
  - When she's only half sure, she asks **"Did you ask …? Yes / No"**.
  - A follow-up that's asked out loud, suggested or pinned, is filed as a follow-up of the current question.
  - **Mark as asked** stays as a fallback for typed captions or an outside meeting.
- **Follow-ups:**
  - Each one shows its source: Claude (live), Prepared, Built-in, or From your plan.
  - **Pin** keeps up to 3 on top. A pinned follow-up unpins by itself once it's asked.
  - The latest follow-ups survive a page reload.
- **Prepared follow-ups:** while a point of a good answer is still missing, its prepared follow-up stays offered until it's covered or asked, even with Claude down. When Claude answers with fewer follow-ups than set, prepared ones fill the gap.
- **Your rating per question** counts first on the scorecard, ahead of Isha's own score, and Claude's draft never overrides it. The report shows each question's rating, section, type and source.
- **Ask Isha:**
  - A private chat drawer: ask for a harder question, what to ask about a resume claim, or whether a point was covered.
  - Any question Isha suggests can be **pinned** or **added to the plan**.
  - The newest follow-up shows at the bottom while it's open, and the button's badge counts new follow-ups.
  - Without Claude it answers from the plan: what's covered, what's missing, the prepared follow-ups, and what's still to ask.
- **The side rail** opens Candidate, Plan (reorder, skip, add), Resume, Rounds, Notes, Integrity and Transcript in a drawer, so the main screen has no transcript.
- **Before Start**, the screen explains how it works in four steps, next to the Prepare questions button.

## Files
- **New:**
  - `backend/services/isha_prep.py`: sections, types, levels, built-in questions, Isha's picks, checks
  - `frontend/src/components/PrepareQuestions.jsx`: Prepare questions and the mix table
  - `backend/tests/test_v13.py`
- **Changed:**
  - `backend/routes/isha.py`:
    - prepare (GET and POST), rate, chat;
    - "Did you ask" and follow-up hearing;
    - the scorecard fix;
    - the source in the report.
  - `backend/services/ai.py`: prepared follow-ups, Ask Isha
  - `backend/services/scorecard.py`: your ratings come first
  - `backend/services/settings.py`: `f2f.minutes`
  - `backend/routes/reports.py`: score edit check
  - `frontend/src/pages/app/IshaRoom.jsx`: the stage layout, pins, Ask Isha, rating
  - `frontend/src/styles.css`
- **Older tests updated for the new order:** in `test_v04`, the Introduction now opens the plan, before the recruiter's own questions.
