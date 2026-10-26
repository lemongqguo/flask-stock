# 003 告警阈值与告警历史（Alarm Thresholds & History）

**状态**：已实现　|　**最后更新**：2026-10-26
**实现**：`views/stock_orders.py`、`models/stock_pe.py`、`models/stock_pb.py`、`models/stock_warehouse.py`、`models/stock_alarm.py`、`utils/alarm_rules.py`、`utils/alarm_throttle.py`、`database.py`
**相关变更**：[2026-10-21 M1 缺陷治理](../changes/2026-10-21-m1-defect-hardening.md)（已修复 D-03 冷却、D-09 索引）、
[2026-10-21 告警表补齐类型字段](../changes/2026-10-21-alarm-type-fields.md)（新增 3.5 节）、
[2026-10-23 账户设置](../archive/changes/2026-10-23-account-profile.md)（新增 3.6 节：通知开关与每日汇总）

---

## 1. 场景

用户为每只股票设置三类阈值（价格档位 / PE 档位 / PB 档位），系统在下探到阈值时产生告警并邮件通知；
用户可在"告警历史"页回溯过去触发过哪些告警。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| 三档 | 每类阈值各有 `valueone` / `valuetwo` / `valuethree` 三个档位，数值上通常一档最宽松、三档最严苛 |
| 建仓告警 | 当前价 **低于等于** 某档建仓价时触发 |
| 卖出告警 | 当前价 **高于等于** `sell_rate` 时触发 |
| 告警记录 | `stock_alarm` 表中的一条文本记录，`alarm_text` 描述触发内容 |

## 3. 当前有效行为

### 3.1 阈值设置 `GET/POST /stock/alarm_settings`

- 通过 `alarm_type` 参数在三个分支间切换（分支起点 `stock_orders.py:350 / 382 / 408`）：
  - `warehouse`：当前价、卖出价 `sell_rate`、三档建仓价、股息率、备注
  - `pe`：三档 PE 阈值
  - `pb`：三档 PB 阈值
- 保存到对应子表（`stock_warehouse` / `stock_pe` / `stock_pb`），按 `stock_master_id` 关联。

### 3.2 触发判定（由监控服务调用，见 [004](./004-monitor-service.md)）

判定逻辑集中在 `utils/alarm_rules.py` 的纯函数中（无数据库/网络依赖，可单测）：

- 卖出 `check_sell`：`current_price >= sell_rate`；`sell_rate` 未设置或当前值缺失时不告警。
- 三档 `determine_lower_gear`：先判第一档，命中后再判第二档，再命中则判第三档，返回 1/2/3：
  - 建仓价：`current_price <= stock_value{N}`
  - PE：`pe_ttm <= pe_value{N}`
  - PB：`pb <= pb_value{N}`
  - 第一档阈值未设置（`None`/`0`）时整类告警关闭；第二/第三档未设置时退化为较低档位。
- 命中后统一走 `StockMonitor._emit_alarm`：**冷却检查 → `StockAlarm.create` → `send_mail`**。

### 3.3 告警冷却（去重）

- 冷却 key：`{stock_master_id}:{类型}[:{档位}]`（`make_alarm_key`），例如 `12:price:2`、`12:sell`。
- 同一 key 在 `ALARM_COOLDOWN_SECONDS`（环境变量，默认 14400 秒 = 4 小时）内**只产生一条记录、只发一封邮件**。
- 冷却期由 `AlarmThrottle` 提供：`should_fire(key)` 放行并记录时间，`clear(key)` / `clear_prefix(prefix)` 撤销冷却。
- 条件消失即撤销冷却：价格回到阈值上方时清除对应 key，使再次下探能**立即重新告警**，而不是继续被冷却挡住。
- `ALARM_COOLDOWN_SECONDS=0` 表示不限制（每次命中都告警），行为回退到历史版本。

### 3.4 告警历史 `GET /stock/recent_alarms`

- 分页展示，支持关键字搜索与起止日期筛选。
- 结果按 `alarm_time DESC` 排序。
- `stock_alarm` 表已建索引 `idx_alarm_time(alarm_time)` 与 `idx_stock_alarm(stock_master_id, alarm_time)`；`database.py` 对存量库做幂等补索引迁移。
- **按归属可见**（2026-10-26）：`stock_alarm` 自身没有归属列，靠 `JOIN stock_master` 继承订单的 `user_id`。
  普通用户只见自己订单产生的告警，**KPI `get_stats()` 与列表同口径**过滤；管理员见全量。
  侧栏「指标监控」徽标（`count_recent_indicator`）同样按归属计数。

### 3.5 告警类型与通知状态

`stock_alarm` 早期只有 `alarm_text`，无法按类型筛选。现补充四个字段：

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `alarm_type` | `price` / `sell` / `pe` / `pb` / `indicator` / `unknown` | 告警类型，供历史页按类型筛选 |
| `alarm_subtype` | `combo`；历史数据另有 `low52w` / `drawdown` / `rs20` / `rs5` | 指标类细分（见 [006](./006-stock-indicator.md)）。2026-10-23 起指标只写 `combo`（四项同时成立），四个旧取值是此前按单指标告警时留下的真实记录，页面仍识别 |
| `alarm_level` | 1 / 2 / 3 | 价格与估值的档位，其余为 NULL |
| `notify_status` | `pending` / `sent` / `failed` / `skipped` / `unknown` | 邮件送达结果 |

- **写入**：`StockAlarm.create()` 落库时写入类型字段，`notify_status` 初始为 `pending`；发信后由 `_emit_alarm` 回写为 `sent` / `failed` / `skipped`（邮件关闭或无收件人为 `skipped`，**不是** `failed`）。
- **冷却 key**：`{stock_master_id}:{type}:{subtype|档位}`。指标类自 2026-10-23 起只有 `combo` 一个子类型（四项 AND 组合），
  故指标只占一个冷却 key；四个旧子类型的 key 只对应历史告警。
