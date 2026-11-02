# Code2Hire · Powered by AcknowledgerFirst

AI agents for every side of hiring.

- **Hira** (recruiter agent): drafts jobs, shortlists with reasons, runs MCQ rounds and voice AI interviews, and writes evidence-linked reports.
- **Isha** (live F2F copilot): reads every sentence the candidate says and suggests the next question to the interviewer.
- **Disha** (candidate agent): learning paths, practice, skill-check badges, certifications and job matching.

**Stack:** Python (Flask, SQLAlchemy) · React (Vite) · MySQL 8 · **Anthropic** for all AI work · **Azure Speech** for all voice.

---

## 1. Run it

### Option A: Docker (MySQL included)

```bash
cp backend/.env.example backend/.env      # add your Anthropic and Azure keys (optional; see section 3)
docker compose up --build
```

- App: http://localhost:8080
- API: http://localhost:5050/api/health

Demo data is seeded on the first start.

### Option B: Local development

**Requirements:** Python 3.11+, Node 20+, MySQL 8.

```sql
CREATE DATABASE code2hire CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'code2hire'@'%' IDENTIFIED BY 'code2hire';
GRANT ALL ON code2hire.* TO 'code2hire'@'%';
```

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # set DATABASE_URL and keys
python seed.py                    # creates tables and demo data (use --reset to start again)
python app.py                     # http://localhost:5050

# frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173 (proxies /api to :5050)
```

**Single server for production:** run `npm run build`. Flask then serves `frontend/dist` itself, so `gunicorn -w 3 -b 0.0.0.0:5050 app:app` is all you need.

### Demo accounts (password `Code2Hire@123`)

| Email | What it shows |
|---|---|
| super@code2hire.ai | Superadmin: companies, credits, integrations, global defaults, question bank, certification review, audit |
| admin@acme.test | Company Admin: people, stacked roles, custom roles, grants and cover, policies, settings, branding |
| priya@acme.test | Manager **and** Interviewer (stacked roles); approvals; Isha live room |
| rahul@acme.test | Recruiter **and** Interviewer, scoped to the Engineering team |
| anita@acme.test | Interviewer only |
| vikram@acme.test | Hiring manager on one job only (job-level assignment, no company role) |
| arjun@demo.test | Candidate with an MCQ invite |
| meera@demo.test | Candidate with an AI voice interview invite |

### Tests

```bash
cd backend && pytest -q
```

The test runs one end-to-end journey on SQLite across every role:

- onboarding, stacked roles, and setting locks and inheritance
- the Hira job draft, and policy approvals (including two-approver offers)
- signup, apply, shortlist and Ask Hira
- the MCQ round with integrity warnings, pause and resume
- the AI interview with follow-ups, then report review, versioning and client and candidate sharing
- the Isha live room, per-sentence analysis and scorecard
- separation of duties
- grants with expiry, analytics, report builder and CSV export
- practice, skill-check badges and public verification, learning paths, and a two-section certification exam

---

## 2. Everything is configurable

Settings inherit **Platform → Company → Team → Job → Round**.

- Every screen shows where each value comes from.
- Any level can **lock** a value so the levels below can't change it.
- Superadmin edits platform defaults. Company Admins edit company and team values. Recruiters edit the job tab and each round.

| Group | Examples |
|---|---|
| AI | Anthropic model (Opus / Sonnet / Haiku), summary length, interview language, topics the AI must never ask about |
| Voice | Voice on or off, **Hira's default voice**, **voices candidates may choose from** (with ▶ preview), speaking rate, candidate can choose, silence timeout |
| MCQ | Number of questions, minutes, negative marking, randomise |
| AI interview | Number of questions, follow-up depth, difficulty, minutes, attempts |
| Pass rules | Auto-advance threshold, auto-reject threshold, apply automatically |
| Integrity | Warnings allowed, fullscreen, face check, paste block, events that pause at once |
| Isha | On or off, number of options shown, hide AI scores until the scorecard is submitted |
| Reports | Scale, review before sharing, what clients see, what candidates see |
| Policies | Separation of duties, re-interview limit, decision SLA, data retention |
| Certifications | Validity, retake cool-down |

Other configuration areas:

- **Policies:** "When [event] if [conditions] then [require N approvals / block / notify]". Covers job publish, offers, rejections, re-interviews, report sharing, sensitive grants and credit thresholds.
- **Roles and permissions:** 25 permissions and 5 built-in roles, plus custom roles. Roles stack per person and can be scoped to the company, a team or a job. Grants can expire. Temporary cover is supported. There is a quarterly access review.
- **Certifications:** an 8-step builder covering sections and weights, grading bands, proctoring, eligibility, attempts and fee, validity and output.
- **Hiring templates, question banks** (global and company), and **saved table views** and **saved reports**.

## 3. Anthropic and Azure

Add keys in either place:

- `backend/.env`
- in the app: **Superadmin → AI, voice and defaults → Integrations**, which has a **Test** button for each service

| | Used for |
|---|---|
| **Anthropic** (`services/ai.py`) | Every AI task goes through one `ask_json()` call that uses the model chosen in settings. It covers: job drafts, MCQ generation, resume scoring, interview plans, follow-ups, evidence-linked reports, Isha's brief, per-sentence analysis and scorecard, candidate feedback, learning paths, Disha's path, Ask Hira filters and plain-language report building. |
| **Azure Speech** (`services/speech.py`, `frontend/src/lib/speech.js`) | **TTS** for Hira's voice (SSML, any neural voice, configurable rate). **STT** in the browser with short-lived tokens, used for candidate answers and for Isha's live transcript. Isha can also listen to a shared meeting tab's audio. The voice catalogue is loaded live from Azure and filtered by the allowed-voices setting. |

**Without keys** every flow still works, with deterministic built-in logic and the browser's own speech engines. You can demo the whole product first and add the keys later.

## 4. Built-in video call for F2F rounds

F2F rounds (with Isha or human-only) now run on a built-in video call. No Meet, Zoom or Teams is needed.

**How it connects:**
- Video and audio go **directly between the two browsers** (WebRTC).
- Code2Hire only relays the short setup messages (`routes/call.py`, using plain HTTP long-polling, so no extra server is needed).
- The interviewer always starts the connection. If either person refreshes the page or reconnects, the call re-establishes by itself.

**Interviewer (Isha room):**
- **Join video call** opens a floating window you can drag, resize, minimise or expand. The candidate is shown large, with your own video small in the corner.
- Controls: mute, camera, screen share, chat, hang up. A REC badge shows while recording.
- Status badges show "candidate muted", "candidate is sharing their screen" and "candidate left the call tab".

**Candidate (`/room/<id>`, opened from the Join button on their home page):**
- A notice says the call is recorded, that it is AI-assisted with live captions, and suggests headphones.
- Camera and microphone check, then consent, then the call.
- Inside the call: a waiting room until the interviewer arrives, the interviewer shown large, plus mute, camera, screen share and chat.

**Isha hears the candidate:**
- The candidate's browser turns their speech into live captions. It uses Azure Speech when configured, and the browser's own engine otherwise.
- The captions go to the interviewer's room, and Isha analyses every sentence: tags, live score, coverage and the next question.
- "My microphone" and "Other meeting tab" are still available as alternatives.

**Recording:**
- The interviewer's browser records the candidate's video with both voices mixed. It is uploaded when the interview ends.
- It plays back inside the report. Every view is logged, and the recording is never shown in the client or candidate versions of the report.

**Settings** (group "Video call", configurable per platform, company, team, job or round):
- built-in call on or off
- captions for Isha
- recording
- screen sharing
- chat
- telling the interviewer when the candidate leaves the tab
- how many minutes early candidates can join
- STUN and TURN servers

**Production notes:**
- Add a **TURN server** (for example coturn, or a managed service) under the settings. Without one, some corporate networks block peer-to-peer media.
- Browsers only allow camera and microphone on **HTTPS** (or localhost).
- Each open call keeps one long-poll request per person, so the Docker image runs gunicorn with 16 threads per worker. Raise the thread or worker count for many simultaneous calls.

## 5. Question bank

The question bank lives at **Question bank** for managers and anyone else with the question-management permission, and at **Global question bank** for the Superadmin.

- **Folders:** nest as deep as you like, for example *Engineering / Backend / Python* or *Campus 2026 / Aptitude*. Each folder shows its question count, and an orange dot when questions are waiting for approval. You can rename, describe, move or delete a folder. Deleting a folder moves its questions up a level; nothing is lost.
- **Versions:**
  - Every content edit (text, options, correct answer, explanation, skill, level, tags) saves a new version, with who made it, when, and a note.
  - The History tab compares any version with the current one and can restore it. A restore is saved as a new version, so history is never rewritten.
  - Status and folder changes don't create versions.
- **Candidates aren't affected by edits:** each MCQ attempt freezes the exact versions it started with. Editing a question mid-round, or later, never changes what a candidate saw or how they were scored.
- **Detail panel:** Preview shows the question as the candidate sees it, with the correct option and explanation. Edit lets you change the question and its options (up to six), tags, folder and suggested time. Performance shows times asked, correct rate, how candidates answered each option, results by version, and which jobs used it.
- **Bulk actions and filters:** move to folder, approve, tag, set level, archive. Smart views for Waiting for approval, Unfiled and Archive. Filters by skill, tag, level, status and source.
- **Hira drafts** straight into a folder, as pending. **CSV import** creates missing folders from a path such as `A / B / C`. **CSV export** works for the whole bank or one folder, and there's a template to download.
- **Code2Hire bank:** companies can browse the global bank read-only and **copy** questions into their own bank to edit.
- **Rounds:** under *Rounds and rules → Configure round → mcq.folder_ids*, pick folders. That round then draws only approved questions from those folders and their sub-folders. With no folders chosen, questions are picked by the job's skills as before.

## 6. Adding candidates and the portal link

Recruiters, interviewers and managers can add candidates. This uses the new **candidates.add** permission, which you can also give to custom roles.

1. Click **+ Add candidate** in the top bar, or use the button on the Talent pool page or a job's Candidates tab.
2. Add one person, or paste a list (name, email, phone, skills). Optionally attach them to a job.
3. Each candidate gets a **personal link**. Copy it, or send it by email or WhatsApp with a ready-written message.
4. The link **opens the candidate's portal straight away**, with no password. They see the job and their next steps. A banner and a welcome pop-up ask them to **set their own password**, with a strength meter.
5. Once they set a password, the link stops working and they sign in normally. Links expire after `invite.link_days` (7 by default). Setting `invite.require_password` makes the password step compulsory before using the portal.

**Tracking and follow-up:**
- **Added candidates** shows each person's state: *Link sent*, *Opened link*, *Active* or *Link expired*.
- **Get link again** issues a new link and kills the old one. It isn't offered once the candidate is active, so staff can never open a portal that belongs to someone with their own password.
- Staff invites from Company admin get the same kind of link.

**Security:** only a hash of each link's token is stored. Opening and setting a password are written to the audit log.

**Not built yet:** Code2Hire doesn't send email or WhatsApp itself. The Email and WhatsApp buttons open your own mail or WhatsApp app with the message filled in.

## 7. Database upgrades

On start-up, Code2Hire adds any missing columns to existing tables (`services/migrate.py`). That means an existing MySQL database picks up new fields, like the ones above, without losing data. Use Alembic for renames or other non-additive changes.

## 8. Project map

```
backend/
  app.py              app factory; serves the built frontend
  config.py           environment settings
  models.py           27 tables (MySQL 8 / SQLite)
  seed.py             demo data
  services/
    ai.py             Anthropic: all AI tasks, each with a fallback
    speech.py         Azure Speech: token, voices, TTS
    settings.py       inheritance resolver: defaults, locks, sources
    perms.py          JWT auth, stacked scoped roles, grants
    policy.py         policy engine
    pipeline.py       rounds, pass rules, matching, credentials, credits
    audit.py          audit log and notifications
  routes/
    auth, platform, company, jobs, rounds, isha, reports,
    candidate, certs, inbox, public, speech, call,
    qbank (question bank), people (added candidates and portal links)
  tests/test_e2e.py
