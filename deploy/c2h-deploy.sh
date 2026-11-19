#!/usr/bin/env bash
# Code2Hire V2 deploy: pull the latest code from git, back up the database, migrate (Alembic), deploy, check.
# Run as root on the server.
#
#   bash c2h-deploy.sh discover     find the app for the domain and its git repo; save settings; change nothing
#   bash c2h-deploy.sh deploy       pull -> build frontend -> back up database + code -> copy code -> pip ->
#                                   alembic upgrade head -> restart -> health check   (add --force to redo the same commit)
#   bash c2h-deploy.sh status       running version and commit, service, migration revision, last backups
#   bash c2h-deploy.sh log          follow the last deploy's log (e.g. after your connection dropped)
#   bash c2h-deploy.sh rollback     put the code from the last backup back and restart
#
# Settings: /etc/code2hireV2-deploy.conf (written by discover; edit it if anything is wrong).
# deploy runs in the background and writes /root/c2h-backups/deploy-<time>.log, so a dropped SSH connection
# doesn't stop it halfway. If anything fails after the code was copied, the old code is put back and restarted.
# Uploads (resumes, recordings) are not backed up or touched by this script.
set -Eeuo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

CONF="/etc/code2hireV2-deploy.conf"
BACKUPS="/root/c2h-backups"
SRC_DIR="/root/c2h-src"
KEEP_BACKUPS="${KEEP_BACKUPS:-5}"
TS="$(date +%Y%m%d-%H%M%S)"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
grn() { printf '\033[32m%s\033[0m\n' "$*"; }
ylw() { printf '\033[33m%s\033[0m\n' "$*"; }
hdr() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { red "ERROR: $*"; exit 1; }
git_() { git -c safe.directory='*' "$@"; }

[ "$(id -u)" = 0 ] || die "run as root"

# ------------------------------------------------------------------------------------------------ discovery
pid_on_port() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true; }

master_pid() {  # gunicorn workers -> the master
  local p="$1" pp
  while :; do
    pp="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
    [ -n "$pp" ] && [ "$pp" != 1 ] && ps -o args= -p "$pp" | grep -q -E 'gunicorn|python' || break
    p="$pp"
  done
  echo "$p"
}

env_of_pid() { { tr '\0' '\n' < "/proc/$1/environ"; } 2>/dev/null | sed -n "s/^$2=//p" | head -1 || true; }

