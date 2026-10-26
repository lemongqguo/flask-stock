# 变更：账户设置落地（个人资料 / 默认基准指数 / 告警通知）

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 行为变更 + 新增能力 |
| 触发 | 用户要求：按 `design-preview/screens/account.html` 把「个人资料」做成**真功能**（不是静态页），默认基准指数要含上证指数 / 沪深300 / 创业板指 / 恒生指数；告警通知开关要真实生效，且页面上的邮箱必须与真正发邮件的收件人一致 |
| 关联规格 | [001 用户认证](../../current/001-user-auth.md)（个人资料 / 修改密码）、[008 前端 UI](../../current/008-frontend-ui.md)（账户设置页结构）、[003 告警阈值与告警历史](../../current/003-alarm-thresholds.md)（邮件送达）、[006 指标监控](../../current/006-stock-indicator.md)（基准指数） |
| 验证 | 全量 `tests/run_all.py` 通过；新增 `tests/test_account_profile.py` 锁口径与模板契约 |

## 1. 问题与动机

账户设置页此前是**只读展示**：用户名 / 邮箱 / 注册时间只能看，「通知偏好」还是一句"请改环境变量"的占位说明，左侧「修改密码」跳到另一个页。用户明确要求：

1. 个人资料要能改（用户名 / 邮箱 / 手机号 / 默认基准指数）；
2. 默认基准指数要给出**四个可选指数**（上证 / 沪深300 / 创业板指 / 恒生指数），且选择要真的改变指标监控的基准；
3. 告警通知（价格 / PE·PB / 指标 / 每日汇总）要能开关且**真的控制发信**；
4. 页面显示的邮箱必须**与发信收件人同源**——不能页面写 A、实际发到 B。

## 2. 变更类型

- [ ] 缺陷修复
- [x] **行为变更**：`/profile` 由只读改为可写；告警发信受通知开关控制；基准指数由"只认环境变量"改为"账户设置优先"
- [ ] 技术重构
- [x] **新增能力**：手机号 / 默认基准指数 / 最后登录、通知偏好表、每日汇总邮件

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| `/profile` | 只读 `GET` | `GET/POST`：可改用户名 / 邮箱 / 手机号 / 默认基准指数 + 4 个通知开关，一个「保存资料」按钮一次提交 |
| 默认基准指数 | 只有环境变量 `IND_BENCH`（默认沪深300） | **账户设置 > `IND_BENCH` > 沪深300**；候选固定四个：`SH000001 上证指数`、`SH000300 沪深300`、`SZ399006 创业板指`、`HKHSI 恒生指数`；非法值一律回退，不落库 |
| 告警通知开关 | 无（页面只是说明文案） | 落 `user_notify_pref`：价格 / 估值（PE·PB）/ 指标 默认**开**，每日汇总默认**关**；关闭的类型**仍落库告警、但不发邮件**（`notify_status=skipped`） |
| 告警收件人 | `get_alarm_recipients()`（只认环境变量） | `resolve_alarm_recipients()`：**环境变量 `ALARM_RECIPIENTS` 优先，为空时回退到账户邮箱**；页面与发信共用同一个函数，显示即所得 |
| 每日汇总邮件 | 无 | 开关打开后**每天在 `DAILY_SUMMARY_TIME`（默认 08:30）之后发一次**，汇总近 24 小时告警（按类型计数 + 最近 8 条）；无告警不发空邮件；无论成败当天只尝试一轮，状态写 `stats` |
| 最后登录 | 无 | 登录成功回写 `users.last_login`，账户页展示 |
| 修改密码 | 独立页签，失败回渲染只有密码卡 | 与设计稿一致：个人资料与修改密码**同页**两段，密码失败回到同页并保留资料内容 |

## 4. 影响面

- 涉及文件：`database.py`（新表 + 补列）、`models/user.py`、`models/account_settings.py`（新）、`models/stock_alarm.py`、`models/stock_monitor.py`、`utils/alarm_rules.py`、`config.py`、`views/auth.py`、`views/stock_orders.py`、`templates/account.html`、`static/css/theme.css`、`static/js/theme.js`、`.env.example`；
- 数据表：**新增 `user_notify_pref`**；`users` 补 `phone` / `bench_code` / `last_login` / `updated_at` 四列（幂等，不影响存量数据）；
- 既有数据：存量用户新列为 NULL → 基准回退到环境变量/沪深300、通知回退到"三类开、汇总关"（与旧行为一致，无行为回退风险）；
- 新增配置：`DAILY_SUMMARY_TIME`（可选，默认 `08:30`）；
- 路由：`/profile` 由 `GET` 变 `GET+POST`（路径不变）。

