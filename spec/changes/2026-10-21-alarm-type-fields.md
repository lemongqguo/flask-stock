# 2026-10-21 告警表补齐类型字段

| 项 | 值 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 行为变更 |
| 触发 | 告警历史需按「价格 / PE / PB / 指标」筛选并显示邮件送达状态；新功能「指标监控」需落库并区分 4 种子类型 |
| 关联规格 | [003 告警阈值与告警历史](../current/003-alarm-thresholds.md) |
| 验证 | `python tests/run_all.py` → **189 用例全部通过**（原 165，新增 24）；存量库已迁移并回填 **1590 条** |

---

## 1. 问题与动机

`stock_alarm` 只有 `alarm_time` / `alarm_text`，**无类型、无档位、无通知状态**（已在 003 「已知限制」中明确记录），前端只能靠文本解析。直接后果有三：

1. 告警历史页的「按类型筛选」做不出来（前端无字段可用）；
2. 「邮件失败」筛选做不出来（无通知状态字段）；
3. **指标监控（见 [2026-10-21 指标监控](./2026-10-21-stock-indicator.md)）的告警无法表达子类型**，且冷却 key 无法区分 4 种指标，会互相挡住。

本变更是「指标监控」能落库、能筛选、能统计的**前置条件**。

---

## 2. 变更内容

### 2.1 `stock_alarm` 新增字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `alarm_type` | VARCHAR(16) | `price` / `sell` / `pe` / `pb` / `indicator` / `unknown` |
| `alarm_subtype` | VARCHAR(16) NULL | 指标细分：`low52w` / `drawdown` / `rs20` / `rs5` |
| `alarm_level` | TINYINT NULL | 档位 1 / 2 / 3（价格与估值用） |
| `notify_status` | VARCHAR(16) | `pending` / `sent` / `failed` / `skipped` / `unknown` |

新增索引 `idx_alarm_type (alarm_type, alarm_time)`（类型筛选会频繁 `WHERE` + `ORDER BY`）。

### 2.2 存量数据回填

按 `alarm_text` 关键词尽力解析：

| 文本特征 | 回填值 |
| --- | --- |
| 含"卖出" | `sell` |
| 含 "PE" | `pe` |
| 含 "PB" | `pb` |
| 命中价格档位 | `price` |
| **无法识别** | **`unknown`**（已与产品确认，不猜测） |

`notify_status` 存量同样填 `unknown`（历史记录无法得知当时发送结果）。

### 2.3 存量库幂等迁移

`CREATE TABLE IF NOT EXISTS` 不会改动已有表，因此仿照现有 `_INDEX_MIGRATIONS` 新增 `_COLUMN_MIGRATIONS`：先查 `information_schema.COLUMNS`，缺列才 `ADD COLUMN`，可重复执行。

### 2.4 冷却 key 扩展

`make_alarm_key` 由 `{stock_master_id}:{类型}[:{档位}]` 扩展为 `{stock_master_id}:{type}:{subtype|level}`，使 4 种指标各自独立冷却，互不遮挡。

---

## 3. 行为变化

| 场景 | 变更前 | 变更后 |
| --- | --- | --- |
| 告警历史筛选 | 仅关键字 / 日期区间 | 可按类型、邮件状态筛选 |
| 指标告警冷却 | 无此类型 | 4 种指标各自独立冷却 |
| 历史记录类型 | 无 | 可识别的显示类型；不可识别显示「未知」 |
| 邮件发送结果 | 无从得知 | `notify_status` 回写 |

---

## 4. 验证

新增 `tests/test_alarm_type.py`（24 个用例）：

- 新增告警正确写入 `alarm_type` / `alarm_subtype` / `alarm_level`；
- 存量回填：可识别的解析正确、**无法识别的落 `unknown`**；
- 冷却 key 按 `subtype` 隔离（`12:indicator:drawdown` 与 `12:indicator:rs20` 互不影响）；
- `create` 默认 `notify_status='pending'`、异常返回 `None`；`update_notify_status` 空 id 短路、异常返回 False。

**存量库实测**（`python database.py`）：

| 项 | 结果 |
| --- | --- |
| 补字段 | `alarm_type` / `alarm_subtype` / `alarm_level` / `notify_status` 均已添加 |
| 补索引 | `idx_alarm_type` 已创建 |
| 回填 | 1590 条；结果 `price` 1451 / `sell` 66 / `pb` 45 / `pe` 28，**零 unknown** |
| `notify_status` | 全部 `unknown`（历史无法还原发送结果，符合预期） |

回归：`python tests/run_all.py` → 189 用例全部通过；`Unknown column 'notify_status'` 报错归零。

### 测试期望变更（行为变更，非放宽断言）

`tests/test_monitor_service.py` 中 `EmitAlarmCooldownTest` 两处随接口变化更新：

- `StockAlarm.create` 返回值由 `bool` 改为**自增 id**（便于回写状态），mock 的 `return_value` 由 `True` 改为 `1001`；
- `test_alarm_persisted_before_mail` 的调用断言补充 `alarm_type` / `alarm_subtype` / `alarm_level` 三个关键字参数；
- 新增 `test_notify_status_written_back`，锁定"发信后必须回写状态"。

---

## 5. 遗留

- 回填基于文本关键词，历史记录仍会残留少量 `unknown`（可接受：仅影响筛选归类，不影响新记录）。
- `notify_status` 依赖邮件发送结果回写；发送抛错时必须捕获并更新为 `failed`，不得吞异常（遵守 `rules/development-standards.md` 第 3 节）。
- 冷却状态仍在进程内存（T-02 未闭环），多进程部署下本变更不改善这一点。
