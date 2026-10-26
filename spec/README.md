# spec/ 规格目录索引（Index）

> 本文件是本项目**唯一的规格入口**。新人或 Agent 从这里开始，不需要翻历史聊天记录。
> 维护方法见 [Spec.md](./Spec.md)；执行细则见 [rules/README.md](./rules/README.md)。

**最后更新**：2026-10-26　|　**当前基线**：`v1.5.0`　|　**维护状态**：M1~M4 缺陷已闭环；**8 份规格全部已实现**（007 已真实网关验证；006 / 007 页面待人工看观感），**2026-10-26 完成多用户数据隔离**，见 [PROGRESS.md](./PROGRESS.md)

---

## 1. 项目一句话

Flask Stock 是一个 Flask + MySQL 的股票订单监控系统：维护股票订单与三档建仓/卖出阈值，后台线程轮询雪球行情，触发价格/PE/PB 告警并发送邮件，同时采集 K 线并计算 MA5/MA10/MA30 判断金叉/死叉。

**多用户（2026-10-26 起）**：订单归属于各自的账号（`stock_master.user_id`），
普通用户只看自己名下的订单，`role='admin'` 看全量。归属判定统一走 `utils/access.py`，
同一股票代码可被不同用户各持有一条（`UNIQUE(user_id, stock_code)`，见 [ADR-005](./decisions/005-per-user-stock-code-uniqueness.md)）。

---

## 2. 目录职责

`spec/` 下的子目录即"规格目录"的标准分组，命名固定，不得随意新增同级目录：

| 目录 | 职责 | 何时写入 |
| --- | --- | --- |
| [`spec/README.md`](./README.md) | 本索引：当前有效规格入口、状态、已知限制 | 有效约定或状态变化时 |
| [`spec/PROGRESS.md`](./PROGRESS.md) | 开发进度台账：模块进度 + 缺陷/待办，与规格编号双向关联 | 每次需求推进或缺陷状态变化时 |
| [`spec/current/`](./current/) | **当前有效规格**：系统"现在是什么样" | 行为被确认修改并验证后 |
| [`spec/changes/`](./changes/) | **变更记录**：一次变更从提案到合入的全过程 | 一次变更推进过程中 |
| [`spec/decisions/`](./decisions/) | **决策记录（ADR）**：为什么这么选、代价是什么 | 出现重要设计选择时 |
| [`spec/plans/`](./plans/) | **计划**：里程碑、迭代范围、阶段成果 | 排期或范围调整时 |
| [`spec/archive/`](./archive/) | **归档**：已废弃/已被替代的规格与变更 | 变更合入或被替代后 |
| [`spec/rules/`](./rules/) | **持续规则**：本项目的实施规范守则 | 规则本身修订时 |
| [`spec/Spec.md`](./Spec.md) | 维护方法论（本课教材，只读） | 一般不改 |
| [`spec/PROJECT_WIKI.md`](./PROJECT_WIKI.md) | 项目百科：部署、配置、使用指南等背景资料 | 环境/运维信息变化时 |

判断口诀：**"现在是什么样" 看 `current/`，"准备改哪里" 看 `changes/`，"做到哪一步" 看 `PROGRESS.md`，"为什么这么定" 看 `decisions/`。**



spec/
├── README.md        ← 唯一入口：状态/导航/已知限制
├── PROGRESS.md      ← 开发进度台账（与规格双向绑定）
├── Spec.md          ← 方法论（只读保留）
├── PROJECT_WIKI.md  ← 项目百科（保留）
├── rules/           ← 持续规则：实施规范守则
├── current/         ← 当前有效规格 001~005
├── changes/         ← 变更记录（含 _TEMPLATE.md）
├── decisions/       ← 决策记录 ADR-001
├── plans/           ← 计划与路线图 roadmap.md
├── archive/         ← 归档（current/ + changes/）

项目侧配套：`.codebuddy/rules/spec-driven-maintenance.md`（Agent 自动遵循）、
`.env.example`（配置模板）、`tests/`（自动化用例）、`run: python tests/run_all.py`。

---

## 3. 当前有效规格清单

