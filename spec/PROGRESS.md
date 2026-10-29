# 开发进度台账（Progress）

> **本文件是规格与进度的同步枢纽。** 每一条进度/待办都必须指向 `spec/current/NNN-*.md` 规格编号；
> 每一份 `current/` 规格被修改，必须回到本文件更新对应条目的状态。两者不一致视为维护事故。
> 更新时机与格式要求见 [rules/spec-maintenance.md](./rules/spec-maintenance.md)。

**最后更新**：2026-10-26　|　**当前基线**：`v1.5.0`

---

## 0. 状态总览

| 指标 | 数值 |
| --- | --- |
| 功能规格总数 | 8（**8 已实现**） |
| 待归档变更 | 9（006 指标监控：待人工确认 UI 与真实雪球采集周期；**007 AI 页改版一**；**订单列表 AI 快捷入口**；**007 AI 页改版二（搜索式工作台）**：均待人工确认观感；**AI_MODEL 支持清单**：待人工确认下拉；**006 指标告警改四项 AND 组合触发**：待真实环境验证；**006 指标页 AI 快捷入口**、**006 指标页分页 + AI 入口换配色**：待人工确认观感；**004 收盘后照常采集**：待观察真实收盘后日志） |
| 已闭环缺陷 | 15（D-01 ~ D-15） |
| 未闭环待办 | 9（T-01 ~ T-09，P1: 3 / P2: 6）；T-12 已于 2026-10-22 验证闭环 |
| 自动化测试 | 634 个用例（标准库 `unittest`）。运行方式：`./stockvenv/bin/python tests/run_all.py`（Windows：`stockvenv\Scripts\python.exe`）；**必须用项目自带的虚拟环境**（Python 3.12 + numpy 2.5.4 + pandas 3.1.0，已与 `requirements.txt` 对齐）。本机 `.env` 的 `FLASK_DEBUG=1` 会让 `test_no_debug_by_default` 失败（`FLASK_DEBUG=0` 时全通过），非代码缺陷 |

> **归档规则**：变更记录置为「已合入」后移入 `archive/changes/`。007 首次交付已于 2026-10-22 完成真实模型调用验证并归档；
> 006（待真实雪球周期）与 007 改版（待人工确认三栏观感）暂留 `changes/`。

**整体阶段**：M1~M4 的主要缺陷已闭环，进入"补长尾 + 建 CI"阶段。
**本轮进度（2026-10-26）**：完成**多用户数据隔离**——订单归属（`stock_master.user_id`）、
角色（`users.role`）、全站可见性作用域、**越权写操作拦截**、按人唯一（[ADR-005](./decisions/005-per-user-stock-code-uniqueness.md)）、
监控本轮结果共享、告警邮件按归属人发送。真实库迁移已落地（92 条订单回填、唯一键与外键就位），
新增 48 个用例（累计 626 全通过）。**待人工确认**：两种角色视角的页面观感、真实邮件送达、真实雪球去重。

---

## 1. 模块进度表

状态定义：`已实现` = 已上线且行为与规格一致；`部分实现` = 能用但存在已知偏差；`未开始` = 无代码。