discover() {
  local domain="${DOMAIN:-beta.code2hire.ai}"
  hdr "Looking for $domain"
  local vhost port pid mpid cwd="" app_dir="" unit="" venv="" env_file="" owner restart="" cmd
  vhost="$(ls /etc/nginx/sites-enabled/"$domain".conf 2>/dev/null || grep -rlE "server_name[^;]*[[:space:]]$domain([[:space:];]|$)" /etc/nginx/ 2>/dev/null | head -1 || true)"
  [ -n "$vhost" ] || die "no nginx site found for $domain. Run again with DOMAIN=<your domain>"
  echo "nginx site:      $vhost"
  port="$(grep -oE 'proxy_pass\s+https?://(127\.0\.0\.1|localhost|\[::1\]):[0-9]+' "$vhost" | grep -oE '[0-9]+$' | sort | uniq -c | sort -rn | awk 'NR==1{print $2}' || true)"
  [ -n "$port" ] || die "the nginx site has no proxy_pass to a local port"
  echo "app port:        $port"

  pid="$(pid_on_port "$port")"
  if [ -n "$pid" ]; then
    mpid="$(master_pid "$pid")"
    cmd="$(tr '\0' ' ' < /proc/"$mpid"/cmdline || true)"
    cwd="$(readlink -f /proc/"$mpid"/cwd)"
    echo "process:         $mpid  $cmd"
    venv="$(tr '\0' '\n' < /proc/"$mpid"/cmdline | grep -E '/bin/(gunicorn|python[0-9.]*)$' | head -1 | xargs -r dirname | xargs -r dirname || true)"
    unit="$(ps -o unit= -p "$mpid" 2>/dev/null | tr -d ' ' || true)"
    case "$unit" in *.service) : ;; *) unit="" ;; esac
  else
    ylw "Nothing is listening on port $port (the app is down); searching the disk instead."
  fi

  if [ -n "$cwd" ] && [ -f "$cwd/app.py" ] && [ -d "$cwd/../frontend" ]; then app_dir="$(readlink -f "$cwd/..")"
  elif [ -n "$cwd" ] && [ -f "$cwd/backend/app.py" ]; then app_dir="$cwd"
  else
    app_dir="$(find /home /opt /srv /var/www -maxdepth 5 -path '*backend/app.py' 2>/dev/null \
               | while read -r f; do d="$(dirname "$(dirname "$f")")"; [ -d "$d/frontend" ] && echo "$d"; done | head -1 || true)"
  fi
  [ -n "$app_dir" ] && [ -f "$app_dir/backend/app.py" ] || die "could not find the app folder (backend/app.py + frontend/)"
  echo "app folder:      $app_dir  ($(version_of "$app_dir"))"

  if [ -z "$unit" ]; then
    unit="$(grep -lE "WorkingDirectory=.*$app_dir" /etc/systemd/system/*.service 2>/dev/null | head -1 | xargs -r basename || true)"
  fi
  if [ -n "$unit" ]; then
    restart="systemctl restart $unit"
    env_file="$(systemctl show -p EnvironmentFiles --value "$unit" 2>/dev/null | awk '{print $1}' || true)"
    echo "service:         $unit (systemd)"
  else
    ylw "service:         not found. Put the restart command in RESTART_CMD in $CONF."
  fi
  if [ -z "$env_file" ] && [ -f "$app_dir/backend/.env" ]; then env_file="$app_dir/backend/.env"; fi
  for v in "$venv" "$app_dir/backend/venv" "$app_dir/backend/.venv" "$app_dir/venv" "$app_dir/.venv"; do
    if [ -n "$v" ] && [ -x "$v/bin/python" ]; then venv="$v"; break; fi
  done
  [ -x "${venv:-}/bin/python" ] || die "could not find the Python venv"
  echo "python venv:     $venv"
  echo "env file:        ${env_file:-none}"
  owner="$(stat -c %U:%G "$app_dir/backend/app.py")"

  local repo="${REPO_URL:-}" branch="${BRANCH:-}" sub="" top=""
  if command -v git >/dev/null && top="$(git_ -C "$app_dir" rev-parse --show-toplevel 2>/dev/null)"; then
    [ -n "$repo" ] || repo="$(git_ -C "$app_dir" remote get-url origin 2>/dev/null || true)"
    [ -n "$branch" ] || branch="$(git_ -C "$app_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    sub="$(realpath --relative-to="$top" "$app_dir")"; [ "$sub" = . ] && sub=""
    echo "git checkout:    $top (commit $(git_ -C "$top" rev-parse --short HEAD 2>/dev/null))"
  fi
  case "$repo" in git@github.com:*) repo="https://github.com/${repo#git@github.com:}" ;; esac
  if [ -z "$branch" ] || [ "$branch" = HEAD ]; then branch="main"; fi
  echo "git repo:        ${repo:-NOT FOUND}  branch $branch"

  cat > "$CONF" <<EOF
# Code2Hire V2 deploy settings, written by c2h-deploy.sh discover on $(date). Edit if anything is wrong.
DOMAIN="$domain"
APP_DIR="$app_dir"
VENV="$venv"
PORT="$port"
SERVICE="$unit"
RESTART_CMD="$restart"
ENV_FILE="$env_file"
OWNER="$owner"
REPO_URL="$repo"
BRANCH="$branch"
REPO_SUBDIR="$sub"
EOF
  grn "Saved to $CONF."
  if [ -z "$repo" ]; then ylw "Set REPO_URL in $CONF (the public repo, e.g. https://github.com/OWNER/REPO.git)."; fi
}

