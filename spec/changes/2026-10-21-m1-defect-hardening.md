# 2026-10-21 M1 缺陷治理（安全与可靠性加固）

| 项 | 值 |
| --- | --- |
| 状态 | **已合入** |
| 发起 | 2026-10-20 基线梳理后的问题清单 |
| 关联缺陷 | D-01 ~ D-12（全部闭环） |
| 影响规格 | [001](../current/001-user-auth.md)、[002](../current/002-stock-order.md)、[003](../current/003-alarm-thresholds.md)、[004](../current/004-monitor-service.md)、[005](../current/005-kline-signal.md) |
| 验证 | `python tests/run_all.py` → **138 用例全部通过** |

---

## 1. 变更类型

- [x] 新增功能
- [x] 缺陷修复（行为变更，见下文逐条）
- [x] 技术债清理
- [ ] 破坏性变更（无对外 API 变更；配置项新增但不删除，均有默认值）

## 2. 变更动机

基线梳理发现项目"功能可用但不可长期维护"：凭据明文入库、邮件告警实际不可用、
告警无去重会刷屏、生产开 debug、异常被 `print` 吞掉、无任何测试与 `.gitignore`。
本次把 P0/P1 缺陷一次性闭环，并建立回归测试底座。

## 3. 变更内容

### 3.1 D-01 配置与凭据外置（P0）

- `config.py` 重写：删除全部明文凭据，改为环境变量 + 自研极简 `load_dotenv()`（无新增依赖）。
- 新增 `.env.example` 模板；`.gitignore` 排除 `.env`（配合 D-08）。
- 新增 `missing_required_settings()` / `validate_runtime_settings(strict)`：
  `MYSQL_PASSWORD` / `SECRET_KEY` / `XUEQIU_TOKEN` / `MAIL_USERNAME` / `MAIL_PASSWORD` / `ALARM_RECIPIENTS`
  缺失时，生产启动（`app.py` `__main__` 且非 debug）直接 `RuntimeError` 拒绝启动。
- 原 `xueQiutoken` 类名统一为 `XueqiuToken`，`emailReceived.EMAIL_RECEIVED` 改为 `get_alarm_recipients()`。
- `Dockerfile` / `start.sh` 同步改为使用统一的 `MYSQL_*` 变量。

**行为影响**：未配置 `.env` 的环境启动即报错（这是有意的 fail-fast）。

### 3.2 D-02 告警收件人（P0）

- `ALARM_RECIPIENTS` 取代写死的 `[""]`；`send_mail` 发送前校验收件人非空且为合法邮箱。
- 收件人为空时：`logger.warning` + 跳过发信，**不再把 `[""]` 丢给 SMTP**。
- 新增 `MAIL_TIMEOUT`（默认 10s）与 `ALARM_MAIL_ENABLED` 开关。

### 3.3 D-03 告警冷却（P0）

- 新增 `utils/alarm_rules.py`（纯函数：档位判定、文案、冷却 key）与 `utils/alarm_throttle.py`（冷却器）。
- 冷却 key `{stock_id}:{类型}[:{档位}]`，窗口 `ALARM_COOLDOWN_SECONDS`（默认 14400s = 4h）。
- **条件消失即 `clear()` 撤销冷却**，使再次满足条件能立即重新告警。
- `ALARM_COOLDOWN_SECONDS=0` 可退回历史"每次都告警"行为。

**行为影响**：这是**用户可感知的行为变更**——阈值持续满足时不再每轮刷屏。

### 3.4 D-04 交易时段判断（P1）

- 新增 `utils/trading_time.py`：`is_trading_time()`（工作日 09:30–11:30 / 13:00–15:00）、`is_trading_day()`、`describe_session()`。
- `monitor_loop` 在非交易时段进入 `MONITOR_OFF_HOURS_SLEEP`（默认 300s）休眠，不再拉雪球行情。

**行为影响**：非交易时段不再更新价格/PE/PB/K线数据。

### 3.5 D-05 debug 模式与重复线程（P1）

- `Config.DEBUG` 改由 `FLASK_DEBUG` 决定，**默认 0**；`app.run` 不再硬编码 `debug=True`。
- `start_monitoring()` 加 `_start_lock` + 线程存活检查，重复调用返回 `False`。
- 使用 reloader 时只在子进程（`WERKZEUG_RUN_MAIN == 'true'`）启动监控，避免父/子各一个线程。

### 3.6 D-06 测试骨架（P1）

- 新增 `tests/` 共 **138 个用例**，基于标准库 `unittest`（可被 pytest 收集）：
  `test_alarm_rules` / `test_alarm_throttle` / `test_trading_time` / `test_base_query_builder` /
  `test_config` / `test_mail_sender` / `test_kline_signal` / `test_monitor_service` / `test_app_smoke`。