| 模块 | 状态 | 关联规格 | 实现位置 | 备注 |
| --- | --- | --- | --- | --- |
| 用户注册/登录/登出 | 已实现 | [001](./current/001-user-auth.md) | `views/auth.py`、`models/user.py` | 服务端强制密码 ≥ 6 位；登录写入 `session['role']`；仍无 CSRF（T-06） |
| 个人资料 / 修改密码 | 已实现 | [001](./current/001-user-auth.md) | `views/auth.py`、`models/user.py`、`models/account_settings.py` | 已下沉为 `User.update_password()`；资料可写（手机号 / 默认基准指数 / 通知偏好） |
| 登录拦截（全局 + 装饰器） | 已实现 | [001](./current/001-user-auth.md) | `app.py`、`utils/decorators.py` | 双重校验；死装饰器已删除 |
| 订单列表（分页/搜索） | 已实现 | [002](./current/002-stock-order.md) | `views/stock_orders.py`、`models/base.py` | 裸 `WHERE` 隐患已修（D-07） |
| 订单创建 / 编辑 / 删除 | 已实现 | [002](./current/002-stock-order.md) | `views/stock_orders.py` | 删除依赖外键 CASCADE |
| 告警阈值设置（价格/PE/PB） | 已实现 | [003](./current/003-alarm-thresholds.md) | `views/stock_orders.py`、`utils/alarm_rules.py` | 判定规则收敛为纯函数 |
| 告警冷却 / 去重 | 已实现 | [003](./current/003-alarm-thresholds.md) | `utils/alarm_throttle.py` | 默认 4h；条件消失即撤销 |
| 告警历史查询 | 已实现 | [003](./current/003-alarm-thresholds.md) | `views/stock_orders.py`、`database.py` | 已补 `alarm_time` 索引（D-09）；**2026-10-26 起按订单归属过滤** |
| **多用户数据隔离（订单归属 / 可见性 / 越权拦截）** | 已实现（2026-10-26 新增） | [001](./current/001-user-auth.md)、[002](./current/002-stock-order.md) | `utils/access.py`（唯一判定入口）、`database.py`（迁移）、`views/stock_orders.py`、`views/ai_analysis.py`、`models/stock_master.py`、`models/stock_alarm.py`、`models/stock_monitor.py` | `stock_master.user_id` + `users.role`；唯一键改 `UNIQUE(user_id, stock_code)`；监控本轮结果按代码共享；告警邮件按归属人发；[ADR-005](./decisions/005-per-user-stock-code-uniqueness.md) |
| **管理员角色与谋求方式** | 已实现（2026-10-26 新增） | [001](./current/001-user-auth.md) | `models/user.py`、`database.py`、`app.py` | 首个注册用户自动 admin；`flask set-admin <username>`；角色写 session，**变更后需重新登录** |
| 后台监控线程 | 已实现 | [004](./current/004-monitor-service.md) | `models/stock_monitor.py`、`utils/trading_time.py` | 线程唯一、交易时段降频、可中断休眠；无运行时控制面（T-05） |
| 行情/PE/PB 回写 | 已实现 | [004](./current/004-monitor-service.md) | `models/stock_monitor.py` | 分步 try/except + 错误计数 |
| 邮件告警通知 | 已实现 | [004](./current/004-monitor-service.md) | `utils/mail_sender.py`、`config.py` | 收件人前置校验 + 超时 + 开关 |
| 配置与凭据管理 | 已实现 | [004](./current/004-monitor-service.md) | `config.py`、`.env.example` | 环境变量 + 启动自检 fail-fast |
| 日志 | 已实现 | [004](./current/004-monitor-service.md) | `utils/logging_config.py` | 控制台 + 轮转文件（始终落盘）；**2026-10-27 起**支持 `LOG_LEVEL` / `LOG_DIR` / `LOG_TO_FILE` / `LOG_STREAM`，目录改项目根绝对路径，控制台动态解析 stdout（适配 gunicorn `--capture-output`） |
| gunicorn 部署适配 | 已实现（2026-10-27 新增） | [004](./current/004-monitor-service.md) | `gunicorn.conf.py`、`app.prepare_runtime()`、`start.sh`、`Dockerfile` | 强制 `workers=1` + gthread；`post_fork` 起监控、`worker_exit` 停监控；日志打到终端；[变更](./changes/2026-10-27-gunicorn-deployment.md) |
| K 线采集与落库 | 已实现 | [005](./current/005-kline-signal.md) | `models/stock_kline.py` | 按 `trade_date` 存在则更新 |
| MA 均线计算与金叉/死叉 | 已实现 | [005](./current/005-kline-signal.md) | `models/stock_kline.py` | NaN 兜底；MA10 仅展示 |
| 告警类型字段（类型/子类型/档位/通知状态） | 已实现 | [003](./current/003-alarm-thresholds.md) | `database.py`、`models/stock_alarm.py`、`models/base.py`、`utils/alarm_rules.py` | 存量回填 1590 条，零 unknown；[变更](./changes/2026-10-21-alarm-type-fields.md) |
| 指标监控（52 周 / 相对强弱） | 已实现（批次一 + 二 + **组合触发**） | [006](./current/006-stock-indicator.md) | `models/stock_indicator.py`、`utils/indicator_rules.py`（`is_combo_hit`）、`models/stock_monitor.py`、`templates/indicator_list.html`、`templates/recent_alarms.html` | 三表 + 判定 + 采集 + 24h 冷却告警 + `/indicator` 页面 + 告警设置「指标告警」页签；**2026-10-23 起四条 AND 才有告警**（单条 `combo`，一条邮件列四项），页面只显示组合结论；[批次一 / 二变更](./changes/2026-10-21-stock-indicator.md)、[组合触发变更](./changes/2026-10-23-indicator-combo.md)、[ADR-004](./decisions/004-indicator-combo-semantics.md) |
| AI 个股分析 | 已实现（含 10-22 两轮页面改版） | [007](./current/007-ai-analysis.md) | `views/ai_analysis.py`、`utils/ai_client.py`、`utils/ai_prompt.py`、`models/stock_ai.py`、`templates/ai_analysis.html`、`static/js/theme.js` | **搜索式工作台**（hero 搜索框 + 标的条 / 报告 / 参数 + 快照 + 历史）+ 服务端标的搜索 `/stock/ai/api/search` + 分析 / 追问 / 连通测试；**不再铺全量标的列表**；模型选择与 5 个分析维度可配可落库；密钥仅走环境变量；[首次变更](./archive/changes/2026-10-21-ai-analysis.md) / [改版一](./changes/2026-10-22-ai-analysis-ui.md) / [改版二](./changes/2026-10-22-ai-analysis-workspace.md) |
| 前端 UI（双主题 / 去 Bootstrap） | 已实现 | [008](./current/008-frontend-ui.md) | `templates/`、`static/` | 指标监控 / AI 分析页随 006/007；侧栏已按设计稿分「交易 / 监控 / 系统」三组，指标监控带近 24h 指标告警徽标；[底座变更](./changes/2026-10-21-frontend-redesign.md)、[侧栏分组](./archive/changes/2026-10-23-sidebar-groups.md) |
| K 线数据 API + 前端图表 | 已实现 | [005](./current/005-kline-signal.md) | `views/stock_orders.py`、`templates/stock_order_form.html` | Chart.js 已锁定 4.4.1 |

