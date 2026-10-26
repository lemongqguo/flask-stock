# 007 AI 个股分析（AI Analysis）

**状态**：**已实现**（已在真实 OpenAI 兼容网关验证：连通 / 分析 / 追问 / 双风格）　|　**最后更新**：2026-10-23

**相关变更**：[2026-10-21 AI 个股分析](../archive/changes/2026-10-21-ai-analysis.md)（已归档）／
[2026-10-22 AI 分析页改版](../changes/2026-10-22-ai-analysis-ui.md)（三栏 + 搜索 + 模型选择 + 分析维度）／
[2026-10-22 AI 页改版（二）](../changes/2026-10-22-ai-analysis-workspace.md)（**搜索式工作台**：去掉全量标的栏 + 服务端搜索）／
[2026-10-22 AI_MODEL 支持清单](../changes/2026-10-22-ai-model-list.md)（`AI_MODEL` 也可填逗号分隔清单）／
[2026-10-22 订单列表 AI 快捷入口](../changes/2026-10-22-list-ai-shortcut.md)（从列表行直达本页）／
[2026-10-23 追问 Composer](../archive/changes/2026-10-23-ai-composer.md)（模型选择 + 运行时密钥 + 就地连通测试）／
[2026-10-23 连通测试入口唯一化](../archive/changes/2026-10-23-ai-test-entry.md)（参数卡按钮删除，合入 Composer）

**实现位置**：`views/ai_analysis.py`（蓝图 `ai`，`/stock/ai`）、`utils/ai_client.py`、`utils/ai_prompt.py`、
`models/stock_ai.py`、`templates/ai_analysis.html`、`config.py`（`AI_*`）、`database.py`（两张表）。

---

## 1. 场景

基于系统已采集的行情、估值与指标数据，调用 AI 生成个股结构化分析报告，并支持用户追问。

## 2. 接入方式

**自定义模型**模式：**OpenAI 兼容 Responses API**——API 格式 + Base URL + Model ID + API Key，不绑定特定厂商。
`AI_API_STYLE` 决定实际端点：`responses`（默认，`/responses`）或 `chat`（`/chat/completions`，兼容多数自建网关）。

### 2.1 页面与路由

| 路由 | 方法 | 行为 |
| --- | --- | --- |
| `/stock/ai/` | GET | **搜索式工作台**：顶部 `.ai-hero`（居中搜索框 + 状态 chips）+ 下方 `.ai-work`（主区「标的条 + 报告」/ 右栏「参数 + 指标快照 + 历史」）；`?stock_id=` 选标的、`?report_id=` 定位某条记录 |
| `/stock/ai/api/search` | GET | **标的搜索**（`?q=`）：服务端真查库，参数化 `LIKE` 命中 `stock_name` / `stock_code`，返回 ≤12 条（含现价与跳转 URL）；`q` 为空返回空列表 |
| `/stock/ai/analyze` | POST | 生成一次分析：校验启用 / 额度 / 模型白名单 → 组装上下文（按引用范围裁剪）→ 调用模型 → 解析 → 落库 → 回跳 `?report_id=`；可带 `model`、`dimensions[]` |
| `/stock/ai/ask` | POST | 基于**最近一次正式分析**追问（≤ 300 字），回答同样落库（`verdict='问答'`）；同样可带 `model` |
| `/stock/ai/config` | POST | 保存非凭据参数：开关、**模型**、**分析维度（至少一项）**、温度（0~2）、单次上限（100~32000）、月度上限（0~100000，0=不限）、引用范围（至少一项） |
| `/stock/ai/test` | POST | 连通测试：发一次真实请求（`max_output_tokens=16`），页面提示会消耗少量 Token。可选参数 `api_key`（写入**进程内存**后立即用于测试）、`model`（测哪个模型，须在候选清单内）、`clear_key`（清除运行时密钥，回用环境变量） |

页面不出现任何密钥明文：只显示 `key_masked`（如 `sk-***ab`）与「已启用 / 未启用」。