load_conf() {
  [ -f "$CONF" ] || discover
  # shellcheck disable=SC1090
  . "$CONF"
  [ -f "$APP_DIR/backend/app.py" ] || die "APP_DIR in $CONF is wrong: $APP_DIR"
  [ -n "$RESTART_CMD" ] || die "RESTART_CMD is empty in $CONF"
  [ -n "${REPO_URL:-}" ] || die "REPO_URL is empty in $CONF"
}

app_env() {  # one setting the app runs with: the env file, else the running process
  local val=""
  if [ -n "${ENV_FILE:-}" ] && [ -f "$ENV_FILE" ]; then
    val="$(grep -E "^\s*(export\s+)?$1=" "$ENV_FILE" | tail -1 | sed -E "s/^\s*(export\s+)?$1=//; s/^[\"']//; s/[\"']\s*$//" || true)"
  fi
  if [ -z "$val" ]; then
    local p; p="$(pid_on_port "$PORT")"; if [ -n "$p" ]; then val="$(env_of_pid "$(master_pid "$p")" "$1")"; fi
  fi
  echo "$val"
}

APPENV=()
load_app_env() {  # all the app's settings as KEY=VALUE: the running process, then the env file
  APPENV=()
  local p line; p="$(pid_on_port "$PORT")"
  if [ -n "$p" ]; then
    while IFS= read -r line; do case "$line" in [A-Za-z_]*=*) APPENV+=("$line") ;; esac
    done < <({ tr '\0' '\n' < "/proc/$(master_pid "$p")/environ"; } 2>/dev/null || true)
  fi
  if [ -n "${ENV_FILE:-}" ] && [ -f "$ENV_FILE" ]; then
    while IFS= read -r line; do
      line="$(sed -E "s/^[[:space:]]*export[[:space:]]+//; s/^([A-Za-z_][A-Za-z0-9_]*)=[\"'](.*)[\"'][[:space:]]*$/\1=\2/" <<<"$line")"
      case "$line" in [A-Za-z_]*=*) APPENV+=("$line") ;; esac
    done < "$ENV_FILE"
  fi
}
appy() { env "${APPENV[@]}" DATABASE_URL="$(app_env DATABASE_URL)" "$VENV/bin/python" "$@"; }

