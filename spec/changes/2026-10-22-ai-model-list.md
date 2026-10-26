# 2026-10-22 AI_MODEL 支持逗号分隔的模型清单

**状态**：已交付（待人工确认）
**提出日期**：2026-10-22　|　**负责人**：AI 助手
**受影响规格**：[007 AI 个股分析](../current/007-ai-analysis.md)

---

## 1. 问题与动机

用户按"逗号分隔填多个模型"的直觉，把 5 个模型全填进了 `AI_MODEL`：

```
AI_MODEL = qwen3.5-plus,gpt-4o-mini,kimi-k2.5,deepseek-v4-pro,glm-5.3-flash
AI_MODELS = （空）
```

而旧约定里 `AI_MODEL` 是"**单个**默认模型 ID"，清单只在 `AI_MODELS`。于是 `available_models()`
把整串当成一个模型返回：

```
available_models() = ['qwen3.5-plus,gpt-4o-mini,kimi-k2.5,deepseek-v4-pro,glm-5.3-flash']
```

后果有两个，都不该发生：

1. 页面「模型」下拉**只有一个选项**，选项内容是一整串模型名；
2. 这串文本会被当作 `model` 发给网关——**没有哪个网关认这个 ID**，调用必失败，
   而页面还显示"已启用"，用户会以为配置没问题。

根因不是用户填错（逗号分隔是常识直觉），而是实现只认一种填法、且**不校验填进来的是不是一个合法模型 ID**。

## 2. 变更类型

- [x] **行为变更**：`AI_MODEL` 由"单个默认模型"扩展为"默认模型清单，**第一项为默认模型**"
- [x] **行为变更**：保存的模型不在候选清单内时，回退到默认模型而不是把非法串发出去
- [ ] 缺陷修复 / 纯重构 / 新增能力

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| `AI_MODEL` 的语义 | 单个默认模型 ID；填了多个就整串当一个 ID | **逗号 / 分号分隔的模型清单**，**第一项 = 默认模型** |
| `AI_MODELS` 的语义 | 逗号分隔的候选清单 | 不变（仍只做候选清单，且允许分号） |
| 分隔符 | 只有 `,` | `,` 与 `;` 都认（与 `config.py::_get_list` 一致） |
| `available_models()` | `AI_MODEL` 整串 + `AI_MODELS` 逐项 | 两个变量**都**按清单解析；`AI_MODEL` 的第一项排最前，去重保序 |
| `describe_settings()['model']` | `AI_MODEL` 原文（可能是整串） | **`default_model()`**：单个模型 ID（`AI_MODEL` 第一项，缺失则 `AI_MODELS` 第一项） |
| `StockAiConfig.effective()['model']` | `Config.AI_MODEL` 原文 | `ai_client.default_model()`（单个 ID） |
| 表单/库里保存的模型不在清单内 | 拒绝并提示「模型不可用」 | **回退到默认模型**（仍然拒绝伪造的未知模型，只是不再让页面卡死） |
| 页面「模型」chip | 显示 `config.model`，未保存显示「未配置」 | 显示**实际会发出去的那个模型**；库里没存时显示环境变量默认值并标「默认」 |

**不变的部分**：模型白名单校验仍然有效（`is_allowed_model`），密钥仍只走环境变量，
`AI_MODELS` 仍是官方推荐的清单位置（本次只是让 `AI_MODEL` 也容错）。

## 4. 影响面

- 涉及模块/文件：`utils/ai_client.py`（新增 `_split_models` / `default_model`，改写 `available_models` / `describe_settings`）、
  `models/stock_ai.py`（`effective()` 的 env 默认值改取 `default_model()`）、
  `views/ai_analysis.py`（`_model_and_dims` 回退 + 页面新增 `model_display`）、
  `templates/ai_analysis.html`（hero chip 与下拉选中态）、`tests/test_ai_analysis.py`（新增用例）
- 涉及数据表 / 是否需要迁移：**无**
- 是否影响既有数据：`stock_ai_config.model` 若已存了非法长串，本次**不改库**，只是调用时回退到默认模型
- 是否需要新增/修改配置：**无**（现有 `AI_MODEL` / `AI_MODELS` 语义扩展，无需新增变量）

