# 2026-10-22 AI 分析页改版（二）：搜索式工作台（去掉全量标的栏 + 服务端搜索）

**状态**：已交付（待人工确认观感）
**提出日期**：2026-10-22　|　**负责人**：AI 助手
**受影响规格**：[007 AI 个股分析](../current/007-ai-analysis.md) / [008 前端 UI](../current/008-frontend-ui.md)

---

## 1. 问题与动机

上一版（[2026-10-22 AI 分析页改版](../changes/2026-10-22-ai-analysis-ui.md)）把页面做成
「左标的列表 / 中报告 / 右参数」三栏，交付后用户反馈两点：

1. **布局不好看**：三栏把页面切得很碎，左栏一整列股票名既占地方又和订单列表重复；
   视觉上没有任何"入口感"，进来就是一堆密集列表。
2. **标的列表是多余的**：标的已经能从**订单列表行内的「AI 分析」按钮**直接带入，
   AI 页再铺一遍全量股票名纯属重复。
3. **搜索是假搜索**：左栏搜索是**前端过滤**，只覆盖页面一次性加载的前 200 只标的
   （旧约定已在 007 §8 记为限制），标的超过 200 只就搜不到——用户明确要求"一定可以搜索"。

因此本轮把 AI 页从「列表浏览型」改成「**搜索式工作台**」：顶部大搜索框（服务端真搜索）
定标的，下方是「标的条 + 报告 + 参数」，未选标的时展示能力卡片网格（参考
<https://chatglm.cn/main/alltoolsdetail?lang=zh> 的卡片栅格观感）。

## 2. 变更类型

- [x] **行为变更**：AI 页不再渲染全量标的列表；`?stock_id=` 缺失时不再默认选中第一只，而是进入"未选标的"空态
- [x] **新增能力**：服务端标的搜索接口 `GET /stock/ai/api/search`；「最近分析」快捷入口
- [x] **技术重构**：页面只加载当前标的的数据（不再一次性拉 200 只 + 批量快照）

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 页面布局 | 三栏 `.ai-layout`（300 / 1fr / 300）：左「标的列表」/ 中「报告」/ 右「参数 + 快照 + 历史」 | 顶部 `.ai-hero`（居中大搜索框 + 状态 chips）+ 下方 `.ai-work`（`1fr / 320px`）：主区「标的条 + 报告」/ 右栏「参数 + 快照 + 历史」 |
| 现价口径 | 取指标快照 `stock_indicator.price`（实测该列在本环境全为 NULL → 页面恒显示「—」） | **优先取 `stock_warehouse.current_price`**（与订单列表 / 编辑页同一口径，见 [2026-10-21 修复编辑页实时行情](../changes/2026-10-21-order-form-current-price.md)），该列缺失才回退指标快照；两者都没有才渲染「—」 |
| 标的来源 | 页面一次性加载 ≤200 只并铺成左栏列表 | **不加载列表**；标的由 ① 顶部搜索框 ② 订单列表行内「AI 分析」按钮（`?stock_id=`）确定 |
| 标的搜索 | 前端即时过滤已渲染行（`data-text-filter`），只覆盖已加载的前 200 只 | **服务端搜索** `GET /stock/ai/api/search?q=`：参数化 `LIKE` 命中 `stock_name` / `stock_code`，返回 ≤12 条（含最新价与跳转 URL），前端 220ms 防抖下拉 + ↑↓/Enter/Esc 键盘操作 |
| 无 `?stock_id=` | 默认选中列表第一只 | **不选中任何标的**，进入空态：能力卡片网格 + 「最近分析」快捷入口 + 引导文案 |
| 页面数据加载 | `StockMaster.get_all(per_page=200)` + `get_latest_batch(200 ids)` | 只查 `StockMaster.get_by_id(stock_id)` 与 `StockIndicator.get_latest(stock_id)`；批量快照只服务于搜索接口 |
| 快照来源 | 左栏批量快照 map | 右栏快照直接取 `StockIndicator.get_latest(stock_id)`（同一张表同一份数据） |
| 「最近分析」 | 无 | 跨标的最近 5 条 `stock_ai_report`（JOIN `stock_master` 取名称），仅在未选标的时展示，作为回看入口 |

**不变的部分**（避免回归）：路由与 POST 语义、模型白名单校验、维度校验、月度上限、
未启用禁用规则、免责声明、追问留痕、`stock_ai_report` / `stock_ai_config` 表结构。

## 4. 影响面

- 涉及模块/文件：`views/ai_analysis.py`（新增 `search` 接口、页面只加载当前标的、新增 `DIM_ICONS`）、
  `models/stock_ai.py`（新增 `DIMENSION_DESCS`、`StockAiReport.list_recent`）、
  `templates/ai_analysis.html`（整体重写）、`static/css/theme.css`（`.ai-hero` / `.ai-combo` / `.ai-work` / `.ai-target` / `.ai-catalog` 等新组件）、
  `static/js/theme.js`（`initAiSearch` + 新增 6 个 sprite 图标）、`tests/test_ai_analysis.py`（契约用例按新结构改写）
- 涉及数据表 / 是否需要迁移：**无**（只新增查询方法，不改表）
- 是否影响既有数据：**不影响**
- 是否需要新增/修改配置：**无**

