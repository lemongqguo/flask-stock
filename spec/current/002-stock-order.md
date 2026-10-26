# 002 股票订单管理（Stock Order CRUD）

**状态**：已实现　|　**最后更新**：2026-10-26　|　**实现**：`views/stock_orders.py`、`models/stock_master.py`、`models/stock_warehouse.py`、`models/base.py`、`utils/access.py`
**相关变更**：[2026-10-21 M1 缺陷治理](../changes/2026-10-21-m1-defect-hardening.md)（已修复 D-07 SQL 构造缺陷、D-10 死变量）、
[2026-10-26 多用户数据隔离](../archive/changes/2026-10-26-multi-user-ownership.md)（归属 / 可见性 / 按人唯一）

---

## 1. 场景

用户把自己关注的股票登记为一条"订单"，维护名称、代码、目标 PE/PB，以及三档建仓价与卖出价。
订单是监控的输入源：`status=active` 的订单才会被后台监控线程拉取轮询。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| 主订单 `stock_master` | 一条被监控的股票记录，**归属某个用户**（`user_id`）；`stock_code` 在**同一用户内**唯一（如 `SZ002027`） |
| 归属 `user_id` | 订单属于谁。写入时取当前登录用户（服务端），不可通过表单修改 |
| 可见范围 `owner_user_id` | 查询参数：`None` = 管理员全量，`int` = 仅该用户，哨兵 `NO_ACCESS` = 空集。见 `utils/access.py` |
| 仓库 `stock_warehouse` | 持仓侧数据：当前价、卖出价、三档建仓价、股息率 |
| 激活 `status=active` | 纳入监控轮询；`inactive` 不轮询 |
| 三档建仓价 | `stock_valueone` / `stock_valuetwo` / `stock_valuethree` |

## 3. 当前有效行为

### 3.1 列表 `GET /stock/list`

- **可见范围**：普通用户只见自己名下（`stock_master.user_id` = 当前用户）；管理员（`users.role='admin'`）见全量。
  页头统计 `total / active / inactive / 触发告警` 与列表**同口径**过滤。
- 分页：`per_page` 白名单 `5 / 10 / 20 / 50`，超范围回落默认值。
- 支持关键字搜索（模型层按 `search_fields` 拼 `LIKE`）。
- 每行附加最近一次 K 线信号（`StockKline.get_latest_signal`）用于列表展示图标。
- 每行附加近 52 周（自然日 365 天）最低价（`StockKline.get_low_52w_batch`）；**批量查询**取本页订单，无近一年 K 线时显示 `—`（不显示 0，避免误读）。
- 列顺序固定为：**标的 / 现价 / 52周最低 / 卖出价 / 当前 PE / 当前 PB / K线信号 / 状态 / 创建时间 / 操作**（回归用例 `tests/test_low_52w.py` 整体锁定，改动需先改用例）。
- 页头统计：`total` / `active` / `inactive` / `thread_count` / `monitor_running`。

### 3.2 创建 `GET/POST /stock/create`

- 创建主订单，并同时创建 `stock_warehouse`、`stock_pe`、`stock_pb` 三条子记录（即使未填阈值也建空记录）。
- **`user_id` 恒等于当前登录用户**，由服务端从 session 取；表单里塞任何 `user_id` 都无效。
- 插入后用自增主键回查（`execute_insert`），**不再按 `stock_code` 回查**——
  同一代码可被不同用户各自持有，按代码查会拿到别人的那一条。
- **同代码查重限定在自己名下**：只有当自己名下已有该代码时才报「订单代码已存在」。
  唯一性由数据库约束 `UNIQUE KEY uk_user_code (user_id, stock_code)` 兜底（[ADR-005](../decisions/005-per-user-stock-code-uniqueness.md)）。

### 3.3 编辑 `GET/POST /stock/edit/<int:id>`

- 更新主表字段，并对三张子表执行"存在则 update，否则 create"。

### 3.4 删除 `POST /stock/delete/<int:id>`

- 删除主订单，子表记录依赖外键 `ON DELETE CASCADE` 一并清理。

### 3.5 数据访问

- 所有读写经 `models/base.py` 的 `BaseModel`（`execute_query` / `execute_update` / `get_all` / `get_by_id` / `delete_by_id`）。
- 搜索条件由 `BaseModel.build_search_where()` 统一构造：
  - 只有 `search_fields` 非空**且**关键字非空时才追加 `WHERE`，杜绝裸 `WHERE `；
  - 字段名来自类定义并经标识符白名单校验（`isalnum` + `_`），关键字一律 `%s` 参数化；
  - 返回 `(where_sql, params)`，数据查询与 COUNT 查询复用同一条件。
- `get_all` 对 `page` / `per_page` 做下限保护（至少为 1），不会产生负 `OFFSET`。
- 连接来自 `config.get_pool()`（DBUtils `PooledDB`，**惰性创建**：首次 `get_connection()` 时才建池），请求结束由连接池回收。

### 3.6 切换监控状态 `POST /stock/toggle_status/<int:id>`（新增）

- 列表页状态列为内联开关，点击后 `active` ↔ `inactive` 取反切换；
- **目标状态由服务端读取库内当前值后取反**，不接受客户端传值（防止写入非法状态）；
- 切换后重定向回原列表，`next` 保留 `page` / `per_page` / `search`；`next` 必须是站内相对路径，否则回落 `/stock/list`（防开放重定向）；
- 落库复用 `StockMaster.update(id, status=...)`；监控线程无需配合，`get_active_stocks()` 只取 `active`，下一轮轮询即生效；
- 注意：`StockMaster.get_by_id()` 返回的是 **dict 行**（`BaseModel.execute_query` 结果），取字段用 `stock.get('status')`，不是属性访问。
- **注意：两个模型的返回类型不一致**——`StockMaster.get_by_id()` 返回 dict，而 `StockWarehouse / StockPe / StockPb.get_by_stock_master_id()` 返回**模型对象**（要用属性访问）。写视图/测试前必须先确认具体模型的返回类型。
- **现价存 `stock_warehouse.current_price`，`stock_master` 没有该列**（master 只有 `current_pe` / `current_pb`）。列表页靠 `LEFT JOIN stock_warehouse sw` 取 `sw.current_price`；编辑页必须单独查 warehouse，不能写 `stock.current_price`（恒为空）。
- 订单不存在 / 更新失败均 `flash` 提示并回列表；失败走 `logger.exception`。

### 3.7 归属与可见性（2026-10-26）

> 完整变更：[2026-10-26 多用户数据隔离](../archive/changes/2026-10-26-multi-user-ownership.md)；
> 为什么允许同代码跨用户重复：[ADR-005](../decisions/005-per-user-stock-code-uniqueness.md)。

1. **归属**：每条订单有且仅有一个归属用户（`stock_master.user_id`，外键 `users(id) ON DELETE RESTRICT`）。
   下游 `stock_warehouse / stock_pe / stock_pb / stock_alarm / stock_kline / stock_indicator /
   stock_indicator_config / stock_ai_report` 都靠 `stock_master_id` 关联，**归属天然继承，无需各自加列**。
2. **可见性**：普通用户只见自己名下；`role='admin'` 见全量。作用域覆盖——
   订单列表、指标监控页、告警设置、告警历史（含 `get_stats()` KPI）、K 线 API、
   `POST /stock/refresh_quotes`、AI 页与 `/stock/ai/api/search`、侧栏「指标监控」徽标。
3. **写权限**：`edit / delete / toggle_status / alarm_settings 保存 / AI 的 analyze 与 ask` 先取行、
   再用 `utils.access.can_manage()` 校验。不匹配一律 **flash 后重定向**（或 API 返回 403），**不落库**，
   提示统一为「订单不存在或无权访问」——不回显"存在但你看不了"，避免泄露他人订单的存在性。
4. **管理员可视即可管**：`can_manage()` 中 admin 恒 True。要改成"只读 Overview"只需删掉该函数里 `is_admin()` 分支。
5. **同一代码可跨用户重复**：唯一键为 `(user_id, stock_code)`。代价是行情 / K 线按人重复落库，
   由监控线程的**本轮结果共享**抵消外部请求量增长。
6. **判定入口唯一**：`utils/access.py`。任何地方都不要自己拼 `WHERE user_id = `。
7. **失败关闭**：归属缺失或会话不完整 → 不可见、不可改（哨兵 `NO_ACCESS` 生成 `1 = 0`）。

## 4. 验收条件

1. 创建订单后，`stock_master` 与 `stock_warehouse`、`stock_pe`、`stock_pb` 各有一条关联记录。
2. 同一 `stock_code` 不允许重复创建。
3. 编辑后列表页立即反映新值；`status=active` 的订单出现在监控待拉取集合中。
4. 删除订单后，其 PE/PB/告警/K线记录一并消失（外键级联）。
5. 分页参数传入非白名单值（如 `per_page=999`）时不报错，回落到默认分页大小。
6. 列表每行能正确显示最近一次信号图标（金叉 / 死叉 / 震荡 / 无数据）。
7. **对未定义 `search_fields` 的模型传入关键字，不产生裸 `WHERE`，查询正常返回**（回归用例 `tests/test_base_query_builder.py`）。
8. 数据查询与 COUNT 查询的 `WHERE` 子句完全一致，分页总数正确。
9. `page=0` / `page=-5` / `per_page=0` 时不抛异常，`OFFSET` 不为负。
10. 点击状态开关后取反落库并回到原分页位置；伪造 `status` 字段无效；`next` 为站外地址时回落 `/stock/list`（回归用例 `tests/test_status_toggle.py`）。
11. 普通用户看不到别人名下的订单（列表、指标页、告警设置、告警历史、AI 页与搜索、K 线 API 全部同口径）；
    admin 看到全量。
12. 直接请求 `/stock/edit|delete|toggle_status/<别人的 id>` → 一律被拦且**不落库**；
    `/stock/api/kline/<别人的 id>` → 403。
13. 新建订单的 `user_id` 等于当前登录用户；表单里伪造 `user_id` 无效。
14. 同一 `stock_code` 可被不同用户各持有一条；同一用户重复添加则被唯一键挡下。
15. 以上 11~14 由回归用例 `tests/test_multi_user_ownership.py` 锁定。

## 5. 已知限制

- 无软删除、无操作人记录。
- 创建/编辑无服务端表单校验组件（Flask-WTF 已引入但未使用），依赖前端约束。
- `stock_code` 依赖前端拼接交易所前缀（`SH`/`SZ`/`BJ`），服务端未校验格式。
- **无"转让订单"入口**：订单创建后 `user_id` 不可改，只能通过删掉重建实现转移到他人名下。
- **管理员列表没有「归属用户」列**：admin 看到全量但看不出每行属于谁，人多时会难以分辨。
- 同一只票被多人持有会导致行情 / K 线 / 指标快照**按人重复落库**（[ADR-005](../decisions/005-per-user-stock-code-uniqueness.md) 的既定代价）。
