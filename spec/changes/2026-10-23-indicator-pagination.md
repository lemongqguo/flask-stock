# 2026-10-23 指标监控页分页（每页 10 条）+ AI 入口换配色

**状态**：已交付　|　**提出日期**：2026-10-23　|　**负责人**：（维护者）
**受影响规格**：[006 指标监控](../current/006-stock-indicator.md)、[008 前端UI](../current/008-frontend-ui.md)

---

## 1. 问题与动机

- 指标监控页一次性取 200 只标的铺在一页（006 §10 已知限制），标的变多后表格很长、不好找；
- 上一轮刚加的「AI 分析」行内入口，hover / focus 走的是紫色 `var(--violet)`，用户要求换一种颜色。

## 2. 变更类型

- [x] **新增能力**：分页（新场景）+ 既有入口的配色调整
- [ ] 缺陷修复 / 行为变更 / 技术重构

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 取数范围 | 固定 `page=1, per_page=200`，一页铺完 | `?page=` / `?per_page=`，**默认每页 10 条**，可选 5 / 10 / 20 / 50（与订单列表同款 select） |
| 底部控件 | 无 | `total_pages > 1` 时显示 `.pager`（首页 / 上一页 / 页码 / 下一页 / 尾页，与订单列表同款） |
| KPI「监控标的」 | = 本页行数（等于总数） | = **全量标的数**（`get_all` 返回的 total），不再随翻页跳动 |
| KPI「组合命中 / 未采集」 | 全量 | **本页**口径（只取本页快照），foot 文案注明 |
| AI 入口配色 | 紫色 `--violet`（唯一配色） | **可切换变体**：`.row-ai` 默认紫（订单页不变），指标页加 `.row-ai.blue` 走信息蓝；hover 规则只读变量 `--ai-hue` / `--ai-soft`，不写死颜色 |
| 表格列宽 | 标的列自适应 + 其余定宽（96 ~ 230，宽窄悬殊） | **七列全定宽**（300 / 110 / 180 / 120 / 140 / 200 / 110 = 1160），独立类 `.table-indicator` 的 `min-width` = 定宽之和；窄屏只横向滚动（`.table-wrap`），不反向压列宽 |
| 空态 | 「暂无监控标的」 | 不变（无 pager） |

判定 / 告警 / 采集逻辑零改动。

## 4. 影响面

- 涉及模块/文件：`views/stock_orders.py::indicator_list`、`templates/indicator_list.html`、`static/css/theme.css`、`
  tests/test_indicator_page.py`
- 涉及数据表 / 是否需要迁移：无（`BaseModel.get_all` 本就带 `ORDER BY id DESC LIMIT/OFFSET`，翻页顺序稳定）
- 是否影响既有数据：否
- 是否需要新增/修改配置：否

## 5. 实施要点

- 分页参数与订单列表同口径：`per_page` 白名单 `[5, 10, 20, 50]`，非法值回落 10；
  `BaseModel.get_all` 内部已有 `max(1, ...)` 与 `ORDER BY id DESC`，不另写 SQL。
- 配色变体用 CSS 变量（`--ai-hue` / `--ai-soft`）而不是复制一套 hover 规则：加 `class="row-ai blue"` 即可换色，
  订单页零改动保持紫色。
- 列宽沿用订单列表 D-13 的教训：`colgroup` 定宽之和必须等于 `.table-indicator` 的 `min-width`，
  否则窄屏会反向压缩列宽（已有用例锁死二者相等）。
- KPI 语义必须说清：只有「监控标的」是全量，命中 / 未采集是本页——混着看会得出"翻页后命中数变了"的误判。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 默认每页 10 条、多出的翻到第 2 页 | `IndicatorPaginationTest` | ✅ |
| 页码链接保留 `per_page` | 同上 | ✅ |
| KPI「监控标的」= 全量（不随页码变） | 同上 | ✅ |
| 单页不满时不显示分页条 | 同上 | ✅ |
| AI 入口配色变体：默认紫 / `.row-ai.blue` 蓝、订单页不带 blue | `RowAiColorTest`（3 例） | ✅ |
| 七列全定宽且定宽之和 == CSS min-width | `IndicatorTableLayoutTest` | ✅ |
| 全量回归 | `stockenv\Scripts\python.exe tests/run_all.py`（`FLASK_DEBUG=0`） | ✅ 573 用例全通过（累计新增 10 个） |

- 实际验证到的范围：视图分页数学（按真实 `LIMIT/OFFSET` 语义 mock）、模板渲染契约（行数 / pager / KPI）、CSS 配色断言、全量回归。
- **未验证**的范围（明确写出来）：
  1. **真实库翻页**：`StockMaster.get_all` 被 mock，未连 MySQL 实跑；
  2. **浏览器观感**：分页条与每页条数下拉的排版、蓝色在两套主题下的对比度，需人工核对。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/006-stock-indicator.md` §9 页面约定 + §10 已知限制（原「一次最多 200 只」已失效）已更新
- [x] `../PROGRESS.md` 已更新
- [x] `../README.md` 已同步（进行中变更清单）
- [x] 决策记录：无需新增（纯 UI 能力，无取舍）
- [ ] 本目录已移入 `../archive/changes/`（待人工确认观感后归档）