---

## 2. 缺陷 / 待办台账

优先级：**P0** 影响正确性或安全，须先修；**P1** 影响可靠性/可维护性；**P2** 优化项。
状态：`待办` → `进行中` → `已验证` → `已合入`（合入后从本表移除，转入变更记录归档）。

| ID | 优先级 | 问题 | 关联规格 | 状态 |
| --- | --- | --- | --- | --- |
| D-01 | P0 | `config.py` 明文硬编码 DB 密码 / SECRET_KEY / SMTP 授权码 / 雪球 Token，且已入库 | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-02 | P0 | `EMAIL_RECEIVED = [""]` 为空，4 处 `send_mail` 实际必然失败 | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-03 | P0 | 告警无去重/冷却，条件持续满足时每轮重复写记录并重复发邮件 | [003](./current/003-alarm-thresholds.md) | ✅ 已合入 |
| D-04 | P1 | 无交易时段判断，非交易时间仍按 30~300s 随机 sleep 轮询 | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-05 | P1 | 生产仍 `debug=True`；reloader 下可能重复启动多个监控线程 | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-06 | P1 | 无自动化测试、无 CI | 全局 | 🟡 部分合入（测试已建，CI 见 T-01） |
| D-07 | P1 | `models/base.py` 搜索字段缺失时拼出裸 `WHERE` 导致 SQL 错误；存在三元表达式当语句的无效写法 | [002](./current/002-stock-order.md) | ✅ 已合入 |
| D-08 | P1 | 无 `.gitignore`，`stockenv/`、`logs/` 在仓库内 | 全局 | ✅ 已合入（仓库尚未 `git init`，见 T-03） |
| D-09 | P2 | `stock_alarm.alarm_time` 无索引却频繁 `ORDER BY` | [003](./current/003-alarm-thresholds.md) | ✅ 已合入 |
| D-10 | P2 | 死代码：`utils/decorators.py` 的 `admin_required`/`permission_required`、`mail_sender.send_alarm_mail`、`main.js` 图表占位、分页死变量 | [001](./current/001-user-auth.md) | ✅ 已合入 |
| D-11 | P2 | 多处异常仅 `print` 后被吞（models 目录 25 处 `except Exception`）；日志从不落盘 | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-12 | P2 | `views/auth.py` 使用 Werkzeug 新版已移除的 `url_parse` | [001](./current/001-user-auth.md) | ✅ 已合入 |
| D-13 | P2 | 订单列表「AI 分析」入口在缩窗 / 小屏下重叠甚至名称整块消失：第一列 168px 装不下、flex 拒绝收缩、加 `min-width:0` 后又把名称压到 0 宽。改「十列全定宽 + min-width=定宽之和，宽度不够只滚动」，headless 实测 1440/1180/1024/900 四宽度 | [008](./current/008-frontend-ui.md) | ✅ 已合入 |
| D-13 | P1 | 雪球 Token 失效（`400016`）时每只股票每轮打 ERROR + 堆栈，且仍按节流反复请求 | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-14 | P1 | Ctrl+C 无反应无法退出（非 daemon 线程池被 join，最长卡 300s） | [004](./current/004-monitor-service.md) | ✅ 已合入 |
| D-15 | P2 | 暗色主题下 `<select>` 展开的 option 弹层是白底 + 浅灰字（AI 追问框模型下拉几乎看不清）：原生弹层不吃 CSS 变量，主题块缺 `color-scheme`，option 也没显式配色 | [008](./current/008-frontend-ui.md) | ✅ 已合入 |

