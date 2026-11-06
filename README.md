# Flask Stock 股票监控系统

基于 Flask、MySQL、Gunicorn 和雪球行情数据的股票监控应用，支持多用户数据隔离、订单管理、行情与 K 线监控、指标监控、邮件告警和 AI 个股分析。

本文档给出一套从空环境到正式运行的实施流程，包括 MySQL 准备、环境变量配置、Docker 镜像构建、容器启动、首次登录、升级回滚、数据库备份恢复和常见故障排查。

## 1. 运行架构与要求

### 1.1 运行组件

- Python 3.12
- Flask 2.3.3
- MySQL 8.0（推荐，使用 `utf8mb4`）
- Gunicorn：固定 **1 个 worker**，通过 `gthread` 线程处理并发
- Docker：应用和日志通过容器运行，业务数据保存在外部 MySQL
- 外部服务：雪球行情、SMTP 邮件服务；AI 分析为可选功能

应用启动时会自动执行以下操作：

1. 等待 MySQL 的地址和端口可连接；
2. 执行 `python database.py`，幂等创建业务表并补充已有库的字段、索引和约束；
3. 严格检查生产环境必填配置；
4. 启动 Gunicorn 和后台行情监控线程。

> **重要：**不要同时运行多个应用容器或增加 Gunicorn worker 数。监控线程、告警冷却和部分运行时状态保存在进程内存中，多实例会造成重复行情请求、重复监控和状态不一致。

### 1.2 服务器准备

需要提前安装并启动 Docker，且部署用户具有执行 `docker` 命令的权限：

```bash
docker version
docker info
```

默认端口：

| 端口 | 用途 |
|---|---|
| `5000/tcp` | Flask Stock Web 服务 |
| `3306/tcp` | MySQL；仅在应用需要跨容器或跨主机访问时开放 |

容器内的 `127.0.0.1` 指向应用容器自身，**不是宿主机或另一台数据库服务器**。MySQL 与应用不在同一容器时，`MYSQL_HOST` 应填写数据库服务器 IP 或应用容器可解析、可访问的 DNS 名称。

## 2. 准备 MySQL 数据库

可以使用已有的 MySQL 8.0，也可以使用 Docker 新建 MySQL。应用不会自动创建数据库本身，因此必须先创建空库和访问账号。

### 2.1 方案 A：使用已有 MySQL

在 MySQL 服务器上使用有建库、建账号权限的管理员登录：

```bash
mysql -h 127.0.0.1 -P 3306 -u root -p
```

执行以下 SQL，并替换其中的数据库密码：

```sql
CREATE DATABASE stockdb
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'stock'@'%' IDENTIFIED BY '请替换为强数据库密码';

GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, INDEX, REFERENCES
ON stockdb.* TO 'stock'@'%';
```

这里的 DDL 权限是必要的：应用每次启动都会检查表结构，升级时还可能执行 `CREATE TABLE`、补字段、补索引或调整约束。完成初始化后，不建议在应用运行期间直接撤销这些权限，否则后续升级可能失败。

账号示例使用 `'stock'@'%'` 是为了兼容容器来源 IP。生产环境应结合 MySQL 账号主机范围、防火墙或安全组限制访问来源，不要把 MySQL 无保护地暴露到公网。

### 2.2 方案 B：用 Docker 新建 MySQL

如果服务器上没有 MySQL，可以执行：

```bash
sudo install -d -m 750 /opt/flask-stock/mysql

docker run -d \
  --name stock-mysql \
  --restart always \
  -p 3306:3306 \
  -v /opt/flask-stock/mysql:/var/lib/mysql \
  -e MYSQL_ROOT_PASSWORD='请替换为MySQL-root强密码' \
  -e MYSQL_DATABASE=stockdb \
  -e MYSQL_USER=stock \
  -e MYSQL_PASSWORD='请替换为stock强密码' \
  -e TZ=Asia/Shanghai \
  mysql:8.0
```

等待数据库初始化完成：

```bash
docker logs -f --tail 100 stock-mysql
```

看到日志包含 `ready for connections` 后按 `Ctrl+C` 退出日志查看。该命令只会退出日志跟踪，不会停止数据库。

随后验证：