**入口**：侧栏「AI 分析」，以及**订单列表每行「标的」列右端的「AI 分析」按钮**（`/stock/ai/?stock_id=<id>`，GET 链接）。
列表侧只做跳转，不预判启停状态；未启用时落到本页仍按既有规则显示原因并禁用提交入口。

**标的怎么定（二选一，页面不铺列表）**：

1. 从订单列表行内「AI 分析」进入（`?stock_id=`）；
2. 在**顶部搜索框**输入名称或代码 → 下拉来自 `/stock/ai/api/search`（服务端真查库，220ms 防抖，
   ↑↓ / Enter / Esc 键盘可达）→ 点选即跳 `?stock_id=`。

不带 `?stock_id=` 或 `?stock_id=` 指向不存在的标的时，**不默认选中任何标的**，进入「未选标的」空态
（能力卡片网格 + 「最近分析」快捷入口 + 引导文案）；右栏参数卡**仍渲染**，保证未启用时也能保存参数。

**布局**按 `theme.css` 的 `.ai-hero` + `.ai-work`（`minmax(0,1fr) / 320px`）：≤1240px 右栏三卡横排下沉，
≤1000px 收成单栏。页头不占 KPI 卡，状态 / 本月调用 / 模型 / 密钥脱敏压成 hero 里的 chips。

## 3. 数据模型

### 3.1 `stock_ai_report`

`id`、`stock_master_id`(FK, CASCADE)、`model`、`prompt_version`、`verdict`、`confidence`、`content_json`、`tokens_used`、`created_at`。用于复盘与调用量统计。

- `verdict`：五档之一（买入 / 增持 / 持有 / 减持 / 回避）；无法识别记 `未知`；**追问记录固定为 `问答`**，便于与评级统计区分；
- `confidence`：0~100，模型超界时**夹紧**到边界；
- `content_json`：结构化结果（summary / points / supports / risks / disclaimer / raw / parsed / context / scope / **dimensions / dimension_keys**）；追问时存 `{question, answer}`；
- `model`：本次**实际**调用的模型（页面选的模型落在这里，便于事后比较不同模型）；
- 索引：`(stock_master_id, created_at)` 与 `created_at`（月度计数用）。

### 3.2 `stock_ai_config`

**仅存非凭据参数**：温度、最大 Token、月度调用上限、引用数据范围、启用开关、**默认模型**、**默认分析维度**。单行表（`id=1`）。

- `enabled`：与环境变量 `AI_ENABLED` 是**与关系**——环境总闸关闭时表内开启无效（只能更关，不能更开）；
- 温度 / 上限 / 引用范围 / 模型 / 维度：表内非空值覆盖 `AI_*` 默认值；
- `data_scope`：逗号串，合法段为 `quote` / `valuation` / `indicator` / `kline`，非法段忽略；
- `dimensions`：逗号串，合法键见 §3.3，非法段忽略；空 = 全维度。

### 3.3 分析维度（`DIMENSIONS`）

维度是**给模型的关注点清单**，不是数据白名单（数据取舍由 §5 的引用范围控制）。
**每个维度都必须有本系统已采集的数据支撑**，否则模型只能编：

| 键 | 标签 | 依据数据 |
| --- | --- | --- |
| `valuation` | 估值 | `current_pe` / `target_pettm` / `current_pb` / `target_pb` |
| `technical` | 技术面 | 5 / 20 日涨跌（`ret_5d` / `ret_20d`） |
| `relative` | 相对强弱 | `rs_20d` / `rs_5d_ratio`（对比基准指数） |
| `position` | 52 周位置 | `high52w` / `low52w` / `pct_from_low52w` / `drawdown_52w` |
| `risk` | 风险 | 告警命中（`flag_*`）与「数据不足」项 |

设计稿中的「基本面 / 消息面」**不提供**：本系统没有财报与新闻数据源，放出来只会诱导模型编造。

## 4. 配置与安全

