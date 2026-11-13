# 2026-11-13-turnover-legend-toggle：图例点击隐藏/显示系列

- 状态：已合入（待人工确认观感后归档）
- 日期：2026-11-13
- 负责人：用户 + Agent
- 影响规格：`009-market-turnover`
- 决策记录：无新增（交互对齐 K 线页 Chart.js 图例默认点击隐藏；自绘 canvas 实现等效语义）

## 1. 问题与动机

用户反馈：「为何点击图例没有隐藏的功能了，以前都有这个设计的」。
核对：K 线页（`stock_order_form.html`）用 Chart.js，其图例 `onClick` 默认即点击隐藏/显示数据集；
市场页为自绘 canvas（ADR-007），2026-11-13 新增的轴下图例是静态 `<span>` 展示，缺该交互 → 补齐。

## 2. 变更类型

- [x] 行为变更 / 新增能力：图例由静态展示改为点击切换系列可见性（含合计主线）。

## 3. 旧约定 → 新约定

| 维度 | 旧约定 | 新约定 |
| --- | --- | --- |
| 图例元素 | 静态 `<span>` | `<button data-series=total/sh/sz/bj>`，点击切换；原生键盘 Enter/Space 等效；`aria-pressed` 反映可见性 |
| 隐藏态视觉 | 无 | `is-off`：整项 opacity .45 + 删除线 + 色条灰化；hover 底色反馈、`:focus-visible` 描边 |
| Y 轴定标 | 四条线非空值共同定标 | **可见**系列非空值共同定标（隐藏合计后可放大分量量级对比） |
| 全部隐藏 | 不可能 | 允许：不画参考线与 Y 刻度（避免伪造 0~1 刻度），保留 x 轴标签 + 居中提示「所有系列已隐藏 · 点击下方图例恢复」 |
| 悬停/tooltip | 四值全量 | 仅可见系列行与同色圆点；全部隐藏不弹 tooltip |
| 面积填充 | 跟随合计 | 跟随合计且合计隐藏时一并消失 |
| 状态生命周期 | 无 | 内存态 `hidden`：跨 60s 刷新 / 区间切换 / 缩放平移 / 主题切换保留；页面重载重置（与 Chart.js 实例级语义一致） |

## 4. 影响范围

- `templates/market_turnover.html`（图例 markup、hidden 状态、draw/tooltip/悬停点过滤、click handler、页脚提示）。
- `static/css/theme.css`（`.mk-legend-item` 按钮化 + `is-off` / hover / focus-visible 态）。
- `tests/test_market_turnover_chart.py`（6 → 10 用例）。
- 无后端 / API / 表结构 / 配置变更。

## 5. 实施要点

1. 图例 span→button + 容器 `id="mkLegend"` 委托 click；原生 button 保证键盘可达与屏幕阅读器语义。
2. `hidden` 对象 + `SERIES_INDEX = {sh:1,sz:2,bj:3,total:4}` 映射；draw 的定标循环、分量 stroke、
   合计面积+主线、单点圆点、悬停圆点全部按 hidden 过滤；tooltip 行按 hidden 组装。
3. 面积填充保持在分量线之前绘制（半透明填充不盖分量），仅合计隐藏时跳过。
4. 全部隐藏兜底：placeholder 范围仅供坐标函数不 NaN；不画参考线/Y 刻度，居中提示文案。
5. 切换后立即 `draw()` 并按需刷新 tooltip（hover 中切换不残留隐藏系列行）。

## 6. 验证范围与结果

- 单测：`python -m unittest tests.test_market_turnover tests.test_turnover_auto_sync tests.test_shell_layout tests.test_market_turnover_chart` → **71/71 OK**（47+10+4+10）。
- JS 语法：抽取 block scripts 替换 url_for 后 `node --check` 通过。
- 运行时仿真（浏览器子代理不可用，改用 Node + DOM/canvas stub 驱动真实页面脚本、记录绘制调用）：7 项全过——
  初始四线齐绘 / 隐藏沪市去 stroke+is-off+aria / 隐藏合计去主线+面积 / tooltip 仅可见行 /
  全隐藏居中提示且无系列 stroke / 全隐藏不弹 tooltip / 恢复四线清 is-off。
- 未验证：真实库页面观感（待人工确认）；像素级渲染（仿真只记录绘制调用，不做像素采样）。

## 7. 合入清单

- [x] 变更记录完成
- [x] 相关测试已调整（先失败后通过）
- [x] `current/009` 已更新
- [x] `PROGRESS.md` / `README.md` 已更新
- [x] 验证结果已回填
- [ ] 经确认后归档