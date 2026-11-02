# 2026-10-27-gunicorn-deployment：gunicorn 部署适配（单进程 + 日志打到终端）

**状态**：已交付　|　**提出日期**：2026-10-27　|　**负责人**：
**受影响规格**：[004 后台监控服务](../current/004-monitor-service.md)

---

## 1. 问题与动机

用 `gunicorn app:app` 起服务后，终端里除了 gunicorn 自己的 `Booting worker`，**几乎看不到应用日志**，
看起来像"服务起来了但没在干活"。排查结论不是日志被吞，而是**启动路径断了一半**：

1. gunicorn 只做 `import app`，`app.py` 的 `__main__` 块**永不执行** →
   `start_monitoring_on_startup()`、`install_shutdown_handlers()`、`validate_runtime_settings(strict=True)` 全被跳过。
   而项目里几乎所有"持续输出"的日志都来自监控线程，于是除了启动那一行，之后确实一行都没有；
   fail-fast 与优雅退出也一并失效。
2. `LOG_LEVEL` 环境变量写在 Dockerfile 里，但 **`config.py` / `app.py` 都不解析它**，
   改这个变量没有任何效果；级别固定 INFO，而监控的日常日志大多是 `DEBUG`。
3. `log_dir='logs'` 是**相对路径**，落点是进程当前工作目录而不是项目根：在 `/` 下敲 gunicorn 就往 `/logs/` 写，
   权限不足时只打一条 warning 就静默降级。
4. `StreamHandler()` 无参 = `sys.stderr`，且 handler 在 import 时就把流对象固定下来；
   gunicorn `--capture-output` 是在 worker 起来**之后**才替换 `sys.stdout`，两边对不上。
5. Dockerfile 的 `CMD` 把 stdout/stderr 重定向到 `/app/logs/stdout/flask-stock.stdout`，
   `docker logs` 看不到任何东西（而该目录在镜像里并不存在）。

## 2. 变更类型

- [ ] **缺陷修复**：实现没有满足原有约定 → 依据现有规格补回归测试后修复
- [x] **行为变更**：产品需要调整原有行为 → 先改这里的约定，再改测试期望
- [x] **技术重构**：行为不变，内部结构变化 → 说明为什么安全
- [ ] **新增能力**：新增场景 → 需新建或扩展 `../current/` 规格

> 重构部分（`__main__` 副作用抽成 `prepare_runtime()`）：对 `python app.py` 这条路径 **行为与顺序完全一致**，
> 只是把相同的调用搬进函数，安全性来自"调用序列未变"。

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 生产启动方式 | `python app.py`（自带 Werkzeug 开发服务器） | `gunicorn -c gunicorn.conf.py app:app`（`start.sh` 默认走这条） |
| 进程模型 | 单进程，无并发池 | **强制单进程** `workers=1` + `worker_class='gthread'`（`threads` 默认 8） |
| 监控线程启动点 | `app.py` 的 `__main__` 块 | `app.prepare_runtime()`，由 `post_fork` 钩子调用；两条启动路径共用 |
| 退出处理 | `__main__` 里注册 SIGINT/SIGTERM | gunicorn 下**不注册**（`install_signals=False`），改由 `worker_exit` 钩子 `monitor.stop_monitoring()` |
| 日志级别 | `Config.DEBUG` 决定，忽略环境变量 | `'DEBUG' if Config.DEBUG else None` → 交给 `LOG_LEVEL` 环境变量（默认 INFO） |
| 日志目录 | 相对路径 `logs/`（跟随 cwd） | 项目根目录下 `logs/`，可用 `LOG_DIR` 覆盖 |
| 控制台输出流 | `sys.stderr`（启动时固定） | 默认 `sys.stdout`，且每次写入重新解析（`LOG_STREAM=stderr` 可切回） |
| 容器日志出口 | 重定向到 `logs/stdout/flask-stock.stdout` | 直接进容器 stdout/stderr，`docker logs` 可见 |

## 4. 影响面

- 涉及模块/文件：`app.py`（新增 `prepare_runtime()`）、`utils/logging_config.py`（环境变量 + 绝对路径 + 动态流）、
  新增 `gunicorn.conf.py`、`start.sh`、`Dockerfile`、`spec/PROJECT_WIKI.md`、`spec/README.md`、`PROGRESS.md`、004 §3.7 / §5
- **同批配套调整（同一环境不一致导致，一并修掉）**：
  - 新增 `.gitignore`（此前缺失，虚拟环境 `stockvenv/`、`.env`、`logs/` 会被一并提交）；
  - `requirements.txt` 的 numpy / pandas 由 1.24.3 / 2.0.3 对齐到实际安装的 2.5.4 / 3.1.0——旧组合是 Python 3.9 时代的锁版本，
    在 3.12 上没有预编译 wheel 会退回源码编译失败；
  - `Dockerfile` 基础镜像随之由 `python:3.9-slim` 升到 `python:3.12-slim`；
  - `requirements-dev.txt` 尾部几行 `-w 4…` 缺少 `#` 注释符，`pip install -r` 会把它当参数解析，已改为注释并更正启动方式。
