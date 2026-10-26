#!/bin/bash
set -e

# 等待数据库准备就绪（跳过等待可直接设置 WAIT_DB=0）
if [ "${WAIT_DB:-1}" = "1" ]; then
  echo "等待数据库 ${MYSQL_HOST}:${MYSQL_PORT} ..."
  for _ in $(seq 1 60); do
    if timeout 1 bash -c "echo > /dev/tcp/${MYSQL_HOST}/${MYSQL_PORT}" 2>/dev/null; then
      break
    fi
    sleep 2
  done
fi

echo "检查数据库结构..."
python database.py

echo "启动应用程序..."
exec python app.py
