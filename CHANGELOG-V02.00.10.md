# Code2Hire V02.00.10 · candidate portal redesign, forgot password by email, staff edit candidates

This release covers:
- every gap in `Code2Hire_Candidate_Page_QA_Issues_Updated_v2.xlsx` (CP-001 to CP-011) and
  `Code2Hire_Portal_Review_2.xlsx` (GLB, HOM, JOB, APP, PRA, SKL, LRN, CER, FDB, PRF), plus the PDF redesign of the
  candidate pages;
- **forgot password by email**, with **SMTP settings** in Superadmin → Platform settings → Integrations (BETACODE2-17,
  password part);
- **Change password for everyone, admins included**, from a new avatar menu;
- **staff edit a candidate and add or replace the resume** (recruiters, interviewers, company admins, managers);
- a **strict profile-strength formula** that uses every item;
- **Disha on Home** (the floating Ask Disha button is unchanged);
- **a certification's Knowledge section verifies the skill**.

**Still on hold:** WhatsApp (BETACODE2-41), the landing page revamp. Other emails (invites, reminders) still go
through the existing channels. Only password reset and the SMTP test use the new mailer.

**Version:** V02.00.10 (16 Nov 2026). Candidates see it once at the bottom of the side menu. It is also in `GET /api/health`.
**Database:** migration **008**, or Alembic `0009_v10_candidate_portal`. It adds `candidate_profiles.saved_jobs`,
`learning_paths.meta` and the table `product_feedback`. It makes no data changes.
**Tests:** new `backend/tests/test_v10.py` (23 tests). All **185** backend tests pass on SQLite and on MariaDB 10.11.
Migration 008 (SQL and Alembic) gives the same schema as a fresh install, survives down and up, and is safe to re-run.
Browser walkthrough `walk10`: 18 of 18 steps pass. The V05–V09 walkthroughs still pass (93 steps).

## Deploy
1. Back up the database.
2. Run `mysql -u USER -p DBNAME < backend/migrations/sql/008_v10_accounts_and_candidate_portal.up.sql`, or `alembic upgrade head`.
3. Deploy the code, rebuild the frontend (`npm ci && npm run build`) and restart.
4. Set `C2H_PUBLIC_URL=https://your-domain` in the backend environment so reset links point at the public site.
5. Sign in as superadmin and fill in **Email (SMTP)** under Platform settings → Integrations. Presets fill in
   Gmail / Google Workspace, Microsoft 365, Zoho Mail (India) and Amazon SES (Mumbai). Press **Send test email**. Until SMTP is saved, "Forgot password?" tells
   people to ask their admin.

## Accounts
| What | How it works |
|---|---|
| Forgot password | Use the "Forgot password?" link under the password box. The reply is the same whether the email exists or not. Requests are limited to 5 per 15 minutes per address. The link is valid for 60 minutes and works once. A new request cancels the old link. Reset links can never open a candidate portal. |
| Reset page | `/reset/<token>` shows the email address, takes the new password with the usual strength rules, and signs the person in. |
| SMTP settings | Fields: host, port, STARTTLS / SSL / None, username, password (stored masked), from address, from name and reply-to. Values are checked before saving. Send test email reports SMTP errors in plain words. |
| Change password | The avatar menu (top right) has Change password for everyone, including superadmin and company admins. The menu also holds Profile and privacy (candidates), Change the name shown (superadmin) and Sign out, which now asks before signing out. |

## Staff edit a candidate
- An **Edit** button appears in the Talent pool, a job's candidate list and Added candidates. **Edit candidate**
  appears on the application page. It shows for anyone with the new permission `candidates.edit`: recruiters,
  interviewers, company admins, managers and the superadmin.
- **Details and skills** tab: name, headline, city, phone, experience, target role and skills. The email (the
  sign-in) can't be changed, and verified skills can't be removed or lowered.
- **Add / Replace resume** tab: upload a PDF, DOCX or TXT file, or paste the text. Disha shows what will change
  before anything is saved.
- Staff can only edit people who belong to their company (applied, or added by the team). Every change is in the
  audit log (`candidate.edit`, `candidate.resume_by_staff`), and the candidate is told when their resume is changed.

## Profile strength (strict, 100 points)
| Item | Points | Counts when |
|---|---|---|
| Full name | 5 | Present |
| Resume | 15 | At least 200 characters |
| Headline | 10 | Present |
| City | 10 | Present |
| Phone | 10 | 10 to 15 digits |
| Years of experience | 10 | Set (0 = fresher counts) |
| At least 5 skills | 10 | 5 or more |
| Target role | 10 | Set |
| A verified skill | 20 | At least one |

Each missing item is a chip that jumps to its field. Home also shows a 5-step "Your next steps" checklist, which is
hidden once all 5 steps are done.

## Resume (CP-004)
A new resume **replaces** the skills that came from the old resume. Skills added by hand and verified skills always
stay. Before saving, the candidate (or staff member) sees what will be added, removed and filled in, and can untick
any change. Skill names are spelled properly (e.g. "sap attp" becomes SAP ATTP), and "Java" is no longer found inside
"JavaScript".