- 入口：`python tests/run_all.py` 或 `python -m unittest discover -s tests -t .`
- 全部用例不连真实数据库、不发真实邮件（mock 隔离）；`test_app_smoke` 在导入 `app` 时 patch 掉连接池。
- **未建立 CI**（无 `.github/workflows`），见"遗留"。

### 3.7 D-07 `base.py` SQL 构造缺陷（P1）

- `BaseModel.search_fields` 默认为 `None`，`build_search_where()` 在无搜索字段或空关键字时返回 `('', [])`，
  从根上消除裸 `WHERE `。
- 字段名经白名单校验并用反引号包裹；关键字参数化。
- COUNT 查询与数据查询复用同一 `where_sql`；`page`/`per_page` 下限保护。

### 3.8 D-08 `.gitignore`（P1）

- 新增 `.gitignore`：排除 `stockenv/`、`__pycache__/`、`logs/`、`.env`、`*.log`、`.pytest_cache/`、IDE 目录等。
- 新增 `.env.example` 作为可提交的模板。

### 3.9 D-09 `alarm_time` 索引（P2）

- `stock_alarm` 建表增加 `idx_alarm_time(alarm_time)` 与 `idx_stock_alarm(stock_master_id, alarm_time)`。
- `database.py` 增加 `_ensure_indexes()`：查 `information_schema.STATISTICS`，为**存量库**幂等补索引，失败仅 warning 不阻断启动。

### 3.10 D-10 死代码清理（P2）

- 删除 `utils/decorators.py` 的 `admin_required` / `permission_required`（依赖不存在的字段）。
- 删除 `utils/mail_sender.py` 的 `send_alarm_mail`（无调用点）。
- 删除 `static/js/main.js` 的 `initializeCharts` 空占位。
- 删除 `views/stock_orders.py` 中未传入模板的 `start_page` / `end_page` 死变量。

### 3.11 D-11 异常可观测性（P2）

- 新增 `utils/logging_config.py`：控制台 + `logs/stock_app.log`（5MB × 10 轮转）。
  **修复"仅在 `not app.debug` 时挂载文件 handler，等于从不落盘"**。
- `models/` 下 25 处 `print(f"...{e}")` 全部替换为 `logger.exception(...)`（带堆栈）。
- `database.init_database()` 返回 `bool`，不再 `exit(1)`；连接池改为**惰性创建**。
- `app.py` 补 403/404/500 错误处理页。

### 3.12 D-12 过期 API（P2）

- `views/auth.py` 的 `werkzeug.urls.url_parse` 改为标准库 `urllib.parse.urlparse`，封装为 `_is_safe_redirect()`。
- 顺带：改密码的写库下沉到 `User.update_password()`（视图层不再直接写 SQL）；注册/改密服务端强制密码 ≥ 6 位。

## 4. 影响面评估

| 范围 | 影响 |
| --- | --- |
| 数据结构 | `stock_alarm` 新增 2 个索引（幂等迁移，不改列） |
| 配置 | 新增 `FLASK_DEBUG` / `MONITOR_ENABLED` / `MONITOR_MAX_WORKERS` / `MONITOR_MAX_STOCKS` / `MONITOR_ERROR_SLEEP` / `MONITOR_OFF_HOURS_SLEEP` / `FETCH_MIN_DELAY` / `FETCH_MAX_DELAY` / `ALARM_COOLDOWN_SECONDS` / `ALARM_RECIPIENTS` / `ALARM_MAIL_ENABLED` / `MAIL_TIMEOUT` / `LOG_LEVEL`；旧变量名 `EMAIL_RECEIVED` 移除 |
| 外部接口 | 无 HTTP 路径或响应结构变更 |
| 用户可感知 | ①告警不再刷屏；②非交易时段不再更新数据；③未配置 `.env` 时拒绝启动 |
| 部署 | 必须注入环境变量或提供 `.env`；否则启动失败（fail-fast） |

## 5. 验证方式与结果

```
python tests/run_all.py
→ Ran 138 tests ... OK
```

覆盖要点：档位判定边界、冷却放行/拦截/撤销、交易时段边界、`base.py` 无裸 `WHERE`、
配置解析与明文凭据红线、邮件收件人前置校验、均线信号边界与 NaN、
监控线程唯一性、收件人为空跳过发信、应用蓝图与路由装配。

## 6. 遗留与后续

- **未建立 CI**：`.github/workflows/test.yml` 仍待补（依赖可用的 CI 环境）。
- **未初始化 Git 仓库**：D-08 的 `.gitignore` 已就位，但仓库尚未 `git init`。
- **历史凭据仍需轮换**：`config.py` 的明文密码/SECRET_KEY/雪球 Token 已被删除，但**这些值曾入库，必须在服务端全部更换**。
- **告警冷却状态在进程内存**：多进程部署需改为共享存储。
- **交易日历为近似**：未接入法定节假日。
- **负 PE 会命中 PE 档位**：当前行为已由测试锁定，是否过滤需产品决策。
