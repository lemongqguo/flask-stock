---
description: flask-stock 项目的规格驱动维护守则。每次修改代码、需求变更、缺陷修复时必须先读并遵守，保证规格、进度与代码三者同步。
globs: ["**/*"]
alwaysApply: true
---

# 规格驱动维护守则（flask-stock）

本规则适用于对 `d:/flask-stock` 的**任何**改动。项目长期维护，规格是唯一事实来源。

## 0. 动手前必读（顺序）

1. `spec/README.md` —— 索引：当前有效规格清单、已知限制。
2. `spec/PROGRESS.md` —— 进度：模块状态、缺陷台账（D-xx）。
3. `spec/current/NNN-*.md` —— 与你改动相关的那份当前有效规格。
4. `spec/rules/development-standards.md` —— 编码硬约束。

**没读就动手 = 违规。**

## 1. 先判断变更类型

| 类型 | 判断依据 | 正确做法 |
| --- | --- | --- |
| 缺陷修复 | 实现没满足 `current/` 已有约定 | **不改规格**，补回归用例后修复 |
| 行为变更 | 产品要求改原有行为 | 先在 `changes/` 改约定，再改测试与代码 |
| 纯重构 | 行为不变，内部结构变化 | 说明为什么安全，通常无需新规格 |
| 新增能力 | 新增场景 | 新建 `current/NNN-slug.md` 规格 |

## 2. 变更闭环（不得跳步）

1. 在 `spec/changes/NNN-slug/change.md` 建变更记录（复制 `spec/changes/_TEMPLATE.md`），写明：问题、旧约定→新约定、影响面、验证范围。
2. 实施代码改动，遵守 `spec/rules/development-standards.md`。
3. 按记录中的验证范围实际验证，填写结果，**明确写出未验证的范围**。
4. 合入：把差异写入 `spec/current/` 对应规格。
5. 同步：更新 `spec/PROGRESS.md`（模块状态 + 缺陷台账）与 `spec/README.md`（清单 / 已知限制）。
6. 涉及方案取舍时补 `spec/decisions/NNN-*.md`。
7. 把变更记录状态置为 `已合入`，目录移入 `spec/archive/changes/`。

## 3. 同步硬约束

- 改了 `spec/current/` → 必须回改 `spec/PROGRESS.md`。
- 改了台账条目 → 必须有 `../current/NNN-*.md` 链接；无规格的模块先补规格再开发。
- 缺陷 `已验证` → 同步更新对应规格的"已知限制"。
- 编号 `NNN` / `D-NN` 只增不复用、不删除，废弃项归档不删。

## 4. 安全红线

- 禁止新增任何明文凭据（密码 / SECRET_KEY / SMTP 授权码 / 第三方 Token）。新配置走 `os.environ.get`。
- **禁止**把 `config.py` 中的真实凭据输出到对话、文档、Issue 或注释里；示例一律用占位符。
- 不得提交 `stockenv/`、`logs/`、`__pycache__`、`.env`。
- 新代码禁止 `except Exception: pass` / 仅 `print`；必须 `logger.exception` 并返回可判定的失败值。

## 5. 输出要求

- 汇报改动时，必须同时说明：**改了哪些代码 + 更新了哪些 spec 文件 + 变更编号 + 验证范围**。
- 若本次改动未同步 spec，必须显式说明原因并提示用户补做。
