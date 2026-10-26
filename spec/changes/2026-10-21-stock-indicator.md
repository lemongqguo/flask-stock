# 2026-10-21 指标监控（52 周 + 相对强弱）

| 项 | 值 |
| --- | --- |
| 状态 | **已合入**（批次一数据侧 + 批次二页面 / 页签；UI 观感待人工确认，真实库 / 真实行情未验证） |
| 类型 | 新增能力 |
| 触发 | 需求：长期指标（52 周最低 / 52 周回撤 > 35%）+ 短期指标（20 日跑输市场 15% / 5 日跌幅 2.5 倍），落库并邮件通知 |
| 关联规格 | 新建 `../current/006-stock-indicator.md`（验证后合入） |
| 前置 | [2026-10-21 告警表补齐类型字段](./2026-10-21-alarm-type-fields.md)、[2026-10-21 前端 UI 改版](./2026-10-21-frontend-redesign.md) |
| 验证 | 两批均通过全量回归（391 用例）+ 真实库页面 / 读写验证，见 [第 8 节](#8-实施与验证记录2026-10-22) |

---

## 0. 交付批次（2026-10-22 定）

产品决定分两批交付，**批次一先做数据侧，验收通过后再做页面**：

| 批次 | 范围 | 状态 |
| --- | --- | --- |
| 一 | 三张新表、`IND_*` 配置、判定纯函数、指标采集与落库、24h 冷却告警、自动化测试、文档同步 | 已完成 |
| 二 | `/indicator` 指标监控页、侧栏导航、告警设置「指标告警」页签（由 `disabled` 占位改为可编辑表单） | 已完成（2026-10-22） |

---

## 0.1 口径裁决（2026-10-22）

- **`design-preview/` 不作为项目约定**：该目录仅为开发前的样例预览，一切以实现所在的 `spec/` 为准。
  UI 只有视觉层面参考作用，阈值、数据结构、页面结构均以本变更与 `006` 为准。
- **52 周新低阈值取 5.0%**（`IND_LOW52W_NEAR_PCT = 5.0`），作废设计稿中的旧草案 `3.0%`。
- **阈值覆盖粒度为个股级**：`stock_indicator_config` 按 `stock_master_id` 唯一，留空继承全局环境变量；
  不做设计稿中的「全局规则编辑页」。

---

## 1. 判定口径（已与产品确认定稿）

| 指标 | 类型 | 判定式 | 参数 |
| --- | --- | --- | --- |
| 52 周新低 | 长期 | `(现价 − low52w) / low52w ≤ 5%` | `IND_LOW52W_NEAR_PCT = 5.0` |
| 52 周回撤 | 长期 | `(现价 − high52w) / high52w ≤ −35%` | `IND_DRAWDOWN_52W_PCT = 35` |
| 20 日跑输 | 短期 | `ret20(个股) − ret20(基准) ≤ −15%` | `IND_RS20_PCT = 15` |
| 5 日倍数 | 短期 | 两者均跌，且 `\|ret5(个股)\| ≥ 2.5 × \|ret5(基准)\|`，且 `\|ret5(个股)\| ≥ 3%`、`\|ret5(基准)\| ≥ 0.5%` | `IND_RS5_RATIO = 2.5`、`IND_RS5_MIN_DROP_PCT = 3.0`、`IND_RS5_MIN_BENCH_DROP_PCT = 0.5` |

**口径决策说明**：

- 「5 日低于市场 2.5 倍」采用**倍数式**而非「跑输 2.5 个百分点」，因为 20 日那条已用百分点差，两者语义互补（20 日看持续弱势、5 日看突发急跌），且倍数能自适应市场波动。
- 倍数式在横盘市场会失真（基准跌 0.2%、个股跌 0.6% 即满足 2.5 倍），故加**两道护栏**：个股跌幅 ≥ 3%、基准跌幅 ≥ 0.5%。
- 基准指数默认 **沪深300（`SH000300`）**：持仓标的均为其成分股；上证指数只覆盖沪市，会使深市标的的对比失真。走 `IND_BENCH` 可切换。
- 冷却：指标类 **24 小时**（`IND_COOLDOWN_HOURS = 24`），价格 / 估值仍为 4 小时。理由：52 周回撤 > 35% 是**持续状态**，会连续多日为真，4 小时冷却会导致一天多条、连发一周。

---

## 2. 新增数据表

### 2.1 `stock_indicator`（指标快照与命中标记）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT PK | 自增主键 |
| `stock_master_id` | BIGINT FK | 关联 `stock_master.id`，级联删除 |
| `trade_date` | DATE | 数据归属交易日；与 `stock_master_id` 组成唯一键 |
| `price` / `high52w` / `low52w` | DECIMAL(12,4) | 现价与 52 周高低（雪球原始值） |
| `pct_from_low52w` | DECIMAL(8,4) | 距 52 周低的百分比 |
| `drawdown_52w` | DECIMAL(8,4) | 52 周回撤（负值） |
| `ret_5d` / `ret_20d` | DECIMAL(8,4) | 个股 5 / 20 交易日涨跌幅 |
| `bench_code` | VARCHAR(16) | 基准指数代码，默认 `SH000300` |
| `bench_ret_5d` / `bench_ret_20d` | DECIMAL(8,4) | 基准同期涨跌幅 |
| `rs_20d` / `rs_5d_ratio` | DECIMAL(8,4) | 20 日相对强弱 / 5 日跌幅倍数 |
| `flag_low52w` / `flag_drawdown` / `flag_rs20` / `flag_rs5` | TINYINT | 四类判定是否命中（0/1） |
| `notified_at` | DATETIME NULL | 邮件通知时间；指标类默认 24 小时冷却 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

### 2.2 `stock_indicator_config`（单标的阈值覆盖）

`stock_master_id` 唯一；字段留空表示**继承全局环境变量**。用于「告警设置 → 指标告警」页签的个股级调参。

### 2.3 `stock_bench_kline`（基准指数日线）

`bench_code`、`trade_date`、`close`，唯一键 `(bench_code, trade_date)`。

**为什么必须新建**：现有 `stock_kline` 通过 `stock_master_id` 关联订单，而基准指数不是订单，无法复用该表。计算 5 / 20 日相对强弱**必须有基准的历史收盘价**，故单独建表。

---

## 3. 数据来源

| 数据 | 来源 |
| --- | --- |
| `high52w` / `low52w` | 雪球 `quote_detail` 直接提供，**无需自行计算 52 周窗口** |
| 个股 5 / 20 日涨跌幅 | 已有 `stock_kline` 收盘价 |
| 基准 5 / 20 日涨跌幅 | 新增采集基准指数日线 → `stock_bench_kline` |

---

## 4. 通知

命中即写 `stock_alarm`（`alarm_type='indicator'`，`alarm_subtype` 为具体指标）并发送邮件；冷却 24 小时；`notify_status` 回写发送结果。

---

## 5. 实施要点

- 判定逻辑抽为纯函数（对齐现有 `utils/alarm_rules.py` 的风格），便于单测；
- 采集复用监控循环，不新增线程；
- **新股上市不足 20 个交易日时 `ret_20d` 为 NULL，该指标不参与判定**，避免误报；
- 全部阈值走环境变量，在 `config.py` 给出默认值并登记 `PROJECT_WIKI.md` 配置章节。

### 5.1 与规格的两处偏离（2026-10-22 实施时确认）

| 项 | 规格写法 | 实现 | 理由 |
| --- | --- | --- | --- |
| 外键列类型 | `stock_master_id BIGINT` | `INT` | 外键列类型必须与 `stock_master.id`（INT）完全一致，否则 MySQL 报 errno 150 拒建外键；`id` 主键仍为 BIGINT |
| 基准采集位置 | 「复用现有 K 线采集逻辑」 | `StockBenchKline.sync_from_snowball()` 直接读雪球原始 dict | 走 `StockKline` 会引入 pandas 依赖，使判定逻辑不可脱离数值栈单测；kline 解析只是数行 dict 取值 |

---

## 6. 验证计划

新增 `tests/test_indicator_rules.py`（4 条判定式 + 护栏边界 + NULL 不判定）、`tests/test_indicator_collect.py`（落库与唯一键 upsert、幂等 + 监控链路告警与冷却）。回归 `python tests/run_all.py`。

---

## 7. 遗留

- 基准指数日线需新增采集任务（交易时段每日一次，已实现）。
- 相对强弱以「交易日」为单位，`stock_kline` 缺交易日时按现有数据近似，可能与真实交易日数有偏差。
- 指标监控页一次最多展示 200 只标的（`per_page=200`），超过需分页（当前监控上限 100/轮，暂不构成问题）。

---

## 8. 实施与验证记录（2026-10-22）

### 8.1 批次一改动清单

| 文件 | 改动 |
| --- | --- |
| `database.py` | 新增 `stock_indicator` / `stock_indicator_config` / `stock_bench_kline` 三张表（幂等建表） |
| `config.py` | 新增 `IND_*` 9 个配置项（含总开关 `IND_ENABLED`、`IND_BENCH`、`IND_COOLDOWN_HOURS`） |
| `utils/indicator_rules.py` | 新增：四条判定纯函数、两道护栏、`n_day_return`、`resolve_thresholds`、`evaluate_indicators`、`build_indicator_alarm` |
| `models/stock_indicator.py` | 新增：指标快照 upsert、单标的阈值覆盖、基准日线采集（不用 pandas） |
| `models/stock_kline.py` | 新增 `get_recent_closes()`（返回升序收盘价列表，给 5 / 20 日涨跌用） |
| `models/stock_monitor.py` | `quote_detail` 取值补 `high52w` / `low52w`；新增 `_check_indicators` / `_emit_indicator_alarm` / `_maybe_sync_bench`；`_emit_alarm` 新增 `throttle` 参数以支持指标独立冷却；`get_status` 暴露 `indicator_cooldown_seconds` |
| `.env.example` | 登记 `IND_*` 配置（注释说明默认可用、按需放开） |
| `tests/test_indicator_rules.py`、`tests/test_indicator_collect.py` | 新增 76 个用例 |

### 8.2 批次二改动清单（页面 / 页签）

| 文件 | 改动 |
| --- | --- |
| `views/stock_orders.py` | 新增 `/stock/indicator`（`indicator_list`）+ `_range_position()`；`alarm_settings` 增加 `alarm_type='indicator'` 分支（`_parse_indicator_thresholds` / `_global_indicator_thresholds`）；GET 时批量取回 `StockIndicatorConfig.get_map()`；保存后重定向 `?tab=indicator` |
| `templates/indicator_list.html` | 新增：4 个 KPI + 最新快照表（52 周区间条 / 回撤 / 5-20 日收益 / 四类徽标）+ 判定规则说明；缺数据渲染「—」「未采集」 |
| `templates/alarm_settings.html` | 「指标告警」页签去掉 `disabled`，替换为 6 字段表单（长期 / 短期分组，占位显示全局值）；四个页签共用 `active_tab` 决定 `on` / `hidden` |
| `templates/base.html` | 侧栏新增「指标监控」导航项（`#i-gauge`，带 `title`） |
| `static/css/theme.css` | 新增 `.ind-range` / `.ind-range-foot` / `.ind-flags`（52 周区间条复用既有 `range52-*`） |
| `models/stock_indicator.py` | 新增 `StockIndicator.get_latest_batch()`、`StockIndicatorConfig.get_map()`（各一次 IN 查询，避免逐标 N+1） |
| `utils/indicator_rules.py` | 新增常量 `DEFAULT_BENCH_CODE` |
| `tests/test_indicator_page.py` | 新增 26 个用例（路由 / 登录拦截 / 导航项 / 页面渲染 / 空态 / DB 异常降级 / 区间位置 / 阈值解析与保存 / 页签切换 / Decimal 预填格式） |

### 8.3 验证结果

全量回归（**项目自带虚拟环境** `stockenv`：Python 3.11 + numpy 1.24.3 + pandas 2.0.3）：

```powershell
stockenv\Scripts\python.exe tests\run_all.py
# Ran 391 tests ... OK  （0 失败 / 0 错误 / 0 跳过）
```

- 基线 289 → **391 个用例全部通过**：批次一新增 76、批次二新增 26，**无 skip**（此前因 numpy/pandas
  二进制不兼容而跳过的 12 个监控链路用例，在 `stockenv` 下全部实跑通过）。
- 单模块复核：`test_indicator_rules` 46、`test_indicator_collect` 30、`test_indicator_page` 26，均 OK。

> 注意：**必须用 `stockenv` 的解释器**。全局解释器（numpy 2.x）会让 import pandas 的模块直接崩溃。

### 8.4 真实环境验证（2026-10-22 补充，不 mock）

部署环境的 `.env` 已配置（`192.168.50.76:3306/uatstockdb`），`app` 导入时 `init_database()` 已实跑建表，据此补做：

| 验证项 | 结果 |
| --- | --- |
| 三张表建出 | ✅ `stock_indicator` / `stock_indicator_config` / `stock_bench_kline` 均存在于 `information_schema` |
| 幂等建表重复执行 | ✅ 应用多次启动未报错（`CREATE TABLE IF NOT EXISTS`） |
| `GET /stock/indicator`（真实库） | ✅ 200；4 个 KPI 渲染；91 只标的中无快照的显示「未采集」 |
| `GET /stock/alarm_settings?stock_id=1&tab=indicator` | ✅ 200；指标页签默认展开，6 个字段齐全 |
| 真实写入 `stock_indicator_config` | ✅ POST 后回读 `(low52w_near_pct=4.0000, drawdown_52w_pct=NULL, rs20_pct=12.0000)`——**留空确实落 NULL（继承全局）** |
| 保存后重定向 | ✅ `302 → /stock/alarm_settings?stock_id=1&tab=indicator` |
| 验证数据清理 | ✅ 已 `DELETE` 该行，`stock_indicator_config` 恢复 0 行（不污染 UAT 数据） |

### 8.5 未验证范围

- **真实雪球采集链路未跑通**：`stock_bench_kline` 与 `stock_indicator` 目前各 0 / 1 行，
  基准日线同步、指标随监控轮次写入、命中告警与邮件均未在真实行情下观察完整周期。
- **UI 仅模板契约测试**（`tests/test_indicator_page.py` 断言渲染出的 HTML），没有浏览器级回归；
  区间条位置、徽标配色等观感需人工核对。
- 指标监控页的排序 / 分页未做（按订单表顺序取前 200 只）。
- 邮件内容仅在单测层面验证文案，**未实际发信**。
