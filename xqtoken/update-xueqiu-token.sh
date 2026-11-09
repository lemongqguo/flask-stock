#!/bin/bash
# 雪球 Token 自动更新脚本（精简版）
# 每周一 9:00 执行：agent-browser 获取雪球 cookie 更新 .env，重启 flask-stock
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 生成环境记得修改.env配置文件的真实路径
CONFIG_FILE="${SCRIPT_DIR}/.env"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="${SCRIPT_DIR}/.env"
STATE_FILE="${SCRIPT_DIR}/xueqiu-state.json"
LOG_FILE="${SCRIPT_DIR}/logs/xueqiu-token-update.log"
PARSE_FILE="${SCRIPT_DIR}/logs/.token-parse.json"
mkdir -p "$(dirname "$LOG_FILE")"

# 降低 headless 被识别为自动化工具的概率
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ARGS=(--user-agent "$UA" --args "--no-sandbox" --args "--disable-dev-shm-usage" --args "--disable-blink-features=AutomationControlled")

log() { echo "$*" >> "$LOG_FILE"; }
echo "=== $(date '+%Y-%m-%d %H:%M:%S') 雪球 Token 更新开始 ===" >> "$LOG_FILE"

# 解析 agent-browser 的 cookies JSON -> {"xq_a_token":"","u":"","names":[]}
parse_cookies() {
python3 -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: d = {}
cookies = d if isinstance(d, list) else (d.get("data") or {}).get("cookies") or []
val = lambda n: next((c.get("value", "") for c in cookies if c.get("name") == n), "")
print(json.dumps({"xq_a_token": val("xq_a_token"), "u": val("u"),
                  "names": [c.get("name", "") for c in cookies if c.get("name")]}))'
}

# 从解析结果 JSON 中取字段
field() { python3 -c "
import json, sys
v = json.load(sys.stdin).get('$1', '') or ''
print(', '.join(v) if isinstance(v, list) else v)"; }

TITLE=""
PARSED='{"xq_a_token":"","u":"","names":[]}'

# ---- 方案一：浏览器 ----
log "启动浏览器..."
/usr/local/bin/agent-browser close 2>/dev/null || true
sleep 2
STATE_OPT=()
if [ -f "$STATE_FILE" ]; then
    STATE_OPT=(--state "$STATE_FILE")
else
    log "警告：未找到保存的登录状态，将使用游客模式"
fi

for url in "https://xueqiu.com/hq" "https://xueqiu.com/"; do
    /usr/local/bin/agent-browser open "$url" "${STATE_OPT[@]}" "${ARGS[@]}" >> "$LOG_FILE" 2>&1
    for i in 1 2 3 4; do  # 轮询最多约 20 秒，等 xq_a_token 种下
        sleep 5
        TITLE=$(/usr/local/bin/agent-browser eval "document.title" 2>/dev/null | tr -d '"\r\n')
        PARSED=$(/usr/local/bin/agent-browser cookies get --json 2>/dev/null | parse_cookies)
        [ -n "$(echo "$PARSED" | field xq_a_token)" ] && break
    done
    log "  $url 页面标题: $TITLE"
    [ -n "$(echo "$PARSED" | field xq_a_token)" ] && break
done

# ---- 方案二：requests 兜底 ----
if [ -z "$(echo "$PARSED" | field xq_a_token)" ]; then
    log "浏览器未拿到 xq_a_token，尝试 requests 兜底..."
    PARSED=$(python3 - <<PY || echo '{"xq_a_token":"","u":"","names":[]}'
import json, requests
s = requests.Session(); s.headers["User-Agent"] = "$UA"
token = u = ""
for url in ("https://xueqiu.com/", "https://xueqiu.com/hq"):
    try: s.get(url, timeout=15)
    except Exception: continue
    token = s.cookies.get("xq_a_token", "") or token
    u = s.cookies.get("u", "") or u
    if token: break
print(json.dumps({"xq_a_token": token, "u": u, "names": [c.name for c in s.cookies]}))
PY
)
fi

echo "$PARSED" > "$PARSE_FILE"
TOKEN=$(echo "$PARSED" | field xq_a_token)
U=$(echo "$PARSED" | field u)

if [ -z "$TOKEN" ]; then
    log "错误：未能获取到 xq_a_token"
    log "  页面标题: ${TITLE:-未知}（若为「访问提示」即被雪球风控拦截，最多几小时后自动解封，勿频繁重试）"
    log "  实际 cookie: $(echo "$PARSED" | field names)"
    /usr/local/bin/agent-browser close 2>/dev/null || true
    exit 1
fi

log "获取到 token: xq_a_token=${TOKEN:0:10}... ${U:+u=$U}"
/usr/local/bin/agent-browser state save "$STATE_FILE" 2>/dev/null || true

# ---- 更新 .env ----
NEW_TOKEN="xq_a_token=${TOKEN}"
[ -n "$U" ] && NEW_TOKEN="${NEW_TOKEN};u=${U}"
sed -i "s|    TOKEN = \".*\"|    TOKEN = \"${NEW_TOKEN}\"|" "$CONFIG_FILE"
log ".env 已更新 ($CONFIG_FILE)"

# ---- 验证 token ----
VALID=$(python3 -c "
import requests
try:
    r = requests.get('https://stock.xueqiu.com/v5/stock/quote.json?symbol=SZ000858&extend=detail',
        headers={'Cookie': '$NEW_TOKEN', 'User-Agent': '$UA'}, timeout=10)
    print('VALID' if r.status_code == 200 and 'data' in r.text else 'INVALID')
except Exception:
    print('INVALID')" 2>/dev/null)
if [ "$VALID" = "VALID" ]; then log "✅ Token 验证通过"; else log "⚠️ Token 验证未通过"; fi

/usr/local/bin/agent-browser close 2>/dev/null || true

docker restart flask-stock
log "重启docker容器flask-stock完成"
log "=== 更新完成 ==="
