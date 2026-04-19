#!/bin/bash
# E2E smoke test — гоняется после каждого деплоя, валидирует критические флоу.
# Exit 0 = все зелёные, exit >0 = есть красные.
#
# Usage:
#   ./scripts/e2e_smoke.sh              # против https://maxsurge.ru
#   BASE=http://localhost:8090 ./scripts/e2e_smoke.sh

set -u

BASE="${BASE:-https://maxsurge.ru}"
CURL="curl -sk --max-time 10"
CJ=$(mktemp -t e2e-cj.XXXXXX)
trap "rm -f $CJ" EXIT

PASS=0
FAIL=0
RESULTS=()

check() {
    local name="$1"
    local expected="$2"
    local actual="$3"
    if [ "$expected" = "$actual" ]; then
        RESULTS+=("✅ $name")
        PASS=$((PASS+1))
    else
        RESULTS+=("❌ $name: expected=$expected got=$actual")
        FAIL=$((FAIL+1))
    fi
}

echo "=== E2E smoke against $BASE ==="

# 1. Public endpoints return 200
for path in / /health /status /terms /privacy /contacts /about /login /register /robots.txt /sitemap.xml; do
    code=$($CURL -o /dev/null -w "%{http_code}" "$BASE$path")
    check "GET $path" "200" "$code"
done

# 2. Protected admin endpoints should redirect/401 without auth
code=$($CURL -o /dev/null -w "%{http_code}" "$BASE/app/admin/")
[ "$code" = "303" ] || [ "$code" = "401" ] || [ "$code" = "302" ] || [ "$code" = "307" ]
check "GET /app/admin/ unauthenticated rejects" "0" "$?"

# 3. /health contents
health=$($CURL "$BASE/health")
status=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
check "/health returns status=ok" "ok" "$status"

# 4. /openapi.json closed in prod
code=$($CURL -o /dev/null -w "%{http_code}" "$BASE/openapi.json")
check "/openapi.json closed" "404" "$code"

# 5. /api/docs closed
code=$($CURL -o /dev/null -w "%{http_code}" "$BASE/api/docs")
check "/api/docs closed" "404" "$code"

# 6. /metrics requires auth
code=$($CURL -o /dev/null -w "%{http_code}" "$BASE/metrics")
check "/metrics requires auth" "401" "$code"

# 7. Security headers present on /
headers=$($CURL -I "$BASE/")
echo "$headers" | grep -qi "strict-transport-security" && hsts=1 || hsts=0
check "HSTS header present" "1" "$hsts"
echo "$headers" | grep -qi "x-content-type-options" && xcto=1 || xcto=0
check "X-Content-Type-Options present" "1" "$xcto"
echo "$headers" | grep -qi "x-frame-options" && xfo=1 || xfo=0
check "X-Frame-Options present" "1" "$xfo"

# 8. CSRF cookie issued on first GET
$CURL -c "$CJ" "$BASE/login" -o /dev/null
grep -q "csrf_token" "$CJ" && csrf=1 || csrf=0
check "CSRF cookie issued" "1" "$csrf"

# 9. /register rate-limited after 4th attempt (if reached)
# (skip in smoke — too intrusive for prod)

# 10. Payment webhooks reject unsigned POST
code=$($CURL -o /dev/null -w "%{http_code}" -X POST "$BASE/app/billing/webhook-rb" -d "OutSum=1&InvId=1&SignatureValue=bad")
check "RB webhook rejects bad signature" "400" "$code"

code=$($CURL -o /dev/null -w "%{http_code}" -X POST "$BASE/app/billing/webhook-pd" -d "order_id=1&sum=1&signature=bad")
check "PD webhook rejects bad signature" "400" "$code"

# Report
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
for r in "${RESULTS[@]}"; do echo "  $r"; done

exit $FAIL