- **存量回填**：`init_database()` 按 `alarm_text` 反推类型（关键词 + 档位正则），**无法识别的一律落 `unknown`**，不猜测。只处理 `alarm_type IS NULL` 的行，可重复执行。历史记录的 `notify_status` 无法还原，统一为 `unknown`。

### 3.6 告警通知开关（2026-10-23 账户设置）

- 账户设置 → 告警通知四个开关（价格 / PE·PB / 指标 / 每日汇总）落 `user_notify_pref`，
  解析入口统一在 `models/account_settings.py`（`notify_enabled`），与页面显示同源。
- 开关关系：`price`、`sell` 受"价格告警"控制；`pe`、`pb` 受"PE / PB 告警"控制；`indicator` 受"指标告警"控制；
  **未登记的类型一律放行**（宁可多发一封，也不能静默吞掉告警）。
- 关掉某类告警 = **邮件跳过（`notify_status=skipped`），告警仍照常落库**：历史页依旧可查，
  且 `skipped` 不计入「发送失败」统计（失败只统计 `failed`）。
- 收件人解析 `resolve_alarm_recipients()`：环境变量 `ALARM_RECIPIENTS` 优先，为空时回退到账户邮箱；
  **页面展示与发信调用同一个函数**，不存在"页面写 A、邮件发到 B"。
  这条是**全局口径**的收件人，仅用于"没有归属人"的场景（如每日汇总、监控的兜底分支）。
- **按订单归属人收件**（2026-10-26）：告警邮件先取**订单归属人**的邮箱（`recipients_for_user(user_id)`），
  并套用**该用户自己**的通知开关（`prefs_for_user(user_id)`）——谁的票触发就通知谁、按谁的开关决定发不发。
  归属人没填邮箱时回退环境变量 `ALARM_RECIPIENTS`；归属缺失（存量数据）时走上面的全局口径。
  仍有**一个例外**：**每日汇总邮件**不做逐用户拆分，**保持全局口径**，见 §5 已知限制。
- **每日汇总邮件**：开关打开后，每天在 `DAILY_SUMMARY_TIME`（默认 `08:30`，配置见 `.env.example`）之后发一次，
  内容为近 24 小时告警（分类型计数 + 最近 8 条）；无告警不发空邮件；成败都只尝试一轮，状态记在 `stats['daily_summary']`。

## 4. 验收条件

1. 保存阈值后重新进入设置页，能看到已保存的值。
2. `current_price <= stock_valuetwo`（且未触及第三档）时，产生"第二档"告警，不误报为第一档（按三档→二档→一档的优先级）。
3. `current_price >= sell_rate` 时产生卖出告警。
4. PE / PB 阈值命中时分别产生对应类型告警。
5. 告警历史页可按日期区间筛选出对应记录，且最新告警排在最前。
6. 删除订单后其告警记录随外键级联清除。
7. **条件持续满足时，冷却窗口内只产生 1 条记录、只发 1 封邮件**（回归用例 `tests/test_alarm_throttle.py`、`tests/test_monitor_service.py`）。
8. **条件消失后再次满足，可立即重新告警**（冷却被 `clear` 撤销）。
9. 档位判定边界：`current == valueone` 判为第一档；`current == valuethree` 判为第三档。
10. 新告警写入 `alarm_type` / `alarm_subtype` / `alarm_level`，并在发信后回写 `notify_status`（回归用例 `tests/test_alarm_type.py`）。
11. 存量告警在 `init_database()` 时按文本回填类型，无法识别的落 `unknown`；重复执行安全。
12. 指标类自 2026-10-23 起按 `combo` 单键冷却：四项指标的 AND 组合成立才写一条告警；
    单条（如仅 52 周回撤达 35%）不再单独告警（回归用例 `tests/test_indicator_collect.py`、`tests/test_indicator_rules.py`）。
13. 告警历史与 KPI 按订单归属过滤：普通用户只见自己订单的告警，admin 见全量
    （回归用例 `tests/test_multi_user_ownership.py`）。
14. 告警邮件发给**订单归属人**，并按该用户自己的通知开关决定是否发送。

## 5. 已知限制

- ~~**告警无状态字段**~~（已解决）：`stock_alarm` 现已有 `alarm_type` / `alarm_subtype` / `alarm_level` / `notify_status`；仍**无"是否已读"字段**（暂无此需求）。
- **冷却状态仅存于进程内存**：单进程部署有效；多进程/多实例部署需改为共享存储。
- **冷却粒度到档位**：价格从第二档继续跌到第三档会各自告警一次，属预期行为；同一档位反复穿越则受冷却约束。
- 阈值设置未做档位间大小关系的合法性校验（例如三档价可以填得比一档高）。
- **负 PE 会命中档位**：亏损公司 `pe_ttm` 为负且必然小于正阈值，会产生 PE 告警；当前未做"负值不告警"的过滤（已由 `tests/test_alarm_rules.py` 锁定该行为，待产品决策）。
- **告警历史已按归属隔离**（2026-10-26 起），不再全体可见；仍有两个残留：
  - **每日汇总邮件是全局口径**（见 §3.6）：汇总所有用户近 24h 告警后发到全局收件人。
    若有人开启「每日汇总」，会先把这里改造成逐用户发送，否则就是跨用户泄露。
  - 告警记录本身没有独立的归属列，删除归属订单会连带删掉告警（`stock_alarm` → `stock_master` 级联）。
