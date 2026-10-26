# 变更：侧栏导航分组重构（对齐设计稿）

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 行为变更（导航结构 + 品牌副标） |
| 触发 | 用户要求：按 `design-preview/screens/orders.html` 的侧栏布局改造项目前端——「交易 / 监控 / 系统」三组分组、系统组收纳账户设置与退出登录、指标监控带徽标 |
| 关联规格 | [008 前端 UI](../../current/008-frontend-ui.md)（§4.1 侧栏结构）、[003 告警阈值与告警历史](../../current/003-alarm-thresholds.md)（徽标数据源） |
| 验证 | 全量 `tests/run_all.py` 通过（见 §6）；模板渲染核对三组标题顺序、系统组两个入口、徽标 0 时隐藏 |

## 1. 问题与动机

设计稿（`design-preview/screens/*.html`）的侧栏是**三组分组导航** + 底部状态卡，而实现是**单个「监控」组堆 6 项**：

- 交易类（订单列表 / 添加订单 / 告警设置 / 告警历史）与监控类（指标监控 / AI 分析）混在一起，功能性质看不出来；
- 「账户设置」「退出登录」只藏在顶栏头像下拉里，与设计稿的「系统」组不一致，新用户找不到；
- 设计稿在「指标监控」上有告警数徽标，实现没有，指标告警只能进页面才发现。

008 §4.1 已写明"模板形态以 `design-preview/screens/*.html` 为准"，本次是把侧栏补齐到设计稿形态。

## 2. 变更类型

- [ ] 缺陷修复
- [x] **行为变更**：侧栏导航的分组方式、入口位置、品牌副标发生变化 → 先改本记录，再改测试期望与代码
- [ ] 技术重构
- [x] **新增能力**（小范围）：指标监控徽标（真实数据源）

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 分组 | 单组「监控」6 项 | **三组**：交易（订单列表 / 添加订单 / 告警设置 / 告警历史）、监控（指标监控 / AI 分析）、系统（账户设置 / 退出登录） |
| 账户设置 / 退出登录 | 仅顶栏头像下拉 | 侧栏「系统」组**常驻**两个入口；顶栏下拉**保留**（那里还显示当前用户名） |
| 折叠控件 | 「监控」组标题右侧 | 位置不变（仍在「监控」组标题右侧）；折叠后三组的文字全部隐藏，只剩图标 + 折叠按钮 |
| 指标监控徽标 | 无 | `.nav-badge` 显示**近 24 小时「指标」类告警条数**；为 0 时不渲染（不显示假数字） |
| 品牌副标 | `Stock Terminal` | `Stock Monitor`（与设计稿一致，`base.html` / `auth.html` 同步） |

## 4. 影响面

- 涉及模块/文件：`templates/base.html`（侧栏结构）、`templates/auth.html`（副标）、`models/stock_alarm.py`（新增 `count_recent_indicator`）、`app.py`（context processor 注入 `nav_badges`）、`tests/test_sidebar.py`；
- 数据表 / 迁移：**无**（只读 `stock_alarm`，`alarm_time` 已有索引 D-09）；
- 是否影响既有数据：否；
- 是否新增/修改配置：否；
- 路由：不变（复用 `stock.*` / `ai.page` / `auth.profile` / `auth.logout`）。

## 5. 实施要点

- **分组容器**：每组外面包一层 `div`（组标题 + `nav`），`.sidebar` 的 `gap: 20px` 因此落在"组与组之间"，组内标题与导航只隔 `margin-bottom: 8px`——与 `design-preview/assets/design.css` 结构完全一致，**CSS 无需改动**。
- **折叠兼容**：折叠态规则命中 `.nav-group-label span`（不是整块标题）与 `.nav-item span`，新增的「交易」「系统」组标题自然一起隐藏；折叠按钮仍在「监控」组，避免"按钮自己消失"的老坑。
- **系统组是普通 `<a>` 链接**（GET），不塞表单——与「列表里不塞表单」的既有约定一致；`auth.logout` 本身就是 GET。
- **徽标必须真实**：`StockAlarm.count_recent_indicator(hours=24)` 只做一次 `COUNT(*)`（`alarm_type='indicator'` + `alarm_time` 区间），查询异常 `logger.exception` 后返回 `0`——徽标宁可少显示，也不许写死数字（008 §4.1「禁止写死文案」同类约束）。
- **查询时机**：`app.context_processor` 只在**已登录**时查该计数（未登录侧栏不渲染），单页一次 COUNT，失败降级为 0，不影响页面渲染。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 三组标题顺序 | `tests/test_sidebar.py::test_nav_groups_order`（渲染 `/stock/list` 断言「交易 → 监控 → 系统」） | 通过 |
| 系统组两个入口 | `test_system_group_entries`（`/profile`、`/logout` 链接存在且带 `title`） | 通过 |
| 折叠按钮仍在「监控」组标题内 | `test_button_inside_group_label`（改为按含 `data-side-toggle` 的 label 定位） | 通过 |
| 徽标 0 时隐藏 / >0 时显示真实数 | `test_nav_badge_hidden_when_zero` / `test_nav_badge_renders_count` | 通过 |
| 徽标计数降级 | `test_count_recent_indicator_*`（SQL 断言 + 异常返回 0） | 通过 |
| 全量回归 | `python tests/run_all.py` | 通过 |

- 实际验证到的范围：模板结构与链接、徽标取值契约、全量后端回归。
- **未验证**的范围（如实记录）：折叠/主题的真实点击效果与浅色主题观感——本机无浏览器自动化环境，UI 表现需人工刷新确认（与「侧栏导航可折叠」「主题切换」的历史验证状况一致）。

## 7. 合入清单

- [x] 代码已合并
- [x] `../../current/008-frontend-ui.md` 已更新为新的有效约定（侧栏三组 + 徽标）
- [x] `../../PROGRESS.md` 模块进度与变更历史已更新
- [x] `../../README.md` 变更清单已同步
- [x] 无重要取舍（分组沿用设计稿，徽标口径取"近 24h 指标告警"），未新增 ADR
- [x] 本文件已归档到 `../../archive/changes/`
