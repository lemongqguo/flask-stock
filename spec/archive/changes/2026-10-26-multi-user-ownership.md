# 2026-10-26 多用户数据隔离（订单归属 + 管理员全量可见）

**状态**：✅ **已合入**（2026-10-26）　|　**提出日期**：2026-10-26　|　**负责人**：（维护者）
**受影响规格**：[001 用户认证](../current/001-user-auth.md)、[002 股票订单管理](../current/002-stock-order.md)、
[003 告警阈值与告警历史](../current/003-alarm-thresholds.md)、[004 后台监控服务](../current/004-monitor-service.md)、
[007 AI个股分析](../current/007-ai-analysis.md)、[008 前端UI](../current/008-frontend-ui.md)
**前置评估**：[`design-preview/多用户数据隔离-需求评估.md`](../../design-preview/多用户数据隔离-需求评估.md)

---

## 1. 问题与动机

需求原文三条：① 用户登录后只能看到自己名下的股票；② 只有 admin 能看到全部；③ 现有数据库能否实现。

**现状（2026-10-26 评估确认）**：

1. `stock_master` 没有任何归属字段，全库订单共享；`spec/current/002-stock-order.md` §5 已把「订单不区分用户」写成已知限制。
2. `users` 没有角色字段，`admin_required` 早在 D-10 就因依赖不存在的 `role` 被当死代码删除。
3. 由此产生**实际越权**：改 URL 即可编辑/删除/暂停他人订单；`?stock_id=` 可看他人阈值与 AI 报告；
   `POST /stock/refresh_quotes` 传任意 `ids` 可批量拉他人行情；`GET /stock/api/kline/<id>` 无任何校验。
4. `models/account_settings.py` 的「最近保存过的账户即全局生效」口径在多用户下会漂移：
   A 保存一次设置，B 的告警邮件就改投给 A。

结论：数据库**不能直接**满足，但**纯加法改造即可满足**（加 2 列 + 索引 + 调 1 个唯一键），不重建库、不丢数据。
真正的工作量在代码：全项目 16 处 `stock_master` 读写点都没有用户维度。

## 2. 变更类型

- [ ] **缺陷修复**：实现没有满足原有约定 → 依据现有规格补回归测试后修复
- [x] **行为变更**：产品需要调整原有行为 → 先改这里的约定，再改测试期望
- [ ] **技术重构**：行为不变，内部结构变化 → 说明为什么安全
- [x] **新增能力**：新增场景 → 需新建或扩展 `../current/` 规格

> 说明：越权本身属**安全类缺陷**，但因其根因是「订单本就无归属」这一产品约定缺失，
> 按守则 §1「行为变更」处理——先在本文档定新约定，再同步改测试期望。

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 订单归属 | 无 `user_id`，所有登录用户共享同一批订单（002 §5 已知限制） | 每行 `stock_master.user_id` 必有归属；新建时取当前登录用户，**不接受客户端传值** |
| 订单可见性 | 所有登录用户看到**全量**订单 | 普通用户只见自己名下；**admin 见全量** |
| 写操作授权 | 登录即可改任意订单 | 取行后校验归属，不匹配 → 403 / flash 回列表 + `logger.warning` |
| `stock_code` 唯一性 | 全局唯一，`VARCHAR(20) NOT NULL UNIQUE` | **方案 A**：`UNIQUE KEY uk_user_code (user_id, stock_code)`；同一代码可被多个用户各持有一条 |
| 股票代码查重 | 全局查重，第二人添加同代码报「已存在」 | 按归属查重：只有当**自己名下**已有该代码时才报错 |
| 管理员标识 | 无 | `users.role ENUM('user','admin') DEFAULT 'user'`；登录时写入 `session['role']` |
| 告警历史可见性 | 全库 | 按订单归属过滤；`get_stats()` KPI 同口径 |
| K 线 / AI 报告 / 指标页 / 告警设置 | 全量可见 | 同上述作用域 |
| 侧栏「指标监控」徽标 | 全库近 24h 指标告警数 | 按归属过滤 |
| 同一代码的行情拉取 | 一条订单 = 一次雪球请求 | **监控线程按 `stock_code` 做本轮缓存**，同代码一轮只取一次行情 / 一次 K 线，结果回写所有持有该代码的订单 |
| 告警收件人 | 「最近保存过的账户」邮箱 + 其通知开关 | 按**订单归属人**的邮箱与其通知开关；该用户没邮箱时回退环境变量 `ALARM_RECIPIENTS` |
| 管理员能否改别人的订单 | （不存在该问题） | **可视即可管**：`utils.access.can_manage()` 里 admin 恒 True。选它是为了避免「看得见却点不动」的半残页面；要改成只读只需删掉该函数里 `is_admin()` 那一分支 |
| 删除用户 | 无删除入口 | `stock_master.user_id` 外键用 `ON DELETE RESTRICT`，禁止因删用户误清历史行情与告警 |

