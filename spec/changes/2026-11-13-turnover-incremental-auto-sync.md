# 2026-11-13-turnover-incremental-auto-sync：成交额增量同步 + 监控线程自动同步

**状态**：已合入（待真实环境观察 3h 周期后归档）　|　**提出日期**：2026-11-13　|　**负责人**：用户 + Agent
**受影响规格**：[009 市场成交额](../current/009-market-turnover.md)、[004 后台监控服务](../current/004-monitor-service.md)
**决策记录**：[ADR-008 增量窗口与监控线程自动同步](../decisions/008-turnover-incremental-and-auto-sync.md)

---

## 1. 问题与动机

1. **每次手动同步都全量拉取**：东财 3 个指数各返回约 8800 行（响应约 1MB+），腾讯向前翻页约 15 次请求。
   库已有全量历史（用户已入库腾讯口径 8807 行）后，日常更新只需要最近几天，全量拉取纯属浪费（用户明确反馈）。
2. **无自动同步**：每日更新靠手动按钮 / CLI，容易忘。用户要求把增量同步挂进监控线程（`stock_monitor.py`），**每 3 小时跑一次**。

## 2. 变更类型

- [x] **行为变更**：同步取数范围由「每次全量」改为「库非空走增量」→ 先改这里的约定，再改测试期望
- [x] **新增能力**：监控线程周期性自动同步（默认 3 小时，可配置）

## 3. 旧约定 → 新约定

| 项 | 旧约定 | 新约定 |
| --- | --- | --- |
| 同步取数范围 | 每次全量（1990 至今，东财 `beg=19900101` / 腾讯翻页 2000×20） | **库非空且最新日期距今 ≤100 自然日 → 增量**：东财沪深 `beg=库最新-100自然日`、北证 `lmt=N`；腾讯 `count=N` 单页（N=max(60, 缺口自然日+10)）。通常只取最近约 60 个交易日 |
| 全量触发 | 每次同步都是全量 | 仅三种：库为空 / 库最新距今 >100 自然日（超窗回退）/ CLI 显式 `--full` |
| 增量校验 | 无（只有全量校验 8000/500/10 天） | 增量分流：三市各 ≥1 条、沪市最新距今 ≤10 天、**源最新 ≥ 库最新**、**窗口必须覆盖库最新日期**；不达标判该源不可用（auto 降级逻辑不变） |
| 备源 60 日保护 | 全量 + 腾讯 + 库非空 → 只写最近 60 个交易日 | **全量路径不变**；增量路径取数窗口本身即保护（只取最近区间），不再叠加裁剪 |
| 自动同步 | 无（未接监控线程） | 监控线程 `_maybe_sync_turnover()`：默认每 10800s（3h）一次；**失败也计入间隔**；**空库跳过**（防无人值守腾讯全量口径污染）；调用点在雪球退避检查**之前**（成交额源与雪球无关） |
| CLI | `flask sync-turnover [--source ...]` | 增加 `--full` 强制全量校准（建议每月一次）；输出增加模式（incremental/full） |
| 页面按钮 | 每次全量 | **智能模式**：库非空增量、库空全量；UI 与冷却（60s）不变，不提供全量选项 |
| 同步 summary | 无 mode 字段 | 增加 `mode: incremental/full`（页面/CLI/日志可见） |

## 4. 影响面

- 涉及模块/文件：`utils/turnover_source.py`（增量取数 + 校验分流）、`models/market_turnover.py`（同步编排）、
  `models/stock_monitor.py`（自动同步挂钩 + 状态字段）、`config.py` / `.env.example`（2 个新配置）、
  `app.py`（CLI `--full`）、`views/market.py`（仅 docstring）、`tests/`（更新 + 新增）。
- 涉及数据表 / 是否需要迁移：**无表结构变更，无迁移**。
- 是否影响既有数据：不影响。upsert 幂等语义不变；增量只是缩小取数/写入范围。
- 是否需要新增/修改配置：新增 `TURNOVER_AUTO_SYNC_ENABLED`（默认 1）、`TURNOVER_AUTO_SYNC_INTERVAL`（默认 10800 秒）。

## 5. 实施要点

