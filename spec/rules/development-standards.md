# 开发与编码规范

> 本文件约束代码层面的硬要求。当前项目存在若干历史问题（见 [`../PROGRESS.md`](../PROGRESS.md)），
> **新代码不得再犯同样的问题**；修改到相关文件时顺手修正。

---

## 1. 配置与密钥（安全红线）

- **禁止**在 `config.py` 或任何代码里新增明文密码、SECRET_KEY、SMTP 授权码、第三方 Token。
- 新增配置项一律走 `os.environ.get(...)` 读取，并在 `config.py` 给出无敏感信息的默认值；同时在 `PROJECT_WIKI.md` 的配置章节登记。
- 不得把 `stockvenv/`、`stockenv/`、`logs/`、`__pycache__`、`*.pyc`、`.env` 提交进仓库（`.gitignore` 已于 2026-10-27 补齐）。
- 现有的 [D-01 明文凭据](../PROGRESS.md) 属待修复项；修复前，**不要把 `config.py` 的当前内容贴到任何对话、Issue 或文档中**。
- 涉及密钥的示例一律写成 `<your-password>` 占位符。

## 2. SQL 与数据访问

- 只允许通过 `models/base.py` 的 `BaseModel` 执行 SQL，**禁止在视图层手写 UPDATE/INSERT**（现有 `views/auth.py:116-125` 为待清理项）。
- 一律使用参数化查询（`%s` 占位 + 参数元组），禁止字符串拼接用户输入。
- 新增可搜索模型时必须定义 `search_fields`；未定义时禁止传入 `search_query`（见 [D-07](../PROGRESS.md)）。
- 新增表/字段必须同时在 `database.py` 的 `CREATE TABLE IF NOT EXISTS` 与 `PROJECT_WIKI.md` 的数据字典中登记。
- 频繁 `ORDER BY` / `WHERE` 的字段要有索引（如 `stock_alarm.alarm_time`，见 D-09）。

## 3. 异常处理与日志

- 禁止 `except Exception: pass` 或仅 `print` 后吞掉异常（models 目录现有 25 处，见 D-11）。
- 捕获异常必须至少 `logger.exception(...)` 记录上下文，并向调用方返回可判定的失败值。
- 监控线程内的异常不得中断主循环，但必须可观测（记日志 + 计数）。
- 生产环境必须让 `logs/stock_app.log` 真正生效（当前 `debug=True` 导致文件 handler 不挂载，见 D-05）。

## 4. 后台任务与并发

- 监控线程**全局唯一**：新增启动入口前必须检查 `monitor.is_running`，避免 reloader 重复拉起多个线程。
- 外部 API 调用必须有节流与失败退避；新增轮询逻辑需先确认是否需要交易时段判断（D-04）。
- 告警类副作用必须有**幂等/冷却**设计，禁止"条件持续满足就每轮重复触发"（D-03）。

## 5. 路由与视图

- 新增业务路由默认加 `@login_required`；全局 `before_request` 拦截不作为唯一防线。
- **辅助函数必须写在路由装饰器之前**：插在 `@bp.route(...)` 与视图函数之间会把装饰器挂到辅助函数上，原视图丢失端点（2026-10-21 修编辑页时踩过，`/edit/<id>` 挂到了 helper，12 个用例报 `BuildError`）。
- 所有写操作使用 POST；关键操作需在变更记录中说明是否需要 CSRF（当前项目未启用 CSRF，属已知限制）。
- 新增路由必须同步更新 `PROJECT_WIKI.md` 的路由表与对应 `current/` 规格的"当前有效行为"。
- 视图函数保持薄：校验参数 → 调模型 → 渲染/返回 JSON；业务逻辑放模型层。

## 6. 前端

- 新增外部 CDN 资源**必须锁定版本**（Chart.js 已锁定 4.4.1，K 线图唯一外部依赖；其余一律本地资源）。
- 公共交互逻辑放 `static/js/theme.js`，样式放 `static/css/theme.css`，禁止在模板里堆大段内联脚本。
  例外：`<head>` 中主题防闪烁的极小段引导脚本（约 5 行，外置会导致执行过晚）。
  页面专属交互写成声明式 `data-*` 属性交给 `theme.js` 统一接管（页签、chips 过滤、阶梯百分比、防重复提交等）；
  依赖模板变量注入的页面专属脚本（如 K 线图初始化）可保留在 `{% block scripts %}`。
- 模板继承 `templates/base.html`；登录/注册与错误页为独立整页模板（无侧栏）。新增页面需在导航中登记。
- **不引入** Bootstrap / jQuery / FontAwesome；图标用 `theme.js` 注入的内联 SVG sprite（`<use href="#i-*">`）。
- 双主题：颜色一律走 CSS 变量（`--up` 红涨 / `--down` 绿跌），禁止在组件上写死颜色。

## 7. 测试

- 纯逻辑（告警档位判定、K 线信号判定、均线计算）**必须有 pytest 用例**；M4 前至少覆盖这两处。
- 缺陷修复采用"先写会失败的用例 → 修复 → 转绿"的顺序，并在变更记录中记录验证范围。
- 无法自动化验证的部分，必须在变更记录的"未验证范围"中明确写出。
- **mock 必须复刻真实的返回类型**：`BaseModel.execute_query` / `StockMaster.get_by_id` 返回的是 **dict 行**，不是模型对象；
  但 **`StockWarehouse / StockPe / StockPb.get_by_stock_master_id` 返回的是模型对象**（属性访问）。
  两个模型返回类型不一致，写测试/视图前先确认具体模型，不要从上一个模型的写法推断。
  用 `mock.Mock(status=...)` 之类的对象替身会让"属性访问"在测试里通过、在真实路径上抛 `AttributeError`
  （2026-10-21 列表页状态开关 500 即由此漏出）。替身一律按真实类型构造（如 `{'id': 1, 'status': 'active'}`）。
- **接口类改动除单测外，必须做一次不 mock 的真实调用验证**（可写库的操作选可还原的场景，验证后还原），
  只靠 mock 无法发现契约不一致的问题。

## 8. 依赖与环境

- 新增第三方依赖必须写入 `requirements.txt` 并锁定版本，同时在 `PROJECT_WIKI.md` 技术栈表中登记。
- Python 目标版本 **3.12**（2026-10-27 起，随 numpy 2.5 / pandas 3.1 对齐）；注意 pandas/numpy 二进制兼容（见 `PROJECT_WIKI.md` 常见问题）。
- 开发与跑测试统一使用项目根目录的 `stockvenv/`（Windows 上是历史资料里的 `stockenv/`）；**不改动虚拟环境目录内容**。

## 9. 文档一致性

- 改动涉及配置、路由、数据表时，同步更新 `spec/PROJECT_WIKI.md` 的对应章节。
- 改动涉及行为时，同步更新 `spec/current/` 与 `spec/PROGRESS.md`（见 [spec-maintenance.md](./spec-maintenance.md)）。
- 所有文档中的日期使用 `YYYY-MM-DD`；路径使用相对链接，便于移动。

---

## 修订记录

| 日期 | 修订内容 |
| --- | --- |
| 2026-10-20 | 初版：以当前已知缺陷（D-01~D-12）为反面清单建立硬约束 |
| 2026-10-21 | 第 7 节补两条测试约束：mock 必须复刻真实返回类型（dict 行）；接口类改动须做一次不 mock 的真实调用验证 |
