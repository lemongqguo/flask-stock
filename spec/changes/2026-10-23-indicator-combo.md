# 2026-10-23 指标告警改「四项同时满足」组合触发

**状态**：已交付（待真实环境验证后归档）　|　**提出日期**：2026-10-23　|　**负责人**：（维护者）
**受影响规格**：[006 指标监控](../current/006-stock-indicator.md)、[008 前端UI](../current/008-frontend-ui.md)、[003 告警阈值与告警历史](../current/003-alarm-thresholds.md)

---

## 1. 问题与动机

原实现把四条指标当作**四个独立信号**：任一条命中即各自告警一次（`_check_indicators` 里 `for subtype in SUBTYPES` 逐个发信）。

用户反馈：**单个条件触发筛选出来的标的不符合策略**——52 周新低、52 周回撤、20 日跑输、5 日倍数各自都会挑出一大票股票
（尤其「52 周回撤 >35%」是长期持续状态，满足的标的一抓一大把），四个 OR 叠加后告警量远超预期，失去筛选价值。

因此四条之间必须由 OR 改为 **AND**：四项同时成立才构成一次有效信号。

## 2. 变更类型

- [x] **行为变更**：产品需要调整原有行为 → 先改这里的约定，再改测试期望
- [ ] 缺陷修复 / 技术重构 / 新增能力

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 四条指标的组合关系 | OR：任一命中即告警 | **AND：四项全部命中才告警** |
| 一次组合命中产生几条告警 | 每个命中的 subtype 各一条（最多 4 条 / 4 封邮件） | **仅一条**，`alarm_subtype='combo'`，正文列出四项实测值与阈值 |
| 冷却 key | `stock_id:indicator:<subtype>`，四种指标互不遮挡 | `stock_id:indicator:combo`，组合只有一个 key |
| 指标监控页指标状态列 | 四个独立角标（52 周新低 / 52 周回撤 / 20 日跑输 / 5 日急跌 +「正常」） | **只显示组合结论**（满足 / 不满足 / 未采集） |
| 页面 KPI | 长期命中 / 短期命中分列计数 | 改为「组合命中」单一计数（保留监控标的 / 最新快照） |
| 缺数据（新股不足 20 交易日、基准未采集） | 该指标判 False，其余仍可单独告警 | 该指标判 False（不变），AND 组合下**整体不告警**——宁可不报，不可误报 |
| 四条 flag 列（`flag_low52w` 等） | 落库并展示 | **仍逐项落库**（供排查与未来扩展），但页面不再单独展示其命中状态 |

## 4. 影响面

- 涉及模块/文件：`utils/indicator_rules.py`、`models/stock_monitor.py`、`views/stock_orders.py`、
  `templates/indicator_list.html`、`templates/recent_alarms.html`、`tests/test_indicator_rules.py`、
  `tests/test_indicator_collect.py`、`tests/test_indicator_page.py`
- 涉及数据表 / 是否需要迁移：**无表结构变更**（`alarm_subtype` 已是 `VARCHAR(16)`，`combo` 可直接写入）
- 是否影响既有数据：**否**。历史 `low52w/drawdown/rs20/rs5` 告警行保留原样（是真实的单指标命中记录），
  页面徽标 `recent_alarms.html` 仍识别这四个旧取值，另加 `combo`
- 是否需要新增/修改配置：**否**，阈值项与 `IND_*` 全部不变

## 5. 实施要点

1. `utils/indicator_rules.py`：新增 `SUBTYPE_COMBO='combo'`、**不进** `SUBTYPES`（`SUBTYPES` 仍是四条原子指标，
   避免把组合混进 `hit_subtypes` / 逐项判定）；新增 `is_combo_hit(flags)` 纯函数（`all(...)`）；
   `evaluate_indicators` 返回值新增 `combo_hit`；`build_indicator_alarm` 的合法取值扩到 `ALARM_SUBTYPES`，新增组合文案分支。
2. `models/stock_monitor.py`：`_check_indicators` 由「遍历四条逐个发」改为「算一次 `is_combo_hit`，命中才发一条 combo 告警」，
   未命中仍 `throttle.clear(key)`（保持「条件消失可重新告警」语义）。
3. 页面：只显示组合结论，KPI 由 长期/短期 改为「组合命中」。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 组合判定 AND 语义（含缺数据） | `tests/test_indicator_rules.py::ComboHitTest`（6 例） | ✅ 通过 |
| `evaluate_indicators` 返回 `combo_hit` | `EvaluateTest.test_combo_hit_only_when_all_four` / `test_combo_false_in_existing_metrics_case` | ✅ 通过 |
| 组合邮件文案列全四项 + 阈值 | `AlarmTextTest.test_combo_text_lists_all_four` | ✅ 通过 |
| 监控链路：四项全中只写 1 条 combo 告警 | `test_combo_writes_single_alarm` | ✅ 通过（告警正文含四项） |
| 24h 冷却仍生效 / 条件消失可重报 | `test_combo_within_24h_only_once`、`test_condition_cleared_then_reappears_alerts_again` | ✅ 通过 |
| 单条 / 三条命中不再告警 | `test_single_subtype_hit_never_alerts`、`test_three_of_four_still_no_alert` | ✅ 通过 |
| 基准缺失 / 新股不告警 | `test_missing_bench_data_no_combo_alarm`、`test_new_stock_no_combo_alarm` | ✅ 通过 |
| 页面只显示组合结论 + KPI 口径 | `tests/test_indicator_page.py`（KPI / 徽标 / 未采集计数，3 例改 + 1 例新增） | ✅ 通过 |
| 全量回归 | `stockenv\Scripts\python.exe tests/run_all.py` | ✅ 560 用例；`test_no_debug_by_default` 因本机 `.env` 的 `FLASK_DEBUG=1` 失败（置 `FLASK_DEBUG=0` 后 OK），与本次改动无关 |

- 实际验证到的范围：判定纯函数、监控链路发告警路径（含冷却与回写）、页面渲染契约（模板级）、全量回归。
- **未验证**的范围（明确写出来）：
  1. **未跑真实雪球行情 / 数据库**：监控链路全部用 mock（`StockKline` / `StockBenchKline` / `StockIndicator` 均为 mock），
     真实采集下四项能否同时成立（尤其基准日线是否具备 21 条）尚未验证；
  2. **未发真实邮件**：`_send_alert_mail_status` 未启用 SMTP，组合邮件正文只做了纯函数层面的文案断言；
  3. **页面观感未做浏览器核对**：仅模板契约测试（延续 006 已知限制），需人工确认；
  4. `alarm_subtype='combo'` 写入真实 MySQL 后被告警历史页筛选 / 统计的表现未实跑（表结构无变更，理论上兼容）。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/006-stock-indicator.md` 已更新为新的有效约定（§1 / §2 / **§3.1 组合关系** / §6 / §8 / §9 / §10）
- [x] `../current/003-alarm-thresholds.md` 已同步 subtype 取值、冷却 key 与验收条件 12
- [x] `../PROGRESS.md` 模块进度与缺陷台账已更新
- [x] `../README.md` 已知限制已同步（新增第 10、11 条；规格清单与决策清单已加 004）
- [x] 涉及重要取舍时已补 [`../decisions/`](../decisions/) 决策记录 → [ADR-004](../decisions/004-indicator-combo-semantics.md)
- [ ] 本目录已移入 `../archive/changes/`（**待真实环境验证后再归档**，与 006 批次一 / 二一致）