| 编号 | 规格 | 状态 | 主要实现位置 |
| --- | --- | --- | --- |
| 001 | [用户认证](./current/001-user-auth.md) | 已实现 | `views/auth.py`、`models/user.py`、`utils/decorators.py` |
| 002 | [股票订单管理](./current/002-stock-order.md) | 已实现 | `views/stock_orders.py`、`models/base.py` |
| 003 | [告警阈值与告警历史](./current/003-alarm-thresholds.md) | 已实现 | `views/stock_orders.py`、`utils/alarm_rules.py`、`utils/alarm_throttle.py` |
| 004 | [后台监控服务](./current/004-monitor-service.md) | 已实现 | `models/stock_monitor.py`、`utils/trading_time.py`、`utils/mail_sender.py`、`utils/logging_config.py` |
| 005 | [K线采集与均线信号](./current/005-kline-signal.md) | 已实现 | `models/stock_kline.py`、`views/stock_orders.py` |
| 006 | [指标监控](./current/006-stock-indicator.md) | 已实现（批次一 + 二 + **组合触发**） | `models/stock_indicator.py`、`utils/indicator_rules.py`、`models/stock_monitor.py`、`templates/indicator_list.html`、`views/stock_orders.py` |
| 007 | [AI个股分析](./current/007-ai-analysis.md) | 已实现 | `views/ai_analysis.py`、`utils/ai_client.py`、`utils/ai_prompt.py`、`models/stock_ai.py`、`templates/ai_analysis.html` |
| 008 | [前端UI](./current/008-frontend-ui.md) | 已实现 | `templates/`、`static/css/theme.css`、`static/js/theme.js` |

> 已废弃的规格（被上面某份替代）移入 [`spec/archive/`](./archive/)，并在原文件头部标注替代关系。

---

## 4. 进行中的变更

| 变更 | 类型 | 关联规格 | 顺序 |
| --- | --- | --- | --- |
| [2026-10-21 指标监控](./changes/2026-10-21-stock-indicator.md) | 新增能力 | [006](./current/006-stock-indicator.md) | 1（**批次一 + 二已交付**，待真实环境验证） |
| [2026-10-21 AI 个股分析](./archive/changes/2026-10-21-ai-analysis.md) | 新增能力 | [007](./current/007-ai-analysis.md) | 2（**已交付并在真实网关验证完毕，已归档**；`AI_API_STYLE=responses｜chat` 两种风格均实测通过） |
| [2026-10-22 AI 页改版](./changes/2026-10-22-ai-analysis-ui.md) | 新增能力 + 修复 | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | 2（**已交付**：三栏 + 搜索 + 模型选择 + 分析维度；待人工确认观感） |
| [2026-10-22 订单列表 AI 快捷入口](./changes/2026-10-22-list-ai-shortcut.md) | 新增能力 | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | 2（**已交付**：标的列右端直达 AI 页，不新增列；待人工确认观感） |
| [2026-10-22 AI 页改版二（搜索式工作台）](./changes/2026-10-22-ai-analysis-workspace.md) | 行为变更 + 新增能力 | [007](./current/007-ai-analysis.md) / [008](./current/008-frontend-ui.md) | 2（**已交付**：去全量标的栏 + 服务端搜索；待人工确认观感） |
| [2026-10-22 AI_MODEL 支持清单](./changes/2026-10-22-ai-model-list.md) | 行为变更 | [007](./current/007-ai-analysis.md) | 3（**已交付**：`AI_MODEL` 可按逗号 / 分号填多个，默认取第一项；待人工确认下拉） |
| [2026-10-23 指标告警改「四项同时满足」组合触发](./changes/2026-10-23-indicator-combo.md) | 行为变更 | [006](./current/006-stock-indicator.md)、[003](./current/003-alarm-thresholds.md) | 1（**已交付**：四条由 OR 改 AND，只发一条 combo 告警；待真实环境验证） |
| [2026-10-23 指标页 AI 快捷入口](./changes/2026-10-23-indicator-ai-shortcut.md) | 新增能力 | [006](./current/006-stock-indicator.md)、[007](./current/007-ai-analysis.md)、[008](./current/008-frontend-ui.md) | 1（**已交付**：每行标的右端直达 AI 页，不新增列；待人工确认观感） |
| [2026-10-23 指标页分页 + AI 入口换配色](./changes/2026-10-23-indicator-pagination.md) | 新增能力 | [006](./current/006-stock-indicator.md)、[008](./current/008-frontend-ui.md) | 1（**已交付**：默认每页 10 条；AI 入口改信息蓝；待人工确认观感） |
| [2026-10-23 收盘后照常采集](./changes/2026-10-23-offhours-collection.md) | 行为变更 | [004](./current/004-monitor-service.md)、[006](./current/006-stock-indicator.md)、[003](./current/003-alarm-thresholds.md) | 1（**已交付**：非交易时段由停采改慢采；待观察真实收盘后日志） |

