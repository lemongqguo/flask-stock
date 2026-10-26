# 006 指标监控（Stock Indicator）

**状态**：**已实现**（批次一数据侧 + 批次二页面 / 页签 + **2026-10-23 组合触发**）　|　**最后更新**：2026-10-23

**相关变更**：[2026-10-21 指标监控](../changes/2026-10-21-stock-indicator.md)、
[2026-10-23 指标告警改「四项同时满足」组合触发](../changes/2026-10-23-indicator-combo.md)、
[2026-10-23 指标页 AI 快捷入口](../changes/2026-10-23-indicator-ai-shortcut.md)
**前置变更**：[2026-10-21 告警表补齐类型字段](../changes/2026-10-21-alarm-type-fields.md)

**实现位置**：`models/stock_indicator.py`、`utils/indicator_rules.py`、`models/stock_monitor.py`、
`views/stock_orders.py`（`indicator_list` / 告警设置 `indicator` 分支）、
`templates/indicator_list.html`、`templates/alarm_settings.html`、`templates/base.html`、
`config.py`（`IND_*`）、`database.py`（三张表）。

> **口径唯一来源是 `spec/`**：`design-preview/` 仅为开发前的样例预览，其阈值（如 52 周新低 3%）
> 与页面结构（如「全局规则编辑」）均已作废，一切以本文件与变更记录为准。

---

## 1. 场景

为每只监控中的股票计算长期与短期指标，**四项同时满足才落库告警并邮件通知**：

- **长期**：接近 52 周最低、52 周回撤超过 35%；
- **短期**：20 个交易日跑输基准 15%、5 日跌幅达基准的 2.5 倍。

四条之间是 **AND**（2026-10-23 起），不是 OR。理由：单条件命中的标的太多（尤其「52 周回撤 >35%」
是长期持续状态），单个条件筛出来的结果不符合策略。见
[变更 2026-10-23](../changes/2026-10-23-indicator-combo.md) 与
[ADR-004](../decisions/004-indicator-combo-semantics.md)。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| `high52w` / `low52w` | 雪球 `quote_detail` 直接提供的 52 周最高 / 最低价 |
| 52 周回撤 | `(现价 − high52w) / high52w`，负值 |
| 相对强弱（RS） | 个股涨跌幅 − 基准涨跌幅；20 日用**百分点差**，5 日用**倍数** |
| 基准 | 默认沪深300 `SH000300`，由 `IND_BENCH` 配置 |
| 组合信号（`combo`） | **四条同时成立**才算命中；是唯一的告警触发口径，也是唯一的 `alarm_subtype` 取值 |

## 3. 判定规则（当前有效约定）

| 指标 | 类型 | 判定式 | 参数（默认） |
| --- | --- | --- | --- |
| 52 周新低 | 长期 | `(现价 − low52w) / low52w ≤ 阈值` | `IND_LOW52W_NEAR_PCT = 5.0` |
| 52 周回撤 | 长期 | `(现价 − high52w) / high52w ≤ −35%` | `IND_DRAWDOWN_52W_PCT = 35` |
| 20 日跑输 | 短期 | `ret20(个股) − ret20(基准) ≤ −15%` | `IND_RS20_PCT = 15` |
| 5 日倍数 | 短期 | 两者均跌，且 `\|ret5股\| ≥ 2.5 × \|ret5基准\|`，且 `\|ret5股\| ≥ 3%`、`\|ret5基准\| ≥ 0.5%` | `IND_RS5_RATIO = 2.5`、`IND_RS5_MIN_DROP_PCT = 3.0`、`IND_RS5_MIN_BENCH_DROP_PCT = 0.5` |

**护栏的必要性**：倍数式在横盘市场会失真（基准跌 0.2%、个股跌 0.6% 即满足 2.5 倍），故要求个股跌幅 ≥ 3%、基准跌幅 ≥ 0.5%，否则不判定。

**新股处理**：上市不足 20 个交易日时 `ret_20d` 为 NULL，**该指标不参与判定**，避免误报。

### 3.1 组合关系（当前有效约定）

| 项 | 约定 |
| --- | --- |
| 组合判定 | `is_combo_hit(flags)` = 四条 **全部** 命中（AND）；纯函数，见 `utils/indicator_rules.py` |
| 单条命中 | **不告警**。四条 flag 仍逐项落库（`flag_low52w` / `flag_drawdown` / `flag_rs20` / `flag_rs5`），供排查与未来扩展 |
| 缺数据 | 该条判 `False` → 组合不成立 → 不告警（新股 / 基准未采集天然安全） |
| 告警条数 | 一次组合命中只产生 **一条** 告警：`alarm_type='indicator'`、`alarm_subtype='combo'`，正文列出四项实测值与阈值 |
| 冷却 key | `stock_id:indicator:combo`（单一 key，无 subtype 维度） |

