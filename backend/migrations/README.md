# Database migrations

Two equivalent ways to update a server. Pick one.

| SQL file / Alembic revision | Release | What it adds | Needed if your server... |
|---|---|---|---|
| 001 / 0002_video_call | V02.00.02 | `call_signals` table | was deployed before the built-in video call (Oct 24) |
| 002 / 0003_qbank_links | V02.00.02 | `question_folders`, `question_versions`, `invite_links` tables; 6 columns on `questions`; 2 columns on `candidate_profiles`; backfills version 1 for every existing question | is older than V02.00.02 |
| 003 / 0004_beta_fixes | V02.00.03 | `login_throttles` table; `invite_links.shared_at`, `shared_via`; 5 dispute columns on `reports`; `hiring_templates.updated_by`, `updated_at`, `archived`; data fixes (below) | is older than V02.00.03 |

No permission or settings rows are needed: permissions and settings live in code and use their defaults.

### Data fixes in 003 / 0004
- Jobs with hires needed below 1 become 1 (fixes "0 / -5" in the jobs list). Negative salaries are cleared; salary bands saved upside down (minimum above maximum) are swapped.
- Duplicate open invites for the same candidate and round are set to `cancelled`; the running one, else the newest invite, is kept. Credits already used for duplicates are not refunded automatically.
- Disputes raised before this release become `open` with their raise date.
- Personal links created before this release count as sent (they were shown as "Link sent").
- Accounts with emails that can't receive mail are **not** changed. List them with the query at the end of `003_beta_fixes.up.sql` and decide case by case.

### Optional: old interview times (BETACODE2-6)
Before V02.00.03, interview times were saved as the interviewer's local clock time. If all your interviewers schedule in
India (IST), run `003_optional_fix_old_interview_times.sql` **once**, right after 003, to convert upcoming interviews to UTC.
Change `330` in the file for another timezone. Skip it if you're not sure, and reschedule upcoming interviews by hand instead.

## Before you start
1. Back up: `mysqldump --single-transaction -u USER -p DBNAME > backup_$(date +%F).sql`
2. Set `C2H_AUTO_MIGRATE=0` in the backend environment so the app does not change the schema by itself.
3. Behind nginx, keep `C2H_TRUST_PROXY=1` (the default) and make sure nginx sends the client address:
   `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`. Sign-in limits are per address. Without a proxy, set `C2H_TRUST_PROXY=0`.

## Option A: plain SQL (mysql client)
```bash
# only if the table is missing:  SHOW TABLES LIKE 'call_signals';
mysql -u USER -p DBNAME < migrations/sql/001_video_call.up.sql
# only if the server is older than V02.00.02:  SHOW TABLES LIKE 'invite_links';
mysql -u USER -p DBNAME < migrations/sql/002_question_bank_and_candidate_links.up.sql
mysql -u USER -p DBNAME < migrations/sql/003_beta_fixes.up.sql
# optional, once, see above:
# mysql -u USER -p DBNAME < migrations/sql/003_optional_fix_old_interview_times.sql
```
Run each file once. MySQL 8 has no `ADD COLUMN IF NOT EXISTS`, so a file stops with "Duplicate column" if it has already
been applied. That error is harmless and means the update is already in place.
Rollback: the `.down.sql` files in reverse order (003, then 002, then 001). Data fixes are not undone.

## Option B: Alembic (safe to re-run)
```bash
cd backend && pip install -r requirements.txt
export DATABASE_URL="mysql+pymysql://USER:PASS@HOST:3306/DBNAME?charset=utf8mb4"
alembic current                 # empty on a server that never used Alembic
alembic stamp 0001_baseline     # only then, once: marks the existing database as the first release
alembic upgrade head            # applies what's missing, skipping anything already present
alembic current                 # -> 0004_beta_fixes (head)
```
A server already updated to V02.00.02 with Alembic shows `0003_qbank_links`; `alembic upgrade head` applies only 0004.
Rollback one step: `alembic downgrade -1`.

## Then deploy the code
1. Copy the new `backend/` and `frontend/` code to the server.
2. `pip install -r backend/requirements.txt` (adds `openpyxl` for Excel uploads)
3. `cd frontend && npm ci && npm run build` (adds the on-device face check; its 190 KB model ships in `frontend/public/models`)
4. Restart the backend (gunicorn) and reload nginx.

## Tested
On MariaDB 10.11 (MySQL compatible), starting from a copy of a V02.00.02 database with bad data planted in it:
- 003 up gives exactly the same columns and indexes as a fresh install, and fixes the planted data (negative hires,
  upside-down salary band, duplicate invites);
- 003 down returns exactly to the V02.00.02 schema;
- Alembic 0004 matches the SQL, downgrades and re-upgrades cleanly, and skips work already done by the app's automatic upgrade;
- the full regression suite (36 tests) passes against MariaDB itself.
