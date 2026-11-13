# 2026-11-12 壳层布局反馈（侧栏四组折叠控件 + 成交额页平铺自适应）

**状态**：已合入（待归档：页面观感人工确认）　|　**提出日期**：2026-11-12　|　**负责人**：用户 + Agent
**受影响规格**：[008 前端 UI](../current/008-frontend-ui.md)（侧栏折叠控件）、[009 市场成交额](../current/009-market-turnover.md)（页面布局）

---

## 1. 问题与动机

用户两条反馈：

1. 侧栏只有「监控」组标题行有 « 折叠控件，要求**交易 / 行情 / 系统同一行位置都加一个和监控一样的折叠控件**；
2. 市场成交额看板**布局不对：不是平铺自适应屏幕**——旧 `.mk-wrap` 自带 `max-width: 1400px` 居中，
   大屏两侧留白；图表固定 420px 高，窗口下半截空着。项目底座本有「`.content` 全宽 + `.card-fill` 撑满剩余高度」
   约定（订单列表等页已用），看板移植时违反了它。

## 2. 变更类型

- [ ] 缺陷修复
- [x] **行为变更**（侧栏控件分布 + 看板布局约定）
- [ ] 技术重构
- [ ] 新增能力

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 折叠控件 | 仅「监控」组标题右侧一个 | **交易 / 行情 / 监控 / 系统四个组标题行右侧各一个**，同一状态同步（aria / title / chevron 方向一起切换），共享 `sidebar-collapsed` 记忆；折叠态下四个控件仍可见可点（隐藏的是 span 不是整块标题，既有约定） |
| 看板宽度 | `.mk-wrap` max-width 1400px 居中 | **不设宽度上限**，随 `.content` 全宽平铺（`width:100%; flex:1`） |
| 看板高度 | 图表固定 420px（窄屏 320px） | **flex 链撑满剩余高度**：`.content → .mk-wrap → .mk-chart-card → .mk-chart-wrap` 逐级 `flex:1`（与 `.card-fill` 同约定），图表最小 300px（窄屏 260px），矮屏自然滚动 |
| 宽屏指标 | 6 指标卡 3 列 × 2 行 | **≥1500px 单行 6 列平铺**；≤900px 维持堆叠（2 列 / 单列） |

## 4. 影响面

- 涉及模块/文件：
  - `templates/base.html`：三个组标题行补折叠按钮（与监控同款 markup）
  - `static/js/theme.js`：`initSideToggle` 改 `querySelectorAll('[data-side-toggle]')`，apply/click 对全部按钮同步
  - `static/css/theme.css`：`.mk-wrap` 去上限改全宽 flex；`.mk-chart-card` / `.mk-chart-wrap` 改 flex 撑满；新增 ≥1500px 媒体（6 列）；≤900px 图表改 min-height；背景渐变改百分比尺寸随宽度缩放
  - 新增 `tests/test_shell_layout.py`（4 用例：四控件 / 多按钮同步 / 全宽平铺 / 图表撑满）
- 涉及数据表 / 配置：无
- 是否影响既有数据：不影响（纯前端壳层）

## 5. 实施要点

1. **多按钮同步**：apply() 遍历全部按钮切 aria/title/chevron；任一按钮点击都 toggle 同一 `.shell.side-collapsed` 并写 localStorage，刷新后记忆恢复。
2. **折叠态可见性**：沿用「隐藏 `.nav-group-label span` 而非整块」的既有坑位约定，四个控件折叠后仍留得下、点得开。
3. **平铺 flex 链**：`.main`(min-height:100vh) → `.content`(flex:1) → `.mk-wrap`(flex:1) → `.mk-chart-card`(flex:1) → `.mk-chart-wrap`(flex:1, min-height:300px)；canvas 绝对定位 + ResizeObserver 重绘，尺寸变化自动跟随。
4. **窄屏不回归**：≤1000px 侧栏自动收图标且 `.side-toggle` 隐藏（既有规则，四控件一致）；≤900px hero 堆叠、图表 min-height 260px。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 单测 / 契约 | `python -m unittest tests.test_market_turnover tests.test_shell_layout` | ✅ 33/33 通过（29 + 4） |
| 四控件同步 | 真实浏览器点击交易/行情/系统/监控任一控件 | ✅ 折叠 66px、四按钮 aria/title/chevron 同步；折叠态点行情可展开；跨刷新记忆（localStorage）往返一致 |
| 全宽平铺 | 同源 iframe 精确 1920×1080 视口实测 | ✅ `.mk-wrap` 1611px（= content 内宽，1400 上限消失；与 content 外宽差 57.6px 为其响应式 padding，属页面留白非上限）；无横向溢出 |
| 图表撑满 | 同上 | ✅ `mkChartWrap` 高 608px（>420，撑到窗口底部）；hero-right 6 列 |
| 响应式 | iframe 1000×800 / 620×900 | ✅ 3 列 / 2 列堆叠、图表 331px / 300px 自适应、无横向溢出 |
| 双主题 | 1920 视口切浅色 | ✅ 浅色全宽平铺正常、canvas 重绘、0 console 错误 |
| 截图取证 | Browser 子代理两轮 | ⚠️ **未产出**：IDE Browser 视图隐藏（NATIVE_BROWSER_VIEWPORT_UNAVAILABLE），需人工打开面板后才能截图；功能以 JS 实测为准 |

- **未验证**的范围：人工观感确认（待用户）；既有 634 用例回归（套件不在本工作区）。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/008-frontend-ui.md` 已更新（四组折叠控件）
- [x] `../current/009-market-turnover.md` 已更新（平铺自适应 + 壳层契约验收）
- [x] `../PROGRESS.md` 台账已更新（667 用例、待归档 12）
- [x] `../README.md` 已同步（进行中变更 + 用例数）
- [ ] 本目录已移入 `../archive/changes/`（待人工确认观感后归档）