- 涉及数据表 / 是否需要迁移：**无**
- 是否影响既有数据：**否**
- 是否需要新增/修改配置：新增可选环境变量 `LOG_LEVEL` / `LOG_DIR` / `LOG_TO_FILE` / `LOG_STREAM` /
  `BIND` / `USE_GUNICORN` / `GUNICORN_THREADS` / `GUNICORN_TIMEOUT` / `GUNICORN_KEEPALIVE` / `GUNICORN_GRACEFUL_TIMEOUT`

## 5. 实施要点

1. **`prepare_runtime(strict=False, install_signals=True)`**：把 `__main__` 里的三段副作用
   （配置校验 → socket 默认超时 → 退出处理器 → 起监控）收成一个函数；gunicorn 在 `post_fork` 里以
   `strict=True, install_signals=False` 调用。
2. **信号处理器不能在 gunicorn 下注册**：gunicorn 自己接管 `SIGINT`/`SIGTERM` 实现 graceful timeout，
   重复注册会破坏 `_previous_handlers` 语义（且我们的处理器会 `raise KeyboardInterrupt`，在 worker 里行为不可控）。
3. **`preload_app = False`**：master 里 import `app` 会顺势建好 MySQL 连接池，fork 后父子共享连接 socket；
   单 worker 下预加载也省不了内存，因此统一由 worker 自加载。监控线程同理，只能放在 `post_fork`（worker 进程内）。
4. **`threads` 必须配 `gthread`**：sync worker 会忽略 `threads` 参数，不显式指定 `worker_class` 等于没加并发。
5. **`timeout` 提到 120s**：AI 分析最坏要等到 `AI_TIMEOUT`（默认 60s），gunicorn 默认 30s 会把正常请求判为卡死并杀 worker。
6. **日志三重保障**：`accesslog='-'` / `errorlog='-'`（到终端）+ `capture_output=True`（收 print 与第三方库输出）+
   应用侧 `StreamHandler(_StreamProxy())`（动态解析 stdout，兼容 capture 的重定向）。文件 handler 仍保留落盘。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 应用能被 gunicorn 正常加载启动 | `stockvenv/bin/gunicorn -c gunicorn.conf.py app:app`（真实 MySQL） | ✅ 通过：`Listening at 0.0.0.0:5000` + `Using worker: gthread` + `Booting worker` |
| 启动时副作用（`prepare_runtime`）确实执行 | 观察启动日志 | ✅ 通过：出现「数据库结构检查完成」「订单监控服务已启动」（`MONITOR_ENABLED=0` 时对应"已禁用"日志） |
| 监控线程在 gunicorn 下起来 | `MONITOR_ENABLED=1` 启动 | ✅ 通过：「监控循环启动 pid=…」「股票监控已启动 thread=stock-monitor」 |
| 配置自检 fail-fast | 同上（`prepare_runtime(strict=True)`） | ✅ 未缺失必填项即正常启动；缺失路径未验证 |
| 日志打到终端 | 观察 stdout / 文件 | ✅ 通过：访问日志（`"GET / HTTP/1.1" 302`）、gunicorn INFO、应用 INFO/DEBUG 均出现在终端；同时落盘 `logs/stock_app.log` |
| `LOG_LEVEL` 生效 | `LOG_LEVEL=DEBUG` / `WARNING` 分别启动 | ✅ 通过：根 logger 级别随之变化 |
| 日志目录不再跟 cwd 漂移 | 在 `/tmp` 下调用 `setup_logging()` | ✅ 通过：落到 `/opt/src/flask-stock/logs/stock_app.log` |
| worker 退出时停监控 | `timeout` 发 SIGTERM | ✅ 通过：`Worker exiting` 后出现「股票监控已停止」 |
| HTTP 请求处理 | `curl http://127.0.0.1:5000/` | ✅ 通过：302 到登录页，访问日志记录正常 |

- 实际验证到的范围：本机 `stockvenv`（Python 3.12 / Flask 2.3.3 / gunicorn 26.2.0）+ 真实 MySQL 的完整启动、
  请求处理、日志输出、退出流程，均已跑通。
- **未验证**的范围：长时间运行一整个交易日的监控行为、邮件送达、`docker build` 后的容器启动
  （本机未装 Docker）、`docker stop` 的优雅退出耗时、页面 UI 行为。**上线前建议在目标镜像里再跑一次。**

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/004-monitor-service.md` 已更新（§3.7 配置与可观测性、§5 已知限制补充单进程约束）
- [x] `../PROGRESS.md` 模块表「日志」行已更新
- [x] `../README.md` 已知限制已同步（新增第 14 条：必须单进程部署）
- [ ] 涉及重要取舍时已补 [`../decisions/`](../decisions/) 决策记录（暂不需要：取舍写在本文 §5）
- [ ] 本目录已移入 `../archive/changes/`（待真实环境验证后再归档）