```bash
docker exec -it stock-mysql \
  mysqladmin -u stock -p ping
```

按提示输入 `stock` 用户密码，返回 `mysqld is alive` 即表示可用。

这种部署方式中，应用容器仍使用本文给出的默认 bridge 网络启动，因此 `.env` 中的 `MYSQL_HOST` 应填写**宿主机实际 IP**，不要填写 `stock-mysql` 或 `127.0.0.1`。同时确认宿主机的 3306 端口允许来自 Docker 网桥的连接。

## 3. 准备宿主机目录与 `.env`

### 3.1 创建目录

镜像使用非 root 用户 `app` 运行，其默认 UID/GID 为 `1000:1000`。宿主机日志目录必须允许该用户写入：

```bash
sudo install -d -m 750 -o 1000 -g 1000 /opt/flask-stock/config
sudo install -d -m 750 -o 1000 -g 1000 /opt/flask-stock/logs
sudo install -d -m 700 /opt/flask-stock/backup
```

### 3.2 创建生产配置

在项目源码根目录执行，从模板复制配置：

```bash
cd /opt/buildflask/aaa/flask-stock
sudo cp .env.example /opt/flask-stock/config/.env
sudo chown 1000:1000 /opt/flask-stock/config/.env
sudo chmod 600 /opt/flask-stock/config/.env
sudo vi /opt/flask-stock/config/.env
```

生成 Flask 会话密钥：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

以下是一份可用于首次启动的最小生产配置。请替换所有占位值，尤其是数据库地址、密码、雪球 Token 和邮箱授权码：

```dotenv
# Flask
FLASK_DEBUG=0
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
SECRET_KEY=替换为刚生成的64位十六进制随机字符串

# MySQL：填写数据库服务器地址，不要在容器场景填写127.0.0.1
MYSQL_HOST=192.168.1.10
MYSQL_PORT=3306
MYSQL_USER=stock
MYSQL_PASSWORD=替换为stock用户的数据库密码
MYSQL_DATABASE=stockdb
MYSQL_CHARSET=utf8mb4

# 默认8个HTTP线程 + 6个监控线程，连接池保留余量
MYSQL_MAX_CONNECTIONS=19
MYSQL_MIN_CACHED=2
MYSQL_MAX_CACHED=10
MYSQL_POOL_WAIT_TIMEOUT=10
MYSQL_CONNECT_TIMEOUT=10
MYSQL_READ_TIMEOUT=30
MYSQL_WRITE_TIMEOUT=30
MYSQL_TCP_KEEPALIVE=1
MYSQL_KEEPALIVE_IDLE=60
MYSQL_KEEPALIVE_INTERVAL=30
MYSQL_KEEPALIVE_COUNT=3

# 邮件告警；MAIL_PASSWORD通常填SMTP授权码，不是邮箱登录密码
MAIL_SERVER=smtp.qq.com
MAIL_PORT=465
MAIL_USE_SSL=1
MAIL_USE_TLS=0
MAIL_USERNAME=your-account@qq.com
MAIL_PASSWORD=替换为SMTP授权码
MAIL_TIMEOUT=10
ALARM_RECIPIENTS=receiver1@example.com,receiver2@example.com
ALARM_MAIL_ENABLED=1
ALARM_COOLDOWN_SECONDS=10800
DAILY_SUMMARY_TIME=08:30

# 雪球登录Cookie中的xq_a_token及用户ID
XUEQIU_TOKEN="xq_a_token=替换为真实Token;u=替换为雪球用户ID"

# 行情与指标监控
MONITOR_ENABLED=1
MONITOR_MAX_WORKERS=6
MONITOR_MAX_STOCKS=100
MONITOR_ERROR_SLEEP=5
FETCH_MIN_DELAY=30
FETCH_MAX_DELAY=300
IND_ENABLED=1
IND_BENCH=SH000300

# 首次部署可关闭AI；需要时参考.env.example补齐AI_API_*配置
AI_ENABLED=0

# 日志
LOG_LEVEL=INFO
```

配置注意事项：

