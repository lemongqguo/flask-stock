# 2026-10-21 雪球接口错误降级处理

| 项 | 值 |
| --- | --- |
| 状态 | **已合入** |
| 类型 | 缺陷修复（行为变更） |
| 触发 | 生产运行日志中出现 `400016` 错误码 + 完整堆栈，每只股票每轮一条 |
| 关联规格 | [004 后台监控服务](../current/004-monitor-service.md) |
| 验证 | `python tests/run_all.py` → 151 用例全部通过（新增 13 个） |

---

## 1. 变更动机

雪球 Token 失效时，接口返回：

```json
{"error_description":"遇到错误，请刷新页面或者重新登录账号后再试","error_code":"400016"}
```

`pysnowball` 把它原样 `raise Exception(response.content)`。原实现不区分
**外部服务的业务错误** 与 **程序 bug**，一律 `logger.exception`，导致：

1. 每只股票每轮都打一条 ERROR + 完整堆栈，日志被淹没；
2. 监控看不出"其实只是 Token 过期"，排障成本高；
3. Token 失效期间仍按 30~300s 节流反复请求，白白消耗配额。

> 原则：**外部服务返回的错误是可预期的，只提示；程序自己的 bug 才打堆栈。**

## 2. 变更内容

### 2.1 新增 `utils/snowball_errors.py`

- `parse_xueqiu_error(exc)` → `(error_code, error_description)`。
  兼容 bytes repr（含 `\xNN` UTF-8 转义，JSON 无法解析，故使用正则兜底 + `unicode_escape` 还原）。
- 错误分类：`AUTH_ERROR_CODES`（400016/400027/10001）、`RATE_LIMIT_CODES`（400017）、`NOT_FOUND_CODES`（400015）。
- `should_backoff(code)`：Token 失效与限流需要退避。
- `describe(code, description)`：把错误码翻译成人话。

### 2.2 `models/stock_monitor.py`

- 新增退避状态：`_xueqiu_backoff_until` / `_xueqiu_backoff_reason`，对外暴露 `xueqiu_backoff_remaining`。
- `get_stock_data`：
  - 无 Token → 按 `XUEQIU_NOTICE_INTERVAL` 节流提示一次（`WARNING`），返回 `None`；
  - 退避期内 → 直接返回 `None`，不请求；
  - 捕获异常 → `parse_xueqiu_error`：
    - 识别为业务错误 → **只打 WARNING 提示，不打堆栈**；需退避的进入退避；
    - 无法识别 → 仍 `logger.exception`（保留堆栈，便于定位真 bug）。
- `_sync_kline`：退避期内跳过 K 线拉取。
- `monitor_loop`：退避期内整轮跳过，休眠后继续（不再逐只重试）。
- `get_status()` 增加 `xueqiu_backoff_remaining` / `xueqiu_backoff_reason`。

### 2.3 `models/stock_kline.py`

`get_kline_data_from_snowball` 同样降级：业务错误只 `WARNING`，未知异常才 `exception`。

### 2.4 新增配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `XUEQIU_BACKOFF_SECONDS` | 600 | Token 失效/限流后的退避秒数 |
| `XUEQIU_NOTICE_INTERVAL` | 300 | 同一错误码重复提示的最小间隔 |

## 3. 行为影响

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| Token 失效 | 每只股票每轮 ERROR + 堆栈 | 一条 WARNING：`雪球 Token 无效或已过期（400016）：…；已暂停请求雪球 600 秒` |
| 退避期内 | 继续按节流反复请求 | 整轮跳过，到点自动恢复 |
| 限流 400017 | ERROR + 堆栈 | WARNING + 退避 |
| 代码不存在 400015 | ERROR + 堆栈 | WARNING（按错误码节流），不退避 |
| 网络/解析等未知异常 | ERROR + 堆栈 | 保持 ERROR + 堆栈（不变） |

## 4. 验证

新增 `tests/test_snowball_errors.py`（13 个用例）：
bytes repr 解析、非 JSON 兜底、分类函数、
**Token 失效只产生 WARNING 无 ERROR**、进入退避、退避期不重复请求、
退避期不刷日志、K 线同步跳过、未知异常仍打堆栈、代码不存在不触发退避。

## 5. 遗留

- 错误码清单来自已知样本，雪球未公开完整码表；未知业务码会走"非退避类 WARNING"分支，属安全默认。
- Token 更新后需**重启进程**才会立即恢复（否则等退避自然结束）。
- 未实现"Token 失效时发邮件通知管理员"，如需请另立变更。