running_version() { curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" 2>/dev/null | "$VENV/bin/python" -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true; }
version_of() { grep -oE 'V[0-9]{2}\.[0-9]{2}\.[0-9]{2}' "$1/backend/config.py" | head -1 || true; }

# ------------------------------------------------------------------------------------------------ steps
fetch_source() {  # sets SRC (folder with backend/ and frontend/) and COMMIT
  if [ -d "$SRC_DIR/.git" ] && [ "$(git_ -C "$SRC_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
    git_ -C "$SRC_DIR" fetch -q --depth 1 origin "$BRANCH"
    git_ -C "$SRC_DIR" reset -q --hard FETCH_HEAD
    git_ -C "$SRC_DIR" clean -q -fdx -e node_modules
  else
    rm -rf "$SRC_DIR"
    GIT_TERMINAL_PROMPT=0 git_ clone -q --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR" \
      || die "could not clone $REPO_URL (branch $BRANCH)"
  fi
  COMMIT="$(git_ -C "$SRC_DIR" rev-parse HEAD)"
  SRC="$SRC_DIR${REPO_SUBDIR:+/$REPO_SUBDIR}"
  [ -f "$SRC/backend/app.py" ] && [ -d "$SRC/frontend" ] || die "the repo has no backend/ and frontend/ folders"
}

build_frontend() {  # in the clean copy, before anything live changes
  local f="$SRC/frontend"
  command -v npm >/dev/null || die "npm is not installed; install Node.js 18+ and run again"
  cp -a "$APP_DIR"/frontend/.env* "$f"/ 2>/dev/null || true   # this server's VITE_ settings, if any
  echo "building the frontend ($(node -v)) ..."
  if [ -f "$f/package-lock.json" ]; then (cd "$f" && npm ci --no-audit --no-fund --loglevel=error)
  else (cd "$f" && npm install --no-audit --no-fund --loglevel=error); fi
  (cd "$f" && npm run build --silent)
  [ -f "$f/dist/index.html" ] || die "the frontend build made no dist/index.html"
}

backup() {  # database and code only
  local dir="$1" url
  mkdir -p "$dir"
  url="$(app_env DATABASE_URL)"; [ -n "$url" ] || die "DATABASE_URL not found in $ENV_FILE or the running app"
  echo "database ..."
  eval "$("$VENV/bin/python" - "$url" <<'PY'
import sys, shlex
from urllib.parse import urlsplit, unquote
u = urlsplit(sys.argv[1].replace("mysql+pymysql://", "mysql://", 1))
print(f"DBH={shlex.quote(u.hostname or 'localhost')} DBP={u.port or 3306} DBU={shlex.quote(unquote(u.username or ''))} "
      f"DBPW={shlex.quote(unquote(u.password or ''))} DBN={shlex.quote(u.path.lstrip('/'))}")
PY
)"
  MYSQL_PWD="$DBPW" mysqldump --single-transaction --quick --routines --triggers --no-tablespaces \
    -h "$DBH" -P "$DBP" -u "$DBU" "$DBN" | gzip > "$dir/db-$DBN.sql.gz" || die "database backup failed"
  [ "$(zcat "$dir/db-$DBN.sql.gz" | tail -1 | grep -c 'Dump completed')" = 1 ] || die "database backup looks incomplete"
  echo "  $dir/db-$DBN.sql.gz ($(du -h "$dir/db-$DBN.sql.gz" | cut -f1))"
  echo "code ..."
  tar czf "$dir/code.tgz" -C "$APP_DIR" --exclude=node_modules --exclude=venv --exclude=.venv \
      --exclude=__pycache__ --exclude=backend/uploads --exclude=uploads --exclude=.git .
  echo "  $dir/code.tgz ($(du -h "$dir/code.tgz" | cut -f1))"
  "$VENV/bin/pip" freeze > "$dir/pip-freeze.txt" 2>/dev/null || true
  echo "$DBN" > "$dir/db_name.txt"
  git_ -C "$APP_DIR" rev-parse HEAD > "$dir/commit.txt" 2>/dev/null || true
}

copy_code() {  # $1 = folder holding backend/ and frontend/
  local keep=(--exclude='.git/' --exclude='.env' --exclude='.env.*' --exclude='venv/' --exclude='.venv/'
              --exclude='node_modules/' --exclude='__pycache__/' --exclude='/backend/uploads/' --exclude='/uploads/'
              --exclude='*.db' --exclude='/backend/instance/')
  rsync -a "${keep[@]}" "$1"/ "$APP_DIR"/
  for d in backend/routes backend/services backend/migrations backend/tests frontend/src frontend/dist frontend/public; do
    if [ -d "$1/$d" ]; then rsync -a --delete "${keep[@]}" "$1/$d"/ "$APP_DIR/$d"/; fi
  done
  chown -R "$OWNER" "$APP_DIR" --from=root:root 2>/dev/null || true
}

sync_git_head() {  # the app folder is a git checkout: point it at the deployed commit (files already match)
  local c="$1"
  git_ -C "$APP_DIR" rev-parse --git-dir >/dev/null 2>&1 || return 0
  git_ -C "$APP_DIR" fetch -q origin "$BRANCH" 2>/dev/null || true
  if git_ -C "$APP_DIR" cat-file -e "$c" 2>/dev/null; then git_ -C "$APP_DIR" reset -q --mixed "$c"; fi
}

migrate() {
  cd "$APP_DIR/backend"
  load_app_env
  local state
  state="$(appy - <<'PY'
import os
from sqlalchemy import create_engine, inspect, text
e = create_engine(os.environ["DATABASE_URL"])
i = inspect(e)
t = set(i.get_table_names())
if "alembic_version" in t:
    with e.connect() as c:
        r = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    print("alembic", r or "")
elif "resume_files" in t and "history" in {c["name"] for c in i.get_columns("jobs")}:
    print("sql-v11")
elif "users" in t:
    print("sql-old")
else:
    print("empty")
PY
)"
  echo "database state: $state"
  case "$state" in
    alembic*) : ;;
    sql-v11) echo "first Alembic run: marking the database as V02.00.11"; appy -m alembic stamp 0010_v11_resume_files ;;
    sql-old) echo "first Alembic run: marking the baseline";            appy -m alembic stamp 0001_baseline ;;
    empty)   die "the database has no tables" ;;
  esac
  appy -m alembic upgrade head
  echo "migration revision now: $(appy -m alembic current 2>/dev/null | tail -1)"
  cd - >/dev/null
}