- 生产启动会强制检查 `MYSQL_PASSWORD`、`SECRET_KEY`、`XUEQIU_TOKEN`、`MAIL_USERNAME`、`MAIL_PASSWORD` 和 `ALARM_RECIPIENTS`，缺少任意一项都会导致 worker 启动失败。
- 即使暂时不发送邮件，也建议填写有效的邮件配置；当前生产自检仍把邮件相关项目列为必填。
- `ALARM_RECIPIENTS` 支持多个邮箱，使用英文逗号分隔。
- `MYSQL_MAX_CONNECTIONS` 不应小于 `GUNICORN_THREADS + MONITOR_MAX_WORKERS + 5`；默认配置对应 `8 + 6 + 5 = 19`。
- AI 功能默认可以关闭。启用时需要配置 `AI_API_BASE`、`AI_MODEL`、`AI_API_KEY`、`AI_API_STYLE` 和 `AI_TIMEOUT`，完整项目见 `.env.example`。
- `.env` 包含数据库密码、Token 和邮箱授权码，不得提交到 Git、打进镜像或发送到公开渠道。

## 4. 获取或构建应用镜像

### 4.1 直接拉取已发布镜像

如果不需要重新构建，可以直接拉取指定版本：

```bash
docker pull registry.cn-shanghai.aliyuncs.com/ggq126/stock:v20261105
```

### 4.2 从源码构建镜像

当前 `Dockerfile` 使用 `COPY ./flask-stock/ .`，因此构建上下文必须是项目目录的**上一级目录**。以当前源码位于 `/opt/buildflask/aaa/flask-stock` 为例：

```bash
cd /opt/buildflask/aaa

docker build \
  --pull \
  -f flask-stock/Dockerfile \
  -t registry.cn-shanghai.aliyuncs.com/ggq126/stock:v20261105 \
  .
```

构建前必须注意：Docker 只读取**构建上下文根目录**的 `.dockerignore`。上述命令的上下文是 `/opt/buildflask/aaa`，所以仅依靠 `flask-stock/.dockerignore` 不足以排除项目里的真实 `.env`。

请在 `/opt/buildflask/aaa/.dockerignore` 中合并以下规则；如果文件已存在，保留其原有内容，不要直接覆盖：

```dockerignore
flask-stock/.env
flask-stock/logs/
flask-stock/stockvenv/
flask-stock/stockenv/
flask-stock/venv/
**/.git/
**/__pycache__/
**/*.py[cod]
**/.pytest_cache/
**/*.log
```

构建完成后检查镜像：

```bash
docker image inspect \
  registry.cn-shanghai.aliyuncs.com/ggq126/stock:v20261105 \
  --format '{{.Id}} {{.Created}}'
```

如需发布到阿里云镜像仓库：

```bash
docker login registry.cn-shanghai.aliyuncs.com
docker push registry.cn-shanghai.aliyuncs.com/ggq126/stock:v20261105
```

正式版本建议使用不可变的新标签，不要在生产环境反复覆盖同一个标签。

## 5. 启动应用容器

确认 MySQL 可连接、数据库已创建、`/opt/flask-stock/config/.env` 已填写并且日志目录权限正确后，执行：

```bash
docker run -d \
  -p 5000:5000 \
  --restart always \
  --name flask-stock \
  -v /opt/flask-stock/config/.env:/app/.env \
  -v /opt/flask-stock/logs:/app/logs \
  -e TZ=Asia/Shanghai \
  registry.cn-shanghai.aliyuncs.com/ggq126/stock:v20261105
```

挂载说明：

| 宿主机路径 | 容器路径 | 用途 |
|---|---|---|
| `/opt/flask-stock/config/.env` | `/app/.env` | 数据库、邮件、雪球和应用配置 |
| `/opt/flask-stock/logs` | `/app/logs` | 持久化应用日志及轮转文件 |

MySQL 不在这两个挂载目录中，业务数据由外部 MySQL 持久化。删除应用容器不会删除 MySQL 数据，但仍应在升级前备份数据库。

## 6. 首次启动验收

### 6.1 检查容器与健康状态

```bash
docker ps --filter name=flask-stock
docker inspect flask-stock --format '{{json .State.Health}}'
```

镜像健康检查启动后有 60 秒宽限期，之后每 30 秒请求一次应用。健康状态应最终变为 `healthy`。

