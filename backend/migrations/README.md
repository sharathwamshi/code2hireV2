# Database migrations

Two equivalent ways to update a server. Pick one.

| Migration | What it adds | Needed if your server... |
|---|---|---|
| 001 / 0002_video_call | `call_signals` table | was deployed before the built-in video call (Oct 24) |
| 002 / 0003_qbank_links | `question_folders`, `question_versions`, `invite_links` tables; 6 columns on `questions`; 2 columns on `candidate_profiles`; backfills version 1 for every existing question | any server before Oct 29 |

No permission or settings rows are needed: the new `candidates.add` permission and the
`qbank.*` / `invite.*` settings live in code and use their defaults until changed in the UI.

## Before you start
1. Back up: `mysqldump --single-transaction -u USER -p DBNAME > backup_$(date +%F).sql`
2. Set `C2H_AUTO_MIGRATE=0` in the backend environment so the app does not change the schema by itself.
   (With it left at the default `1`, the app adds missing tables, columns and indexes on start-up;
   that is fine for small installs, but production should use the files below.)

## Option A: plain SQL (mysql client)
```bash
# only if the table is missing:  SHOW TABLES LIKE 'call_signals';
mysql -u USER -p DBNAME < migrations/sql/001_video_call.up.sql
mysql -u USER -p DBNAME < migrations/sql/002_question_bank_and_candidate_links.up.sql
```
Run each file once. MySQL 8 has no `ADD COLUMN IF NOT EXISTS`, so 002 stops with
"Duplicate column" if it has already been applied. That error is harmless and means
the update is already in place. Rollback: the `.down.sql` files, in reverse order (002 then 001).

## Option B: Alembic (safe to re-run)
```bash
cd backend && pip install -r requirements.txt
export DATABASE_URL="mysql+pymysql://USER:PASS@HOST:3306/DBNAME?charset=utf8mb4"
alembic stamp 0001_baseline     # once: marks the existing database as the first release
alembic upgrade head            # applies 0002 and 0003, skipping anything already present
alembic current                 # -> 0003_qbank_links (head)
```
Rollback one step: `alembic downgrade -1`. Use Alembic for all future changes once you start with it.

## Then deploy the code
1. Copy the new `backend/` and `frontend/` code to the server.
2. `pip install -r backend/requirements.txt`
3. `cd frontend && npm ci && npm run build`
4. Restart the backend (gunicorn) and reload nginx.

## Tested
On MariaDB 10.11 (MySQL compatible) against a copy of the old schema with seeded data:
up migrations give exactly the same columns and indexes as a fresh install, down migrations
return exactly to the old schema, Alembic skips work already done by the app's automatic upgrade,
and the app ran with `C2H_AUTO_MIGRATE=0` (question edit to version 2, add candidate, portal link, set password).
