# Code2Hire V02.00.03 · beta bug fixes

Fixes the beta bug list BETACODE2-1 to 48, except the items on hold below. Database changes: migration 003 / Alembic
0004 (see `backend/migrations/README.md`). Tests: `backend/tests/test_fixes.py` names each ticket it covers.

## On hold (by request)
- BETACODE2-41 WhatsApp sending (pre-filled recipient, "Did you send it?", message template). The existing WhatsApp and Email buttons are unchanged apart from -38.
- BETACODE2-17 Forgot password (needs an email service).
- Landing page revamp. The three landing bugs (-9, -10, -11) are fixed on the current page.
- BETACODE2-42 full visual revamp. This release does the consistency and phone-width work; the visual redesign waits for a target design.

## Fixed

| Ticket | Fix |
|---|---|
| -1 | One email rule for every form and API (signup, add candidate, staff invite, onboarding). `sonu@123`, `harish@1234`, `sakshi@com` are refused. Existing bad accounts are listed by a query in migration 003, not changed. |
| -2 | Sign-in lock: 5 failures per email in 15 min, or 30 per address, lock for 15 min. Same message whether or not the account exists. Failed sign-ins go to the audit log. Also on signup, invite links, password change and credential verify. |
| -3, -48 | Face check that works in every browser (on-device model, nothing streamed). 2+ people for ~3 s or no face for ~6 s raises a warning with a camera snapshot for reviewers. A "we can see you" check before the round starts. |
| -4 | One warning count from the server for the banner and the header badge. |
| -5 | In-app confirm for "End interview early" (and everywhere: all 9 browser `confirm()`/`prompt()`/`alert()` calls replaced). Our own dialogs never count as leaving fullscreen. |
| -6 | All times stored in UTC and shown in each viewer's local time. The "When" field sends the timezone; the candidate's join window uses the same instant. Optional SQL converts already-scheduled interviews. |
| -7 | One live invite per candidate per round. Inviting again reschedules it (no second charge); a running round can't be re-invited. Migration cancels existing duplicates. |
| -8 | Join button shows "Opens at 12:21 pm" until the join window, then switches on by itself. |
| -9 | "Build my plan" asks Hira for any job title (rate limited); no more Java plan for every role. |
| -10, -11 | Mascot no longer clipped; input and button the same height, stacked on phones. |
| -12 | Scores are stored out of 5 and shown on the company's scale (5, 10 or 100); gauges and bars can't overflow. |
| -13, -19 | Job cards fill the row; with few jobs, a "want more matches" card. |
| -14 | Timer counts from the server's time left, never the device clock; re-syncs after sleep; submits at 0 or less with retries; the server closes overdue rounds itself. Time paused by the recruiter isn't counted. |
| -15 | Recording sound: the audio mixer is started (and restarted on the next click if the browser refuses). The interviewer is warned if the recording has no sound. |
| -16 | DevTools "window size" guess removed (side panels and scaling no longer flag anyone). Keyboard shortcuts still count. |
| -18, -28 | Job rules on create and edit: title required, hires 1–1000, minimum salary ≤ maximum, no past deadline. Migration fixes existing bad jobs. |
| -20 | Verify is disabled until an ID is typed; the ID format is checked. |
| -21 | Toasts: the same message refreshes instead of stacking, at most 3, each closable; Save buttons ignore double clicks. |
| -22, -24 | Test checks the key typed in the box (without saving), says which key it tested, and answers in a plain sentence. |
| -23 | `?new=1` is removed once the dialog opens, so refresh/Back don't reopen it. |
| -25 | /admin pages always show the platform menu, even with support access on. |
| -26 | Templates: edit, duplicate, archive/restore, delete with confirm. Jobs made from a template keep their rounds. |
| -27 | No sideways scroll (side menu and pages). |
| -29, -33 | One score format everywhere: "3.0 / 5 · 60%". Integrity shows "Clean" or "N warnings". |
| -31 | Disputes page (platform and company): candidate's note, report, transcript and integrity; grant a re-interview, change the outcome, or dismiss with a message the candidate sees. Candidates can raise one dispute per round. |
| -32 | Onboard a company: required marks, inline errors, domain/GST checks, duplicate company/admin checks. |
| -34 | Certifications show Progress and Score separately, with each section's score, weight and points. |
| -35 | Copies are named "(copy)", "(copy 2)", "(copy 3)"; never "(copy) (copy)". Same for questions and templates. |
| -36, -43, -44, -45, -46, -47 | Add candidate redesigned: required name and email, phone with country code (digits only), City suggestions, "More details", resume upload fills the form, duplicate check while typing, sticky footer, page scroll locked, clear disabled reason, "Add candidate" / "Add and add another", success screen, "Discard changes?", list preview with errors in red, CSV/Excel upload with template, summary "N added, N skipped, N duplicates". |
| -37, -38 | Link states: Not sent, Link sent (only after Copy/Email/WhatsApp), Opened, Active, Expired, No link yet, each with a tooltip. "New link" button with tooltip and a confirm when a link already exists. Email/WhatsApp are the main actions, Copy is a button, the expiry note is prominent, "Close" not "Done", Email off for invalid addresses. |
| -39 | Notifications: Clear one, Clear all, Mark all read. |
| -40 | Round type shows its full name. |

## Also fixed while testing
- A report that wasn't finished yet could be opened by staff of another company. Now limited to the job's company.
- "Add to a job" from the talent pool accepted any user id; now only people in the company's pool.
- A team-scoped recruiter only found out at the end of the new-job form that they must pick their team; the form now preselects it, and Duplicate shows only when allowed.
- Names written surname-first ("Nair, Vikas") were refused.
- Profile edits (name, phone, city, experience) are now validated.