## 5. 实施要点

1. 解析逻辑集中在 `ai_client._split_models()`，两个变量共用，避免两处各写一套 split；
   分隔符与 `config.py::_get_list` 对齐（`,` 与 `;`），空项丢弃、保序去重。
2. `default_model()` 是**唯一**"实际发出去的默认模型"来源，`describe_settings` 与
   `StockAiConfig.effective()` 都用它，避免页面上显示的与真正调用的不是同一个。
3. 回退只发生在"保存的值不在候选清单"这一种情况，且**白名单校验没有放松**：
   回退后仍然必须是清单内的模型，清单为空才报错。
4. 不修 `.env`：这是配置习惯问题，代码兼容即可，同时在使用说明里写清
   「清单放 `AI_MODELS`、`AI_MODEL` 放单个默认模型」是推荐写法。

## 6. 验证范围与结果

### 6.1 真实环境验证（不 mock，读真实 Config）

| 验证项 | 结果 |
| --- | --- |
| 复现原状 | ✅ `available_models()` 返回 1 项（整串），下拉只有一个选项 |
| 修复后 `available_models()` | ✅ 返回 5 项：`['qwen3.5-plus', 'gpt-4o-mini', 'kimi-k2.5', 'deepseek-v4-pro', 'glm-5.3-flash']` |
| `default_model()` | ✅ `qwen3.5-plus`（第一项） |
| `effective()['model']` | ✅ `qwen3.5-plus`，不再是整串 |
| 页面渲染 | ✅ 下拉 5 个 option，默认选中 `qwen3.5-plus`；hero chip 显示 `qwen3.5-plus · 默认` |

### 6.2 回归

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 全量回归 | `stockenv\Scripts\python.exe tests\run_all.py` | 见 §6.3 |
| 新增用例 | `AI_MODEL` 多模型拆分 / 默认值取第一项 / 分号分隔 / 非法值回退 | 见 §6.3 |

### 6.3 回归

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 全量回归 | `stockenv\Scripts\python.exe tests\run_all.py` | ✅ **479 用例 OK**（474 → +5） |
| `AI_MODEL` 多模型拆分 | 用例断言 `available_models()` 拆成 3 项、`default_model()` 取第一项 | ✅ |
| 分号也当分隔符 | 用例 `AI_MODELS='m-a;m-b,m-c'` | ✅ |
| 整串不再是合法模型 | 用例断言 `is_allowed_model('m-a,m-b')` 为 False | ✅ |
| 下拉渲染 | 用例断言 3 个 option + 默认选中第一项 + chip 显示「m-a · 默认」 | ✅ |
| 库里旧值回退 | 用例把 `effective()` 的 model 设成清单外的值，断言回退 + 页面提示 | ✅ |
| 伪造模型仍被拒 | 既有用例 `test_analyze_rejects_unknown_model` | ✅ 未回归（表单提交**不**回退，仍显式报错） |

### 6.4 未验证范围

- **未做真实 AI 调用**：本轮只改模型解析与页面取值，未触碰请求体组装；
  用户环境里 `qwen3.5-plus` / `gpt-4o-mini` / `kimi-k2.5` / `deepseek-v4-pro` / `glm-5.3-flash`
  这 5 个 ID 是否真的被网关支持，只能由页面「连通测试」暴露。
- 未改用户的 `.env`（清单仍在 `AI_MODEL` 里），代码已兼容；若之后挪到 `AI_MODELS` 无需再改代码。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/007-ai-analysis.md` 已更新为新的有效约定（§4 变量表 / §5 白名单与回退规则 / 验收 11.1）
- [x] `../PROJECT_WIKI.md` 已同步（环境变量表、`stock_ai_config.model` 说明、使用步骤）
- [x] `../PROGRESS.md` 模块进度与台账已更新
- [x] `../README.md` 进行中变更清单已同步
- [ ] 本目录移入 `../archive/changes/`（待人工确认下拉后归档）
