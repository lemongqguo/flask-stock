# 004 后台监控服务（StockMonitor）

**状态**：已实现　|　**最后更新**：2026-10-26
**实现**：`models/stock_monitor.py`、`utils/mail_sender.py`、`utils/trading_time.py`、`utils/alarm_rules.py`、`utils/alarm_throttle.py`、`utils/snowball_errors.py`、`utils/logging_config.py`、`app.py`、`config.py`
**相关变更**：
[2026-10-21 M1 缺陷治理](../changes/2026-10-21-m1-defect-hardening.md)（D-01~D-12）、
[2026-10-21 雪球接口错误降级](../changes/2026-10-21-xueqiu-error-handling.md)（D-13）、
[2026-10-21 优雅退出](../changes/2026-10-21-graceful-shutdown.md)（D-14）、
[2026-10-26 多用户数据隔离](../archive/changes/2026-10-26-multi-user-ownership.md)（本轮结果共享 + 收件人按归属人）

---

## 1. 场景

应用启动后拉起一个守护线程，持续轮询所有 `status=active` 的订单：从雪球取行情与 PE/PB 回写数据库，
判断是否触发告警，触发则写告警记录并发送邮件；同时拉取并落库 K 线数据。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| 监控线程 | `StockMonitor` 模块级单例 `monitor`，`start_monitoring()` 创建 `daemon=True` 线程跑 `monitor_loop` |
| 交易时段 | 工作日 09:30–11:30 与 13:00–15:00，由 `utils/trading_time.is_trading_time()` 判定；`describe_session()` 返回 `morning`/`afternoon`/**`noon`**（11:30–13:00 午间休市）/`closed`；**降频只看 `is_trading_time()`**，`describe_session()` 仅用于展示 |
| 轮间隔 | 每轮结束后的休眠：交易时段 `MONITOR_ROUND_INTERVAL`（默认 0 = 立刻下一轮），非交易时段 `MONITOR_OFF_HOURS_ROUND_INTERVAL`（默认 1800s） |
| 非交易时段 | **照常采集**（2026-10-23 起）：行情 / K 线 / 指标 / 告警判定全部照跑，只是每只标的节流更长、轮间隔更长。见 [变更](../changes/2026-10-23-offhours-collection.md) |
| 节流 sleep | `get_stock_data` 内每次调用前随机等待：交易时段 `FETCH_MIN_DELAY~FETCH_MAX_DELAY`（默认 30~300s），非交易时段 `MONITOR_OFF_HOURS_FETCH_MIN_DELAY~MAX`（默认 60~300s），规避雪球限流 |
| 退避期休眠上限 | `MONITOR_OFF_HOURS_SLEEP`（默认 300s）：仅用于雪球 Token 失效 / 限流退避期的 `min(剩余退避, 本值)` |
| 可中断休眠 | `_sleep()` 基于 `threading.Event.wait()`，收到停止信号立即返回，避免 `time.sleep` 卡住停机 |
| 并发池 | `ThreadPoolExecutor(max_workers=MONITOR_MAX_WORKERS)`，默认 6 |
| 告警冷却 | `utils/alarm_throttle.AlarmThrottle`，详见 [003](./003-alarm-thresholds.md) |
| Token | `config.XueqiuToken.TOKEN`（环境变量 `XUEQIU_TOKEN`），经 `pysnowball.set_token()` 注入 |

## 3. 当前有效行为

### 3.1 启动与停止

- `app.py:start_monitoring_on_startup()` 在 `__main__` 中调用：
  1. `MONITOR_ENABLED=0` → 不启动；
  2. `DEBUG=1` 且 `WERKZEUG_RUN_MAIN != 'true'`（reloader 父进程）→ 不启动，**只在子进程启动监控**；
  3. 其余情况 → `monitor.start_monitoring()`。
- `start_monitoring()` 幂等：`_start_lock` 加锁并检查线程存活，重复调用返回 `False` 并记 warning，**全进程只会有一个监控线程**。
- `stop_monitoring()` 设置 `_stop_event` 后 `join(timeout=10)`；所有休眠均为可中断休眠。
- `get_status()` 返回运行状态、线程存活、当前时段、冷却秒数、收件人数、手动刷新进度与统计计数，供排障与页面展示。


### 3.2 主循环 `monitor_loop`

1. 每日汇总邮件（默认 08:30，通常在非交易时段）→ 与时段无关，先处理；
2. 雪球退避期内（`xueqiu_backoff_remaining > 0`）→ **整轮跳过**，休眠后继续；
3. `StockMaster.get_active_stocks(limit=MONITOR_MAX_STOCKS)` 取活跃订单——**刻意不加归属过滤**，
   监控必须照看所有人的订单；取完之后立刻 `_reset_round_cache()` 清空本轮共享缓存；
4. 无活跃订单 → `_sleep(MONITOR_ERROR_SLEEP)`；
5. 有 → `ThreadPoolExecutor` 并发跑 `check_and_alert`（**交易 / 非交易时段同一条链路**）；
6. 轮结束后按当前时段休眠：交易时段 `MONITOR_ROUND_INTERVAL`（默认 0）、
   非交易时段 `MONITOR_OFF_HOURS_ROUND_INTERVAL`（默认 1800s）；
7. 任何异常 → `logger.exception` + 退避后继续，循环不中断。

> **2026-10-23 起非交易时段不再停采**：收盘后 / 午休 / 盘前 / 周末照常跑整轮，
> 只是把"每只标的的节流"和"轮间隔"两个旋钮调大（单只标的再次采集周期约 46 min → 约 80 min）。
> 目的：收盘价、当日 K 线、基准日线能补上，告警判定不停摆。

### 3.3 单次检查 `check_and_alert`

1. `get_stock_data`：随机节流 → `ball.set_token(token)` → `ball.quote_detail(stock_code)`，返回 current / pe_ttm / pb / dividend_yield / name；无 Token 或格式异常返回 `None` 并记日志。
   **经 `_shared_result('quote', stock_code, ...)` 取数**（2026-10-26）：本轮同一 `stock_code` 只真正请求一次，
   后到的同代码订单等待并复用结果。理由见 [ADR-005](../decisions/005-per-user-stock-code-uniqueness.md)——
   同一代码可被多个用户各持有一条，不去重就会对雪球打出 N 次请求。
2. 回写 `StockMaster.update(current_pe, current_pb)` 与 `stock_warehouse.current_price`（**每个订单各写各的**，不共享）。
3. 拉 K 线并落库（`days=40`），失败只记日志不影响告警，见 [005](./005-kline-signal.md)。
   与行情同理，走 `_shared_result('kline', stock_code, ...)` 本轮只拉一次。
4. 依次判定：卖出 → 建仓三档 → PE 三档 → PB 三档（判定细节见 [003](./003-alarm-thresholds.md)）。
5. 告警统一走 `_emit_alarm`：冷却检查 → `StockAlarm.create` → 发邮件。
   **邮件按订单归属人发**：`owner_user_id` 取该订单的 `user_id`，决定收件人与通知开关（见 [003](./003-alarm-thresholds.md) §3.6）。
6. 各步骤独立 `try/except`，异常只累加 `stats['errors']` 并记日志，不向上抛。

### 3.4 邮件发送 `utils/mail_sender.py`

- `smtplib.SMTP_SSL`（或 `SMTP` + `starttls`），`timeout=MAIL_TIMEOUT`（默认 10s），避免 SMTP 卡死拖住监控线程。
- 发送前校验：收件人为空或全部非法 → `logger.error` 并返回 `False`；`MAIL_USERNAME`/`MAIL_PASSWORD` 缺失 → 返回 `False`。
- 收件人取 `config.get_alarm_recipients()`（读 `ALARM_RECIPIENTS`，按 `,`/`;` 切分并过滤非法邮箱）。
- `ALARM_MAIL_ENABLED=0` 时跳过发信（仍会写告警记录）。
- 异常 `logger.exception` 并返回 `False`；`send_alarm_mail` 死代码已移除。

### 3.5 雪球接口错误处理与退避（D-13）

原则：**外部服务返回的业务错误只提示，程序自身的 bug 才打堆栈。**

`utils/snowball_errors.parse_xueqiu_error()` 从异常中解析 `error_code` / `error_description`
（`pysnowball` 抛的是 `Exception(response.content)` 的 bytes repr，中文为 `\xNN` 转义，需正则 + `unicode_escape` 兜底）。

| 类别 | 错误码 | 处理 |
| --- | --- | --- |
| Token 失效 / 未授权 | 400016、400027、10001 | 一条 `WARNING` 提示 + 进入退避 `XUEQIU_BACKOFF_SECONDS`（默认 600s） |
| 限流 | 400017 | 同上 |
| 标的不存在 | 400015 | `WARNING`（按错误码节流 `XUEQIU_NOTICE_INTERVAL`），不退避 |
| 其他业务码 | — | `WARNING` 提示，不退避 |
| 无法识别（网络/解析等） | — | `logger.exception` 保留堆栈 |

退避期内：`get_stock_data` 与 `_sync_kline` 直接返回，`monitor_loop` 整轮跳过。
未配置 `XUEQIU_TOKEN` 时按间隔节流提示一次，不打 ERROR。

### 3.6 优雅退出（Ctrl+C / SIGTERM）

问题根因：`ThreadPoolExecutor` 工作线程是**非 daemon 线程**，解释器退出时
`concurrent.futures.thread._python_exit` 会 join 它们；监控任务最长休眠 300 秒，
于是 `KeyboardInterrupt` 处理完了，进程却卡在 join 上——表现为"按 Ctrl+C 没反应"。

| 组成 | 位置 | 说明 |
| --- | --- | --- |
| 信号处理器 | `utils/shutdown.GracefulShutdown` | 监听 `SIGINT` / `SIGTERM`；首次触发执行停止回调 + 启看门狗 + `raise KeyboardInterrupt`；再次触发立即强退 |
| 看门狗 | 同上 | `SHUTDOWN_TIMEOUT`（默认 5s）内未退出则 `os._exit(130)` |
| 停止回调 | `monitor.stop_monitoring` | 置位 `_stop_event`（打断所有 `Event.wait` 休眠）+ 取消排队任务 |
| 可中断休眠 | `_sleep()` | 基于 `threading.Event.wait()`，收到停止信号立即返回 |
| socket 兜底超时 | `SOCKET_TIMEOUT`（默认 30s） | `pysnowball` 未传 `timeout`，避免线程永久挂起 |
| 任务侧检查 | `check_and_alert` / `_process_stocks` | `_stop_event` 已置位时不再发起请求、不再派发任务 |

- **Windows 的 `SIGBREAK`（Ctrl+Break）刻意不接管**：保留操作系统默认 `TerminateProcess`
  作为最后的强制杀进程通道。
- 线程池改为常驻（`_get_executor()`），`stop_monitoring()` 调用
  `shutdown_executor(wait=False, cancel_futures=True)`。`cancel_futures` 只丢弃**排队中**
  的任务，运行中任务靠 `_stop_event` 与 `SOCKET_TIMEOUT` 快速返回，最终由看门狗兜底。

### 3.7 配置与可观测性

- 全部配置来自环境变量（`.env` 或进程环境）；`config.validate_runtime_settings(strict=True)` 在生产启动时校验必填项，缺失即 `RuntimeError` 拒绝启动。
- `utils/logging_config.setup_logging()`：控制台 + `logs/stock_app.log`（5MB × 10 轮转），**始终挂载文件 handler**（此前仅在非 debug 时挂载，等于从不落盘）。
- `monitor.stats` 累计 `rounds / checks / alarms / errors / last_round_at`。
- `monitor.get_status()` 额外返回 `xueqiu_backoff_remaining` / `xueqiu_backoff_reason`。

## 4. 验收条件

1. 应用启动后 `monitor.is_running == True`，且全进程只有 **1 个** `stock-monitor` 线程（重复调用 `start_monitoring()` 返回 `False`）。
2. 使用 reloader 调试时，监控只在子进程启动，父进程不启动。
3. **非交易时段照常采集**（2026-10-23 起）：收盘后 / 午休 / 周末仍跑完整一轮，只是节流与轮间隔更长；
   可通过 `get_status()['in_trading_hours']` 观察当前时段，`stats['rounds']` 持续增长即为在采。
4. **雪球 Token 失效时只产生一条 WARNING 提示，不产生 ERROR 堆栈，且退避期内不再请求雪球**。
5. 活跃订单的价格、`current_pe`、`current_pb` 被持续刷新（**交易时段与非交易时段都刷**，后者更慢）。
6. 达到阈值时产生 `stock_alarm` 记录并调用 `send_mail`；`ALARM_RECIPIENTS` 为空时明确跳过且不产生发信失败。
7. 单支股票取数异常不影响整轮循环，其他股票继续处理。
8. 停止监控后线程退出，不再产生新的数据库写入。
9. **按 Ctrl+C 后控制台立即出现"正在停止监控服务…"，并在 `SHUTDOWN_TIMEOUT`（默认 5s）内退出**；再按一次立即退出。
10. `docker stop`（SIGTERM）能在超时前优雅退出，不需要等 SIGKILL。

## 5. 已知限制

- **页面只读状态，不能启停**：侧栏底部与顶栏徽标已展示 `get_status()` 的实时状态（见 [008](../current/008-frontend-ui.md)），但**页面上不能启停监控**（需另立变更）。
- **告警冷却状态在进程内存**：多进程部署（如 gunicorn 多 worker）时各进程独立计数，需要多进程时应把 `last_fired` 落到数据库或 Redis。
- **交易日历为"周一至周五"近似**：未接入法定节假日与临时休市安排，节假日仍会按交易时段轮询。
- **Token 更新后需重启进程**才会立即恢复（否则等 `XUEQIU_BACKOFF_SECONDS` 退避自然结束）。
- **Token 失效不会主动通知管理员**（仅本地日志提示）；如需邮件/钉钉告警请另立变更。
- 雪球错误码清单来自已知样本，未公开完整码表；未知业务码按"提示 + 不退避"处理。
- **本轮结果共享的边界**（2026-10-26）：同一 `stock_code` 本轮只取一次行情与 K 线，
  但**写库仍然是每个订单各写各的**，所以同一只票被 N 人持有仍会有 N 份 `stock_kline`。
  **失败不缓存**，但"谁先去取"的那次失败会让同代码的其他订单本轮也拿不到数据（单点失败放大一轮）；
  考虑到同一代码的请求要么都成功要么都失败，判定可接受。
- **等待者会占用线程池槽位**：同代码的第二个任务是阻塞等待而非退回，期间占住一个 worker。
  若将来同一代码被几十人持有，需要重新评估 `MONITOR_MAX_WORKERS`。
- **每日汇总邮件仍是全局口径**：不按归属人拆分，见 [003](./003-alarm-thresholds.md) §5。
- `logs/` 目录需要进程有写权限；不可写时降级为仅控制台输出并记 warning。
