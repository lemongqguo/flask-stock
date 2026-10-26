# 变更：侧栏与顶栏接入实时系统状态

| 项 | 内容 |
| --- | --- |
| 状态 | **已合入**（轮询效果待人工确认） |
| 类型 | 新增能力（实时状态展示） |
| 触发 | 用户：侧栏左下角与右上角「监控运行中」相比设计稿少了内容，且**必须与后端实时关联，不能是静态页** |
| 关联规格 | [004 监控服务](../current/004-monitor-service.md)、[008 前端 UI](../current/008-frontend-ui.md) |
| 验证 | 全量 **253 用例通过**（新增 `tests/test_system_status.py` 17 个）；真实核对：API 返回 monitor/session/cooldown/xueqiu 四项，侧栏 4 行与顶栏徽标按同一份数据渲染 |

## 1. 旧约定 → 新约定

| 位置 | 旧 | 新（对齐设计稿 `design-preview/screens/orders.html`） |
| --- | --- | --- |
| 侧栏底部 `.side-foot` | 静态两行「风格：交易终端」「配色：红涨绿跌」 | 四行实时状态：**监控**（运行中/已停止）、**交易时段**（早盘/午盘/午间休市/已收盘/非交易日）、**告警冷却**（N 小时）、**雪球**（正常/限流退避中/未配置） |
| 顶栏 `.topbar` | 无监控徽标 | `<span class="pill live"><i class="dot"></i> 监控运行中</span>`，停止时变为「监控已停止」并去掉 `live` |

## 2. 数据来源（全部实时，无一处写死）

- 监控：`monitor.get_status()['running']`（线程真实状态）；
- 交易时段：`utils/trading_time.describe_session()`；
- 告警冷却：`Config.ALARM_COOLDOWN_SECONDS`（默认 14400s = 4 小时）；
- 雪球：`monitor.get_status()['xueqiu_backoff_remaining']` 与 Token 是否配置。

## 3. 需要新增的后端能力

1. `describe_session()` 增加 **午间休市** 档位——现在 11:30~13:00 与收盘后同样返回 `closed`，设计稿要能显示"午间休市"；
2. `utils/system_status.build_system_status(monitor)`：把 `get_status()` 转成页面文案（唯一来源，API 与模板共用）；
3. `GET /stock/api/system_status`：返回 JSON，供前端定时刷新；
4. `app.py` 注册 `context_processor` 注入 `system_status`，所有页面首屏就有值（无空白闪烁）。

## 4. 前端刷新策略

- 首屏由服务端渲染（context_processor），避免加载瞬间空白；
- `theme.js` 新增 `initSystemStatus()`，每 30s 拉一次 `/stock/api/system_status` 局部更新（交易时段会随时间变化，不刷新页面也要变）；
- 页面不可见（`document.hidden`）时跳过请求，避免无谓消耗。

## 5. 不改的部分

- 不改监控线程行为、不改告警冷却逻辑；
- `describe_session()` 的既有取值（`morning` / `afternoon` / `closed`）保持兼容，只**新增** `noon`。

## 6. 验证范围

- `describe_session()` 各时段取值（含 noon）；
- API 返回字段完整且随 monitor 状态变化（用真实 monitor 实例，不 mock 状态机）；
- 页面首屏渲染出 4 行 + 顶栏徽标；
- 全量 `python tests/run_all.py`。
