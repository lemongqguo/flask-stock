# 变更：AI 分析追问框改为 Composer（模型选择 + 密钥 / 连通测试）

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 行为变更（交互形态 + 新增运行时密钥能力） |
| 触发 | 用户要求：AI 页底部提问框改为参考图的 Composer 样式；「深度思考」改为**可选模型**，「智能搜索」改为**密钥**，连通测试并入同一处 |
| 关联规格 | [007 AI 个股分析](../../current/007-ai-analysis.md)（§2.1 路由、§4.1 运行时密钥、§6 行为约定）、[008 前端 UI](../../current/008-frontend-ui.md)（AI 页 Composer） |
| 验证 | `tests/test_ai_analysis.py` + 全量 `tests/run_all.py`（见 §6） |

## 1. 问题与动机

原提问框是一行「input + 提问按钮」，功能上只有"填问题"，而模型与密钥都散落在右栏参数卡：

- 追问想换模型得先滚到右栏、改下拉、点「保存参数」——三步才生效，且改的是"默认模型"，不是"这一次用哪个"；
- 密钥只能在 `.env` 里改，改完还要重启进程；连通测试也在右栏，和密钥不在同一处，「配了密钥想立刻验证」要来回找。

参考图（Composer）的形态正好把这三件事收进一个框：**输入 + 底部左侧工具条（模型 / 密钥）+ 右下圆形发送**。

## 2. 变更类型

- [ ] 缺陷修复
- [x] **行为变更**：追问框的结构与交互（模型选择位置、密钥入口位置）
- [x] **新增能力**：运行时录入密钥（进程内存）与就地连通测试

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 追问框形态 | `.ask-bar`：单行 input + 右侧「提问」按钮 | `.ask-box` Composer：多行输入（Enter 发送 / Shift+Enter 换行）+ 底部工具条 + 圆形发送按钮 |
| 模型选择 | 仅在右栏参数卡（保存默认模型） | 追问框内有**模型 pill**（下拉），选中的模型**只作用于本次追问**并真实下发、落库 `stock_ai_report.model`；右栏仍管"默认模型" |
| 密钥 | 只能改 `.env` 的 `AI_API_KEY`（重启生效） | 追问框「密钥」pill 展开输入框：粘贴即写入**当前进程内存**并立即用于后续调用（含连通测试）；可一键「用回环境变量」 |
| 连通测试 | 右栏参数卡按钮 | 与密钥同一处（`/stock/ai/test`），测的就是刚录入的密钥 / 所选模型 |
| 入口禁用 | 未启用时输入框禁用 | 「发送」与输入框在未就绪时禁用；**密钥输入与测试始终可用**（否则没有密钥就永远没法录密钥） |

## 4. 影响面

- 文件：`templates/ai_analysis.html`、`static/css/theme.css`、`static/js/theme.js`、`utils/ai_client.py`、`views/ai_analysis.py`、`tests/test_ai_analysis.py`；
- 数据表 / 迁移：**无**（密钥绝不入库）；
- 配置：无新增环境变量；
- 路由：`/stock/ai/test` 增加可选参数 `api_key` / `model` / `clear_key`，**不新增路由**。

## 5. 取舍与安全边界（重点）

1. **密钥只存进程内存**：`utils/ai_client._RUNTIME_KEY`，不落库、不落文件、不进日志、不回显（页面只显示 `mask_key()` 结果）。
   - 理由：项目硬约束是「第三方 Token 禁止入库 / 禁止明文凭据」（`development-standards.md` §1）。
     要让「页面能填密钥且立即生效」，唯一不破坏该约束的落点就是内存。
   - 代价（如实记录）：**进程重启后失效**，回到 `.env` 的 `AI_API_KEY`；多进程部署时各进程不一致（本系统为单进程 Flask + 监控线程，故可接受）。
2. **不引入"密钥保存"按钮**：录入与验证合并成「测试连通性」——录一个坏密钥却显示"已保存"，比不保存更坑。
3. **模型白名单不放宽**：Composer 下拉只渲染 `AI_MODEL` + `AI_MODELS` 的候选，服务端 `_selection()` 仍校验，
   伪造值拒绝（不静默回退）。
4. **追问用的模型不写回默认值**：Composer 选的是"这一次"，避免聊天时随手换模型把参数卡也改掉。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| Composer 结构（输入 / 模型 pill / 密钥 pill / 圆形发送 / 密钥面板） | `AiComposerTest.test_composer_structure` / `test_model_options_come_from_config` | 通过 |
| 追问携带 Composer 选的模型并落库 | `AiComposerTest.test_ask_uses_composer_model` | 通过 |
| 伪造模型被拒且不发请求 | `test_ask_rejects_unknown_model` / `test_test_route_rejects_unknown_model` | 通过 |
| 运行时密钥：立即可用、脱敏展示、优先级高于环境变量 | `RuntimeKeyTest.test_runtime_key_makes_ready` / `test_runtime_key_overrides_env_key` | 通过 |
| 测试连通性会带上刚录入的密钥与所选模型 | `AiComposerTest.test_test_route_saves_runtime_key_and_uses_model` | 通过 |
| 不填密钥时不误清已有密钥 / 「用回环境变量」清空 | `test_test_route_without_key_only_tests` / `test_test_route_clear_key` / `RuntimeKeyTest.test_clear_runtime_key_restores_env` | 通过 |
| 密钥不写日志、不入返回体、不回显页面 | `RuntimeKeyTest.test_runtime_key_never_leaks_in_logs` / `test_runtime_key_never_leaks_in_return_value` + 路由断言 | 通过 |
| 未就绪时「发送」禁用但密钥入口可点 | `AiViewTest.test_action_buttons_disabled_when_not_ready` | 通过 |
| 真实链路冒烟（真实库渲染 + 真实网关请求） | 临时脚本：GET 页面后 POST `/stock/ai/test` 带错误密钥，得到可判定失败、页面无明文回显、`key_source=runtime`→清除后 `env`；脚本已删除 | 通过 |
| 全量回归 | `python tests/run_all.py`（541 用例） | 通过 |

- 实际验证到的范围：模板结构、模型真实下发、运行时密钥生效 / 优先级 / 清除、连通测试的参数传递与真实请求（失败可判定）、全量后端回归。
- **未验证**的范围（如实记录）：
  - **一次成功的**连通测试：本机密钥失效（`400016`），只能验证"坏密钥被正确拒绝"，无法验证"好密钥返回 OK"；
  - Composer 的视觉观感（圆角 / 聚焦描边 / Enter 行为）需人工刷新浏览器确认——本机无浏览器自动化。

## 7. 合入清单

- [x] 代码已合并
- [x] `../../current/007-ai-analysis.md` 已更新（路由参数 + §4.1 密钥来源 + Composer 约定 + 验收 / 限制）
- [x] `../../current/008-frontend-ui.md` 已更新（AI 页 Composer 结构 + 圆形按钮契约）
- [x] `../../PROGRESS.md` 模块进度与变更历史已更新
- [x] `../../README.md` 变更清单已同步
- [x] 取舍已在 §5 说明（进程内存密钥），未新增 ADR
- [x] 本文件已归档到 `../../archive/changes/`