检查启动日志：

```bash
docker logs --tail 200 flask-stock
```

正常启动应能看到数据库就绪、数据库结构检查完成和 Gunicorn 启动相关日志。持续观察可执行：

```bash
docker logs -f --tail 100 flask-stock
```

### 6.2 验证 HTTP 服务

在宿主机执行：

```bash
curl -fsS http://127.0.0.1:5000/login > /dev/null && echo 'HTTP访问正常'
```

然后从浏览器访问：

```text
http://服务器IP:5000
```

未登录时会跳转到登录页。如果服务器启用了防火墙或云安全组，只向受信任的来源开放 5000 端口；正式对外提供服务时，建议通过 Nginx 等反向代理启用 HTTPS，而不是直接把 Flask 端口暴露到公网。

### 6.3 注册并设置管理员

1. 打开注册页面，创建第一个用户；
2. **全新数据库中的第一个注册用户会自动成为管理员**；
3. 后续注册用户默认为普通用户，只能看到自己名下的订单；
4. 管理员可以查看全部订单；
5. 创建一条 active 状态的订单，观察行情、K 线和指标是否随监控周期更新。

如需把已有用户提升为管理员：

```bash
docker exec flask-stock flask --app app set-admin 用户名
```

被提升的用户必须退出并重新登录，新的管理员角色才会写入会话。

如需手动重新执行数据库初始化：

```bash
docker exec flask-stock flask --app app init-db
```

正常情况下不需要手动执行，因为容器每次启动都会自动完成这一步。

## 7. 日常容器运维

### 7.1 启动、停止与重启

```bash
docker start flask-stock
docker stop flask-stock
docker restart flask-stock
```

修改 `.env` 后必须重启容器才能生效：

```bash
sudo vi /opt/flask-stock/config/.env
docker restart flask-stock
docker logs --tail 100 flask-stock
```

更换 `SECRET_KEY` 会使已有登录会话失效，这是预期行为。

### 7.2 查看日志

容器标准输出：

```bash
docker logs -f --tail 200 flask-stock
```

宿主机应用日志：

```bash
tail -f /opt/flask-stock/logs/stock_app.log
```

应用日志单文件达到 5 MiB 后轮转，保留 10 个历史文件。即使文件日志不可用，也应能通过 `docker logs` 查看控制台日志。

> Docker 的 `--restart always` 主要处理进程退出，不会仅因为健康检查显示 `unhealthy` 就自动重建容器。出现 `unhealthy` 时应结合健康状态和应用日志排查数据库、网络或阻塞问题。

### 7.3 升级应用

升级顺序建议为：备份数据库和 `.env` → 拉取新镜像 → 停止旧容器 → 使用相同挂载启动新容器 → 验证。

```bash
# 1. 先按第8节完成数据库备份，并另行妥善保存.env

# 2. 拉取新版本
docker pull registry.cn-shanghai.aliyuncs.com/ggq126/stock:新版本标签

# 3. 停止并删除旧应用容器；不会删除外部MySQL数据
docker stop flask-stock
docker rm flask-stock

# 4. 重新执行第5节的docker run命令，只把最后的镜像标签替换为新版本
```

启动后检查：

```bash
docker ps --filter name=flask-stock
docker logs --tail 200 flask-stock
curl -fsS http://127.0.0.1:5000/login > /dev/null && echo '升级后HTTP访问正常'
```

### 7.4 回滚

如果新版本仅涉及应用代码，可停止并删除当前应用容器，再按第 5 节使用旧镜像标签启动。

但应用启动可能自动升级数据库结构。**数据库结构变更不一定能向后兼容**；如果旧版本无法读取新结构，应停止使用异常版本，并按备份恢复与旧版本匹配的数据库。不要在没有备份的情况下直接回滚。

## 8. 数据库备份与恢复

### 8.1 在线备份

以下命令使用 MySQL 8 客户端工具。宿主机没有 `mysqldump` 时，可安装 MySQL 客户端，或在网络、版本和输出重定向均确认无误后使用对应 MySQL 8 容器中的工具。