> 已合入：[告警表补齐类型字段](./changes/2026-10-21-alarm-type-fields.md)（003 新增 3.5 节）、
> [前端 UI 改版](./changes/2026-10-21-frontend-redesign.md)（008，UI 底座先行，新功能页面直接按新样式落）、
> [订单列表内联切换监控状态](./changes/2026-10-21-order-status-toggle.md)（002 新增 3.6 节）、
> [订单列表新增「52周最低」列](./changes/2026-10-21-list-52w-low.md)（002 列表节）、
> [侧栏导航可折叠](./changes/2026-10-21-sidebar-collapse.md)（008，交互效果待人工确认）、
> [修复编辑页「实时行情」现价](./changes/2026-10-21-order-form-current-price.md)（002，现价取 warehouse）、
> [侧栏与顶栏接入实时系统状态](./changes/2026-10-21-system-status-panels.md)（004/008，含 `describe_session` 新增「午间休市」档）、
> [订单列表新增「刷新行情」按钮](./changes/2026-10-22-refresh-quotes-button.md)（008，只查库 + 只刷当前页）、
> ~~[表格行淡色底](./changes/2026-10-22-table-row-bg.md)（008，**已回退**）~~、
> [告警行/暂停行专属背景](./changes/2026-10-22-row-state-bg.md)（008，多色渐变 + 流动呼吸）、
> [静态资源加版本号](./changes/2026-10-22-static-version.md)（008，修复前端改动不生效）、
> [侧栏导航分组](./archive/changes/2026-10-23-sidebar-groups.md)（008，交易 / 监控 / 系统三组 + 指标监控徽标）、
> [账户设置落地](./archive/changes/2026-10-23-account-profile.md)（001/003/008，个人资料可写 + 默认基准指数四选 + 告警通知开关 + 每日汇总邮件）、
> [AI 追问 Composer](./archive/changes/2026-10-23-ai-composer.md)（007/008，模型选择 + 运行时密钥 + 就地连通测试）、
> [连通测试入口唯一化](./archive/changes/2026-10-23-ai-test-entry.md)（007/008，Composer 内「测试连通性」pill，参数卡按钮删除）。

已合入的变更见 [`spec/changes/`](./changes/)（最新：[2026-10-21 优雅退出](./changes/2026-10-21-graceful-shutdown.md)）。
新建变更见 [`spec/changes/README.md`](./changes/README.md)。
**已归档**：[2026-10-21 AI 个股分析](./archive/changes/2026-10-21-ai-analysis.md)（007，2026-10-22 完成真实模型调用验证后移入
[`spec/archive/changes/`](./archive/changes/)，后续变更记录将按守则 2.7 归档）。

---

## 5. 决策记录（ADR）

| 编号 | 主题 | 状态 |
| --- | --- | --- |
| [001](./decisions/001-spec-directory-structure.md) | 采用 `rules/plans/current/changes/decisions/archive` 分组管理规格与进度 | 已接受 |
| [002](./decisions/002-frontend-stack.md) | 移除 Bootstrap / jQuery / FontAwesome CDN，自建设计系统并支持双主题 | 已接受 |
| [003](./decisions/003-indicator-rule-semantics.md) | 5 日指标用倍数式（含护栏）、指标冷却 24h、基准取沪深300 | 已接受（组合口径见 004） |
| [004](./decisions/004-indicator-combo-semantics.md) | 指标告警改为四项 AND 组合触发（单发一条 combo 告警与一封邮件） | 已接受 |

---

## 6. 已知限制（Known Limitations）

