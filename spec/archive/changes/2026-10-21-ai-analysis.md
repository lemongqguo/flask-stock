# 2026-10-21 AI 个股分析

> 已于 2026-10-22 合入 [007](../../current/007-ai-analysis.md)，本文件仅作历史依据。

| 项 | 值 |
| --- | --- |
| 状态 | **已合入**（表 / 参数 / 拦截 + **真实模型调用**均已验证，见 §8.5） |
| 类型 | 新增能力 |
| 触发 | 需求：接入 AI 分析个股，输出结构化报告并支持追问 |
| 关联规格 | 新建 `../current/007-ai-analysis.md`（实施验证后合入） |
| 验证 | 443 用例全绿 + 真实库验证 + **真实模型调用验证**，见 [第 8 节](#8-实施与验证记录) |

---

## 1. 接入方式

采用**自定义模型**模式：**OpenAI 兼容 Responses API**（API 格式 + Base URL + Model ID + API Key），不绑定特定厂商。

---

## 2. 新增数据表

### 2.1 `stock_ai_report`（报告留痕）

`id`、`stock_master_id`(FK, CASCADE)、`model`、`prompt_version`、`verdict`、`confidence`、`content_json`、`tokens_used`、`created_at`。

用于复盘与调用量统计。

### 2.2 `stock_ai_config`（可调参数）

**仅存非凭据参数**：温度、最大 Token、月度调用上限、引用数据范围、启用开关。

> 产品决策（2026-10-21）：AI 参数**新建表**存储，密钥除外。

---

## 3. 配置与安全

| 变量 | 说明 |
| --- | --- |
| `AI_ENABLED` | 总开关；未启用时页面显示「未启用」而非报错 |
| `AI_API_BASE` | Base URL，末尾不带斜杠，`/responses` 自动补全 |
| `AI_MODEL` | 模型 ID |
| `AI_API_KEY` | **仅从环境变量读取** |
| `AI_TEMPERATURE` / `AI_MAX_TOKENS` / `AI_MONTHLY_LIMIT` | 默认值，可被 `stock_ai_config` 覆盖 |

**安全红线（依据 `rules/development-standards.md` 第 1 节）**：

- `AI_API_KEY` **不写入数据库、不在页面回显明文、不打印进日志**；
- 页面密钥输入框只做"已配置 / 未配置"的脱敏展示；
- 示例一律使用占位符，禁止出现真实密钥。

---

## 4. 输入与输出

**输入**：全部取自系统已有表（行情、PE/PB、`stock_indicator`、`stock_kline`），**不额外抓取外部数据**。

**输出**（固定结构）：评级 + 置信度 + 核心结论 + 关键要点 + 支撑/风险 + 免责声明。

**连通测试**：提供一次真实请求的测试能力，明确提示会消耗少量 Token。

**免责声明**：报告必须携带「由 AI 基于公开行情数据生成，不构成投资建议」字样。

---

## 5. 实施要点

- 新增 `utils/ai_client.py` 封装 OpenAI 兼容调用，超时必传（遵守项目对外部调用的要求）；
- 异常必须 `logger.exception` 并返回可判定的失败值，**禁止 `except Exception: pass`**；
- 月度上限达限时明确拒绝并提示，不静默失败；
- 未配置密钥时返回「未启用」状态，不抛异常、不打堆栈。

---

## 6. 验证计划

新增 `tests/test_ai_client.py`：

- 未配置时返回「未启用」而非异常；
- 密钥不出现在日志、响应体与落库内容中；
- 月度上限拦截生效；
- 超时与异常被捕获并返回失败值。

回归 `python tests/run_all.py`。

---

## 7. 遗留

- 首期**不接流式输出**（后续可另立变更）。
- Token 计费统计依赖模型返回值，各厂商字段不一致：按可选字段解析，缺失记 0。
- AI 输出具备不确定性，同一标的两次分析结论可能不同，属预期行为。
- 追问只带最近一次正式报告的上下文，不留存完整消息历史。

---

## 8. 实施与验证记录（2026-10-22）

### 8.1 改动清单

| 文件 | 改动 |
| --- | --- |
| `config.py` | 新增 `AI_*` 9 项（`AI_ENABLED` 默认关闭、`AI_API_BASE`、`AI_MODEL`、`AI_API_KEY`、`AI_API_STYLE`、`AI_TEMPERATURE`、`AI_MAX_TOKENS`、`AI_MONTHLY_LIMIT`、`AI_TIMEOUT`） |
| `database.py` | 新增 `stock_ai_report`（含 FK→`stock_master` CASCADE、`(stock_master_id, created_at)` 与 `created_at` 索引）、`stock_ai_config`（单行，`id=1`） |
| `utils/ai_client.py` | 新增：OpenAI 兼容调用，`responses` / `chat` 双风格、**超时必传**、失败返回 `{ok,status,...}`、`mask_key()` 脱敏、`test_connection()` |
| `utils/ai_prompt.py` | 新增：`SYSTEM_PROMPT`、`PROMPT_VERSION='ai-007-v1'`、上下文组装（**按引用范围裁剪**、缺失值写「数据不足」）、结构化解析（代码块 / 夹杂话术 / 纯文本兜底）、免责声明以本地常量为准 |
| `models/stock_ai.py` | 新增：报告写入/查询/月度计数、参数读写与「环境总闸 ∧ 表内开关」合并语义 |
| `views/ai_analysis.py` | 新增蓝图 `ai`（`/stock/ai`）：页面、分析、追问、参数、连通测试；月度上限拦截、未启用拦截 |
| `templates/ai_analysis.html`、`templates/base.html`、`static/css/theme.css` | 新增报告页（KPI / 报告卡 / 追问 / 历史 / 参数）、侧栏「AI 分析」导航项（`#i-sparkles`）、`.ai-*` 样式 |
| `.env.example` | 登记 `AI_*`（密钥留空占位） |
| `tests/test_ai_analysis.py` | 新增 52 个用例（客户端 / 提示词 / 模型 / 视图四层） |

### 8.2 验证结果

```powershell
stockenv\Scripts\python.exe tests\run_all.py
# Ran 443 tests ... OK  （0 失败 / 0 错误 / 0 跳过）
```

- 基线 391 → **443 个用例全部通过**（新增 52，全部在 `tests/test_ai_analysis.py`）。
- 单模块复核：`test_ai_analysis` 52 passed（其中 2 条覆盖报告卡 / 问答分支的模板渲染）。

### 8.3 真实环境验证（不 mock）

| 验证项 | 结果 |
| --- | --- |
| 两张表建出 | ✅ `stock_ai_report` / `stock_ai_config` 均存在于 `information_schema` |
| 外键与索引 | ✅ `stock_ai_report → stock_master` 的 FK 存在；`idx_ai_report_stock` / `idx_ai_report_created` 已建 |
| `GET /stock/ai/?stock_id=1`（真实库） | ✅ 200，91 只标的进左侧 rail，分析 / 追问 / 连通测试 / 参数四组表单齐全 |
| 未启用提示 | ✅ 页面显示「AI 分析未启用」并禁用 4 个提交入口 |
| 参数真实写入 | ✅ 回读 `(enabled=1, temperature=0.40, max_tokens=900, monthly_limit=7, data_scope='quote,kline')`，验证后已 `DELETE` 还原（表 0 行） |
| 未启用时分析拦截 | ✅ POST `/analyze` 被拒且 `stock_ai_report` 仍为 0 行 |

### 8.4 真实模型调用验证（2026-10-22 补充，凭据已配置，不 mock）

`.env` 已填 `AI_ENABLED=1` + Base / Model / Key（`AI_API_STYLE=responses`，网关：`api.agicto.cn`，模型 `qwen3.5-plus`），据此补做：

| 验证项 | 结果 |
| --- | --- |
| 就绪判定 | ✅ `is_ready() = (True, '')`；页面不再显示「未启用」，4 个提交入口可用 |
| 连通测试（真实请求） | ✅ `status='ok'`，耗时 **4.9 s**，消耗 269 tokens，返回 `OK` |
| **真实生成分析**（`/stock/ai/analyze`，标的 1） | ✅ 302 → `?report_id=2`；`parsed=true`，评级 + 置信度 55 + 要点 / 支撑 / 风险齐全，3357 tokens |
| **真实追问**（`/stock/ai/ask`） | ✅ 302 → `?report_id=3`；落库 `verdict='问答'`，4877 tokens，**问题与回答均留痕** |
| 超时失败路径（真实发生） | ✅ 追问首次触发 `requests.ReadTimeout`（60 s）→ 页面提示「追问失败：调用超时（60 秒）」，**未落库**；重试即成功 |
| `chat` 风格探测（同一网关） | ✅ `status='ok'`，该网关两种风格都可用 |
| 结构化解析 | ✅ 真实模型返回的是带正文的 JSON（无代码块包裹），`parse_report` 正常提取；置信度 / 评级均落在合法域 |
| 免责声明 | ✅ 正式报告 `disclaimer` 有值；问答分支回退到模板内置文案，页面同样展示 |
| **密钥未落库 / 未回显** | ✅ 全表扫描 `content_json` 不含密钥（含末 8 位子串）为 `False`；页面只渲染 `sk-***8j` |
| 月度计数（真实） | ✅ `count_since(本月 1 日) = 3`，与 `stock_ai_report` 行数一致 |

> 验证产生的 3 行报告（id 1~3）**保留在库**：id 1 为用户自行测试（标的 92），id 2 / 3 为本次验证产出（标的 1）。
> 如需清理：`DELETE FROM stock_ai_report WHERE id IN (2,3);`

**真实环境暴露的一个使用注意**：该网关的模型是**推理型**（单次输出 3k+ tokens），首次追问在 60 s 内没返回。
代码行为正确（超时→可判定失败值→不落库），但**推理型模型建议把 `AI_TIMEOUT` 调到 120~180**，否则长思考会频繁触发超时。

### 8.5 未验证范围

- 报告页观感（徽标、要点列表、长文本换行）无浏览器级回归，仅模板契约测试；真实报告内容由用户肉眼确认。
- 月度上限按 `created_at >= 本月 1 日` 计数，跨时区 / 账期口径未做区分；真实额度（200/月）远未触达，达限拦截只在单测验证。
- 仅对 `api.agicto.cn` 一家网关实测；其他厂商 `responses` 实现的结构差异（已兼容 `output_text` 与
  `output[].content[].text` 两种）仍需在各自环境确认。
- 流式输出、批量 / 定时分析未实现（首期范围外）。