## Certifications: Knowledge section verifies the skill
When a candidate passes a certification's Knowledge (MCQ) section, they earn a verified badge for up to 3 of the
certification's skills at its level. The pass mark is the section's minimum, or 70% when none is set. No badge is
given if the section had more integrity warnings than allowed. Each badge is given once. The final certificate still
needs the whole exam.

## Candidate portal, page by page
| Page | Changes (review ids) |
|---|---|
| Home | Stat cards open their page (CP-001, HOM-03). Profile-strength ring. Next-steps checklist. **Disha panel** with a tip, 4 shortcuts and an ask box that open Ask Disha (CP-006). The Target role field has role chips, and "Show my path" stays off until a role is entered (CP-002, HOM-04). Top 6 skills with a Self-reported / Verified legend and "View all N" (HOM-10). 3 matching jobs. Recent activity (HOM-12). Names are shown with capitals (GLB-05). |
| Jobs | Filters for location, work mode, experience, verified skills only (off, with a hint, when nothing is verified yet) and saved jobs. Result count, removable filter chips, Reset. A banner to verify your best self-reported skill. Neutral match ring (JOB-13). YOU HAVE ✓ and TO LEARN chips that wrap (JOB-06), and clicking a TO LEARN chip builds a path. **Skill alternatives and synonyms match** (JOB-07). Save (bookmark) a job (JOB-11). Applied jobs show the date and "View application". Empty state with Clear filters. |
| Job page | Apply confirmation with next steps. If the resume is missing, the candidate is asked for it instead of seeing an error (CP-003). Each round has a short description. Save button. |
| Applications | Summary cards (active, scheduled, next up with Prepare with Disha). A numbered stepper with a plain state for each round (completed, scheduled, next up, not finished, missed, not selected, upcoming). Tap a round for details and how to prepare. "Technical F2F with Isha" now reads "(AI-assisted)" (APP-04). Prepare for next round opens practice for that role. Withdraw asks first. |
| Practice | **The role is required, and questions are only about the role** (CP-011). The role's skills are preselected (PRA-04), and profile skills can be searched. Quiz mode still shows the question-bank topics with question counts (CD-005). Suggested for you. Easy/Medium/Hard. Question count with a time estimate. Mic notice with Test mic. Retry on past sessions. Empty state. |
| Skill checks | Badges show their expiry. Recommended checks with a reason for each. Skill autocomplete and quick chips. Level 1–5 names and meanings: Beginner, Working, Independent, Advanced, Expert. Rules list, camera notice. Opens with the skill and level from links. |
| Learning paths | "Try" chips from your job gaps instead of fixed examples (CP-009). One path per skill. Correct capitals (LRN-02/03). Minutes per topic. "1 of N done". The current topic is highlighted. Start topic / Practise with Disha / Mark done. A last step for the skill check. A "basic outline" label with **Rebuild with Disha** when the AI was unavailable. Side panel: time left and the application this path leads to. Removing a path asks first (GLB-11). |
| Certifications | State tags: Available, In progress (Continue), Locked (with a button for the check you need), Earned, Retake later, No attempts left. An attempt in progress is no longer told to wait for a retake (CER-04). Shows "Issued by", the pass mark, "Points so far X of 100", and a Status column per section. Spoken sections have a mic-test note. |
| Feedback | How feedback works. Empty state with "Practise an interview while you wait". A "Waiting on" list. **Tell us what you think of Code2Hire**, with topic chips and a 1–5 rating (CP-008). The superadmin reads these under **Candidate feedback**. |
| Profile | Strength banner with chips that jump to each field. Hints and checks on every field. Add-skill box at the top with autocomplete that blocks duplicates. 2-column skill grid with level names and Verify links. Removing a skill asks first. A sticky Save bar appears only when something changed, with a warning if you leave unsaved (PRF-08). Resume preview before saving. "Practice sessions are never shared with employers." |
| Everywhere | **Global search** in the header for jobs, skills and paths (CP-005, GLB-01). Avatar menu. Retry when a page fails to load (GLB-10). Content keeps clear of the floating Ask Disha button. Works on phones with no sideways scroll. Focus rings throughout. |

## Files
- New backend: `services/skills.py`, `services/profile.py`, `services/mailer.py`, `tests/test_v10.py`.
- New frontend: `components/GlobalSearch.jsx`, `components/ResumeReview.jsx`, `components/EditCandidate.jsx`.
- `pages/me/Me.jsx` is rewritten. `Auth.jsx` adds the Forgot password and Reset password pages.
- `Admin.jsx` adds the SMTP card and the Candidate feedback page. `Shell.jsx` adds the avatar menu and search.
- `backend/migrations/sql/008_*`, `backend/migrations/alembic/versions/0009_v10_candidate_portal.py`, and an updated `migrations/README.md`.