**未纳入本次范围（保持现状，在规格中显式声明）**：

- **每日汇总邮件仍是全局口径**：`_maybe_send_daily_summary` 汇总所有用户近 24h 告警并发到全局收件人。
  这是本次有意留下的隔离缺口——该开关默认关闭（`notify_daily=0`），改造需要按用户循环发送，成本与收益不匹配。
  若将来有人开启「每日汇总」，必须先把这里改造成逐用户发送，否则会造成跨用户泄露；
- `stock_ai_config`（AI 温度 / 月度上限 / 数据范围）仍是单行全局表，月度上限**全体共享**；
- `stock_indicator_config` 的「留空继承全局」语义不变；
- 注册仍开放，新用户默认 `role='user'`、订单列表为空；
- 管理员列表未加「归属用户」列（评估稿 §7-Q7）。

## 4. 影响面

- 涉及模块/文件：
  - 新增 `utils/access.py`（**唯一归属判定入口**）
  - `database.py`（迁移 + 建表）
  - `models/user.py`、`models/base.py`、`models/stock_master.py`、`models/stock_alarm.py`、`models/account_settings.py`
  - `models/stock_monitor.py`（本轮行情缓存 + 收件人按归属人）
  - `views/auth.py`、`views/stock_orders.py`、`views/ai_analysis.py`、`app.py`
  - 受影响测试：`tests/test_status_toggle.py`、`test_refresh_quotes.py`、`test_indicator_page.py`、
    `test_page_stats.py`、`test_ai_analysis.py`、`test_form_quote.py`、`test_app_smoke.py`、`test_account_profile.py`、
    `test_monitor_service.py`；新增 `tests/test_multi_user_ownership.py`
- 涉及数据表 / 是否需要迁移：**需要**
  - `users` 加 `role`
  - `stock_master` 加 `user_id` + 索引 + 外键（RESTRICT）
  - 唯一键：删 `UNIQUE(stock_code)` → 加 `UNIQUE(user_id, stock_code)`
- 是否影响既有数据：**是**
  - 存量订单 `user_id` 全部回填为「`id` 最小的用户」，该用户同时被置为 admin，保证改造后立刻有管理员；
  - 回填只处理 `user_id IS NULL`，幂等可重复执行。
- 是否需要新增/修改配置：**否**（不引入任何环境变量，不触碰安全红线）

## 5. 实施要点

1. **判定收敛到一处**（对齐 `models/account_settings.py` 头部注释的教训）：新增 `utils/access.py`，
   提供 `is_admin()` / `current_user_id()` / `visibility_scope()` / `owned_stock_or_none()`。
   各视图**只调用，不自己拼 `WHERE user_id =`**，杜绝「页面写一套、监控另一套」的漂移。
2. **失败关闭**：归属缺失（`user_id` 为 None）或取不到行 → 一律按「不可见 / 不可改」处理，不放行。
3. `session['role']` 缓存：避免每次请求查 `users` 表；管理员权限变更后需重新登录生效（写入规格）。
4. 唯一键调整**必须先完成回填**：否则 `UNIQUE(user_id, stock_code)` 在 `user_id` 为 NULL 时不生效，失去约束意义。
5. 监控的行情缓存**只缓存成功结果**，失败不缓存，保证单点失败不会连坐其他同代码订单。
6. 兼容既有 mock：`StockMaster.get_by_id` 返回的是 **dict 行**（002 §3.6 已注明），
   归属判定用 `stock.get('user_id')`，现有测试 fixture 缺 `user_id` 键的需同步补上。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 迁移是否落地 | 真实库 `uatstockdb`（`app` 启动自检触发 `init_database()`），只读查 `information_schema` | ✅ `users.role`=`enum('user','admin')`、`stock_master.user_id`、`idx_stock_owner`、`uk_user_code (user_id, stock_code)`、`fk_stock_master_user` 全部就位 |