四条 flag 仍保留的理由：组合是"告警口径"，单项是"数据事实"——查明为什么没告警时，需要看到是哪一条不成立。

## 4. 数据模型

### 4.1 `stock_indicator`

唯一键 `(stock_master_id, trade_date)`；`stock_master_id` 外键关联 `stock_master.id` 并级联删除。

字段：`price`、`high52w`、`low52w`、`pct_from_low52w`、`drawdown_52w`、`ret_5d`、`ret_20d`、`bench_code`、`bench_ret_5d`、`bench_ret_20d`、`rs_20d`、`rs_5d_ratio`、`flag_low52w`、`flag_drawdown`、`flag_rs20`、`flag_rs5`、`notified_at`、`created_at`、`updated_at`。

### 4.2 `stock_indicator_config`

单标的阈值覆盖，`stock_master_id` 唯一；字段留空表示继承全局环境变量。

### 4.3 `stock_bench_kline`

`bench_code`、`trade_date`、`close`，唯一键 `(bench_code, trade_date)`。
**建表理由**：现有 `stock_kline` 按 `stock_master_id` 关联订单，基准指数不是订单，无法复用；而相对强弱必须有基准历史收盘价。

## 5. 数据来源

| 数据 | 来源 |
| --- | --- |
| `high52w` / `low52w` | 雪球 `quote_detail`（无需自行计算 52 周窗口） |
| 个股 5 / 20 日涨跌幅 | 已有 `stock_kline` 收盘价 |
| 基准 5 / 20 日涨跌幅 | `stock_bench_kline`（交易时段每日采集一次） |

## 6. 通知与冷却

- **只有组合命中才写** `stock_alarm`：`alarm_type='indicator'`，`alarm_subtype='combo'`（2026-10-23 起）；
  单条命中只更新 `stock_indicator` 的 flag 列，不写告警、不发信；
- 发送邮件并回写 `notify_status`；同时更新 `stock_indicator.notified_at`（该列**不参与** upsert 的 UPDATE 子句，避免被后续刷新清掉）；
- **冷却 24 小时**（`IND_COOLDOWN_HOURS = 24`），价格 / 估值仍为 4 小时。
  理由：52 周回撤 > 35% 是持续状态，组合成立后仍会连续多日为真，短冷却会连发。
- 冷却 key 为单值 `combo`（不再按 4 种 subtype 分开）。历史数据里的 `low52w` / `drawdown` / `rs20` / `rs5`
  是**旧行为的真实记录**，保留原样，告警历史页仍识别这四种取值。
- 实现上指标走**独立的 `AlarmThrottle` 实例**（`StockMonitor._indicator_throttle`），
  `_emit_alarm` 通过新增的 `throttle` 参数接收，与价格 / 估值的冷却器互不干扰。
- **条件消失即清除该指标冷却**（`throttle.clear(key)`），再出现时能重新告警；语义与价格告警一致。

## 6.1 采集时机

| 环节 | 位置 | 频率 |
| --- | --- | --- |
| 基准指数日线 | `StockMonitor._maybe_sync_bench()`（每个监控轮次入口） | 每交易日一次；库内无数据或当天未同步才拉取 |
| 指标快照 | `StockMonitor._check_indicators()`（`check_and_alert` 第 4 步） | 每轮随行情更新，`(stock_master_id, trade_date)` 幂等 upsert |

`IND_ENABLED=0` 时全部跳过；雪球退避期内同步与告警均不发起。

## 7. 配置项

`IND_BENCH`、`IND_LOW52W_NEAR_PCT`、`IND_DRAWDOWN_52W_PCT`、`IND_RS20_PCT`、`IND_RS5_RATIO`、`IND_RS5_MIN_DROP_PCT`、`IND_RS5_MIN_BENCH_DROP_PCT`、`IND_COOLDOWN_HOURS`。

全部走环境变量，在 `config.py` 提供默认值并登记 `PROJECT_WIKI.md`。

## 8. 验收条件