restart_and_check() {  # $1 = expected version
  echo "restarting: $RESTART_CMD"
  bash -c "$RESTART_CMD" 9>&-
  local v=""
  for _ in $(seq 1 45); do
    sleep 2; v="$(running_version)"
    [ "$v" = "$1" ] && break
  done
  [ "$v" = "$1" ] || { red "health check: running '${v:-nothing}', expected '$1'"; [ -n "$SERVICE" ] && journalctl -u "$SERVICE" -n 40 --no-pager; return 1; }
  grn "local health check: $v"
  local pub; pub="$(curl -fsS --max-time 10 "https://$DOMAIN/api/health" 2>/dev/null | "$VENV/bin/python" -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  if [ "$pub" = "$1" ]; then grn "public check https://$DOMAIN: $pub"; else ylw "public check https://$DOMAIN returned '${pub:-nothing}'"; fi
}

rollback_code() {  # $1 = backup folder
  local dir="$1" tmp
  ylw "Putting back the code from $dir ..."
  tmp="$(mktemp -d)"; tar xzf "$dir/code.tgz" -C "$tmp"
  copy_code "$tmp"; rm -rf "$tmp"
  if [ -f "$dir/pip-freeze.txt" ]; then "$VENV/bin/pip" install -q --disable-pip-version-check -r "$dir/pip-freeze.txt" || true; fi
  if [ -s "$dir/commit.txt" ]; then sync_git_head "$(cat "$dir/commit.txt")"; cp "$dir/commit.txt" "$BACKUPS/deployed_commit"; fi
  bash -c "$RESTART_CMD" 9>&-; sleep 5
  ylw "Running now: $(running_version). The database was not restored (migrations are additive)."
  ylw "To restore it as well:  zcat $dir/db-*.sql.gz | mysql -u USER -p $(cat "$dir/db_name.txt" 2>/dev/null)"
}

# ------------------------------------------------------------------------------------------------ commands
SWAPPED=0; BDIR=""
on_exit() {
  local rc=$?
  set +e
  if [ "$SWAPPED" = 1 ] && [ -n "$BDIR" ]; then red "Deploy failed (exit $rc); rolling back the code"; rollback_code "$BDIR"; fi
}

