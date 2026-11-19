#!/usr/bin/env bash
# Code2Hire deploy script for a CloudPanel (or any systemd) server. Use it for every release.
#
#   bash c2h-deploy.sh discover                       find where Code2Hire runs for the domain, save it, change nothing
#   bash c2h-deploy.sh deploy /root/Code2Hire-V02.00.12.zip
#                                                     backup -> code -> packages -> migrate -> restart -> health check
#   bash c2h-deploy.sh status                         version running, service, migration revision
#   bash c2h-deploy.sh rollback                       put the code from the last backup back and restart
#
# Settings are saved in /etc/code2hire-deploy.conf after "discover". Check them once; edit if anything is wrong.
# Override the domain with:  DOMAIN=other.example.com bash c2h-deploy.sh discover
#
# What deploy does, in order (it stops at the first problem):
#   1. checks the zip and reads the new version
#   2. backs up the database (mysqldump), the code, and UPLOAD_DIR (resumes, recordings) to /root/c2h-backups/<time>/
#   3. copies the new code over the old, keeping .env files, the Python venv, node_modules and uploads
#   4. installs Python packages; uses the frontend build shipped in the zip (or rebuilds when the server has VITE_ settings)
#   5. runs the database migrations with Alembic (first time: marks the existing database, then applies what's missing)
#   6. restarts the service and waits for /api/health to report the new version
#   If 3-6 fail, the old code is put back and restarted automatically. Migrations so far are additive / data only,
#   so the old code runs on the migrated database; the database backup is there if you ever need it.
set -Eeuo pipefail

DOMAIN="${DOMAIN:-beta.code2hire.com}"
CONF="/etc/code2hire-deploy.conf"
BACKUPS="/root/c2h-backups"
KEEP_BACKUPS="${KEEP_BACKUPS:-5}"
TS="$(date +%Y%m%d-%H%M%S)"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
grn() { printf '\033[32m%s\033[0m\n' "$*"; }
ylw() { printf '\033[33m%s\033[0m\n' "$*"; }
hdr() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { red "ERROR: $*"; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root"

# ------------------------------------------------------------------------------------------------ discovery
pid_on_port() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true; }