### 2.2 未闭环待办（新增于基线之后）

| ID | 优先级 | 问题 | 关联规格 | 状态 |
| --- | --- | --- | --- | --- |
| T-01 | P1 | 无 CI 流水线，测试只能本地手动跑 | 全局 | 待办 |
| T-02 | P1 | 告警冷却状态存于进程内存，多进程部署会失效 | [003](./current/003-alarm-thresholds.md) | 待办 |
| T-03 | P1 | 仓库尚未 `git init`；历史明文凭据需在服务端轮换 | 全局 | 待办 |
| T-04 | P2 | 交易日历为"周一至周五"近似，未接法定节假日 | [004](./current/004-monitor-service.md) | 待办 |
| T-05 | P2 | 监控无运行时控制面（页面启停 / 健康度） | [004](./current/004-monitor-service.md) | 待办 |
| T-06 | P2 | 无 CSRF 防护（Flask-WTF 已引入未启用） | [001](./current/001-user-auth.md) | 待办 |
| T-07 | P2 | 负 PE 会命中 PE 档位，是否过滤待产品决策 | [003](./current/003-alarm-thresholds.md) | 待办 |
| T-08 | P2 | 历史 K 线的 MA5/MA10/MA30 未回填（stock_id=1：147 条仅 36 条有值），K 线图前段无均线 | [005](./current/005-kline-signal.md) | 待办 |
| T-09 | P2 | 告警历史「冷却拦截」数无法统计——被冷却拦截的告警不落库，无数据可算 | [003](./current/003-alarm-thresholds.md) | 待办 |
| T-10 | P1 | **每日汇总邮件仍是全局口径**：汇总所有用户近 24h 告警发到全局收件人，未按归属人拆分。当前 `notify_daily` 默认关闭无影响，**但一旦有人开启即构成跨用户泄露**，须先改造 | [003](./current/003-alarm-thresholds.md)、[004](./current/004-monitor-service.md) | 待办 |
| T-11 | P2 | **管理员列表没有「归属用户」列**：admin 看到全量订单但看不出每行属于谁，用户多了难以分辨 | [002](./current/002-stock-order.md) | 待办 |
| T-14 | P2 | 同一只票被多人持有时，行情 / K 线 / 指标快照按人重复落库；未在真实环境验证监控去重的实际请求量 | [004](./current/004-monitor-service.md) | 待办 |
| T-12 | P1 | AI 分析未在真实凭据下验证 | [007](./current/007-ai-analysis.md) | **已验证**（2026-10-22 真实网关跑通连通 / 分析 / 追问 / 双风格；见变更记录 §8.4） |
| T-13 | P1 | **gunicorn 部署下监控线程不启动**：`import app` 不执行 `__main__`，监控 / 启动自检 / 退出处理器全部跳过；且 `LOG_LEVEL` 无人解析、日志目录是相对路径 | [004](./current/004-monitor-service.md) | **已交付**（2026-10-27：`app.prepare_runtime()` + `gunicorn.conf.py` 单进程 gthread；[变更](./changes/2026-10-27-gunicorn-deployment.md)，待真实环境跑一轮完整交易日后合入） |

> 变更明细见 [2026-10-21 M1 缺陷治理](./changes/2026-10-21-m1-defect-hardening.md)。

---

## 3. 阶段计划（摘要）

完整路线图见 [`plans/roadmap.md`](./plans/roadmap.md)。

| 阶段 | 目标 | 关键项 | 状态 |
| --- | --- | --- | --- |
| M1 治理底座 | 让项目可长期维护 | 建立规格目录与守则、补齐 `.gitignore`、配置外置（D-01/D-08） | 已完成 |
| M2 告警可用 | 让告警真正送达且不刷屏 | D-02 收件人、D-03 告警冷却、D-11 异常上报 | 已完成 |
| M3 稳定性 | 生产可放心运行 | D-04 交易时段、D-05 debug 模式、D-09 索引 | 已完成 |
| M4 质量保障 | 改动有回归保护 | D-06 测试与 CI、D-07 SQL 修复、D-10/D-12 清理 | 代码已完成，CI 待办（T-01） |
| M5 能力扩展 | 新功能 | 运行时控制面、正式交易日历、Webhook/钉钉通知、MACD/KDJ（须各自立项新变更） | 规划中 |

---

## 4. 变更历史（已合入）

