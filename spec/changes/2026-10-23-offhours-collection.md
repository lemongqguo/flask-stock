# 2026-10-23 收盘后照常采集（不再跳过整轮，只是放慢）

**状态**：已交付　|　**提出日期**：2026-10-23　|　**负责人**：（维护者）
**受影响规格**：[004 后台监控服务](../current/004-monitor-service.md)、[006 指标监控](../current/006-stock-indicator.md)、
[003 告警阈值与告警历史](../current/003-alarm-thresholds.md)

---

## 1. 问题与动机

原 D-04 降频是"**非交易时段整轮跳过**"：15:00 收盘后、午休、盘前、周末一律不拉行情，
只睡 300 s 再判断。副作用：

1. **当天收盘价不落库**（最后一次采集停在 15:00 之前）；
2. **当日 K 线日线不补采** → `ret_5d` / `ret_20d` 用盘中数据近似；
3. 基准日线 `_maybe_sync_bench` 也只在交易时段触发；
4. 收盘后任何告警判定都停摆。

用户要求：**收盘后也要采集，功能照旧，只是每个股票的采集间隔放长；开盘时段间隔短。**

## 2. 变更类型

- [ ] 新增能力
- [x] **行为变更**：非交易时段由"停采"改为"慢采"
- [ ] 缺陷修复 / 技术重构

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 非交易时段（收盘后 / 午休 / 盘前 / 周末） | **跳过整轮**，不拉行情、不采 K 线、不算指标、不判告警，只睡 `MONITOR_OFF_HOURS_SLEEP`(300s) | **照常跑整轮**：行情快照 + PE/PB 回写 + K 线 + 指标 + 告警判定全部执行；轮结束后睡 `MONITOR_OFF_HOURS_ROUND_INTERVAL`（默认 1800s） |
| 每只标的拉取节流 | 不分时段，`FETCH_MIN_DELAY~FETCH_MAX_DELAY`（30~300s） | 交易时段同上；非交易时段用 `MONITOR_OFF_HOURS_FETCH_MIN_DELAY~MAX`（默认 60~300s） |
| 交易时段轮间隔 | 无（一轮结束立刻下一轮） | 新增 `MONITOR_ROUND_INTERVAL`，默认 **0 = 保持现状**；想放慢可自行调大 |
| `MONITOR_OFF_HOURS_SLEEP`(300s) | "跳过整轮"时的休眠 | 仅剩一个用途：雪球退避期的休眠上限 `min(backoff, MONITOR_OFF_HOURS_SLEEP)` |
| `MONITOR_STRICT_TRADING_HOURS` | 声明在 `config.py` 但**代码从未读取**（死配置） | **删除**：本变更确立"收盘也采集"，该开关永远不会再被接线 |

判定时段的方式不变（`utils/trading_time.is_trading_time()`），`describe_session()` 仍只用于展示。

**两类频率旋钮**（默认值的实际效果，按 100 只标的 / 6 并发估算）：

| 时段 | 单轮耗时 | 轮间隔 | 单只标的再次采集周期 |
| --- | --- | --- | --- |
| 交易时段 | ≈ 46 min（每只节流均值 165s） | 0 | ≈ 46 min |
| 非交易时段 | ≈ 50 min（每只节流均值 180s） | 30 min | ≈ 80 min |

## 4. 影响面

- 涉及模块/文件：`config.py`、`models/stock_monitor.py`（`monitor_loop` / `get_stock_data` / 新增 `_fetch_delay_range`）、
  6 个测试的 `FakeConfig`、`tests/test_offhours_collection.py`（新）
- 涉及数据表 / 是否需要迁移：**无**
- 是否影响既有数据：否（只是写得更勤；收盘价 / 当日日线会补上）
- 是否需要新增/修改配置：**需要** 3 个（均有默认值，不配即按上表运行）

## 5. 实施要点

- **"功能照旧"是硬要求**：非交易时段不是"降级采集"，而是同一条 `check_and_alert` 链路完整跑一遍，
  包括价格 / 估值告警与指标组合告警（冷却照常）。
- 频率只由两个旋钮控制（轮间隔 + per-stock 节流），不引入"只采不判"这类半套逻辑——
  半套逻辑会让"为什么这条没告警"难以解释。
- 风险：收盘后也在打雪球 API，请求量上升；已有 Token 失效 / 限流退避（`XUEQIU_BACKOFF_SECONDS`）兜底，
  真被限流时整轮跳过、退避结束再试。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 非交易时段**仍然**调用 `_process_stocks`（不再 continue） | `tests/test_offhours_collection.py` | ✅ |
| 非交易时段轮间隔 = `MONITOR_OFF_HOURS_ROUND_INTERVAL` | 同上 | ✅ |
| 交易时段轮间隔 = `MONITOR_ROUND_INTERVAL`（默认 0） | 同上 | ✅ |
| per-stock 节流区间按时段切换 | `_fetch_delay_range` 用例 | ✅ |
| 全量回归 | `stockenv\Scripts\python.exe tests/run_all.py`（`FLASK_DEBUG=0`） | ✅ 578 用例全通过（新增 5 个） |

- 实际验证到的范围：主循环的时段分支与休眠参数、节流区间选择、全量回归（573 → 579）。
- **未验证**的范围（明确写出来）：
  1. **真实雪球表现**：未连真实 API，收盘后的实际请求量是否会触发限流需观察日志
     （`xueqiu_backoff_reason` / `get_status()['xueqiu_backoff_remaining']`）；
  2. **收盘价补采时机**未实测：理论上 15:00 后第一轮即采到，但该轮内标的仍在按上一时段的节流窗口 sleep，
     实际落库时间可能延后到 15:0x~15:5x；
  3. 未做长时间挂机验证（跨午休 / 周末）。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/004-monitor-service.md` 已更新（术语表、§3.2 主循环、验收条件 3 / 5）
- [x] `../PROGRESS.md` 已更新
- [x] `../README.md` 已同步（进行中变更清单）
- [x] 决策记录：无需新增（用户明确要求，取舍只有"停采 vs 慢采"且已定）
- [ ] 本目录已移入 `../archive/changes/`（待观察一轮真实收盘后的日志后归档）
