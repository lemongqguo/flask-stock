# 005 K线采集与均线信号（K-line & MA Signal）

**状态**：已实现　|　**最后更新**：2026-10-21
**实现**：`models/stock_kline.py`、`views/stock_orders.py`、`templates/stock_order_form.html`、`static/js/main.js`
**相关变更**：[2026-10-21 M1 缺陷治理](../changes/2026-10-21-m1-defect-hardening.md)（已修复 D-10 占位死代码、Chart.js 版本锁定）

---

## 1. 场景

系统定期采集每只股票的近 40 日 K 线并落库，计算 MA5 / MA10 / MA30，
用 MA5 与 MA30 的偏离关系给出"金叉 / 死叉 / 震荡"的趋势信号，在订单列表与编辑页展示，帮助用户判断买卖时点。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| K 线 | 每日 OHLCV：`open/high/low/close/volume`，按 `trade_date` 存储 |
| MA5 / MA10 / MA30 | 收盘价的 5 / 10 / 30 日滚动均值 |
| 金叉 `golden_cross` | 短期均线上穿长期均线，看涨 |
| 死叉 `death_cross` | 短期均线下穿长期均线，看跌 |
| 震荡 `normal` | 均线缠绕，趋势不明 |

## 3. 当前有效行为

### 3.1 采集与落库

- `get_kline_data_from_snowball` 通过 `pysnowball` 拉取 `days=40` 的 K 线；Token 取 `config.XueqiuToken.TOKEN`，缺失时记 error 并返回 `None`。
- `save_kline_data`：按 `trade_date` 判重，**存在则 UPDATE，否则 INSERT**（幂等，重复采集不产生重复行）。
- 监控线程每轮 `check_and_alert` 中调用，失败只记日志、不影响告警判定。

### 3.2 均线计算与信号判定

- 均线：`rolling(5) / rolling(10) / rolling(30)` 作用于收盘价（`stock_kline.py:61-63`）。
- 判定（`StockKline.check_signal`）：

```python
if ma5 is None or ma30 is None or pd.isna(ma5) or pd.isna(ma30): return 'normal'
if   ma5 > ma30 * 1.03: return 'golden_cross'   # 高于 3%
elif ma5 < ma30 * 0.97: return 'death_cross'    # 低于 3%
else:                   return 'normal'
```

- 窗口不足会产生 `NaN`，`pd.isna` 兜底使其判为 `normal`，不会抛异常也不会误报信号。

- **注意：MA10 已计算并存储，但不参与判定**，仅用于前端展示。

### 3.3 数据接口与展示

- `GET /stock/api/kline/<int:stock_id>` 返回最近 60 条的 `trade_date / close_price / ma5 / ma10 / ma30 / signal_type`；异常返回 `{success:false, error}` + 500 并记日志。
- 订单列表每行展示最近一次信号图标（`get_latest_signal`）。
- 订单编辑页用 Chart.js 绘制收盘价与三条均线的折线图（数据源即上述 API）。

## 4. 验收条件

1. 同一 `trade_date` 重复采集后，`stock_kline` 中不出现重复行（UPDATE 幂等）。
2. MA5/MA10/MA30 计算结果与手工按收盘价滚动均值一致。
3. `ma5 > ma30 * 1.03` → `golden_cross`；`ma5 < ma30 * 0.97` → `death_cross`；其余 → `normal`。
4. 边界值：`ma5 == ma30 * 1.03` 与 `ma5 == ma30 * 0.97` 均判为 `normal`（严格大于/小于）。
5. `ma5` 或 `ma30` 为 `None`/`NaN` 时判为 `normal`，不抛异常。
6. MA10 的取值不影响判定结果（仅展示用）。
7. `/stock/api/kline/<id>` 在有数据时返回 `{success:true, klines:[...]}`，最多 60 条，按日期升序。
8. 删除订单后其 K 线记录随外键级联清除。
9. 前端图表能正确渲染 4 条线（收盘价 + MA5/MA10/MA30）。

## 5. 已知限制

- 信号判定是**静态阈值比较**（±3% 偏离），并非严格意义的"上穿/下穿"交叉判定，趋势反转的即时性弱。
- MA10 计算并存储但未用于判定，属冗余字段保留。
- Chart.js 通过 CDN 引入，已锁定 `chart.js@4.4.1`（仍依赖外网可达）。
- 无 MACD / KDJ / RSI 等其他指标；如需扩展须新立变更与规格。
- K 线仅保存近 40 日窗口，更长周期的历史不会累积。
- 单测覆盖判定函数（`tests/test_kline_signal.py`），但"取数 → 落库"链路需要真实雪球 Token，未纳入自动化测试。
