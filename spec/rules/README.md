# 项目实施规范守则（总纲）

> 本目录是**持续规则**：不随单次需求变化，只有在规则本身修订时才改。
> 任何对 `d:/flask-stock` 的修改——无论是人还是 AI 助手——都必须遵守本目录的规范。
> Agent 侧的强制版本见 [`.codebuddy/rules/spec-driven-maintenance.md`](../../.codebuddy/rules/spec-driven-maintenance.md)。

---

## 一、三条不可跳过的原则

1. **规格是唯一事实来源。** 代码与规格不一致时，先判断是"实现错了"还是"约定要改"，再动手；不允许只改代码不碰规格。
2. **先记录，后实施。** 任何行为变化先在 [`../changes/`](../changes/) 建变更记录，再改代码。
3. **现状与进度同步。** 改了 [`../current/`](../current/) 就必须回到 [`../PROGRESS.md`](../PROGRESS.md) 更新状态；反之亦然。

## 二、规则文件

| 文件 | 约束什么 |
| --- | --- |
| [`spec-maintenance.md`](./spec-maintenance.md) | 规格文档的写法、命名、目录、变更闭环、进度同步 |
| [`development-standards.md`](./development-standards.md) | 编码、SQL、异常、日志、安全、配置、前端的硬约束 |

## 三、每次改动的强制检查清单（DoD）

完成定义（Definition of Done），全部勾选才算完成：

- [ ] 已在 `spec/changes/NNN-slug/change.md` 记录本次变更（缺陷修复也需记录，除非纯 typo/注释）
- [ ] 代码改动与变更记录中的"新约定"一致
- [ ] 行为变化已合入 `spec/current/NNN-*.md`（新增能力则新建规格文件）
- [ ] `spec/PROGRESS.md` 的模块进度 / 缺陷台账已同步更新
- [ ] `spec/README.md` 的"当前有效规格清单"或"已知限制"已同步
- [ ] 涉及重要取舍时已新增 `spec/decisions/` 决策记录
- [ ] 没有引入新的明文凭据；没有新增被吞掉的异常
- [ ] 关键纯逻辑（告警判定、信号判定）有回归用例或至少手工验证并记录范围
- [ ] 本次变更记录状态置为 `已合入`，目录移入 `spec/archive/changes/`

## 四、规则的修订

规则本身需要修改时：
1. 在本目录对应文件中直接修改，并在文件末尾追加一行修订记录（日期 + 改了什么 + 为什么）。
2. 若修订影响 Agent 行为，同步修改 `.codebuddy/rules/` 下的对应文件。
3. 重大取舍写进 `../decisions/`。

---

## 修订记录

| 日期 | 修订内容 |
| --- | --- |
| 2026-10-20 | 初版：建立三条原则、DoD 检查清单，配套 `spec-maintenance.md` 与 `development-standards.md` |