1. `high52w` / `low52w` 取自雪球，不自行计算 52 周窗口。
2. 四条判定式与护栏边界均可被单测覆盖（含相等边界）。
3. 新股 `ret_20d` 为 NULL 时不产生 20 日相关告警。
4. 组合命中后写入 `stock_alarm` 且 `alarm_subtype='combo'`；**单条命中不写告警**（四项齐备才算有效信号）。
5. 同一标的 24 小时内只通知一次（`indicator:combo` 单键冷却）。
6. 单只标的取数异常不影响整轮循环。
7. `stock_indicator` 按 `(stock_master_id, trade_date)` 幂等 upsert。
8. `/indicator` 页面能列出每只标的的最新快照；**无快照的标的显示「未采集」而不是 0%**。
9. 页面只显示**组合结论**（满足，已告警 / 未满足 / 未采集），不展示四条指标各自的命中角标；
   KPI 为「监控标的 / 组合命中 / 未采集 / 最新快照」四个（长期 / 短期分组 KPI 已随 2026-10-23 变更取消）。
10. 告警设置页「指标告警」页签可保存单标的阈值，**留空即继承全局**；非法值不落库。
11. 侧栏「指标监控」导航项存在，折叠态下仍可通过 `title` 辨认。
12. 告警历史页「指标」徽标能识别 `combo`（组合信号）与四个旧取值（low52w / drawdown / rs20 / rs5）。

## 9. 页面与配置入口（批次二）

| 入口 | 位置 | 约定 |
| --- | --- | --- |
| 指标监控页 | `/stock/indicator` → `templates/indicator_list.html` | 4 个 KPI（监控标的 / 组合命中 / 未采集 / 最新快照）+ 每标的最新快照表（组合信号列）+ 判定规则说明（注明四项 AND） |
| 标的列 AI 快捷入口 | 同上（2026-10-23 起） | 每行标的右端「AI 分析」按钮，直达 `/stock/ai/?stock_id=<本行>`；**不新增列**，样式复用订单列表同款（`.cell-with-action` / `.row-ai`），纯 GET 链接；指标页用 `.row-ai.blue` 蓝色变体，**订单页保持紫色默认**（配色由 `--ai-hue` / `--ai-soft` 变量切换） |
| 表格列宽 | 同上（2026-10-23 起） | **七列全定宽**（300 / 110 / 180 / 120 / 140 / 200 / 110 = 1160），独立类 `.table-indicator` 的 `min-width` 等于定宽之和；窄屏只横向滚动（`.table-wrap`），不反向压列宽 |
| 分页 | 同上（2026-10-23 起） | `?page=` / `?per_page=`，**默认每页 10 条**（可选 5 / 10 / 20 / 50），>1 页才显示 `.pager`；KPI 只有「监控标的」是全量，命中 / 未采集是**本页**口径 |
| 侧栏导航 | `templates/base.html` | 图标 `#i-gauge`，折叠态靠 `title="指标监控"` 辨认 |
| 阈值配置 | 告警设置 → 「指标告警」页签 | 6 个字段按长期 / 短期分组，占位提示显示**当前全局默认值** |

页面只读库内快照，**不发起任何行情请求**（行情由监控线程采集落库）；保存阈值后重定向回
`?tab=indicator`，避免用户存完被弹回「价格告警」页签。数据访问走 `StockIndicator.get_latest_batch()`
与 `StockIndicatorConfig.get_map()` 两次批量查询，不做逐标查询。

## 10. 已知限制

- 指标监控页**分页展示**（2026-10-23 起，默认每页 10 条，可选 5 / 10 / 20 / 50）；
  翻页顺序由 `BaseModel.get_all` 的 `ORDER BY id DESC` 保证稳定；KPI 中只有「监控标的」是全量，
  「组合命中 / 未采集」是**本页**口径（避免误读为"翻页后命中数变了"）。
- 相对强弱以「交易日」为单位；`stock_kline` 缺失交易日时按现有数据近似，可能与真实交易日数有偏差。
- 基准指数日线采集失败时，相对强弱指标不参与判定 → 组合必然不成立（不误报，也不告警）。
- **四项 AND 使告警非常稀少属预期**：单条（尤其 52 周回撤）命中再也不会单独通知；排查"为什么没告警"只能看库内 flag 列或页面规则说明，页面不展示逐项命中角标。
- 冷却状态仍在进程内存（见 T-02）。
- 外键列 `stock_master_id` 为 `INT` 而非规格草案中的 `BIGINT`（与 `stock_master.id` 对齐，否则 MySQL errno 150 拒建外键）。
- 三张表已在部署库真实建出，页面与阈值覆盖读写已实跑验证（变更记录 8.4）；**真实雪球采集链路尚未跑完整周期**（基准日线与指标快照行数仍为 0 / 1）。
- UI 为模板契约测试（`tests/test_indicator_page.py`），无浏览器级回归，观感需人工核对。