| 变量 | 说明 |
| --- | --- |
| `AI_ENABLED` | 总开关，默认 `0`；未启用时页面显示「未启用」而非报错 |
| `AI_API_BASE` | Base URL，末尾不带斜杠，`/responses`（或 `/chat/completions`）自动补全 |
| `AI_MODEL` | 默认模型：可填**单个 ID**，也可填逗号 / 分号分隔的清单（**第一项 = 实际发出去的默认模型**） |
| `AI_MODELS` | 可选模型清单（逗号 / 分号分隔）；**推荐**把候选清单放这里，`AI_MODEL` 只放默认那一个 |
| `AI_API_KEY` | 环境变量（长期方案）；也可在页面的追问 Composer 里**临时录入**（见 §4.1） |
| `AI_API_STYLE` | `responses`（默认）/ `chat` |
| `AI_TEMPERATURE` / `AI_MAX_TOKENS` / `AI_MONTHLY_LIMIT` / `AI_TIMEOUT` | 默认值（`0.6` / `1200` / `200` / `60s`），前三个可被 `stock_ai_config` 覆盖 |

**硬约束**（依据 `development-standards.md` 第 1 节）：

- `AI_API_KEY` **不入库、不回显明文、不打印进日志**（日志只记状态码、模型名与截断后的响应体）；
- 页面只做「已配置 / 未配置」的脱敏展示（`mask_key()` 只留前 3 位与后 2 位）；
- 文档与示例一律使用占位符。

### 4.1 运行时密钥（2026-10-23，追问 Composer 的「密钥」）

- 生效顺序：**页面录入（进程内存）> 环境变量 `AI_API_KEY`**；`describe_settings()['key_source']`
  取值 `runtime` / `env` / `''`，页面据此标注「本次运行」。
- 存放位置：`utils/ai_client._RUNTIME_KEY`（模块级字典）。**不落库、不落文件、不写日志、不回显**——
  这是"页面能填、填完立刻能用"与"禁止明文凭据落盘"之间唯一不冲突的落点。
- 清除：Composer 的「用回环境变量」（`clear_key=1`）；进程重启同样回到环境变量。
- 录入即测试：不设单独的「保存密钥」按钮，录入与「测试连通性」合并——
  录一个坏密钥却显示"已保存"比不保存更坑。

## 5. 输入与输出

**输入**：行情、PE/PB、`stock_indicator`、`stock_kline`——**全部来自已有表，不额外抓取外部数据**。
按页面「引用数据范围」裁剪：未勾选的段落在提示词里显示为「数据不足」，模型不得据此推断（`build_context(scope=...)`）。

**输出**（固定结构）：评级 + 置信度 + 核心结论 + 关键要点 + 支撑/风险 + **免责声明**。

**连通测试**：发起一次真实请求，页面明确提示会消耗少量 Token。

**免责声明**：报告必须携带「由 AI 基于公开行情数据生成，不构成投资建议」。

## 6. 行为约定

- 未配置密钥 / 未启用时返回 `status='disabled'`，**不抛异常、不打堆栈**，页面按钮 `disabled`；
- 外部调用**必须传超时**（`AI_TIMEOUT`，默认 60s），超时返回 `status='timeout'`；
- 异常必须 `logger.exception` 并返回可判定的失败值，`call_ai()` 统一返回
  `{ok, status, text, tokens, model, error}`，**禁止 `except Exception: pass`**；
- 月度上限达限时明确拒绝并提示（`used >= limit` 即拦），限 `0` 表示不限；
- 防重复提交：三个提交入口都带 `data-submit-once`，按钮点击后变「提交中…」；
  Composer 的圆形发送键带 `data-keep-content`，只禁用、不换文案（否则文字会撑破圆角）；
- 解析失败（模型没按 JSON 返回）**不丢报告**：退化为「未知评级 + 原文摘要」，页面标注"未按约定格式返回"；
- 追问必须先有一次正式分析，否则提示「请先生成一次分析」；问答同样计入月度额度并落库留痕；
- **模型走白名单**：候选 = `AI_MODEL` + `AI_MODELS`（两个变量**都**按逗号 / 分号拆分，`AI_MODEL`
  第一项排最前）；`analyze` / `ask` / `config` 收到的 `model` 必须命中候选，否则拒绝（不静默回退），
  避免把请求打到未知模型；
