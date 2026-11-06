# 使用官方Python运行时作为基础镜像
# 3.12：与本机虚拟环境 stockvenv 一致；旧版 3.9 装不上 requirements.txt 里的 numpy 2.x / pandas 3.x
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 复制项目文件
COPY ./flask-stock/ .

# 安装系统依赖和Python包
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock \
    && (apt-get update || apt-get update || sleep 10; apt-get update) \
    && apt-get install -y --no-install-recommends \
        gcc \
        default-libmysqlclient-dev \
        pkg-config \
        build-essential \
    && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && apt-get purge -y --auto-remove gcc build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 创建非root用户以提高安全性
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app && chmod +x start.sh
USER app

# 敏感配置一律通过运行时环境变量注入（不要在镜像里写死）
# 至少需要：MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE
#           SECRET_KEY XUEQIU_TOKEN MAIL_USERNAME MAIL_PASSWORD ALARM_RECIPIENTS
# 完整清单见 .env.example
# 日志同时由应用落盘到 /app/logs/（见 utils/logging_config.py）
ENV FLASK_DEBUG=0 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    MONITOR_ENABLED=1 \
    LOG_LEVEL=INFO \
    USE_GUNICORN=1

# 暴露端口（与 gunicorn.conf.py 的默认 bind 一致）
EXPOSE 5000

# 健康检查：必须**真的发起一次 HTTP 请求**才算数。
# 进程活着 ≠ 服务可用：2026-10-30 的假死就是进程还在、端口还能 telnet，
# 但所有 worker 线程都堵在取数据库连接上，任何请求都不返回（连 / 的 302 也是）。
# 这里用 urllib 而不是 curl——slim 镜像不一定装 curl。
# 命中 302 也算成功（urlopen 会自动跟随）。5 秒超时：假死时是"永不返回"，超时即失败。
# 自动恢复另需编排配合（Swarm / compose 的 autoheal / 外部看门狗）：
# Docker 默认不会因为 unhealthy 重启容器，但至少 `docker ps` 能立刻看出状态。
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/', timeout=5).status < 500 else 1)"

# 运行应用：不再把 stdout 重定向到文件，日志直接进容器输出，可用 docker logs 查看
CMD ["/bin/sh", "-c", "mkdir -p /app/logs && exec /app/start.sh"]