应用本身只使用普通表，不依赖存储过程、事件、触发器或独立表空间。以下参数可使用前面创建的 `stock` 应用账号备份全部业务表，不要求 root 或全局管理权限。如果管理员额外创建了这些数据库对象，应改用具备相应权限的专用备份账号并调整导出参数。

```bash
sudo install -d -m 700 /opt/flask-stock/backup
BACKUP_FILE="/opt/flask-stock/backup/stockdb-$(date +%Y%m%d-%H%M%S).sql"

mysqldump \
  --host=192.168.1.10 \
  --port=3306 \
  --user=stock \
  --password \
  --single-transaction \
  --quick \
  --skip-add-drop-table \
  --skip-triggers \
  --skip-lock-tables \
  --no-tablespaces \
  --hex-blob \
  --set-gtid-purged=OFF \
  --default-character-set=utf8mb4 \
  stockdb > "$BACKUP_FILE"

gzip "$BACKUP_FILE"
gzip -t "$BACKUP_FILE.gz"
echo "备份完成：$BACKUP_FILE.gz"
```

`--password` 没有直接跟密码，执行时会交互式提示输入，避免密码出现在 shell 历史中。`--single-transaction` 用于 InnoDB 在线一致性备份，备份期间无需停止应用。

备份文件包含完整业务数据，应视为敏感文件。建议：

- 至少每天备份一次，并在每次升级前额外备份；
- 保留多代备份，不只保留最新一份；
- 将备份复制到另一台机器或独立存储；
- 定期实际执行恢复演练，只检查文件存在不代表备份可用；
- 自动化备份时使用受限账号和 MySQL `login-path` 等凭据机制，不要把密码写进脚本或 crontab。

### 8.2 恢复前准备

恢复是高风险操作。推荐使用**新数据库恢复并验证**，不要直接覆盖正在使用的 `stockdb`。

先停止应用写入：

```bash
docker stop flask-stock
```

在 MySQL 管理员会话中创建恢复库，并授权给应用账号：

```sql
CREATE DATABASE stockdb_restore
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, INDEX, REFERENCES
ON stockdb_restore.* TO 'stock'@'%';
```

### 8.3 导入备份并验证

将主机、端口、库名和备份文件路径替换为实际值：

```bash
gunzip -c /opt/flask-stock/backup/stockdb-20261106-020000.sql.gz | \
  mysql \
    --host=192.168.1.10 \
    --port=3306 \
    --user=stock \
    --password \
    --default-character-set=utf8mb4 \
    stockdb_restore
```

检查表和关键数据量：

```bash
mysql \
  --host=192.168.1.10 \
  --port=3306 \
  --user=stock \
  --password \
  stockdb_restore \
  -e "SHOW TABLES; SELECT COUNT(*) AS users FROM users; SELECT COUNT(*) AS orders_count FROM stock_master;"
```

### 8.4 切换到恢复库

1. 修改 `/opt/flask-stock/config/.env`：

   ```dotenv
   MYSQL_DATABASE=stockdb_restore
   ```

2. 启动应用并检查日志：

   ```bash
   docker start flask-stock
   docker logs --tail 200 flask-stock
   ```

3. 登录页面核对用户、订单、行情、告警和指标数据；
4. 验证无误后保留旧库一段时间，不要立即删除。

如果必须恢复到原来的 `stockdb`，应在维护窗口内由数据库管理员制定清空、导入和切换步骤；不要直接对仍有业务表的库重复导入完整备份。

## 9. 数据库日常检查

### 9.1 检查连接和表结构

```bash
mysql -h 192.168.1.10 -P 3306 -u stock -p stockdb \
  -e "SELECT VERSION(); SHOW TABLES;"
```

应用需要的主要表包括：

- `users`、`user_notify_pref`
- `stock_master`、`stock_warehouse`
- `stock_pe`、`stock_pb`
- `stock_alarm`、`stock_kline`
- `stock_indicator`、`stock_indicator_config`、`stock_bench_kline`
- `stock_ai_report`、`stock_ai_config`

### 9.2 升级数据库前的注意事项