master_pid() {  # gunicorn workers -> the master (its parent is systemd/supervisord)
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
  hdr "Looking for $DOMAIN"
  local vhost port pid mpid cwd="" app_dir unit="" venv="" env_file="" owner restart="" mode="systemd" cmd
  vhost="$(ls /etc/nginx/sites-enabled/"$DOMAIN".conf 2>/dev/null || grep -rlE "server_name[^;]*\b$DOMAIN\b" /etc/nginx/ 2>/dev/null | head -1 || true)"
  [ -n "$vhost" ] || die "no nginx site found for $DOMAIN (looked in /etc/nginx)"
  echo "nginx site:      $vhost"
  port="$(grep -oE 'proxy_pass\s+https?://(127\.0\.0\.1|localhost|\[::1\]):[0-9]+' "$vhost" | grep -oE '[0-9]+$' | sort | uniq -c | sort -rn | awk 'NR==1{print $2}' || true)"
  [ -n "$port" ] || die "the nginx site has no proxy_pass to a local port; is $DOMAIN a Python site in CloudPanel?"
  echo "app port:        $port"

  pid="$(pid_on_port "$port")"
  if [ -n "$pid" ]; then
    if ps -o comm= -p "$pid" | grep -q docker-proxy; then
      die "port $port belongs to Docker. This script deploys a systemd/gunicorn install; for Docker run 'docker compose up -d --build' in the app folder"
    fi
    mpid="$(master_pid "$pid")"
    cmd="$(tr '\0' ' ' < /proc/"$mpid"/cmdline || true)"
    cwd="$(readlink -f /proc/"$mpid"/cwd)"
    echo "process:         $mpid  $cmd"
    echo "working dir:     $cwd"
    # the venv is where the gunicorn/python in the command line lives
    venv="$(tr '\0' '\n' < /proc/"$mpid"/cmdline | grep -E '/bin/(gunicorn|python[0-9.]*)$' | head -1 | xargs -r dirname | xargs -r dirname || true)"
    unit="$(ps -o unit= -p "$mpid" 2>/dev/null | tr -d ' ' || true)"
    case "$unit" in
      *.service) : ;;
      *) unit=""
         if ps -o args= -p "$(ps -o ppid= -p "$mpid" | tr -d ' ')" | grep -q supervisord; then
           mode="supervisor"
           restart="supervisorctl restart $(supervisorctl status 2>/dev/null | awk -v p="$mpid" '$0 ~ "pid "p"," {print $1}' || true)"
         else
           mode="manual"
         fi ;;
    esac
    if [ -n "$(env_of_pid "$mpid" DATABASE_URL)" ]; then echo "DATABASE_URL:    set in the running process"; fi
  else
    ylw "Nothing is listening on port $port right now (the app is down). Searching the disk instead."
  fi

  # the app folder: the one holding backend/app.py and frontend/
  if [ -n "${cwd:-}" ] && [ -f "$cwd/app.py" ] && [ -d "$cwd/../frontend" ]; then app_dir="$(readlink -f "$cwd/..")"
  elif [ -n "${cwd:-}" ] && [ -f "$cwd/backend/app.py" ]; then app_dir="$cwd"
  else
    app_dir="$(find /home/*/htdocs/"$DOMAIN" /home /opt /srv /var/www /root -maxdepth 6 -path '*backend/app.py' 2>/dev/null \
               | while read -r f; do d="$(dirname "$(dirname "$f")")"; [ -d "$d/frontend" ] && grep -q APP_VERSION "$d/backend/config.py" 2>/dev/null && echo "$d"; done \
               | awk '!s[$0]++' | head -1 || true)"
  fi
  [ -n "$app_dir" ] && [ -f "$app_dir/backend/app.py" ] || die "could not find the Code2Hire folder (backend/app.py + frontend/)"
  echo "app folder:      $app_dir  ($(grep -oE 'V[0-9]{2}\.[0-9]{2}\.[0-9]{2}' "$app_dir/backend/config.py" | head -1))"

  if [ -z "$unit" ] && [ "$mode" = systemd ]; then  # app down: find the unit by its working directory
    unit="$(grep -lE "WorkingDirectory=.*$app_dir|$app_dir/backend" /etc/systemd/system/*.service 2>/dev/null | head -1 | xargs -r basename || true)"
    [ -n "$unit" ] || mode="manual"
  fi
  if [ "$mode" = systemd ]; then
    restart="systemctl restart $unit"
    env_file="$(systemctl show -p EnvironmentFiles --value "$unit" 2>/dev/null | awk '{print $1}' || true)"
    if [ -z "${venv:-}" ]; then venv="$(systemctl show -p ExecStart --value "$unit" | grep -oE 'path=[^ ;]+' | cut -d= -f2 | xargs -r dirname | xargs -r dirname || true)"; fi
    echo "service:         $unit (systemd)"
  elif [ "$mode" = supervisor ]; then echo "service:         supervisor ($restart)"
  else ylw "service:         not found. Put the restart command in RESTART_CMD in $CONF."
  fi
  if [ -z "${env_file:-}" ] && [ -f "$app_dir/backend/.env" ]; then env_file="$app_dir/backend/.env"; fi
  for v in "$venv" "$app_dir/backend/venv" "$app_dir/backend/.venv" "$app_dir/venv" "$app_dir/.venv"; do
    [ -n "$v" ] && [ -x "$v/bin/python" ] && { venv="$v"; break; }
  done
  [ -x "${venv:-}/bin/python" ] || die "could not find the Python venv (looked for venv/.venv next to the app)"
  echo "python venv:     $venv"
  echo "env file:        ${env_file:-none (settings come from the service)}"
  owner="$(stat -c %U:%G "$app_dir/backend/app.py")"
  echo "file owner:      $owner"

  cat > "$CONF" <<EOF
# Code2Hire deploy settings, written by c2h-deploy.sh discover on $(date). Edit if anything is wrong.
DOMAIN="$DOMAIN"
APP_DIR="$app_dir"
VENV="$venv"
PORT="$port"
SERVICE="${unit:-}"
RESTART_CMD="${restart:-}"
ENV_FILE="${env_file:-}"
OWNER="$owner"
# auto = rebuild the frontend only when the server has frontend/.env* (VITE_ settings) and npm; yes / no to force
BUILD_FRONTEND="auto"
# 1 = skip the UPLOAD_DIR backup (resumes, recordings) if it is very large and backed up some other way
SKIP_UPLOADS_BACKUP="0"
EOF
  grn "Saved to $CONF. Check it, then run:  bash $0 deploy /path/to/Code2Hire-Vxx.xx.xx.zip"
}

load_conf() {
  [ -f "$CONF" ] || discover
  # shellcheck disable=SC1090
  . "$CONF"
  [ -f "$APP_DIR/backend/app.py" ] || die "APP_DIR in $CONF is wrong: $APP_DIR"
  [ -n "$RESTART_CMD" ] || die "RESTART_CMD is empty in $CONF"
}

# The app's own settings (DATABASE_URL, UPLOAD_DIR ...): the env file, else the running process
app_env() {
  local val=""
  if [ -n "${ENV_FILE:-}" ] && [ -f "$ENV_FILE" ]; then
    val="$(grep -E "^\s*(export\s+)?$1=" "$ENV_FILE" | tail -1 | sed -E "s/^\s*(export\s+)?$1=//; s/^[\"']//; s/[\"']\s*$//")"
  fi
  if [ -z "$val" ]; then
    local p; p="$(pid_on_port "$PORT")"; [ -n "$p" ] && val="$(env_of_pid "$(master_pid "$p")" "$1")"
  fi
  echo "$val"
}

