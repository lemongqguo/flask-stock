# 001 用户认证（User Authentication）

**状态**：已实现　|　**最后更新**：2026-10-26　|　**实现**：`views/auth.py`、`models/user.py`、`utils/decorators.py`、`utils/access.py`、`app.py`
**相关变更**：[2026-10-21 M1 缺陷治理](../changes/2026-10-21-m1-defect-hardening.md)（已修复 D-10 死代码、D-12 过期 API）、
[2026-10-26 多用户数据隔离](../archive/changes/2026-10-26-multi-user-ownership.md)（新增角色与数据归属）

---

## 1. 场景

系统为单人/小团队自用的内网监控工具，所有业务页面必须先登录才能访问。
用户需要：注册账号 → 登录 → 使用订单与告警功能 → 查看个人资料 / 修改密码 → 登出。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| session 会话 | Flask 服务端 session，登录成功后写入 `session['user_id']`、`session['username']`、`session['role']` |
| 白名单端点 | `auth.login`、`auth.register`、`static`，未登录也可访问 |
| 密码哈希 | Werkzeug `generate_password_hash` / `check_password_hash`，**不存明文** |
| 角色 `users.role` | `ENUM('user','admin')`，默认 `user`。决定数据可见范围：admin 见全量，user 仅自己名下 |
| 归属 `stock_master.user_id` | 订单归属用户，**由服务端从 session 取**，不接受客户端传值 |

## 3. 当前有效行为

### 3.1 访问控制

- 全局 `@app.before_request` 拦截所有请求：未登录且非白名单端点 → 跳转登录页。
- 业务路由额外叠加 `@login_required`（`utils/decorators.py`）作为二次校验。
- 未登录访问受保护页面时，登录后按 `next` 参数回跳；`next` 由 `_is_safe_redirect()` 用**标准库 `urllib.parse.urlparse`** 校验（无 `scheme` 且无 `netloc` 才放行），避免开放重定向。

### 3.2 注册 `GET/POST /register`

- 用户名查重（视图层 `User.get_by_username` + 模型层 `User.create` 双重校验，防并发重复注册），重复则回显错误。
- 服务端强制密码长度 ≥ 6 位（`User.MIN_PASSWORD_LENGTH`），不再只依赖前端校验。
- 密码经 `set_password` 哈希后入库；异常 `logger.exception` 并返回 `None`。

### 3.3 登录 `GET/POST /login`

- 校验用户名存在 + `check_password` 通过。
- 成功后写 session，跳转 `next` 或订单列表。

### 3.4 登出 `GET /logout`

- 清空 session，跳转登录页。

### 3.5 个人资料 `GET/POST /profile`

- 一次提交同时保存：
  - **用户名 / 邮箱 / 手机号**（`users.username` / `email` / `phone`）；
  - **默认基准指数**（`users.bench_code`，候选固定四个：`SH000001 上证指数`、`SH000300 沪深300`、`SZ399006 创业板指`、`HKHSI 恒生指数`）；
  - **四个告警通知开关**（落 `user_notify_pref`，见 [003](./003-alarm-thresholds.md) §3.6）。
- 校验失败**一律不落库**并回显错误：用户名为空或与他人重名、邮箱不含 `@`、基准不在白名单。
  基准留空存 NULL（回退到环境变量 `IND_BENCH`）。
- 「最后登录」由登录成功时回写 `users.last_login`；「上次更新」读 `users.updated_at`
  （**该列不带 `ON UPDATE`**，否则登录回写 `last_login` 会把该账户顶成"最近保存的账户"——
  生效账户判定依赖它，见 `models/account_settings.py`）。
- 多账户生效口径：全局设置（基准 / 通知 / 收件人回退）以**最近保存过的账户**为准
  （`ORDER BY updated_at DESC, id ASC`）；生效偏好不属于当前账户时页面显式提示。

### 3.6 修改密码 `GET/POST /change_password`

- 修改密码须校验：旧密码正确、两次新密码一致、长度 ≥ 6 位。
- 写库由模型层 `User.update_password(user_id, new_password)` 完成，**视图层不再直接执行 SQL**。
- 与设计稿一致：密码表单与个人资料**同一张卡片内**，失败回到同页并保留资料内容。