## 5. 实施要点

1. **搜索必须真查库**：`BaseModel.build_search_where` 已有 `stock_name` / `stock_code` 白名单
   （`StockMaster.search_fields`），复用 `StockMaster.get_all(page=1, per_page=12, search_query=q)`，
   值一律 `%s` 参数化；**`q` 为空时直接返回空列表**，绝不能退化成"返回全部"（否则又变成铺全量名单）。
2. **搜索结果带跳转 URL**：URL 由服务端 `url_for('ai.page', stock_id=...)` 生成，前端只渲染，
   不自己拼地址，避免前端拼接出越权或不存在的路径。
3. **`?stock_id=` 必须校验存在性**：不再用"列表里有没有"来兜底，直接 `StockMaster.get_by_id`；
   不存在就回到空态（原来的 `_selected_stock_id` 随之删除）。
4. **去掉列表后仍需保留"保存参数"入口**：右栏参数卡在**未选标的时也渲染**，
   否则未启用时用户没法保存参数（旧约定第 7 条要求"保存参数始终可点"）。
5. **失败可判定**：搜索接口查询异常 → `logger.exception` + 500 + `error` 字段，前端显示"搜索失败"，
   不用 `except Exception: pass`。
6. **新增图标进 sprite**：`i-scale` / `i-candles` / `i-compare` / `i-target` / `i-shield` / `i-close`，
   仍然不引外部图标库。
7. **现价换源属于顺带修的缺陷**：改版后「最新价」是标的条的主视觉，才发现指标快照的 `price` 列
   在本环境全为 NULL（旧版藏在左栏小字里没暴露）。现价改走 `stock_warehouse.current_price`，
   与订单列表 / 编辑页对齐（编辑页那次已定过这个口径）。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 全量回归 | `stockenv\Scripts\python.exe tests\run_all.py` | ✅ **474 用例 OK**（462 → +12） |
| 搜索接口命中名称 / 代码 | 用例 mock `StockMaster.get_all` 断言 `search_query` 原样下发与返回结构 | ✅ `q=600519` 命中 `SH600519`，`price` / `url` 正确 |
| `q` 为空不返回全量 | 用例断言 `get_all` 不被调用、返回 `items: []` | ✅ |
| 现价优先取 warehouse | 用例断言 warehouse 值覆盖指标快照 | ✅ 1688.00 覆盖 1600.00 |
| 搜索失败可判定 | 用例 mock `RuntimeError` 断言 500 + `error` | ✅ |
| 关键字超长截断 | 用例断言下发 32 字 | ✅ |
| 未选标的空态 | 用例断言能力卡片 + 最近分析 + **无** `ai-stock-list` | ✅ |
| 非法 `?stock_id=` | 用例断言 200 且回到空态 | ✅ |
| 选中标的 → 标的条 / 快照 / 报告 / 历史 | 用例断言关键文案与结构 | ✅ |
| 未启用按钮禁用 | 用例按 `formaction` 定位按钮断言 `disabled`；保存参数按钮不禁用 | ✅ |

### 6.1 真实环境验证（不 mock，连真实库）

| 验证项 | 结果 |
| --- | --- |
| `GET /stock/ai/`（92 只标的） | ✅ 200；hero + 搜索框（`data-url=/stock/ai/api/search`）+ 能力卡片 + 「最近分析」；**页面里没有全量标的列表** |
| `GET /stock/ai/api/search?q=茅台` | ✅ 命中 `贵州茅台 SH600519`，`price=1310.05`，`url=/stock/ai/?stock_id=4` |
| `?q=6005` / `?q=000` | ✅ 按代码子串命中（SH600570 / SH600519 / SZ000963 …），带真实现价 |
| `?q=`（空） | ✅ `items: []`，未退化成返回全部 |
| `?q=ZZZZ` | ✅ 空结果，无异常 |
| `GET /stock/ai/?stock_id=4` | ✅ 200；标的条（贵州茅台 / 1310.05 / 指标格）+ 指标快照 + 历史分析 + 生成分析 + 换个标的 |
| 现价来源核对 | ✅ `stock_indicator.price` 全为 NULL，`stock_warehouse.current_price` 有值（1310.05 / 108.85 / 100.00）→ 换源后页面显示真实价格 |

### 6.2 未验证范围

- **浏览器级观感未验证**：hero 渐变 / 网格遮罩、搜索下拉的浮层与键盘操作、能力卡片 hover 抬升、
  1240 / 1000px 断点折叠，只做了 CSS 契约与结构断言，需人工看一眼。
- 未做真实 AI 调用（本轮是纯前端 + 查询改动，未触碰 `ai_client` / 提示词）。
- 「最近分析」只取最近 5 条，未分页；条目多时更早的记录只能从标的内的「历史分析」进。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/007-ai-analysis.md` 已更新为新的有效约定（布局 / 搜索接口 / 现价口径 / 验收 10.1 / 已知限制）
- [x] `../current/008-frontend-ui.md` 已同步新组件（页面清单 + AI 页硬约束 + 响应式）
- [x] `../PROGRESS.md` 模块进度与台账已更新
- [x] `../README.md` 进行中变更清单已同步
- [ ] 本目录移入 `../archive/changes/`（待人工确认观感后归档）