# Every setting the app runs with, as KEY=VALUE: the running process first, then the env file
APPENV=()
load_app_env() {
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

# ------------------------------------------------------------------------------------------------ steps
backup() {
  local dir="$1" url upload
  mkdir -p "$dir"
  url="$(app_env DATABASE_URL)"; [ -n "$url" ] || die "DATABASE_URL not found in $ENV_FILE or the running app"
  echo "database ..."
  # parse the SQLAlchemy URL in Python (handles %-encoded passwords)
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
      --exclude=__pycache__ --exclude=backend/uploads .
  echo "  $dir/code.tgz ($(du -h "$dir/code.tgz" | cut -f1))"
  upload="$(app_env UPLOAD_DIR)"; upload="${upload:-$APP_DIR/backend/uploads}"
  echo "$upload" > "$dir/upload_dir.txt"
  if [ "$SKIP_UPLOADS_BACKUP" != 1 ] && [ -d "$upload" ]; then
    echo "uploads ($upload) ..."
    tar czf "$dir/uploads.tgz" -C "$(dirname "$upload")" "$(basename "$upload")" || [ $? -eq 1 ]  # 1 = a file changed while reading
    echo "  $dir/uploads.tgz ($(du -h "$dir/uploads.tgz" | cut -f1))"
  fi
  "$VENV/bin/pip" freeze > "$dir/pip-freeze.txt" 2>/dev/null || true
  echo "$DBN" > "$dir/db_name.txt"
}

copy_code() {  # $1 = folder holding backend/ and frontend/
  command -v rsync >/dev/null || apt-get install -y -qq rsync >/dev/null
  local keep=(--exclude='.env' --exclude='.env.*' --exclude='venv/' --exclude='.venv/' --exclude='node_modules/'
              --exclude='__pycache__/' --exclude='/backend/uploads/' --exclude='/uploads/' --exclude='*.db'
              --exclude='/backend/instance/')
  # Everything is copied over; files only this server has (gunicorn.conf.py, start scripts, logs) are left alone.
  rsync -a "${keep[@]}" "$1"/ "$APP_DIR"/
  # The code folders are mirrored exactly, so files removed in a release don't linger.
  for d in backend/routes backend/services backend/migrations backend/tests frontend/src frontend/dist frontend/public; do
    if [ -d "$1/$d" ]; then rsync -a --delete "${keep[@]}" "$1/$d"/ "$APP_DIR/$d"/; fi
  done
  chown -R "$OWNER" "$APP_DIR" --from=root:root 2>/dev/null || true
}

packages() {
  "$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/backend/requirements.txt"
}

frontend() {
  local build="$BUILD_FRONTEND"
  if [ "$build" = auto ]; then
    build=no; ls "$APP_DIR"/frontend/.env* >/dev/null 2>&1 && command -v npm >/dev/null && build=yes
  fi
  if [ "$build" = yes ]; then
    echo "rebuilding the frontend with this server's frontend/.env ..."
    (cd "$APP_DIR/frontend" && runuser -u "${OWNER%%:*}" -- npm ci --no-audit --no-fund --loglevel=error && runuser -u "${OWNER%%:*}" -- npm run build --silent)
  else
    [ -f "$APP_DIR/frontend/dist/index.html" ] || die "the zip has no frontend/dist and BUILD_FRONTEND is no"
    echo "using the frontend build from the zip"
  fi
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
    sql-v11) echo "first Alembic run: marking the database as V02.00.11 (0010_v11_resume_files)"
             appy -m alembic stamp 0010_v11_resume_files ;;
    sql-old) echo "first Alembic run: marking the baseline; upgrade then adds only what's missing"
             appy -m alembic stamp 0001_baseline ;;
    empty)   die "the database has no tables; this script updates an existing install" ;;
  esac
  appy -m alembic upgrade head
  echo "migration revision now: $(appy -m alembic current 2>/dev/null | tail -1)"
  cd - >/dev/null
}

restart_and_check() {  # $1 = expected version
  echo "restarting: $RESTART_CMD"
  bash -c "$RESTART_CMD" 9>&-  # the lock must not pass to the app
  local v=""
  for _ in $(seq 1 45); do
    sleep 2; v="$(running_version)"
    [ "$v" = "$1" ] && break
  done
  [ "$v" = "$1" ] || { red "health check: running '${v:-nothing}', expected '$1'"; [ -n "$SERVICE" ] && journalctl -u "$SERVICE" -n 40 --no-pager; return 1; }
  grn "local health check: $v"
  local pub; pub="$(curl -fsS --max-time 10 "https://$DOMAIN/api/health" 2>/dev/null | "$VENV/bin/python" -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  if [ "$pub" = "$1" ]; then grn "public check https://$DOMAIN: $pub"; else ylw "public check https://$DOMAIN returned '${pub:-nothing}' (check nginx / DNS / CDN cache)"; fi
}

