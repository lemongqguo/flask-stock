#!/bin/bash
set -e

# 统一日志出口：stderr/stdout 不做重定向，保证 supervisor / docker logs / 终端都能看到日志。
# 注：应用自身的 stdout 不受该变量影响（logging 不是 print），真正的输出由
#     gunicorn.conf.py 的 errorlog/accesslog='-' + capture_output 打到终端。
export PYTHONUNBUFFERED=1

# --- 数据库连接信息：环境变量 > 项目根 .env > 默认值（与 config.py 保持一致）---
MYSQL_HOST="${MYSQL_HOST:-}"
MYSQL_PORT="${MYSQL_PORT:-}"
ENV_FILE="${ENV_FILE:-.env}"
if [ -z "$MYSQL_HOST" ] || [ -z "$MYSQL_PORT" ]; then
  # 只解析需要的两个 key，避免 source 整个 .env（密码里的特殊字符会把脚本搞崩）
  env_get() {
    grep -E "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE" 2>/dev/null \
      | tail -n 1 | cut -d= -f2- | tr -d '"'\''' | tr -d '[:space:]'
  }
  [ -z "$MYSQL_HOST" ] && MYSQL_HOST="$(env_get MYSQL_HOST)"
  [ -z "$MYSQL_PORT" ] && MYSQL_PORT="$(env_get MYSQL_PORT)"
fi
MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

# 等待数据库准备就绪：WAIT_DB=0 跳过；WAIT_DB_RETRIES 控制上限（默认 30 × 2s ≈ 60s）
if [ "${WAIT_DB:-1}" = "1" ]; then
  WAIT_DB_RETRIES="${WAIT_DB_RETRIES:-30}"
  echo "等待数据库 ${MYSQL_HOST}:${MYSQL_PORT} ..."
  _db_ready=0
  for _ in $(seq 1 "$WAIT_DB_RETRIES"); do
    if timeout 1 bash -c "echo > /dev/tcp/${MYSQL_HOST}/${MYSQL_PORT}" 2>/dev/null; then
      _db_ready=1
      break
    fi
    sleep 2
  done
  if [ "$_db_ready" = "1" ]; then
    echo "数据库已就绪"
  else
    echo "警告：${MYSQL_HOST}:${MYSQL_PORT} 在 $((WAIT_DB_RETRIES * 2)) 秒内未就绪，继续启动（应用会自行报连接错误）" >&2
  fi
fi


echo "检查数据库结构..."
python database.py

# 生产默认走 gunicorn（配置见 gunicorn.conf.py）；
# 排障时可用 USE_GUNICORN=0 退回开发服务器。
if [ "${USE_GUNICORN:-1}" = "1" ] && command -v gunicorn >/dev/null 2>&1; then
  echo "启动应用程序（gunicorn -c gunicorn.conf.py app:app）..."
  exec gunicorn -c gunicorn.conf.py app:app
fi

echo "启动应用程序（python app.py）..."
exec python -u app.py