2026-10-21 已完成 D-01 ~ D-12 的修复（见[变更记录](./changes/2026-10-21-m1-defect-hardening.md)）。
当前基线仍存在的限制，完整台账见 [PROGRESS.md](./PROGRESS.md)：

1. **部署必须提供配置**：未设置 `MYSQL_PASSWORD` / `SECRET_KEY` / `XUEQIU_TOKEN` / `MAIL_*` / `ALARM_RECIPIENTS` 时生产启动会直接报错（有意为之的 fail-fast）；模板见项目根目录 `.env.example`。
2. **历史凭据仍需轮换**：明文值虽已从代码删除，但曾入库，**必须在服务端全部更换**。
3. **告警冷却状态在进程内存**：多进程/多实例部署时各进程独立计数，需要多进程时应改为共享存储。
4. **交易日历为近似**：按"周一至周五 09:30–11:30 / 13:00–15:00"判定，未接法定节假日与临时休市。
5. **AI 只实测过一家网关**：`api.agicto.cn`（`responses` / `chat` 双风格均通），换厂商需各自确认返回结构；
   另**推理型模型建议把 `AI_TIMEOUT` 调到 120~180**（默认 60 在长思考时会超时，代码会正确降级为「超时失败、不落库」）。
6. **监控无运行时控制面**：无法在页面上启停监控或查看健康度（`get_status()` 已有数据，未接 UI）。
7. **无 CI**：462 个用例只能本地运行（`stockenv\Scripts\python.exe tests/run_all.py`）。**必须走项目自带的 `stockenv/`**（Python 3.11 + numpy 1.24.3 + pandas 2.0.3）；全局解释器的 numpy/pandas 版本不兼容会让 import pandas 的模块直接崩。
8. **无 CSRF 防护**：Flask-WTF 已引入但未启用，所有 POST 表单裸奔。
9. **负 PE 会命中 PE 档位**：亏损公司必然触发 PE 告警，当前行为已被测试锁定，是否过滤待产品决策。
10. **指标告警要求四项同时成立**（2026-10-23，[ADR-004](./decisions/004-indicator-combo-semantics.md)）：
    52 周新低 / 52 周回撤 / 20 日跑输 / 5 日倍数须 **AND** 命中才发一条 `combo` 告警；
    单条件命中不再通知，告警数量显著下降属预期，不是"没在监控"。
11. **本机回归有一个与环境相关的失败**：`.env` 里 `FLASK_DEBUG=1` 会让 `test_no_debug_by_default` 失败
    （加 `FLASK_DEBUG=0` 即通过），非代码缺陷。
12. **多用户隔离有三处残留（2026-10-26）**：
    - **每日汇总邮件仍是全局口径**：汇总所有用户近 24h 告警发到全局收件人。
      当前 `notify_daily` 默认关闭无影响，**但一旦有人开启即造成跨用户泄露**，须先逐用户改造（台账 T-10）；
    - **AI 月度调用上限全体共享**（`stock_ai_config` 是单行全局表），未按用户配额；
    - **管理员列表没有「归属用户」列**：admin 看到全量但看不出每行属于谁（台账 T-11）。
13. **角色变更需重新登录才生效**：角色在登录时写入 session，库里改角色不会让在线会话升级/降级。
    提升管理员用 `flask set-admin <username>`。

---

## 7. 上手路径

1. 读本文件 → 了解系统当前能力与限制。
2. 读 [`PROGRESS.md`](./PROGRESS.md) → 了解做到哪一步、下一步做什么。
3. 读 [`rules/README.md`](./rules/README.md) → 了解改动必须遵守的流程。
4. 读相关 [`current/NNN-*.md`](./current/) → 了解具体行为与验收条件。
5. 跑一遍 `python tests/run_all.py` → 确认改动没有破坏既有行为。

## 8. 本地启动（修复版）

```bash
copy .env.example .env      # Windows；Linux/macOS: cp .env.example .env
# 编辑 .env，至少填 MYSQL_PASSWORD / SECRET_KEY / XUEQIU_TOKEN / MAIL_* / ALARM_RECIPIENTS
python database.py          # 建表 + 补索引
python app.py               # 启动（默认 debug=0）
```

启动前置校验不通过会直接抛错并列出缺失项，不会带着空配置继续运行。