1. **窗口统一**：增量窗口与备源保护同为 60 个交易日（`INCREMENTAL_DAYS = BACKUP_PROTECT_DAYS`）。
   东财 `beg` 按自然日回看 100 天（≈60 交易日 + 节假日缓冲）；腾讯/北证按条数 N=max(60, 缺口自然日+10)，
   保证「几天没同步 / 长假」缺口被覆盖；缺口 >100 自然日则回退全量，绝不带缺口写入。
2. **校验分流**：`validate()`（全量）原样保留；新增 `validate_recent()`（增量）。`fetch_all(source, since=None)`
   按 since 分流，auto 降级编排不变。
3. **监控挂钩**：照 `_maybe_sync_bench` / `_maybe_send_daily_summary` 范式——`_turnover_next_sync_at`
   （`time.monotonic()`）到点才执行；**到点即置位，成败都计间隔**（交易时段轮间隔为 0，防失败重试风暴）；
   异常隔离 + `stats['errors']` + `logger.exception`，不中断主循环；空库跳过并日志提示先 CSV 导入 / 手动同步；间隔解析容错——非数字配置（TypeError/ValueError）回落默认 10800s，保证先置位再执行（代码审查后加固）。
4. **调用位置**：`monitor_loop` 中放在雪球退避检查之前（与每日汇总同理）——东财/腾讯与雪球 Token 无关，
   雪球退避不得阻断成交额同步。
5. **兼容**：`sync_from_source(source='auto', full=False)` 新参数均有默认值；页面视图零改动（按钮自动变增量）；
   既有全量保护单测改为 mock `get_latest()=None` 走全量路径，语义不变。

## 6. 验证范围与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 增量取数参数（东财 beg / 北证 lmt / 腾讯 count 单页） | 单测 mock http_json 断言 URL | ✅ 通过（IncrementalParamsTest 2 + IncrementalFetchTest 4） |
| 增量校验分流（空/过旧/源落后/窗口未覆盖） | 单测 | ✅ 通过（ValidateRecentTest 5 + auto 降级 since 透传 1） |
| 同步编排（增量/空库全量/超窗回退/--full） | 单测 mock 取数与落库 | ✅ 通过（IncrementalSyncTest 6，含 100 天边界与增量不叠加裁剪） |
| 全量备源 60 日保护不回归 | 既有 3 用例（改 mock get_latest） | ✅ 通过（SyncProtectionTest 3，语义不变） |
| 监控挂钩（开关/间隔/空库守护/失败也计间隔/非法配置回落/调用点在退避前） | 单测 + 静态契约 | ✅ 通过（test_turnover_auto_sync 10：调度 7 + 契约 3） |
| 全量测试套件 | `stockvenv/bin/python -m unittest` | ✅ 本快照 3 个测试模块 61 用例全过（47 + 10 + 4）；8 个改动文件 py_compile 通过；`flask sync-turnover --help` 确认 --full |

- 实际验证到的范围：2026-11-13 以 `FLASK_DEBUG=0 /opt/src/flask-stock/stockvenv/bin/python -m unittest
  tests.test_market_turnover tests.test_turnover_auto_sync tests.test_shell_layout -v` 运行，**61/61 通过**
  （既有 29 + 壳层 4 + 本次新增 28）。本快照缺 `stockvenv/` 与 `tests/run_all.py`，改用可用 venv 直接跑全部测试模块；
  全仓库 695 用例的完整套件需在具备 run_all.py 的环境复跑。
- **未验证**的范围：东财增量真实接口（本机东财不可达，ADR-006 已注明）；腾讯增量真实接口冒烟（视网络情况）；
  监控线程真实 3h 周期运转（需真实环境观察）。

## 7. 合入清单

- [x] 代码已合并
- [x] `../current/009-market-turnover.md` 已更新为新的有效约定（004 监控规格同步一句）
- [x] `../PROGRESS.md` 模块进度与台账已更新
- [x] `../README.md` 已知限制已同步
- [x] 涉及重要取舍已补 [`../decisions/008`](../decisions/008-turnover-incremental-and-auto-sync.md)
- [ ] 本目录已移入 `../archive/changes/`（待真实环境观察后归档）