# 使用官方Python运行时作为基础镜像
FROM python:3.9-slim

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
ENV FLASK_DEBUG=0 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    MONITOR_ENABLED=1 \
    LOG_LEVEL=INFO

# 暴露端口
EXPOSE 5000

# 运行应用
CMD ["/bin/sh", "-c", "/app/start.sh >> /app/logs/stdout/flask-stock.stdout 2>&1"]

