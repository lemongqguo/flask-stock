# 变更：修复订单编辑页「实时行情」现价不准

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 缺陷修复（展示取数错误） |
| 触发 | 用户反馈：订单列表→编辑里的「实时行情」数据不准确 |
| 关联规格 | [002 股票订单管理](../current/002-stock-order.md)、[008 前端 UI](../current/008-frontend-ui.md) |
| 验证 | 全量 **232 用例通过**（新增 `tests/test_form_quote.py` 4 个）；真实页面核对：订单 82 现价 46.91 = 库内 `warehouse.current_price`，行情时间 2026-10-22 09:41，阶梯 `data-current` 与卖出价提示均已恢复 |

## 1. 根因

`stock_master` 表**没有 `current_price` 列**（只有 `current_pe` / `current_pb`），现价由监控线程写入 **`stock_warehouse.current_price`**：

```python
# models/stock_monitor.py
StockMaster.update(id=stock.id, current_pe=..., current_pb=...)          # PE/PB → master
StockWarehouse.update_by_stock_master_id(stock_master_id=..., current_price=current)  # 现价 → warehouse
```

- 列表页 `get_all_with_details()` 用 `LEFT JOIN stock_warehouse sw` 取 `sw.current_price` → **正确**；
- 编辑页 `edit_stock()` 只查了 `StockMaster.get_by_id(id)` → 返回的 dict 里**根本没有 current_price 键**，模板 `stock.current_price` 恒为 `None`。

## 2. 影响面（同一根因的 3 处）

| 位置 | 现象 |
| --- | --- |
| 右侧 rail「实时行情 / 现价」 | 恒显示 **0.00** |
| 「卖出价」下方提示（现价 x，还需 y%） | 条件 `stock.current_price and warehouse.sell_rate` 恒假 → 提示不出现 |
| 三档阶梯「距现价百分比」 | `data-current` 恒为空 → 前端算不出百分比 |

## 3. 顺带修的丢数据路径

`edit_stock` 的 **POST 校验失败分支**只传了 `stock`，没传 `warehouse / pe_record / pb_record`：

```python
return render_template('stock_order_form.html', form_action='edit', stock=stock)
```

后果：`pe_memo` / `pb_memo` 的隐藏字段渲染成空串，用户改完再提交 → **已有 PE/PB 备注被清空**（与 2026-10-21 修掉的 `None` 字面量属同一类脏数据问题）。

## 4. 修复方案

1. 现价一律取 `warehouse.current_price`（与列表页 `sw.current_price` 同源），替换模板里 3 处 `stock.current_price`；
2. POST 校验失败分支改为与 GET 共用同一套上下文加载（stock + warehouse + pe + pb），不再缺字段；
3. rail 增加「行情时间」一行（取 `stock_master.updated_at`，随采集回写更新）——**暂停监控的订单不会采集**，只给数值会让人以为是实时的。

## 5. 不改的部分

- 不改采集逻辑与监控线程写库位置（现价存 warehouse 是当前数据模型，改动面过大）；
- 不改列表页（本来就是 JOIN 取数，正确）。

## 6. 实施说明

- 视图新增 `_form_context(stock)` 统一加载 `stock / warehouse / pe_record / pb_record`，GET 与三处 POST 失败分支共用；
- 现价、阶梯 `data-current`、卖出价提示三处统一取 `warehouse.current_price`；未采集时显示 `—` 而不是 `0.00`；
- rail 新增「行情时间」（`stock_master.updated_at`，随采集回写更新）与暂停监控时的「行情不再刷新」提示——**暂停的订单不会被采集**，只给数字会让人误以为是实时价。

## 7. 过程中踩到的两个坑（已固化到开发规范）

1. **模型返回类型不一致**：`StockMaster.get_by_id()` 返回 **dict 行**，而 `StockWarehouse / StockPe / StockPb.get_by_stock_master_id()` 返回**模型对象**。写测试/视图前必须先确认，不能凭上一个模型的写法推断（本次测试因此先报 `AttributeError: 'StockWarehouse' object has no attribute 'get'`）。
2. **在视图函数前插 helper 会顶掉装饰器**：本次新增 `_form_context` 时插在了 `@stock_bp.route` 之后、`edit_stock` 之前，结果路由挂到了 helper 上、`edit_stock` 失去端点，**12 个用例报 `BuildError: Could not build url for endpoint 'stock.edit_stock'`**。辅助函数必须放在装饰器**之前**。

## 8. 验证范围

- 真实页面核对：编辑页 rail 现价 == `stock_warehouse.current_price`，阶梯 `data-current` 有值，卖出价提示恢复（订单 82 / 77 / 86 逐一核对）；
- 回归用例：现价等于库内 warehouse 值且不为 `0.00`；行情时间存在；`data-current` 非空；POST 校验失败重渲染仍保留 `pe_memo` 原值；
- 全量 `python tests/run_all.py`（232 通过）。

**未验证**：暂停监控订单的「行情不再刷新」提示（需人工把某订单置为 inactive 后看编辑页）。