## 5. 实施要点

- **唯一真值入口**：`models/account_settings.py` 里三个解析函数，页面渲染与后台发信**都调它**，杜绝"页面一套、发信一套"：
  `resolve_bench_code()`、`resolve_alarm_recipients()`、`notify_enabled(alarm_type)`。
- **多账户口径**：系统是单账户运维视角；全局设置（基准 / 通知 / 收件人回退）以**最近保存过的账户**为准（`ORDER BY updated_at DESC, id ASC`），页面在设置不属于当前用户时给出提示。
- **`updated_at` 不带 `ON UPDATE`**：否则登录回写 `last_login` 会把该用户顶成"最近保存"，影响生效判定——`updated_at` 只在保存资料/通知时显式写 `NOW()`。
- **开关关掉 ≠ 不告警**：告警照常落库（历史可查），只是邮件跳过并记 `skipped`，不污染「发送失败」统计。
- **收件人环境变量优先**：不因为账户邮箱就把环境变量里的收件人改掉（避免"多发给别人"）；环境变量为空才回退账户邮箱。
- **基准缓存 60s**：`_check_indicators` 是每只股票一次调用，基准解析不能直接打库，monitor 内缓存 60 秒（测试可 patch）。
- **恒生指数**：雪球符号取 `HKHSI`；当前环境 Token 失效（`400016`）**无法实测四个符号**，故页面展示该基准的「最新交易日」，采集不到就显式显示"尚未采集"，不伪装成正常。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 收件人同源 | `test_recipients_prefer_env` / `test_recipients_fallback_to_account_email` / `test_recipients_empty` | 通过 |
| 基准回退链 | `test_bench_falls_back_to_config` / `test_bench_uses_account_choice` / `test_bench_ignores_unknown_code` | 通过 |
| 通知开关映射 | `test_notify_enabled_by_alarm_type`（price/sell→价格，pe/pb→估值，indicator→指标，未知类型不拦截） | 通过 |
| 发信真的被开关拦住 | `test_mail_skipped_when_type_disabled`（monitor 层 patch send_mail 断言未调用） | 通过 |
| 每日汇总 | `test_daily_summary_disabled` / `test_daily_summary_sends_once_per_day` / `test_daily_summary_no_content_no_mail` | 通过 |
| 资料保存 | `test_profile_post_persists` / `test_profile_post_rejects_bad_email` / `test_profile_post_rejects_duplicate_username` / `test_profile_post_rejects_unknown_bench` | 通过 |
| 页面契约 | `test_benchmark_options_rendered` / `test_notify_toggles_rendered` / `test_recipient_display_matches_sender` | 通过 |
| 全量回归 | `python tests/run_all.py` | 通过 |

- 实际验证到的范围：解析逻辑、监控发信路径、每日汇总触发与幂等、资料 POST 校验、模板渲染契约、全量后端回归。
- **未验证**的范围（如实记录）：
  1. **真实发信**（SMTP）与**雪球基准采集**未实测——本机雪球 Token 已失效（`400016`），四个指数符号（`SH000001`/`SH000300`/`SZ399006`/`HKHSI`）无法联网校验，只能靠页面「最新交易日」显式暴露；
  2. 页面的视觉观感（浅色主题、开关动效）需人工刷新确认——本机无浏览器自动化。

## 7. 合入清单

- [x] 代码已合并
- [x] `../../current/001-user-auth.md` 已更新（3.5 节：个人资料可写 + 通知偏好）
- [x] `../../current/003-alarm-thresholds.md` 已更新（新增 3.6 节：通知开关与每日汇总）
- [x] `../../current/008-frontend-ui.md` 已更新（账户设置页结构 + 开关组件）
- [x] `../../PROGRESS.md` 模块进度与变更历史已更新
- [x] `../../README.md` 变更清单已同步
- [x] 取舍已在 §5 说明（环境变量优先、多账户取最近保存、关开关仍落库），未新增 ADR
- [x] 本文件已归档到 `../../archive/changes/`