deploy_run() {  # the real work; runs detached from the terminal
  local force="${1:-}"
  load_conf
  exec 9>/var/lock/code2hireV2-deploy.lock; flock -n 9 || die "another deploy is running"
  local cur new bdir
  cur="$(version_of "$APP_DIR")"

  hdr "1/6 Latest code from git"
  fetch_source
  new="$(version_of "$SRC")"
  echo "repo $REPO_URL  branch $BRANCH  commit ${COMMIT:0:7}: $(git_ -C "$SRC_DIR" log -1 --format='%s (%an, %cr)')"
  echo "installed: $cur   new: $new   app: $APP_DIR"
  if [ "$force" != --force ] && [ "$COMMIT" = "$(cat "$BACKUPS/deployed_commit" 2>/dev/null)" ] && [ "$(running_version)" = "$new" ]; then
    grn "Already up to date: commit ${COMMIT:0:7} ($new) is live. Use 'deploy --force' to deploy it again."; return 0
  fi

  hdr "2/6 Frontend build"
  build_frontend

  hdr "3/6 Backup (database and code)"
  bdir="$BACKUPS/$TS-$cur"; backup "$bdir"

  hdr "4/6 Code and Python packages"
  trap on_exit EXIT
  SWAPPED=1; BDIR="$bdir"
  copy_code "$SRC"
  sync_git_head "$COMMIT"
  "$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/backend/requirements.txt"
  echo "copied commit ${COMMIT:0:7} into $APP_DIR (kept .env, venv, uploads)"

  hdr "5/6 Database migrations (alembic upgrade head)"
  migrate

  hdr "6/6 Restart and check"
  restart_and_check "$new"
  SWAPPED=0
  echo "$COMMIT" > "$BACKUPS/deployed_commit"
  ls -1dt "$BACKUPS"/*-V* 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -rf
  grn "Done: $cur -> $new (commit ${COMMIT:0:7}). Backup: $bdir"
}

deploy() {  # start deploy_run in the background (survives a dropped connection) and follow its log
  load_conf
  mkdir -p "$BACKUPS"
  local log="$BACKUPS/deploy-$TS.log" run="/root/.c2h-deploy-run.sh"
  cp "$0" "$run"   # run a copy: the deploy may replace this file inside the app folder
  setsid nohup bash "$run" __run "${1:-}" > "$log" 2>&1 < /dev/null &
  local pid=$!
  ln -sf "$log" "$BACKUPS/last-deploy.log"
  echo "Deploy started (pid $pid). Log: $log"
  echo "If your connection drops, it keeps going; reconnect and run:  bash $0 log"
  tail -n +1 -f --pid="$pid" "$log" || true
  wait "$pid" 2>/dev/null || true
}

status() {
  load_conf
  echo "domain:    $DOMAIN"
  echo "app:       $APP_DIR ($(version_of "$APP_DIR") on disk)"
  echo "running:   $(running_version)"
  echo "repo:      $REPO_URL ($BRANCH), deployed commit $(cut -c1-7 "$BACKUPS/deployed_commit" 2>/dev/null || echo none)"
  if [ -n "$SERVICE" ]; then echo "service:   $SERVICE $(systemctl is-active "$SERVICE" || true)"; fi
  (cd "$APP_DIR/backend" && load_app_env && appy -m alembic current 2>/dev/null | tail -1 | sed 's/^/alembic:   /') || true
  if pgrep -f "c2h-deploy-run.sh __run" >/dev/null; then ylw "a deploy is running now: bash $0 log"; fi
  echo "backups:"; ls -1dt "$BACKUPS"/*-V* 2>/dev/null | head -5 | sed 's/^/  /' || true
}

case "${1:-}" in
  discover) discover ;;
  deploy)   deploy "${2:-}" ;;
  __run)    deploy_run "${2:-}" ;;
  status)   status ;;
  log)      [ -e "$BACKUPS/last-deploy.log" ] || die "no deploy log yet"
            p="$(pgrep -f 'c2h-deploy-run.sh __run' | head -1 || true)"
            if [ -n "$p" ]; then tail -n +1 -f --pid="$p" "$BACKUPS/last-deploy.log"; else cat "$BACKUPS/last-deploy.log"; fi ;;
  rollback) load_conf; b="$(ls -1dt "$BACKUPS"/*-V* 2>/dev/null | head -1 || true)"; [ -n "$b" ] || die "no backup found"; rollback_code "$b" ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac