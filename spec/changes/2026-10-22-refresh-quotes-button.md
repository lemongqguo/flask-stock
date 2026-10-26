# 变更：订单列表新增「刷新行情」按钮

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入**（按钮交互待人工确认） |
| 类型 | 新增能力（页面刷新） |
| 触发 | 用户要求：列表页「添加订单」按钮左边加一个「刷新行情」按钮（设计稿 `design-preview/screens/orders.html` 第 65 行已有该按钮） |
| 关联规格 | [002 股票订单管理](../current/002-stock-order.md)、[008 前端 UI](../current/008-frontend-ui.md) |
| 验证 | 全量 **264 用例通过**（新增 `tests/test_refresh_quotes.py` 11 个）；真实调用验证：HTTP 200、耗时 **0.005s**、雪球 SDK 调用 **0 次**、只传 2 个 id 只返回 2 条 |

## 1. 需求

列表页 `page-head` 右侧：`刷新行情`（`btn btn-ghost` + `#i-refresh`）在「添加订单」（`btn btn-primary`）**左边**。

## 2. 用户纠正（首版做错了方向，如实记录）

首版做成了「后台线程刷新**全部活跃订单** + 跳过节流打雪球 API」，用户指出两点错误：

1. **不能全表刷新**——只刷新**当前页**的条数即可；
2. **不用请求雪球网 API**——监控线程在后台持续采集并落库，页面刷新只是**重新查库**。

第二点是根本性的：一次点击打几十次外部请求既慢又容易触发限流，而库里本来就是最新数据。
首版为此加的 `get_stock_data(throttle=...)` 参数、`refresh_quotes_async()` / `_refresh_quotes_worker()` / `manual_refresh`
**已全部回退**，`get_stock_data` 恢复原样（保留节流，不留下无用参数）。

## 3. 最终实现

- `StockMaster.get_quotes_by_ids(ids)`：一次 `LEFT JOIN stock_warehouse` 取回指定订单的
  `current_price / current_pe / current_pb`（**纯查库**）；DECIMAL 显式转 float，避免 jsonify 序列化成字符串；
- `POST /stock/refresh_quotes`：入参 `{'ids': [...]}`（前端传当前页可见行的 `data-id`），
  只接受正整数并**限制 200 个**（防止构造超大请求把整表拉出来）；无 ids 时返回空，**绝不退化成全表刷新**；
- 前端：收集 `#rows tr[data-id]`，按 `data-col="price|pe|pb"` 局部更新单元格，显示「已刷新 N 条」，**不整页 reload**；
- 只更新行情三列（现价 / PE / PB）。「52周最低」来自 K 线日线（一天一次），刷新它无意义，**不在刷新范围内**。

## 4. 已回退的内容

- `get_stock_data(stock_code, throttle=True)` 的 `throttle` 参数；
- `StockMonitor.refresh_quotes_async()` / `_refresh_quotes_worker()` / `manual_refresh` / `_refresh_lock`；
- `get_status()` 与 `build_system_status()` 里的 `refresh` 字段。

保留了 `_persist_quote()`（从 `check_and_alert` 抽出的回写方法，监控循环仍在用）。

## 5. 验证

真实调用（不 mock，盯雪球 SDK）：

```
当前页订单数: 10
HTTP 200  耗时 0.005s
返回条数: 10
雪球 SDK 调用次数: 0        ← 关键：不请求外部接口
id=83 华厦眼科  现价 68.98 (库 68.98)  PE -79.81  PB 1.26
id=84 千金药业  现价 26.20 (库 26.20)  PE  13.28  PB 1.81
只传 2 个 id → 返回 2 条
```

回归用例覆盖：只返回请求的 ids、数值与直接查询一致、**不调用 `get_stock_data`**、无 ids 不刷新全表、ids 上限 200、未登录 302、按钮位置与行标识契约。

## 6. 未验证

- **按钮点击后的交互效果**（旋转图标、单元格局部更新、「已刷新 N 条」提示）：无浏览器自动化，需人工确认；
- 多进程部署下页面读到的是本进程的数据（与既有已知限制同类，纯查库不受影响）。
