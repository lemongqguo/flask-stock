# 2026-10-21 前端 UI 改版（移除 Bootstrap + 双主题）

| 项 | 值 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 技术重构（样式层）+ 行为变更（交互） |
| 触发 | 现有页面基于 Bootstrap 5 + FontAwesome CDN，信息密度低；告警设置页为「N 只股票 × 3 个表单顺序堆叠」，股票一多即不可用 |
| 关联规格 | [008 前端 UI](../current/008-frontend-ui.md) |
| 验证 | `python tests/run_all.py` → **196 用例全部通过**（含 `tests/test_page_stats.py` 7 个）；测试客户端逐页渲染 9/9 路由 200 且无 Bootstrap/jQuery 残留；3 组告警表单 POST 契约通过；偏差修正项见第 7 节 |

---

## 1. 设计方向

**交易终端（Trading Terminal）**：深色优先、信息高密度。

- 配色：**红涨绿跌**（A 股习惯，非欧美绿涨红跌）；金叉 = 红、死叉 = 绿；强调色琥珀金。
- 数字统一 `tabular-nums` 等宽对齐，价格 / PE / PB 可竖向直接对比。
- **深色 / 浅色双主题**：同一套 CSS 变量出两套主题，右上角切换，`localStorage` 记忆，默认深色。

---

## 2. 依赖调整（决策：移除 Bootstrap）

| 依赖 | 处理 | 理由 |
| --- | --- | --- |
| Bootstrap 5 CSS / JS | **移除** | 新界面为自建设计系统，保留只剩类名冲突与覆盖成本 |
| jQuery | **移除** | `static/js/main.js` 已无实际依赖 |
| Font Awesome CDN | **移除** | 改为内联 SVG sprite，离线可用、少两个外部请求 |
| Chart.js 4.4.1 | **保留** | K 线图依赖，版本已锁定 |

---

## 3. 页面范围（8 类）

| 页面 | 关键改动 |
| --- | --- |
| 订单列表 | 4 个 KPI（总订单 / 监控中 / 触发告警 / 采集状态）+ 状态 chips 筛选 + 高密度表格；操作列默认半透明，hover 行才亮 |
| 添加 / 编辑订单 | 四段式（标的信息 / 价格阈值 / 估值阈值 / 备注）+ 三档阶梯（实时显示距现价百分比）+ 右侧固定实时行情栏；编辑态保留 K 线图 |
| 告警设置 | **左侧标的列表 + 右侧多页签（价格 / PE / PB / 指标）**，解决 N×3 表单堆叠 |
| 告警历史 | 按天分组时间线 + 类型筛选 + 邮件送达状态 |
| 指标监控 | 新增（见 [2026-10-21 指标监控](./2026-10-21-stock-indicator.md)） |
| AI 分析 | 新增（见 [2026-10-21 AI 个股分析](./2026-10-21-ai-analysis.md)） |
| 登录 / 注册 | **合并**为分栏 + 页签的单一模板 |
| 账户设置 | 个人资料 / 修改密码 / 通知偏好**合并**，左侧二级导航 |

> 登录注册、个人资料与改密码合并后，模板数量由 10 个降为 8 个。

---

## 4. 影响面

- 涉及文件：`templates/` 全部模板、`static/css/style.css`（193 行）、`static/js/main.js`；
- 新增文件：`static/css/theme.css`（设计系统）、`static/js/theme.js`（主题切换与记忆）；
- 新增路由与模板：指标监控、AI 分析（随 CHG-2 / CHG-3 落地）；
- **不涉及数据表变更**；无新增凭据类配置。

---

## 5. 实施要点

- 设计稿已先行评审通过：`design-preview/`（纯静态预览，不参与构建）；
- 保持现有路由与表单字段名不变，**后端视图层尽量少改**；
- 响应式断点：≤1000px 侧栏收窄为图标、≤640px 表单单列；
- 主题切换需在页面早期执行，避免浅色主题下的白屏闪烁。

---