- **实际发出去的模型一定是单个 ID**：`default_model()` 取清单第一项，页面 chip、调用参数、
  `StockAiConfig.effective()['model']` 都用它——绝不把「a,b,c」整串当模型名发出去；
- **库里保存的模型失效时回退**：`stock_ai_config.model` 若已不在候选清单（历史遗留的整串），
  页面回退到默认模型并标注「已回退」；**表单提交不回退**，仍然显式报错；
- **维度可缺省**：请求没带 `dimensions[]` → 用参数面板保存的默认维度 → 仍为空则全维度；
  维度以中文标签注入提示词，并要求「每个维度至少一条结论、数据不足就写数据不足，不许外推」；
- **搜索在服务端**：`/stock/ai/api/search?q=` 走 `StockMaster.get_all(search_query=...)`
  （`search_fields = ['stock_name', 'stock_code']`，值一律 `%s` 参数化），一次最多 12 条，
  返回 `{items:[{id,name,code,price,url}], total, truncated}`；`url` 由服务端 `url_for` 生成，前端不拼地址。
  **`q` 为空直接返回空列表**——绝不能退化成"返回全部"（否则又变回铺全量名单）；查询失败记日志 + 500 + `error` 字段；
- **现价取 `stock_warehouse.current_price`**（与订单列表 / 编辑页同一口径），该列缺失才回退指标快照的 `price`，
  两者都没有才渲染「—」；
- **未启用只禁「会发请求」的入口**（生成分析 / 追问 / 连通测试）；「保存参数」是纯写库操作，始终可点；
- 追问的用户消息必须以「标的：…」开头（含标的 + 数据 + 上一轮 JSON），**不得把 `SYSTEM_PROMPT` 贴进用户消息**。
- **追问框是 Composer**（`.ask-box`，结构契约在 `templates/ai_analysis.html`）：
  多行输入（Enter 发送 / Shift+Enter 换行，`theme.js initAskComposer()`）+ 底部工具条
  「模型 pill（`select[name=model]`，仅作用于本次追问，服务端仍走白名单）」+「**测试连通性** pill」（展开
  密钥面板：顶部显示脱敏密钥 + `api_key` 输入 +「用这个密钥测一下」+「用回环境变量」）+ 右下圆形发送键。
  它渲染在标的 / 报告分支**之外**：密钥入口必须随时可达（没密钥时正需要它），
  但发送键只在「已就绪 + 有上一轮分析」时可用（`can_ask`），避免点了必然失败。
- **连通测试入口唯一**：只在 Composer，右栏参数卡**不再放**「连通测试」按钮（只保留脱敏密钥文本并指向底部）；
  两处都放会让人不知道该点哪个（见 [2026-10-23 连通测试入口唯一化](../archive/changes/2026-10-23-ai-test-entry.md)）。

## 7. 验收条件

1. 未配置 `AI_API_KEY` 时页面显示「未启用」，无异常、无堆栈。
2. 密钥不出现在日志、响应体与落库内容中。
3. 月度调用上限达限时被拦截并给出提示。
4. 报告包含评级、置信度、关键要点、支撑/风险与免责声明。
5. 每次分析写入 `stock_ai_report`，含模型名与 `prompt_version`。
6. 调用超时或失败时记录日志并返回可判定的失败值，不影响其他页面。
7. 免责声明以本地常量为准——模型漏写或改写不影响页面展示。
8. `responses` 与 `chat` 两种风格都能解析出正文；`usage` 缺失时记 0 tokens 而不是报错。
9. 表内 `enabled` 只能关闭、不能绕过环境变量总闸。
10. 页面为「顶部搜索 + 工作台」（标的条 / 报告 + 参数 + 快照 + 历史）；顶部搜索框按名称或代码**服务端真搜索**，能搜到库中任意标的。
10.1 页面**不渲染全量标的列表**；不带 `?stock_id=` 时进入「未选标的」空态，右栏参数卡仍可保存。
11. 模型下拉的候选项来自 `AI_MODEL` + `AI_MODELS`（都按逗号 / 分号拆分），选中的模型**真实下发**并落库到 `stock_ai_report.model`；伪造模型被拒。
11.1 `AI_MODEL` 填多个模型时下拉要拆成多个选项，默认选中第一项；页面显示与真实下发的是同一个**单个** ID。
12. 分析维度可多选，所选维度进提示词并落库 `content_json.dimensions`；报告页能看出本次用了哪些维度。
13. 参数面板可保存默认模型与分析维度，下次生成时作为默认值生效。
14. 页面缺失数据一律渲染「—」，不得渲染成 `0` / `0.00%`。
15. 追问框是 Composer：输入框 + 模型下拉（候选来自清单，默认选中实际生效模型）+ 密钥 pill + 圆形发送键；
    Enter 发送、Shift+Enter 换行（回归用例 `tests/test_ai_analysis.py::AiComposerTest`）。