| 全局唯一是否已解除 | 同上，查 `STATISTICS` | ✅ 唯一索引 `stock_code` 已 DROP，仅剩非唯一 `idx_stock_code`；唯一性由 `uk_user_code` 承担 |
| 存量回填 | 同上 | ✅ 92 条订单 0 条 `user_id` 为 NULL，全部归 `user_id=1`；`users` 中 `id=1(admin)` 被置 admin，`id=2(root)` 保持 user |
| **按人唯一真的生效** | 真实库重复插入同一 `(user_id, stock_code)` | ✅ MySQL `1062 Duplicate entry '1-SH600809' for key 'stock_master.uk_user_code'`，`create()` 捕获后返回 None |
| SQL 语法与参数绑定 | 真实库直接调用模型方法（**不 mock**）10 个查询 × 三种口径 | ✅ 全部 OK；`NO_ACCESS` 哨兵口径返回空集而不是全量 |
| 可见性 / 越权 / 归属写入（48 例） | `tests/test_multi_user_ownership.py` | ✅ 通过 |
| 全量回归 | `stockenv\Scripts\python.exe tests\run_all.py` | ✅ 626 用例全部通过（原 578 + 新增 48） |

- 实际验证到的范围：数据库迁移（真实库，含唯一键与外键）、带归属过滤的 SQL 在真实 MySQL 上的语法与参数绑定、
  按人唯一的约束行为、视图层可见性与写权限（mock 客户端 + mock 数据访问层）、监控本轮去重（mock 行情源）、
  收件人与偏好按归属人解析（mock 偏好表）、角色默认值与 `set_role` 入参校验。
- **未验证**的范围（明确写出来）：
  1. **未做浏览器观感核对**：普通用户 / admin 两种视角的列表、越权后的 flash 提示文案需人工确认；
     管理员列表**未**加「归属用户」列（需求评估 §7-Q7，本次未实现）。
  2. **未发真实邮件验证「收件人 = 订单归属人」**：`recipients_for_user` / `prefs_for_user` 只做到函数级与 SQL 级验证，
     SMTP 未启用，真实送达未跑。
  3. **监控去重未在真实雪球环境验证**：当前库里 92 条订单全属同一用户，不存在「同一代码多人持有」的真实数据；
     去重只用 mock 验证（同一顺序 Walk 两次只请求一次）。多线程并发分支（等待者路径）亦只做了单线程走查。
  4. **每日汇总邮件仍是全局口径**：`_maybe_send_daily_summary` 会把**所有用户**的告警汇总成一封发到全局收件人，
     本次未改造（默认 `notify_daily=0` 关闭）。这是本次有意留下的隔离缺口，见 §3「未纳入本次范围」。
  5. **AI 月度调用上限仍是全体共享**（`stock_ai_config` 单行表），未按用户隔离。
  6. `flask set-admin` CLI 与「改角色后需重新登录」只在代码层实现，未在真实环境跑过。
  7. **未做性能压测**：`uk_user_code` / `idx_stock_owner` 的实际执行计划未 `EXPLAIN`。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/001-user-auth.md` 已更新（新增 §3.7 角色与数据归属）
- [x] `../current/002-stock-order.md` 已更新（归属 / 可见性 / 唯一键；作废「订单不区分用户」限制）
- [x] `../current/003-alarm-thresholds.md`、`../current/004-monitor-service.md`、`../current/007-ai-analysis.md` 已同步
- [x] `../PROGRESS.md` 模块进度与缺陷台账已更新
- [x] `../README.md` 已知限制已同步（删除「无权限体系」，新增多用户相关限制）
- [x] 涉及重要取舍时已补 [`../decisions/`](../decisions/) 决策记录 → [ADR-005](../decisions/005-per-user-stock-code-uniqueness.md)
- [x] 本目录已移入 `../archive/changes/`