## 6. 验证

项目无 UI 自动化测试（现状），验证方式：

- `python tests/run_all.py` → **189 用例全部通过**（后端行为未受影响）；
- Flask 测试客户端逐页 GET：`/stock/list`、`/stock/create`、`/stock/edit/1`、`/stock/alarm_settings`、`/stock/recent_alarms`、`/login`、`/register`、`/profile`、`/change_password` 共 **9/9 返回 200**，页面源码中无 `bootstrap` / `jquery` 残留引用；
- 三组告警表单（warehouse / pe / pb）POST 提交均正常处理（200），字段契约未变；
- 窄屏响应式为人工核对项（CSS 断点沿用设计稿，`design-preview/` 已评审通过）。

### 附带约定变更

`rules/development-standards.md` 第 6 节「前端」同步更新（改约定先于改代码）：

- 公共交互文件由 `main.js` / `style.css` 改为 `theme.js` / `theme.css`；
- 新增「不引入 Bootstrap / jQuery / FontAwesome」「颜色一律走 CSS 变量」「页面交互声明式 `data-*` 交 `theme.js` 接管」约定，并允许 K 线图等依赖模板变量的脚本留在 `{% block scripts %}`。

### 测试数据污染说明（如实记录）

验证过程中的告警设置 POST 抽测对真实库 `stock_id=1`（宁德时代）写入了测试阈值。已当场执行清除（warehouse/pe/pb 相关字段置 NULL），并在清除后复查确认为空。若该标的原本存在自定义阈值，需用户在「告警设置」页重新录入。

---

## 7. 实施偏差修正（合入后）

用户人工核对发现「添加订单」与设计稿不符、编辑态内容看不到。逐项校对 `design-preview/screens/order-form.html` 后修正：

| # | 偏差 | 修正 |
| --- | --- | --- |
| 1 | K 线图被放进 320px 窄 rail，编辑态几乎看不到 | K 线图移回**主列**作为独立 panel（260px 高），仅编辑态渲染 |
| 2 | 备注被拆成 3 处、缺少独立「备注」段 | 改为设计稿的四段式：标的信息 / 价格阈值 / 估值阈值 / **备注**；PE、PB 备注随各自阈值段 |
| 3 | 保存按钮在主列底部 | 移到右侧 rail「操作」区（重置 + 保存），与设计稿一致 |
| 4 | 右侧 rail 缺「填写提示」 | 补齐 实时行情 / 填写提示 / 操作 三块 |
| 5 | 字段缺 help 文案（代码前缀、暂停含义等） | 按设计稿补齐 |
| 6 | 卖出价无"距现价涨幅"提示 | Jinja 静态渲染 + `theme.js` 的 `initSellHint` 随输入实时更新 |
| 7 | 订单列表 KPI 第 3 项为「已暂停」，设计稿是「触发告警」 | 改为「触发告警」，新增 `StockMaster.count_alarm_active()` |
| 8 | 告警历史页**完全没有 KPI** | 补齐 4 项 KPI，新增 `StockAlarm.get_stats()` |

配套改动：

- `models/stock_master.py`：抽出 `ALARM_ACTIVE_CONDITION`，列表 `is_alarm_active` 与 `count_alarm_active()` **共用同一判定**，避免"KPI 说 2 条、列表高亮 3 行"；
- `models/stock_alarm.py`：新增 `get_stats()`（今日 / 近 7 天 / 邮件送达 / 失败），异常返回 `None` 且模板判空，统计失败不会让整页 500；
- `templates/base.html`：`session.username` 改为 `session.get('username')` 兜底——username 缺失时原写法会让**所有页面 500**；
- `templates/stock_order_form.html`：Chart.js 加载失败时降级为文字提示；`spanGaps: true` 跨越 MA 空点；
- 新增 `tests/test_page_stats.py`（7 个用例），全量 **196 用例通过**。

新发现待办（已入台账）：T-08 历史 K 线 MA 未回填（stock_id=1：147 条仅 36 条有值）；T-09 告警历史「冷却拦截」无法统计（被拦截的告警不落库），现以「发送失败」代替并注明。

### 用户反馈修正（第 2 轮）

用户明确偏好 `design-preview/screens/order-form.html` 的布局，并指出 K 线悬停显示不完整：

| # | 反馈 | 处理 |
| --- | --- | --- |
| 1 | 去掉 PE 备注 / PB 备注，统一只留第 4 项「备注」 | 两个 textarea 移除；`pe_memo` / `pb_memo` 改为**隐藏字段回传原值**（后端用 `request.form.get('pe_memo', '')`，若字段整个消失会把已有备注清空）。PE / PB 备注的编辑入口保留在「告警设置」页 |
| 2 | K 线鼠标悬停显示不完整 | 三处根因：① 默认 `interaction.mode='nearest'` 只显示一个数据集 → 改 `'index'` + `intersect:false`，一次列出收盘价 / MA5 / MA10 / MA30；② 接口返回 Decimal 字符串未转数值 → 新增 `toNum()`；③ 悬停标题只有 `MM-DD` → 改为完整 `YYYY-MM-DD`，空值显示「无数据」 |

**顺带修掉的缺陷**：字段为 `NULL` 时 Jinja 渲染出字符串 `None`，回填再提交会把数据库的 `NULL` 改成字面量 `"None"`（脏数据）。模板内 17 处统一改为 `{{ (x.y or '') if x else '' }}`，并新增 `tests/test_form_render.py`（6 个用例）锁住。

验证：全量 **202 用例通过**；mock 端到端确认订单 2（泸州老窖，PE/PB 备注非空）保存时 `update_by_stock_master_id` 收到的 `memo` 与库内原值一致，未被清空。

### 用户反馈修正（第 3 轮）

订单列表「创建时间」与「操作」之间空隙过大、操作按钮看不到：

- 根因：表格是 `table-layout: auto`，多余宽度被摊到**每一列**；操作列的 `.row-actions` 又是 `justify-content: flex-end`，按钮贴在最右，中间空出一大片；窄屏时更要横向滚动才够得着。
- 处理：改用 `table-layout: fixed` + `<colgroup>` 定宽（数据列紧凑，`标的`列吸收剩余宽度，总 `min-width` 1180 → 1060）；操作列定宽 140px 并 `position: sticky; right: 0` 吸附右侧，滚动时始终可见；单元格统一 `white-space: nowrap` + 省略号截断。
- 顺带：移除了模板里写死的 `style="min-width:1180px"`，列宽统一由 `colgroup` 管理。

全量 202 用例通过；渲染核对 9 列 / 9 单元格一致、操作列 `col-actions` 表头与每行各 1 处。

### 用户反馈修正（第 4 轮）：K 线与均线配色

用户提供参考图：收盘价**青绿实线**，MA5 / MA10 / MA30 分别为**粉 / 蓝 / 黄虚线**。

- 处理：`theme.css` 新增 K 线专用变量 `--kline-price / --kline-ma5 / --kline-ma10 / --kline-ma30`（暗色主题 400 档、亮色主题 600 档，色相一致），模板 datasets 改为引用这些变量，三条均线加 `borderDash: [6, 4]`；
- 约定：K 线配色**不得再借用 `--up / --down / --info` 等语义色**（那些表示涨跌/信息，语义不同），图表颜色一律走 `--kline-*`（回归用例 `tests/test_kline_chart.py`）；
- 已知行为（既有）：图表在页面加载时取一次 CSS 变量，之后**切换主题不会重绘** canvas，需刷新页面才应用新主题配色。

## 8. 遗留

- 项目无 CI（T-01 未闭环），UI 改动无自动化回归，依赖人工核对。
- 移除 Bootstrap 后，若后续需要复杂组件（如日期选择器）需自行实现或按需引入。
- 侧栏底部 `side-foot` 仍为静态文案，未接入真实监控状态（依赖 T-05）。