| 日期 | 变更 | 关联规格 | 记录 |
| --- | --- | --- | --- |
| 2026-10-20 | 建立 `spec/` 规格目录（current/changes/decisions/plans/archive/rules）与进度台账，完成基线梳理 | 全局 | [ADR-001](./decisions/001-spec-directory-structure.md) |
| 2026-10-21 | M1 缺陷治理：D-01~D-12 闭环，新增 138 个自动化用例、`.gitignore`、`.env.example` | 001~005 | [2026-10-21 M1 缺陷治理](./changes/2026-10-21-m1-defect-hardening.md) |
| 2026-10-21 | 雪球接口错误降级：业务错误只提示不打堆栈 + Token 失效自动退避（D-13），新增 13 个用例 | [004](./current/004-monitor-service.md) | [2026-10-21 雪球接口错误降级](./changes/2026-10-21-xueqiu-error-handling.md) |
| 2026-10-21 | 优雅退出：接管 Ctrl+C/SIGTERM + 看门狗强退 + socket 兜底超时（D-14），新增 14 个用例 | [004](./current/004-monitor-service.md) | [2026-10-21 优雅退出](./changes/2026-10-21-graceful-shutdown.md) |
| 2026-10-21 | 告警表补齐类型字段：`alarm_type` / `alarm_subtype` / `alarm_level` / `notify_status` + 幂等列迁移 + 存量回填 1590 条，新增 24 个用例 | [003](./current/003-alarm-thresholds.md) | [2026-10-21 告警表补齐类型字段](./changes/2026-10-21-alarm-type-fields.md) |
| 2026-10-21 | 前端 UI 改版：移除 Bootstrap/jQuery/FontAwesome，自建设计系统 + 双主题，模板 10→8，登录注册/账户设置合并 | [008](./current/008-frontend-ui.md) | [2026-10-21 前端 UI 改版](./changes/2026-10-21-frontend-redesign.md) |
| 2026-10-21 | 订单列表「状态」列改为内联开关：新增 `POST /stock/toggle_status/<id>`，服务端取反切换监控状态（含开放重定向防护），新增 8 个用例 | [002](./current/002-stock-order.md) | [2026-10-21 订单列表内联切换监控状态](./changes/2026-10-21-order-status-toggle.md) |
| 2026-10-21 | 订单列表新增「52周最低」列（现价与卖出价之间）：`StockKline.get_low_52w_batch()` 批量取近 365 天最低价，新增 7 个用例 | [002](./current/002-stock-order.md) | [2026-10-21 订单列表新增「52周最低」列](./changes/2026-10-21-list-52w-low.md) |
| 2026-10-21 | 侧栏新增折叠控件（「监控」标题右侧 chevron）：折叠后只显示功能图标，`localStorage` 记忆，新增 7 个用例 | [008](./current/008-frontend-ui.md) | [2026-10-21 侧栏导航可折叠](./changes/2026-10-21-sidebar-collapse.md) |
| 2026-10-22 | 修复订单编辑页「实时行情」不准：现价存 `stock_warehouse`（master 无此列），编辑页误用 `stock.current_price` 恒为 0；顺带修 POST 校验失败重渲染会清空 PE/PB 备注，新增 4 个用例 | [002](./current/002-stock-order.md) | [2026-10-21 修复编辑页实时行情现价](./changes/2026-10-21-order-form-current-price.md) |
| 2026-10-22 | 侧栏底部与顶栏接入实时系统状态（监控/交易时段/告警冷却/雪球）：新增 `utils/system_status` 与 `GET /stock/api/system_status`，`describe_session` 增「午间休市」档，新增 17 个用例 | [004](./current/004-monitor-service.md)、[008](./current/008-frontend-ui.md) | [2026-10-21 侧栏与顶栏接入实时系统状态](./changes/2026-10-21-system-status-panels.md) |
| 2026-10-22 | 静态资源加版本号（cache busting）：新增 `static_url()` 按 mtime 拼 `?v=`，三个模板改用之——修复"前端改动不生效/按钮点了没反应"；顺带给刷新行情加变化高亮与「已是最新」文案，新增 6 个用例 | [008](./current/008-frontend-ui.md) | [2026-10-22 静态资源加版本号](./changes/2026-10-22-static-version.md) |
| 2026-10-22 | 表格**所有行**加淡色底：新增 `--row-bg` / `--row-bg-hover`（用户反馈效果不好，**已回退**） | [008](./current/008-frontend-ui.md) | [2026-10-22 表格行淡色底](./changes/2026-10-22-table-row-bg.md) |
| 2026-10-22 | 改为**只给告警行/暂停行**专属背景：多色渐变（左起渐隐、右缘收尾），告警行 4.5s 流动 + 2.6s 呼吸（呼吸走 opacity），暂停行灰蓝渐变 + 淡出；sticky 操作列用等效实色且不跑独立动画，新增 19 个用例 | [002](./current/002-stock-order.md)、[008](./current/008-frontend-ui.md) | [2026-10-22 告警行/暂停行专属背景](./changes/2026-10-22-row-state-bg.md) |
| 2026-10-22 | 列表页新增「刷新行情」按钮（添加订单左边）：`POST /stock/refresh_quotes` **只查库**、只刷**当前页**（不打雪球 API，首版做成后台采集已按用户纠正回退），新增 11 个用例 | [008](./current/008-frontend-ui.md) | [2026-10-22 订单列表新增「刷新行情」按钮](./changes/2026-10-22-refresh-quotes-button.md) |
| 2026-10-22 | 指标监控**批次一（数据侧）**：新增 `stock_indicator` / `stock_indicator_config` / `stock_bench_kline` 三表、`utils/indicator_rules.py` 四条判定（含两道护栏）、`IND_*` 配置、监控接入采集与 24h 冷却告警，新增 76 个用例（累计 365 全部通过） | [006](./current/006-stock-indicator.md) | [2026-10-21 指标监控](./changes/2026-10-21-stock-indicator.md) |
| 2026-10-22 | 指标监控**批次二（页面 / 页签）**：新增 `/stock/indicator` 页面 + 侧栏导航项；告警设置「指标告警」页签由占位改为可按标的覆盖阈值（留空继承全局、非法值不落库、保存回跳该页签），新增 26 个用例（累计 391 全部通过） | [006](./current/006-stock-indicator.md) / [008](./current/008-frontend-ui.md) | [2026-10-21 指标监控](./changes/2026-10-21-stock-indicator.md) |
| 2026-10-22 | **AI 个股分析**：新增 `stock_ai_report` / `stock_ai_config` 两表、`utils/ai_client.py`（OpenAI 兼容 Responses / Chat 双风格、超时、密钥脱敏）、`utils/ai_prompt.py`（上下文组装 + 结构化解析）、`/stock/ai/` 报告页（分析 / 追问 / 参数 / 连通测试）、月度上限拦截，新增 52 个用例（累计 443 全部通过） | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | [2026-10-21 AI 个股分析](./archive/changes/2026-10-21-ai-analysis.md) |
| 2026-10-22 | **订单列表 AI 快捷入口**：每行「标的」列右端加「AI 分析」按钮（复用该列吸收的剩余宽度，**不新增列**），点击直达 `/stock/ai/?stock_id=<id>`；修复缩窗重叠（D-13：订单表 min-width 1260 + 三层 `min-width:0` + 名称省略号）；新增 5 个用例锁死「入口指本行 / 10 列不变 / 入口在标的单元格内 / 列宽够用 / 三层收缩规则」 | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | [2026-10-22 订单列表 AI 快捷入口](./changes/2026-10-22-list-ai-shortcut.md) |
| 2026-10-22 | **AI 页改版**：`/stock/ai/` 改三栏（可搜索标的 / 报告 / 参数 + 快照 + 历史）；新增 `AI_MODELS` 模型下拉（服务端白名单）、5 个分析维度（进提示词并落库）、`stock_ai_config.model/dimensions` 两列；修复追问提示词取错下标导致数据上下文丢失；新增 14 个用例（累计 457 全部通过） | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | [2026-10-22 AI 页改版](./changes/2026-10-22-ai-analysis-ui.md) |
| 2026-10-22 | **AI_MODEL 支持逗号分隔清单**：用户把 5 个模型填进 `AI_MODEL`，旧实现把整串当一个 ID（下拉只有 1 项，且整串会被发给网关必失败）。`AI_MODEL` 现在也按 `,` / `;` 拆分（第一项 = 默认模型），新增 `default_model()` 统一"页面显示 / 真实下发 / `effective()`"三个取值口；库里保存的模型失效时回退到默认并标注「已回退」，表单提交仍显式报错。新增 5 个用例（累计 479 全部通过） | [007](./current/007-ai-analysis.md) | [2026-10-22 AI_MODEL 支持清单](./changes/2026-10-22-ai-model-list.md) |
| 2026-10-22 | **AI 页改版二（搜索式工作台）**：去掉全量标的左栏，改为顶部 hero 搜索框 + 工作台（`.ai-work`：标的条 / 报告 + 参数 + 快照 + 历史）；新增 `GET /stock/ai/api/search`（服务端真查库，参数化 LIKE 名称/代码，≤12 条，空 `q` 返回空）、`StockAiReport.list_recent`、`DIMENSION_DESCS`；`?stock_id=` 缺失不再默认选中第一只，改为「未选标的」空态（能力卡片 + 最近分析）；现价改为优先取 `stock_warehouse.current_price`；新增 12 个用例（累计 474 全部通过） | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | [2026-10-22 AI 页改版二](./changes/2026-10-22-ai-analysis-workspace.md) |
| 2026-10-26 | **侧栏运行状态上色**：`build_system_status()` 增 `tone`（ok/bad），监控「运行中」与雪球「正常」显示**绿色**、异常显示**红色**（新增 `--ok`/`--bad` 别名，避免复用红涨绿跌的 `up`/`down` 把颜色整反）；修正 `.side-foot-row b` 特异性压掉颜色类的老问题；轮询时颜色随 `tone` 一起更新；交易时段与告警冷却保持中性色。新增 8 个用例（累计 634 全部通过） | [008](./current/008-frontend-ui.md) | [2026-10-26 侧栏状态上色](./archive/changes/2026-10-26-sidebar-status-colors.md) |
| 2026-10-23 | **修复 D-15（暗色下拉白底）**：两套主题声明 `color-scheme: dark/light`，`.select option` / `.ask-select option` 显式钉背景与文字色；新增 `tests/test_theme_controls.py` 5 个用例（累计 548 全部通过） | [008](./current/008-frontend-ui.md) | 缺陷修复，无独立变更记录（见台账 D-15） |
| 2026-10-23 | **连通测试入口唯一化**：Composer 的「密钥 sk-***」pill 改名为「测试连通性」（脱敏密钥移到面板顶部），右栏参数卡的「连通测试」按钮删除（只留脱敏文本指向底部）；路由与参数未变；新增 2 个用例（累计 543 全部通过） | [007](./current/007-ai-analysis.md)、[008](./current/008-frontend-ui.md) | [2026-10-23 连通测试入口唯一化](./archive/changes/2026-10-23-ai-test-entry.md) |
| 2026-10-23 | **AI 追问 Composer**：底部提问框改为 Composer（多行输入 + Enter 发送 + 底部工具条 + 圆形发送键）；「深度思考」位置改为**模型下拉**（仅作用于本次追问，真实下发并落库），「智能搜索」位置改为**密钥**（仅存进程内存，不落库/不回显/不写日志）+ 就地「测试连通性 / 用回环境变量」；`/stock/ai/test` 新增 `api_key` / `model` / `clear_key`；密钥入口始终可点（未就绪也能录密钥）；新增 14 个用例（累计 541 全部通过） | [007](./current/007-ai-analysis.md)、[008](./current/008-frontend-ui.md) | [2026-10-23 追问 Composer](./archive/changes/2026-10-23-ai-composer.md) |
| 2026-10-23 | **账户设置落地**：`/profile` 由只读变可写（用户名 / 邮箱 / 手机号 / 默认基准指数四选：上证 / 沪深300 / 创业板指 / 恒生指数）；新增 `user_notify_pref` 与 `users` 四列，四个告警通知开关真的拦邮件（仍落库、跳过发信）；收件人改 `resolve_alarm_recipients()`（环境变量优先、回退账户邮箱）并与页面同源；新增每日汇总邮件（`DAILY_SUMMARY_TIME` 默认 08:30，每天一次）；新增 39 个用例（累计 527 全部通过） | [001](./current/001-user-auth.md)、[003](./current/003-alarm-thresholds.md)、[008](./current/008-frontend-ui.md) | [2026-10-23 账户设置](./archive/changes/2026-10-23-account-profile.md) |
| 2026-10-23 | **侧栏导航分组重构**：单组 6 项改为「交易 / 监控 / 系统」三组，系统组收纳账户设置 / 退出登录（顶栏下拉保留），品牌副标改 `Stock Monitor`；「指标监控」新增徽标 = 近 24h 指标告警数（`StockAlarm.count_recent_indicator`，为 0 隐藏、失败降级 0）；折叠控件仍在「监控」组，未改 CSS；新增 9 个用例（累计 488 全部通过） | [008](./current/008-frontend-ui.md) | [2026-10-23 侧栏导航分组](./archive/changes/2026-10-23-sidebar-groups.md) |
| 2026-10-22 | **AI 真实验证闭环**（T-12）：凭据配置后实跑连通测试（4.9 s / 269 tokens）、正式分析（3357 tokens，`parsed=true`）、追问留痕（4877 tokens）、超时失败路径（60 s 未返回→提示且不落库）、`chat` 风格探测；全表扫描确认密钥未落库 | [007](./current/007-ai-analysis.md) | [2026-10-21 AI 个股分析](./archive/changes/2026-10-21-ai-analysis.md) §8.4 |
| 2026-10-23 | **指标告警改「四项同时满足」组合触发**（用户反馈"单条件筛出来的不符合策略"）：四条由 OR 改 AND（`is_combo_hit`），一次组合命中只写一条 `indicator / combo` 告警与一封总览邮件，冷却 key 收敛为单键；四条 flag 仍逐项落库但不展示角标；页面 KPI 改「组合命中 / 未采集」；告警历史徽标支持 `combo`；新增 12 个用例（累计 560） | [006](./current/006-stock-indicator.md)、[003](./current/003-alarm-thresholds.md) | [2026-10-23 组合触发](./changes/2026-10-23-indicator-combo.md) / [ADR-004](./decisions/004-indicator-combo-semantics.md) |
| 2026-10-23 | **指标监控页加「AI 分析」快捷入口**（与订单列表同款）：每行标的右端 ghost 按钮直达 `/stock/ai/?stock_id=<本行>`，复用 `.cell-with-action` / `.row-ai` 与三层 `min-width:0` 收缩规则，**不新增列**、纯 GET 链接；判定 / 告警 / 采集零改动；新增 3 个用例（累计 563） | [006](./current/006-stock-indicator.md)、[007](./current/007-ai-analysis.md)、[008](./current/008-frontend-ui.md) | [2026-10-23 指标页 AI 快捷入口](./changes/2026-10-23-indicator-ai-shortcut.md) |
| 2026-10-23 | **指标监控页分页 + AI 入口换配色**：`?page=` / `?per_page=` 默认每页 10 条（可选 5/10/20/50，与订单列表同款 select 与 `.pager`），KPI「监控标的」改为全量口径、命中/未采集为本页口径；行内 AI 入口改为**可切换变体**（`.row-ai.blue` 蓝色 / 订单页保持紫色默认）；表格七列全定宽 1160（窄屏横向滚动）；新增 10 个用例（累计 573） | [006](./current/006-stock-indicator.md)、[008](./current/008-frontend-ui.md) | [2026-10-23 指标页分页](./changes/2026-10-23-indicator-pagination.md) |
| 2026-10-23 | **收盘后照常采集**（原 D-04 是"非交易时段跳过整轮"，导致收盘价 / 当日 K 线不落库）：删掉跳过分支，非交易时段跑同一条 `check_and_alert` 链路，靠 `MONITOR_OFF_HOURS_ROUND_INTERVAL`(1800s) 与 `MONITOR_OFF_HOURS_FETCH_MIN/MAX_DELAY`(60~300s) 放慢；新增 `MONITOR_ROUND_INTERVAL`(0) 保留交易时段现状；删除死配置 `MONITOR_STRICT_TRADING_HOURS`；新增 5 个用例（累计 578） | [004](./current/004-monitor-service.md)、[006](./current/006-stock-indicator.md)、[003](./current/003-alarm-thresholds.md) | [2026-10-23 收盘后照常采集](./changes/2026-10-23-offhours-collection.md) |
| 2026-10-26 | **多用户数据隔离**：订单归属 `stock_master.user_id` + 角色 `users.role`（admin 见全量 / user 见自己）+ 判定入口唯一化 `utils/access.py`；全站可见性作用域（列表 / 指标页 / 告警设置 / 告警历史 / K 线 API / 刷新行情 / AI 页与搜索 / 侧栏徽标）+ 写操作越权拦截；唯一键由 `UNIQUE(stock_code)` 改 `UNIQUE(user_id, stock_code)`（[ADR-005](./decisions/005-per-user-stock-code-uniqueness.md)）+ 监控本轮结果按代码共享（同代码只请求一次雪球）+ 告警邮件按归属人邮箱与其通知开关；真实库迁移落地（92 条订单回填，`uk_user_code` 已验证拦重复）；新增 48 个用例（累计 626 全通过） | [001](./current/001-user-auth.md)、[002](./current/002-stock-order.md)、[003](./current/003-alarm-thresholds.md)、[004](./current/004-monitor-service.md)、[007](./current/007-ai-analysis.md) | [2026-10-26 多用户数据隔离](./archive/changes/2026-10-26-multi-user-ownership.md) |

---

## 5. 同步规则（速查）

1. **先有变更，后有规格**：任何行为变化先在 `spec/changes/` 建变更记录，再改代码，验证后合入 `spec/current/`。
2. **改规格必改进度**：`current/` 任一文件变动 → 同步更新本文件对应模块状态与"最后更新"日期。
3. **改进度必指规格**：台账每条必须有规格链接；若某模块尚无规格，先补规格再开发。
4. **缺陷闭环**：D-xx 从 `待办` 推进到 `已验证` 时，同步更新对应规格的"已知限制"章节。
5. **编号不复用**：规格编号 `NNN` 与缺陷编号 `D-NN` 只增不删，废弃项移入 `archive/`。
