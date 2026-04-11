#!/bin/bash
# Weekly secrets audit — check file perms, gitignore, stray secrets
set -u

ROOT="/root/max_leadfinder"
LOG_FILE="$ROOT/backups/secrets_audit.log"

send_alert() {
    local msg="$1"
    if [ -f "$ROOT/.env" ]; then
        set -a; . "$ROOT/.env" 2>/dev/null || true; set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=🔑 <b>Secrets audit</b>

${msg}" >/dev/null 2>&1 || true
    fi
}

ISSUES=()

# 1. .env must be 600
if [ -f "$ROOT/.env" ]; then
    PERMS=$(stat -c %a "$ROOT/.env")
    if [ "$PERMS" != "600" ]; then
        ISSUES+=(".env permissions: $PERMS (expected 600)")
        chmod 600 "$ROOT/.env" && ISSUES+=("[auto-fixed .env perms]")
    fi
fi

# 2. age key must be 600
if [ -f /root/.age/maxsurge.key ]; then
    PERMS=$(stat -c %a /root/.age/maxsurge.key)
    if [ "$PERMS" != "600" ]; then
        ISSUES+=("age key permissions: $PERMS")
        chmod 600 /root/.age/maxsurge.key
    fi
fi

# 3. .env must be in .gitignore
if ! grep -qE '^\.env$|^\*\.env$' "$ROOT/.gitignore" 2>/dev/null; then
    ISSUES+=(".env missing from .gitignore")
fi

# 4. .env must NOT be tracked by git
cd "$ROOT"
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    ISSUES+=(".env is tracked by git!")
fi

# 5. Scan for stray secrets in repo
STRAY=$(git grep -lE '(YK_SECRET_KEYs*=s*"[0-9a-zA-Z_-]{20,}"|OWNER_TG_BOT_TOKENs*=s*"[0-9]+:[A-Za-z0-9_-]+"|api_keys*=s*"sk-[A-Za-z0-9]+")' -- '*.py' '*.sh' 2>/dev/null | grep -v -E '^(scripts|\.env|README)' || true)
if [ -n "$STRAY" ]; then
    ISSUES+=("Possible secret leak in: $STRAY")
fi

# 6. session files must be 600
find "$ROOT/sessions" -type f 2>/dev/null | while read f; do
    p=$(stat -c %a "$f")
    if [ "$p" != "600" ]; then
        chmod 600 "$f"
    fi
done

# 7. backup files readable only by root
find "$ROOT/backups" -name '*.db.gz' -not -perm 600 2>/dev/null | while read f; do
    chmod 600 "$f"
done
find /var/backups/maxsurge -name '*.db.gz*' -not -perm 600 2>/dev/null | while read f; do
    chmod 600 "$f"
done

if [ ${#ISSUES[@]} -eq 0 ]; then
    echo "[$(date)] OK — no issues" >> "$LOG_FILE"
    exit 0
fi

MSG=$(printf '%s\n' "${ISSUES[@]}")
echo "[$(date)] ISSUES:" >> "$LOG_FILE"
echo "$MSG" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"
send_alert "$MSG"