rollback_code() {  # $1 = backup folder
  local dir="$1" tmp
  ylw "Putting back the code from $dir ..."
  tmp="$(mktemp -d)"; tar xzf "$dir/code.tgz" -C "$tmp"
  copy_code "$tmp"; rm -rf "$tmp"
  [ -f "$dir/pip-freeze.txt" ] && "$VENV/bin/pip" install -q --disable-pip-version-check -r "$dir/pip-freeze.txt" || true
  bash -c "$RESTART_CMD" 9>&-; sleep 5
  ylw "Running now: $(running_version). The database was not restored (migrations are additive)."
  ylw "To restore it as well:  zcat $dir/db-*.sql.gz | mysql -u USER -p $(cat "$dir/db_name.txt" 2>/dev/null)"
}

# ------------------------------------------------------------------------------------------------ commands
SWAPPED=0; BDIR=""; STAGE=""
on_exit() {  # any failure after the code was replaced puts the old code back
  local rc=$?
  set +e
  if [ "$SWAPPED" = 1 ] && [ -n "$BDIR" ]; then red "Deploy failed (exit $rc); rolling back the code"; rollback_code "$BDIR"; fi
  if [ -n "$STAGE" ]; then rm -rf "$STAGE"; fi
}
deploy() {
  local zip="${1:-}"; [ -f "$zip" ] || die "usage: $0 deploy /path/to/Code2Hire-Vxx.xx.xx.zip"
  load_conf
  exec 9>/var/lock/code2hire-deploy.lock; flock -n 9 || die "another deploy is running"
  mkdir -p "$BACKUPS"
  local log="$BACKUPS/deploy-$TS.log"; exec > >(tee -a "$log") 2>&1
  local cur new stage bdir
  cur="$(grep -oE 'V[0-9]{2}\.[0-9]{2}\.[0-9]{2}' "$APP_DIR/backend/config.py" | head -1)"

  hdr "1/6 Checking the package"
  command -v unzip >/dev/null || apt-get install -y -qq unzip >/dev/null
  stage="$(mktemp -d /root/c2h-stage-XXXX)"; STAGE="$stage"; trap on_exit EXIT
  unzip -q "$zip" -d "$stage"
  local src; src="$(dirname "$(dirname "$(find "$stage" -maxdepth 3 -path '*backend/app.py' | head -1)")")"
  [ -f "$src/backend/app.py" ] && [ -d "$src/frontend" ] || die "the zip doesn't contain backend/ and frontend/"
  new="$(grep -oE 'V[0-9]{2}\.[0-9]{2}\.[0-9]{2}' "$src/backend/config.py" | head -1)"
  echo "installed: $cur   new: $new   app: $APP_DIR"
  local free; free="$(df -Pm /root | awk 'NR==2{print $4}')"; [ "$free" -gt 1024 ] || die "less than 1 GB free on /root"

  hdr "2/6 Backup"
  bdir="$BACKUPS/$TS-$cur"; backup "$bdir"

  hdr "3/6 Code"
  SWAPPED=1; BDIR="$bdir"
  copy_code "$src"
  echo "copied $new into $APP_DIR (kept .env, venv, uploads)"

  hdr "4/6 Packages and frontend"
  packages; frontend

  hdr "5/6 Database migrations"
  migrate

  hdr "6/6 Restart and check"
  restart_and_check "$new"
  SWAPPED=0

  ls -1dt "$BACKUPS"/*-V* 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -rf
  grn "Done: $cur -> $new. Backup: $bdir   Log: $log"
}

status() {
  load_conf
  echo "domain:    $DOMAIN"
  echo "app:       $APP_DIR ($(grep -oE 'V[0-9]{2}\.[0-9]{2}\.[0-9]{2}' "$APP_DIR/backend/config.py" | head -1) on disk)"
  echo "running:   $(running_version || true)"
  [ -n "$SERVICE" ] && echo "service:   $SERVICE $(systemctl is-active "$SERVICE")"
  (cd "$APP_DIR/backend" && load_app_env && appy -m alembic current 2>/dev/null | tail -1 | sed 's/^/alembic:   /') || true
  echo "backups:"; ls -1dt "$BACKUPS"/*-V* 2>/dev/null | head -5 | sed 's/^/  /'
}

case "${1:-}" in
  discover) discover ;;
  deploy)   deploy "${2:-}" ;;
  status)   status ;;
  rollback) load_conf; b="$(ls -1dt "$BACKUPS"/*-V* 2>/dev/null | head -1)"; [ -n "$b" ] || die "no backup found"; rollback_code "$b" ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