16. Composer 选的模型**真实下发**并落库（`stock_ai_report.model`）；伪造模型被拒且不发请求。
17. 未改动 `AI_API_KEY` 时，页面录入的密钥立即生效（`key_source=runtime`），页面只显示脱敏值，
    录入的明文密钥不出现在响应体 / 日志 / 数据库（`RuntimeKeyTest`）；「用回环境变量」后恢复 `env`。
18. 连通测试入口唯一在 Composer 的「测试连通性」pill；右栏参数卡底部**不渲染** `/stock/ai/test`
    （`AiComposerTest.test_test_entry_only_in_composer`）。

## 8. 已知限制

- 首期**不支持流式输出**。
- Token 计费依赖模型返回值，各厂商字段不一致：按可选字段解析，缺失记 0。
- AI 输出具备不确定性，同一标的两次分析结论可能不同，属预期行为。
- 分析结果不构成投资建议，页面必须展示免责声明。
- **推理型模型容易触发超时**：实测网关（`api.agicto.cn` / `qwen3.5-plus`）单次输出 3k+ tokens，追问曾 60 s 未返回；
  代码行为正确（超时→可判定失败值→不落库），但这类模型建议把 `AI_TIMEOUT` 调到 120~180
  （见 [归档变更 §8.4](../archive/changes/2026-10-21-ai-analysis.md)）。
- 目前只对**一家** OpenAI 兼容网关实测过（`responses` 与 `chat` 两种风格均可用）；换厂商仍需各自确认返回结构。
- 追问不留存完整消息历史，只带最近一次正式报告作为上下文；跨轮追问的语义连贯性有限。
- 页面同一时刻只展示一只标的；无批量分析 / 定时分析能力。
- 追问回答不经过结构化解析（`verdict='问答'`，只存原始文本）。
- **不提供「基本面 / 消息面」维度**：无财报与新闻数据源，宁可少给维度也不诱导模型编造（见 §3.3）。
- `AI_MODELS` / `AI_MODEL` 只是候选清单，**不校验该网关是否真的支持**；填错时由「连通测试」暴露（返回 error）。
- 搜索下拉一次最多 12 条，超出只提示「请输入更完整的关键字」（`truncated`），不做翻页。
- **搜索按子串匹配**：`LIKE %q%` 命中名称或代码，代码存的是 `SH600519` 这类带前缀格式，
  搜「600519」能中，搜「000001」只有在库里真存了该串时才中。
- 工作台布局在 1240 / 1000px 断点的折叠效果、hero 渐变与下拉观感只有 CSS 契约测试，浏览器观感需人工确认。
- **运行时密钥只在当前进程有效**：重启即失效（回到 `.env`）；多进程 / 多 worker 部署时各进程各自独立，
  只有录入的那个进程能用。长期方案仍是把 `AI_API_KEY` 写进 `.env`。
- 运行时密钥无法"查看"：页面只给脱敏值，忘了一律重新粘贴（这是刻意的，避免任何形式的明文回显）。
- Composer 的模型下拉只影响**追问**，不影响「生成分析」（后者用参数卡里保存的默认模型）；
  两处各改各的，是有意为之（聊天时随手换模型不应改掉参数）。