### 3.7 角色与数据归属（2026-10-26）

多用户数据隔离的完整约定在 [002](./002-stock-order.md) §3.7；本节只写**认证侧**的部分。

- **角色来源**：`users.role`，`ENUM('user','admin') NOT NULL DEFAULT 'user'`。
  admin 能看到**全部**订单；user 只看自己名下（`stock_master.user_id` 等于自己）。
- **首个用户自动为 admin**：`User.create()` 在全库尚无用户时把新用户置为 `admin`，
  避免全新部署出现「没有管理员，而普通用户又只看自己名下」导致订单谁也看不见的死局。
- **管理员谋求与管理**：
  - `database._ensure_first_admin()`：存量库启动时把 `id` 最小的用户提升为 admin（只在**全库无 admin** 时执行）；
  - `flask set-admin <username>` CLI (`app.py`)：事后提升。
- **角色写进 session**：登录时写 `session['role']`，后续请求不再查 `users` 表。
  **代价：角色变更后必须重新登录才生效**（在线会话不会自动升级/降级）。
- **判定入口唯一**：`utils/access.py` 提供 `owner_scope()` / `can_manage()` / `build_owner_where()`，
  各视图与模型**只调用、不自己拼 `WHERE user_id =`**。
- **失败关闭**：会话不完整 → `owner_scope()` 返回哨兵 `NO_ACCESS`，查询生成 `1 = 0`（空集），
  绝不退化成"全量"。

## 4. 验收条件

1. 未登录访问 `/stock/list` → 302 到登录页。
2. 已注册用户名重复注册 → 页面报错且不产生第二条记录。
3. 数据库中 `users.password_hash` 不等于原始明文密码。
4. 密码短于 6 位 → 注册/改密失败（服务端拦截，不依赖前端）。
5. 旧密码错误 / 两次新密码不一致 → 修改失败且 session 不失效。
6. 登出后再访问受保护页面 → 重新要求登录。
7. `next` 为外站 URL 时不被跟随（仅允许同站相对路径）。
8. 保存资料后重新进入 `/profile`，用户名 / 邮箱 / 手机号 / 基准指数与四个开关都保持已保存的值
   （回归用例 `tests/test_account_profile.py`）。
9. 用户名与他人重名 / 邮箱不含 `@` / 基准填了白名单外的代码 → 页面报错且**不落库**。
10. 全库第一个注册的用户 `role='admin'`；之后注册的为 `user`（回归用例 `tests/test_multi_user_ownership.py::UserRoleTest`）。
11. 登录后 session 中带有 `role`；登出后被清除。
12. 会话缺失 `user_id` 时 `owner_scope()` 返回 `NO_ACCESS`，相关查询返回空集而不是全量。

## 5. 已知限制

- **无密码复杂度要求**（只校验长度 ≥ 6），无注册验证码与登录频率限制。
- **无 CSRF 防护**：`requirements.txt` 引入了 Flask-WTF，但全项目未启用 CSRF Token，所有 POST 表单裸奔。
- **权限粒度只有一层**：只有 `user` / `admin` 两种角色，没有细粒度授权（如"只看某个分组"）。
  需要更多角色时应另立变更扩展 `users.role` 枚举与 `utils/access.py`，而不是在各视图里写死判断。
- **角色变更需重新登录**：角色在登录时写入 session，在库里改角色不会影响已登录会话。
- **仍有 CSRF 缺口**（见上一节），admin 账号同样受影响。
- 无"记住我"、无登录失败锁定、无审计日志。
- **基准指数的雪球符号未经联网实测**：当前环境 Token 失效（`400016`），`SH000001` / `SH000300` /
  `SZ399006` / `HKHSI` 四个符号只能在使用时由「最新交易日」是否为空来暴露采集是否成功（页面已显式展示）。
- `login` 的错误提示不区分"用户不存在"与"密码错误"（当前已统一为同一提示，符合安全实践）。