- 备份整个业务库，而不是只备份 `stock_master`；
- 检查应用账号仍有 `CREATE`、`ALTER`、`INDEX` 和 `REFERENCES` 权限；
- 大表执行结构变更可能耗时或锁表，应安排维护窗口；
- 不要在多个应用实例启动时并发执行结构迁移；
- 查看启动日志中是否有“数据库结构检查失败”“补充字段失败”或“调整唯一键失败”；
- 多用户版本会把没有归属的历史订单归到最早注册用户，并在没有管理员时把首个用户提升为管理员，升级后应核对归属和角色。

## 10. 常见故障排查

| 现象 | 重点检查 | 处理方式 |
|---|---|---|
| 容器反复重启 | `docker logs --tail 200 flask-stock` | 检查必填配置是否缺失，修正 `.env` 后重启 |
| 日志提示无法连接 MySQL | `MYSQL_HOST`、端口、防火墙、MySQL 状态 | 容器场景不要使用 `127.0.0.1`；确认容器到数据库的 3306 连通性 |
| 提示数据库不存在 | `MYSQL_DATABASE` | 先创建空库，保证库名与 `.env` 一致 |
| 提示 Access denied | 用户名、密码、账号来源主机和授权 | 核对 `'stock'@'%'` 或更严格来源账号的权限与密码 |
| 启动时建表或迁移失败 | 应用账号 DDL 权限 | 补充 `CREATE`、`ALTER`、`INDEX`、`REFERENCES` 后重新初始化 |
| `/app/logs` 权限不足 | 宿主机目录属主 | 执行 `sudo chown -R 1000:1000 /opt/flask-stock/logs` |
| 5000 无法访问 | 容器状态、端口映射、防火墙 | 检查 `docker ps`、5000 端口占用和安全组规则 |
| 一直显示 unhealthy | `.State.Health` 输出、数据库连接、慢请求 | 查看最近健康检查错误和应用日志，不要只依赖进程是否存在 |
| 页面能打开但行情不更新 | `MONITOR_ENABLED`、订单 active 状态、雪球 Token、监控日志 | 更新有效 Token，确认监控线程已启动，并留意外部请求节流间隔 |
| 邮件无法发送 | SMTP 地址、SSL/TLS、授权码、收件人 | QQ 邮箱通常使用 465 + SSL，密码字段填写 SMTP 授权码 |
| AI 显示未启用 | `AI_ENABLED` 和 `AI_API_*` | 首次部署可保持 `AI_ENABLED=0`，需要时按 `.env.example` 配置 |

查看健康检查最近失败原因：

```bash
docker inspect flask-stock \
  --format '{{range .State.Health.Log}}{{println .End .ExitCode .Output}}{{end}}'
```

临时排查数据库启动等待时，可以在 `docker run` 中额外传入 `-e WAIT_DB=0` 跳过启动脚本的端口等待，但这不会解决数据库连接问题，也不建议作为正式配置。

## 11. 可选：不使用 Docker 的本地运行

仅用于开发或联调，建议使用 Python 3.12 虚拟环境：

```bash
python3.12 -m venv stockvenv
source stockvenv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑.env后初始化数据库
python database.py

# 使用与生产相同的Gunicorn入口
gunicorn -c gunicorn.conf.py app:app
```

`gunicorn.conf.py` 已固定单 worker，不要再通过 `-w 4` 等参数增加进程数。需要调整 HTTP 并发时，可谨慎调整 `GUNICORN_THREADS`，并同步增大 `MYSQL_MAX_CONNECTIONS`。

## 12. 安全 checklist

上线前至少确认：

- [ ] `.env` 未被 Git 跟踪，也未被复制进镜像；
- [ ] `SECRET_KEY` 是独立生成的强随机值；
- [ ] MySQL 使用独立应用账号，不使用 root；
- [ ] MySQL 和 Web 端口均受防火墙或安全组限制；
- [ ] 雪球 Token、邮箱授权码、AI Key 不出现在日志、文档或截图中；
- [ ] 对外访问通过 HTTPS 反向代理；
- [ ] 公开注册入口符合实际使用范围，必要时在反向代理层限制 `/register`；
- [ ] 只运行一个应用实例，Gunicorn 保持单 worker；
- [ ] 已完成数据库备份，并验证过至少一次恢复流程；
- [ ] 容器健康状态、控制台日志和文件日志均正常。
