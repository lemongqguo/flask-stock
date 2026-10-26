# 2026-10-21 优雅退出（Ctrl+C 无法退出）

| 项 | 值 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 缺陷修复（可观测性 / 可用性） |
| 触发 | 控制台按 Ctrl+C 无反应，必须强制关闭终端才能结束进程 |
| 关联规格 | [004 后台监控服务](../current/004-monitor-service.md) |
| 验证 | `python tests/run_all.py` → 165 用例全部通过（新增 14 个） |

---

## 1. 根因

按下 Ctrl+C 后 `KeyboardInterrupt` **其实已经抛出了**，进程却迟迟不退出。真正卡住的是**解释器退出阶段**：

1. `concurrent.futures.ThreadPoolExecutor._adjust_thread_count()` 创建工作线程时**没有设 `daemon=True`**（已在本机 Python 3.11.3 源码中确认）；
2. CPython 通过 `concurrent.futures.thread._python_exit`（由 `threading._register_atexit` 注册）在解释器退出时 **join 这些非 daemon 线程**；
3. 监控任务的节流休眠最长 300 秒（`FETCH_MAX_DELAY`），且 `pysnowball` 底层 `requests` **未传 `timeout`**，网络异常时可永久挂起。

于是主线程早就收尾完毕，进程却卡在 `join()` 上 —— 表现为"按 Ctrl+C 没反应"。

> 现场验证（本机）：`ThreadPoolExecutor` 提交两个 60 秒任务后，
> `concurrent.futures.thread._threads_queues` 中有 2 个线程待 join。

## 2. 变更内容

### 2.1 新增 `utils/shutdown.py`

`GracefulShutdown` + `install_graceful_shutdown(timeout, callbacks)`：

- 监听 `SIGINT`（Ctrl+C）与 `SIGTERM`（`docker stop` / `kill`）；
- 首次触发：记 warning 提示 → 依次执行停止回调 → 启动看门狗 → `raise KeyboardInterrupt` 回到主线程走正常收尾；
- 看门狗：`SHUTDOWN_TIMEOUT`（默认 **5 秒**）内未退出则 `os._exit(130)`，绕过 atexit 与 join；
- 再次触发：立即 `os._exit(130)`；
- 回调异常相互隔离（某个炸了不影响其余回调）；
- `set_socket_default_timeout()`：设置全局 socket 默认超时。

**刻意不接管 Windows 的 `SIGBREAK`（Ctrl+Break）**：它走操作系统默认的 `TerminateProcess`，
是"连优雅退出都失效"时最后的强制杀进程手段；一旦注册 Python 处理器，这个逃生通道就没了。

### 2.2 `models/stock_monitor.py`

- 线程池改为**常驻**（`_get_executor()` 懒创建，不再每轮 `with ThreadPoolExecutor(...)`），
  新增 `shutdown_executor(wait=False, cancel_futures=True)`；
- `stop_monitoring(join_timeout=5)` 先取消排队任务再 join，超时不再阻塞调用方；
- `check_and_alert` / `_process_stocks` 在 `_stop_event` 已置位时直接返回，不再派发新任务；
- `_process_stocks` 捕获 `CancelledError`，线程池关闭后停止派发。

> 注意：`cancel_futures=True` 只丢弃**排队中**的任务，已在跑的任务仍要自己返回。
> 因此真正保证退出的是看门狗，配合下面两件事让运行中任务尽快返回：
> 休眠走 `_stop_event.wait()`（可被立即打断）、网络调用受 `SOCKET_TIMEOUT` 兜底。

### 2.3 `config.py`

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SHUTDOWN_TIMEOUT` | 5.0 | 看门狗超时秒数，超过即 `os._exit` |
| `SOCKET_TIMEOUT` | 30.0 | 全局 socket 默认超时，`0` 表示不启用 |

### 2.4 `app.py`

- 启动时 `set_socket_default_timeout(Config.SOCKET_TIMEOUT)`；
- `install_shutdown_handlers()` 注册 `monitor.stop_monitoring` 为停止回调；
- `app.run()` 外包 `try/except KeyboardInterrupt` + `finally: monitor.stop_monitoring()`。

## 3. 行为变化

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 交易时段按 Ctrl+C | 无反应，最长卡 300 秒 | 立即打印"收到 SIGINT，正在停止监控服务…"，≤5 秒退出（rc=130） |
| 再按一次 Ctrl+C | 无反应 | 立即强制退出 |
| `docker stop`（SIGTERM） | 等 10 秒后被 SIGKILL | 优雅停止，≤5 秒退出 |
| Windows Ctrl+Break | 立即终止 | **不变**（保留为强制杀进程通道） |
| 网络挂起 | 线程可能永久卡住 | 受 `SOCKET_TIMEOUT` 30 秒兜底 |

## 4. 验证

新增 `tests/test_shutdown.py`（14 个用例）：

- 首次信号执行回调并 `raise KeyboardInterrupt`；回调异常被隔离；
- 二次信号调用强制退出；**看门狗超时后强制退出**（Ctrl+C 卡死的兜底）；
- `timeout=0` 不启看门狗；`install/uninstall` 能恢复原处理器；
- `set_socket_default_timeout` 开关；
- 线程池懒创建、`shutdown_executor` 取消排队任务且幂等；
- `stop_monitoring` 释放线程池；停止后 `check_and_alert` / `_process_stocks` 不再派发。

> 测试踩坑记录：`GracefulShutdown(timeout=0.01)` 放进 `setUp` 会让残留看门狗真的
> `os._exit` 掉测试进程（首次跑出 `exit=130`）。默认必须 `timeout=0` 关闭看门狗。

## 5. 遗留

- 运行中任务不会被动中断（Python 无法安全 kill 线程），因此极端情况下仍依赖看门狗强退。
- `os._exit` 会跳过 `atexit` 与连接池优雅关闭；DB 连接由操作系统回收，生产若需更干净的收尾可另立变更。
- `SOCKET_TIMEOUT` 同时作用于数据库连接（30 秒），若后续有慢查询需调大或改为仅对 HTTP 生效。
