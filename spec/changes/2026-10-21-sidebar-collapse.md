# 变更：侧栏导航可折叠

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入**（交互效果待人工确认） |
| 类型 | 新增能力（交互） |
| 触发 | 用户要求：侧栏「监控」组标题右侧加一个折叠控件（图标即可），折叠后只显示各功能图标 |
| 关联规格 | [008 前端 UI](../current/008-frontend-ui.md)（布局与组件） |
| 验证 | 全量 **225 用例通过**（新增 `tests/test_sidebar.py` 7 个，锁模板/静态资源契约）；渲染核对按钮结构、4 个导航项 title、未登录时不渲染 |

## 1. 旧约定 → 新约定

| 项 | 旧 | 新 |
| --- | --- | --- |
| 侧栏宽度 | 固定 `--sidebar-w`（232px），仅在窗口 ≤1000px 时自动收窄 | 用户可手动折叠：`.shell.side-collapsed` 覆盖 `--sidebar-w` 为 66px |
| 折叠入口 | 无 | 「监控」组标题右侧一个 chevron 图标按钮 |
| 折叠后 | — | 只显示各功能图标（`span` 文字、品牌名、徽标、侧栏底部信息隐藏），导航项 `title` 悬停可看名称 |
| 状态记忆 | — | `localStorage` 键 `sidebar-collapsed`，与主题切换一致 |

## 2. 设计要点

- **复用窄屏已有表现**：`@media (max-width:1000px)` 早就是"只留图标"的规则，折叠态沿用同一套（`.side-collapsed` 下同样的选择器），避免两套逻辑漂移；
- `nav-group-label` 改为 flex 两端对齐，文字包进 `<span>`——**标题整块不能 `display:none`**，否则折叠后按钮自己也没了（故窄屏规则里的 `.nav-group-label` 改为 `.nav-group-label span`）；
- 窄屏（≤1000px）下隐藏折叠按钮：此时宽度已被媒体查询锁定，按钮点了不会有变化，留着会让人以为坏了。

## 3. 影响面

- `static/js/theme.js`：sprite 新增 `i-chevron-left` / `i-chevron-right`；新增 `initSideToggle()` 并在 `DOMContentLoaded` 注册；
- `templates/base.html`：组标题加按钮；4 个导航项加 `title`；
- `static/css/theme.css`：`.side-collapsed` 系列规则 + `.side-toggle` 样式 + 宽度过渡。

## 4. 安全约束

- 按钮为 `<button type="button">`，不会误触发表单提交；带 `aria-label` / `aria-expanded` / `title`，折叠后仍有可访问名称；
- 状态只存 `localStorage`，不涉及敏感数据。

## 5. 验证范围

- 模板渲染：按钮存在、位于 `nav-group-label` 内、4 个导航项均有 `title`（回归用例 `tests/test_sidebar.py`）；
- 回归：全量 `python tests/run_all.py`；
- **未验证（如实记录）**：真实点击折叠效果、刷新后 `localStorage` 状态记忆——本机**无 node/浏览器自动化环境**，JS 未做任何语法或运行时校验（曾尝试 `node --check` 失败，脚本却误报"通过"）。这部分只能由用户刷新页面人工确认，与主题切换的验证状况一致。