frontend/src/
  components/
    DataTable         table standard: search, sort, filters, pagination, columns, bulk, density
    Settings          inheritance editor and voice picker with preview
    ReportView        one report renderer for every audience
    Mascot            Hira, Isha, Disha
    Shell, ui
  lib/
    speech.js         Azure STT and TTS with browser fallback
    call.js           WebRTC call hook, recorder and upload
    integrity.js      tab, focus, fullscreen, paste, devtools, face events
  pages/
    public/           landing, login, signup, verify, shared report, public jobs
    admin/            Superadmin
    app/              Today, Jobs (5-step Hira wizard), candidate record, reports,
                      Isha live room, interviews, analytics and builder, approvals,
                      talent pool, certifications, question bank, company admin
    me/               candidate home, jobs, applications, practice, skills and badges,
                      learning, certifications, feedback, profile and privacy
    room/             candidate checks and consent, MCQ room, voice interview, paused, done
```

## 9. Known limits

- **Calls are one-to-one:** one interviewer and one candidate. Panels with several interviewers, and silent observers, are not supported yet.
- **Captions need a supported browser:** they come from the candidate's browser, so a browser without speech recognition (and no Azure key) means no captions. The interviewer can switch Isha to "My microphone" or type sentences instead.
- **Face checks:** these use the browser's `FaceDetector` API, which Chrome supports only behind a flag. Where it is missing, the face rule is skipped. Tab, focus, fullscreen, paste and devtools detection work everywhere. For production-grade face detection, add a vision model or a proctoring service.
- **Not built yet:** email and calendar sending, SSO, payments for certification fees, and coding rounds. Notifications are in-app only.
- **Database migrations:** tables are created with `db.create_all()`. Add Alembic before your first schema change in production.

## Updating an existing server
Database changes ship as migration files in `backend/migrations/` (plain SQL and Alembic).
See `backend/migrations/README.md`. Set `C2H_AUTO_MIGRATE=0` in production so only those files change the schema.
