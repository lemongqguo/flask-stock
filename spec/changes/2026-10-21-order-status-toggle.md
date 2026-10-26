# 变更：订单列表内联切换监控状态

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 新增能力（交互 + 接口） |
| 触发 | 订单列表「状态」列长得像开关（`<span class="status on"><i class="switch">`），但点不动 —— 设计稿 `design-preview/screens/orders.html` 里它就是纯展示标签，后端也没有切换接口，改状态只能进编辑页 |
| 关联规格 | [002 股票订单管理](../current/002-stock-order.md)（新增 3.6 节） |
| 验证 | 全量 **210 用例通过**（新增 `tests/test_status_toggle.py` 8 个）；渲染核对 10 行各 1 个开关、每行仍 9 列 |

## 1. 问题

- 状态列视觉上是开关，用户自然会去点，但它是 `<span>`，无任何交互；
- 想改状态必须进编辑页 → 翻页找订单 → 选下拉 → 保存，路径过长；
- 后端无对应接口，前端无从下手。

## 2. 旧约定 → 新约定

| 项 | 旧 | 新 |
| --- | --- | --- |
| 状态列 | 纯展示 `<span>` | 可点击开关（`<button type="submit">` 包在 form 里，POST 提交） |
| 切换接口 | 无 | `POST /stock/toggle_status/<int:id>`，取反切换 `active` ↔ `inactive` |
| 目标状态来源 | — | **由服务端从库里读当前值再取反**，不接受客户端传值（避免非法状态值） |
| 切换后 | — | 重定向回原列表（保留 `page` / `per_page` / `search`），KPI 随之刷新 |

## 3. 影响面

- `models/stock_master.py`：**不改**，复用现有 `StockMaster.update(id, status=...)`（不新增模型方法，接口面最小）；
- `views/stock_orders.py`：新增 `toggle_status` 路由 + `_safe_list_url()` 站内跳转校验；
- `templates/stock_order_list.html`：状态列改为可提交开关；
- `static/css/theme.css`：`.status-switch` 样式；
- 监控线程无需改动：`get_active_stocks()` 只取 `active`，状态改变后下一轮轮询即生效。

## 4. 安全约束

- 路由加 `@login_required`；
- **不接受客户端传入的目标状态**，只做取反；
- 重定向目标 `next` 必须校验为站内相对路径（拒绝 `//host`、`http://`、反斜杠变体），杜绝开放重定向；
- 失败时 `logger.exception` 并 `flash`，不吞异常。

## 5. 实施说明

- 状态列改为 `<form><button type="submit" class="status switch-btn">`，外观沿用 `.status`（开关滑块、配色不变），只补 `cursor: pointer` 与 hover；
- 表单携带 `next = request.full_path`，切换后回到原来的分页 / 搜索位置；
- 目标状态取反后由 `StockMaster.update(id, status=...)` 落库；监控线程无需配合改动——`get_active_stocks()` 只取 `active`，下一轮轮询自动生效；
- 切换结果写 `logger.info`，失败 `logger.exception` + `flash`，不吞异常。

## 6. 实施陷阱：mock 掩盖了真实契约

首版上线后点击开关直接 500：

```
File "views/stock_orders.py", line 366, in toggle_status
    new_status = 'inactive' if stock.status == 'active' else 'active'
AttributeError: 'dict' object has no attribute 'status'
```

根因：`BaseModel.get_by_id()` 返回的是 **dict 行**（`execute_query` 结果的 `result[0]`），视图却按模型对象做属性访问。
而用例里替身写的是 `mock.Mock(status='active')`——属性访问在 mock 上永远成立，**真实路径一次都没被覆盖到**。

修正：

- 视图改用 `stock.get('status')`；日志里同样残留的 `stock.status` 一并修正；
- `tests/test_status_toggle.py` 的替身改为真实类型 `{'id': 1, 'status': 'active'}`，并在注释里写明原因；
- 补做**不 mock 的真实点击验证**（订单 92：active → inactive → 再切回 active，两次均 302，最终状态还原），确认真实路径可用。

已固化为硬约束（[开发规范第 7 节](../rules/development-standards.md)）：mock 必须复刻真实返回类型；接口类改动须额外做一次不 mock 的真实调用验证。

## 7. 验证范围

- `StockMaster.set_status()`：成功 / 失败（mock）；
- `toggle_status` 路由：取反正确、订单不存在时 flash 报错、`next` 非法时回落列表首页；
- 回归：全量 `python tests/run_all.py`；
- 人工：点击开关后状态与 KPI 同步刷新、chips 过滤仍生效。

**未验证**：并发点击（无锁，同其他 POST 一致）、多用户场景（项目本身不区分用户）。
