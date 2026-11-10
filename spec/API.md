# Flask Stock API 与批量操作使用文档

> 最后更新：2026-11-10  
> 默认服务地址：`http://127.0.0.1:5000`  
> 本文依据当前 Flask 路由实现整理，面向脚本调用、订单批量维护和行情批量查询。

## 1. 使用前必读

当前项目不是独立的 RESTful JSON API 服务，而是由以下两类接口组成：

1. **JSON 接口**：标的搜索、批量读取行情、系统状态、K 线数据。
2. **Web 表单接口**：登录、订单创建/编辑/删除、状态切换、告警设置、AI 分析等。参数使用 `application/x-www-form-urlencoded`，结果主要通过 HTTP 重定向和页面 Flash 消息表达。

批量调用时需要特别注意：

- 除 `POST /stock/refresh_quotes` 外，**没有单请求批量写入接口**。批量创建、编辑、删除等操作需要循环逐条调用。
- 所有业务接口都依赖 Flask Session Cookie，不支持 Bearer Token 或 API Key 鉴权。
- 未登录访问返回 `302` 并跳转 `/login`，不是 `401`；跟随重定向后可能得到登录页的 `200 text/html`。
- 表单写操作成功通常返回 `302`，但部分失败也会返回 `302`，**不能只根据状态码判断业务成功**。
- 普通用户只能查看和管理自己的订单；管理员可以查看和管理全部订单。
- 当前项目未启用 CSRF 防护。Cookie 文件等同于登录凭据，必须妥善保管，生产环境应通过 HTTPS 调用。

## 2. 接口总览

### 2.1 JSON 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/stock/alarm/api/search?q=<关键字>` | 搜索可用于告警设置的标的 |
| GET | `/stock/ai/api/search?q=<关键字>` | 搜索可用于 AI 分析的标的 |
| POST | `/stock/refresh_quotes` | 按订单 ID 批量读取数据库中的最新行情 |
| GET | `/stock/api/system_status` | 获取监控、交易时段、冷却和行情源状态 |
| GET | `/stock/api/kline/<stock_id>` | 获取指定订单最近 60 条 K 线 |

### 2.2 表单接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/login` | 登录并建立 Session |
| GET | `/logout` | 退出登录 |
| POST | `/stock/create` | 创建订单 |
| POST | `/stock/edit/<id>` | 全量更新订单及阈值 |
| POST | `/stock/delete/<id>` | 删除订单 |
| POST | `/stock/toggle_status/<id>` | 将订单状态取反 |
| POST | `/stock/alarm_settings` | 更新某一类告警设置 |
| POST | `/stock/ai/analyze` | 生成并保存一次 AI 分析 |
| POST | `/stock/ai/ask` | 基于最近一次正式分析追问 |
| POST | `/stock/ai/config` | 保存全局 AI 非凭据参数 |
| POST | `/stock/ai/test` | 测试 AI 网关连通性 |

纯 HTML 页面（例如 `/stock/list`、`/stock/recent_alarms`）不作为结构化数据接口使用。

## 3. 通用调用约定

### 3.1 Base URL 与编码

以下示例统一使用：

```bash
export BASE_URL="http://127.0.0.1:5000"
export COOKIE_JAR="./.flask-stock.cookies"
```

- 表单字段使用 UTF-8。
- JSON 请求使用请求头 `Content-Type: application/json`。
- 搜索参数应进行 URL 编码；使用 curl 时推荐 `--get --data-urlencode`。
- 数字字段使用十进制数字，不要使用中文逗号或千分位。

### 3.2 登录并保存 Cookie

不要把真实密码写进脚本或命令历史。下面通过隐藏输入读取密码：

```bash
export STOCK_USERNAME="<your-username>"
read -r -s -p "密码: " STOCK_PASSWORD
echo
export STOCK_PASSWORD

# 创建仅当前用户可读写的 Cookie 文件
(umask 077; : > "$COOKIE_JAR")

curl -sS \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o /dev/null -w 'HTTP %{http_code}\n' \
  --data-urlencode "username=${STOCK_USERNAME}" \
  --data-urlencode "password=${STOCK_PASSWORD}" \
  "${BASE_URL}/login"

unset STOCK_PASSWORD
```

登录表单字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `username` | 是 | 用户名 |
| `password` | 是 | 密码 |

返回判断：

- 登录成功：`302`，`Location` 通常指向 `/`。
- 登录失败：`200`，返回登录 HTML 页面。

验证 Session 是否可用：

```bash
curl -sS \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  "${BASE_URL}/stock/api/system_status"
```

如果返回的是 HTML 而不是 JSON，通常表示 Session 缺失、过期或登录失败。

后续 curl 示例都同时携带 `-c "$COOKIE_JAR" -b "$COOKIE_JAR"`：前者保存服务端更新的 Session，后者发送现有 Session。

### 3.3 登出

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o /dev/null \
  "${BASE_URL}/logout"
```

登出后建议删除本地 Cookie 文件：

```bash
rm -f -- "$COOKIE_JAR"
```

## 4. JSON 接口

### 4.1 搜索标的

提供两个搜索入口，搜索逻辑相同，仅返回的 `url` 不同：

| 接口 | `url` 指向 |
| --- | --- |
| `GET /stock/alarm/api/search` | 对应标的的告警设置页 |
| `GET /stock/ai/api/search` | 对应标的的 AI 分析页 |

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `q` | 是 | 按股票名称或代码模糊匹配；服务端最多保留前 32 个字符 |

行为说明：

- `q` 为空时返回空数组，不会返回全部订单。
- 每次最多返回 12 条。
- `total` 是匹配总数，`truncated=true` 表示还有结果未包含在 `items` 中。
- 普通用户只搜索自己的订单；管理员搜索全部订单，因此同一代码可能出现多条不同归属的记录。

请求示例：

```bash
curl -sS -G \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  --data-urlencode "q=SH600519" \
  "${BASE_URL}/stock/alarm/api/search"
```

成功响应：

```json
{
  "items": [
    {
      "id": 1,
      "name": "贵州茅台",
      "code": "SH600519",
      "price": 1480.0,
      "url": "/stock/alarm_settings?stock_id=1"
    }
  ],
  "total": 1,
  "truncated": false
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items[].id` | integer | 订单 ID，即其他接口使用的 `stock_id` |
| `items[].name` | string | 股票名称 |
| `items[].code` | string | 股票代码 |
| `items[].price` | number/null | 数据库中保存的现价，未采集时为 `null` |
| `items[].url` | string | 对应功能页面，不是 JSON 数据地址 |

数据库异常时返回 HTTP `500`，响应中可能包含 `error` 字段。

### 4.2 批量读取最新行情

```http
POST /stock/refresh_quotes
Content-Type: application/json
```

请求体：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ids` | array | 是 | 订单 ID 数组；无效项会被忽略，最多处理前 200 个有效格式项 |

请求示例：

```bash
curl -sS \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -H 'Content-Type: application/json' \
  -d '{"ids":[1,2,3]}' \
  "${BASE_URL}/stock/refresh_quotes"
```

成功响应：

```json
{
  "quotes": [
    {
      "id": 1,
      "current_price": 1480.0,
      "current_pe": 24.31,
      "current_pb": 8.15
    }
  ],
  "updated_at": "14:30:05"
}
```

注意事项：

- 该接口**只读数据库，不会立即请求雪球**。`updated_at` 是本次接口响应时间，不是行情采集时间。
- 价格、PE、PB 尚未采集时对应字段为 `null`。
- 不属于当前用户可见范围的 ID 会被静默忽略，不返回错误。
- 传入空数组或全部 ID 被过滤时，返回 `quotes: []`。
- 超过 200 个 ID 时应在客户端分批，不要依赖服务端截断行为完成全量查询。

### 4.3 获取系统状态

```http
GET /stock/api/system_status
```

请求示例：

```bash
curl -sS \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  "${BASE_URL}/stock/api/system_status"
```

响应示例：

```json
{
  "monitor": {
    "running": true,
    "tone": "ok",
    "text": "运行中"
  },
  "session": {
    "key": "morning",
    "text": "早盘交易中"
  },
  "cooldown": {
    "seconds": 14400,
    "text": "4 小时"
  },
  "xueqiu": {
    "ok": true,
    "tone": "ok",
    "text": "正常",
    "reason": ""
  },
  "updated_at": "10:30:00"
}
```

`session.key` 的可能值包括 `morning`、`afternoon`、`noon`、`closed`。`xueqiu.ok=false` 时应同时查看 `text` 和 `reason`，常见原因包括 Token 未配置或行情源限流退避。

### 4.4 获取 K 线数据

```http
GET /stock/api/kline/<stock_id>
```

路径参数：

| 参数 | 说明 |
| --- | --- |
| `stock_id` | 订单 ID，不是股票代码 |

请求示例：

```bash
curl -sS \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  "${BASE_URL}/stock/api/kline/1"
```

成功响应：

```json
{
  "success": true,
  "klines": [
    {
      "trade_date": "2026-11-09",
      "close_price": "1480.00",
      "ma5": "1472.00",
      "ma10": "1460.00",
      "ma30": "1435.00",
      "signal_type": "golden_cross"
    }
  ]
}
```

说明：

- 最多返回最近 60 条记录，并按交易日从早到晚排列。
- 数据库 Decimal 字段在 JSON 中可能表现为数字字符串；空值为 `null`，调用方需要自行转换。
- `signal_type` 取值为 `golden_cross`（金叉）、`death_cross`（死叉）或 `normal`（震荡）。
- 无数据时返回 `success: true` 和空 `klines`。
- 订单不存在或无权访问时返回 HTTP `403`：`{"success":false,"error":"无权访问该标的"}`。
- 服务异常时返回 HTTP `500` 和 `success: false`。

## 5. 订单表单接口

### 5.1 订单字段

创建和编辑共用以下字段：

| 字段 | 类型 | 创建 | 编辑 | 说明 |
| --- | --- | --- | --- | --- |
| `stock_name` | string | 必填 | 必填 | 订单/股票名称 |
| `stock_code` | string | 必填 | 必填 | 业务约定使用 `SH`、`SZ`、`BJ` 前缀，例如 `SH600519` |
| `target_pettm` | number | 可选 | 可选 | 目标 PE |
| `target_pb` | number | 可选 | 可选 | 目标 PB |
| `status` | string | 不使用 | 可选 | `active` 或 `inactive`；编辑时缺省为 `active` |
| `dividend_yield` | number | 可选 | 可选 | 股息率百分比 |
| `sell_rate` | number | 可选 | 可选 | 目标卖出价 |
| `stock_valueone` | number | 可选 | 可选 | 第一档建仓价 |
| `stock_valuetwo` | number | 可选 | 可选 | 第二档建仓价 |
| `stock_valuethree` | number | 可选 | 可选 | 第三档建仓价 |
| `memo` | string | 可选 | 可选 | 价格/建仓备注 |
| `pe_valueone` | number | 可选 | 可选 | 第一档 PE |
| `pe_valuetwo` | number | 可选 | 可选 | 第二档 PE |
| `pe_valuethree` | number | 可选 | 可选 | 第三档 PE |
| `pe_memo` | string | 可选 | 可选 | PE 备注 |
| `pb_valueone` | number | 可选 | 可选 | 第一档 PB |
| `pb_valuetwo` | number | 可选 | 可选 | 第二档 PB |
| `pb_valuethree` | number | 可选 | 可选 | 第三档 PB |
| `pb_memo` | string | 可选 | 可选 | PB 备注 |

重要约束：

- 同一登录用户名下 `stock_code` 唯一；不同用户可以各自拥有相同代码。
- 新订单归属于当前登录用户，客户端不能通过 `user_id` 指定归属。
- 创建接口会忽略 `status`，新订单默认是 `active`。
- 后端没有完整校验交易所前缀和三档价格顺序，调用方应确保代码正确，并保证第一档 > 第二档 > 第三档。
- 无法解析的数字会按空值处理。编辑时这可能把原值清空，因此不要提交非数字内容。

### 5.2 创建订单

```http
POST /stock/create
Content-Type: application/x-www-form-urlencoded
```

最小请求只包含 `stock_name` 和 `stock_code`。完整示例：

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o create-result.html \
  --data-urlencode 'stock_name=贵州茅台' \
  --data-urlencode 'stock_code=SH600519' \
  --data-urlencode 'target_pettm=25' \
  --data-urlencode 'target_pb=8' \
  --data-urlencode 'sell_rate=1800' \
  --data-urlencode 'stock_valueone=1500' \
  --data-urlencode 'stock_valuetwo=1400' \
  --data-urlencode 'stock_valuethree=1300' \
  --data-urlencode 'pe_valueone=25' \
  --data-urlencode 'pb_valueone=8' \
  --data-urlencode 'memo=分批建仓' \
  "${BASE_URL}/stock/create"

grep -q '订单创建成功！' create-result.html \
  && echo '创建成功' \
  || echo '创建失败，请检查 create-result.html 中的提示'
```

成功时重定向到 `/stock/list`。创建响应不会直接返回新订单 ID，需要创建后通过搜索接口按代码查询，并在客户端按 `code` 精确匹配。

### 5.3 编辑订单

```http
POST /stock/edit/<id>
Content-Type: application/x-www-form-urlencoded
```

**这是全量覆盖语义，不是 PATCH。** 编辑时需要提交希望保留的全部字段：

- 可选数字字段缺省会写成 `NULL`。
- `memo`、`pe_memo`、`pb_memo` 缺省会写成空字符串。
- `status` 缺省会按 `active` 处理，可能意外启用原本暂停的订单。

因此，批量局部修改前必须先获取并保存完整订单数据。当前没有订单详情 JSON 接口，可以从 `GET /stock/edit/<id>` 的表单中读取原值，或者由业务侧维护完整输入数据。

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o edit-result.html \
  --data-urlencode 'stock_name=贵州茅台' \
  --data-urlencode 'stock_code=SH600519' \
  --data-urlencode 'status=active' \
  --data-urlencode 'target_pettm=25' \
  --data-urlencode 'target_pb=8' \
  --data-urlencode 'sell_rate=1850' \
  --data-urlencode 'stock_valueone=1500' \
  --data-urlencode 'stock_valuetwo=1400' \
  --data-urlencode 'stock_valuethree=1300' \
  --data-urlencode 'pe_valueone=25' \
  --data-urlencode 'pb_valueone=8' \
  --data-urlencode 'memo=调整卖出价，其余值保留' \
  "${BASE_URL}/stock/edit/1"
```

成功时重定向到订单列表，并显示 `订单更新成功！`。订单不存在或无权访问时也会重定向到列表，所以仍需检查 Flash 消息。

### 5.4 删除订单

```http
POST /stock/delete/<id>
```

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o delete-result.html \
  -X POST \
  "${BASE_URL}/stock/delete/1"
```

删除会清理主订单及按外键级联的关联数据，不可恢复。成功、失败和无权访问最终都可能重定向到订单列表，必须检查页面是否包含 `订单删除成功！`。

### 5.5 切换监控状态

```http
POST /stock/toggle_status/<id>
```

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o toggle-result.html \
  -X POST \
  "${BASE_URL}/stock/toggle_status/1"
```

服务端读取当前状态并取反：

- `active` → `inactive`
- 其他状态 → `active`

该操作**不是幂等接口**，重复调用会反复切换。批量任务如果要求“必须设置为指定状态”，不要循环调用此接口，应通过编辑接口提交完整订单数据和明确的 `status`。

可选表单字段 `next` 用于成功后返回指定站内列表地址，一般批量脚本无需传入。

## 6. 告警设置接口

```http
POST /stock/alarm_settings
Content-Type: application/x-www-form-urlencoded
```

每次请求只更新一种告警类型。公共字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `stock_id` | 是 | 订单 ID |
| `alarm_type` | 是 | `warehouse`、`pe`、`pb`、`indicator` 之一 |

### 6.1 价格告警：`alarm_type=warehouse`

字段：`sell_rate`、`dividend_yield`、`stock_valueone`、`stock_valuetwo`、`stock_valuethree`、`memo`。

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o alarm-result.html \
  --data-urlencode 'stock_id=1' \
  --data-urlencode 'alarm_type=warehouse' \
  --data-urlencode 'sell_rate=1800' \
  --data-urlencode 'dividend_yield=1.5' \
  --data-urlencode 'stock_valueone=1500' \
  --data-urlencode 'stock_valuetwo=1400' \
  --data-urlencode 'stock_valuethree=1300' \
  --data-urlencode 'memo=价格告警' \
  "${BASE_URL}/stock/alarm_settings"
```

### 6.2 PE/PB 告警

- `alarm_type=pe`：提交 `pe_valueone`、`pe_valuetwo`、`pe_valuethree`、`pe_memo`。
- `alarm_type=pb`：提交 `pb_valueone`、`pb_valuetwo`、`pb_valuethree`、`pb_memo`。

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o alarm-pe-result.html \
  --data-urlencode 'stock_id=1' \
  --data-urlencode 'alarm_type=pe' \
  --data-urlencode 'pe_valueone=25' \
  --data-urlencode 'pe_valuetwo=22' \
  --data-urlencode 'pe_valuethree=20' \
  --data-urlencode 'pe_memo=PE 分档提醒' \
  "${BASE_URL}/stock/alarm_settings"
```

价格、PE、PB 组内同样采用覆盖语义：可选数字留空会保存为 `NULL`，备注留空会保存为空字符串。只更新单档时也应提交该组其他需要保留的值。

### 6.3 指标告警：`alarm_type=indicator`

| 字段 | 范围 | 留空语义 |
| --- | --- | --- |
| `low52w_near_pct` | 0.1～100 | 继承全局配置 |
| `drawdown_52w_pct` | 0.1～100 | 继承全局配置 |
| `rs20_pct` | 0.1～100 | 继承全局配置 |
| `rs5_ratio` | 0.1～20 | 继承全局配置 |
| `rs5_min_drop_pct` | 0～100 | 继承全局配置 |
| `rs5_min_bench_drop_pct` | 0～100 | 继承全局配置 |

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o alarm-indicator-result.html \
  --data-urlencode 'stock_id=1' \
  --data-urlencode 'alarm_type=indicator' \
  --data-urlencode 'low52w_near_pct=5' \
  --data-urlencode 'drawdown_52w_pct=35' \
  --data-urlencode 'rs20_pct=15' \
  --data-urlencode 'rs5_ratio=2.5' \
  --data-urlencode 'rs5_min_drop_pct=3' \
  --data-urlencode 'rs5_min_bench_drop_pct=0.5' \
  "${BASE_URL}/stock/alarm_settings"
```

指标阈值成功后返回 `stock_id` 对应页面并保留 `tab=indicator`。全部字段留空表示该订单六项都继承全局默认值。

## 7. AI 相关表单接口

AI 接口同样返回 HTML 重定向，不返回报告 JSON。调用前需要配置并启用 AI，且每次正式分析、追问和连通测试都会消耗外部模型 Token。

### 7.1 生成分析

```http
POST /stock/ai/analyze
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `stock_id` | 是 | 订单 ID |
| `model` | 否 | 必须位于服务端候选模型清单；缺省使用已保存模型或默认模型 |
| `dimensions` | 否 | 可重复提交；缺省使用已保存维度 |

`dimensions` 可选值：`valuation`、`technical`、`relative`、`position`、`risk`。

```bash
curl -sS -L \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -o ai-analyze-result.html \
  --data-urlencode 'stock_id=1' \
  --data-urlencode 'dimensions=valuation' \
  --data-urlencode 'dimensions=technical' \
  --data-urlencode 'dimensions=risk' \
  "${BASE_URL}/stock/ai/analyze"
```

成功后跳转到 `/stock/ai/?stock_id=<id>&report_id=<报告ID>`。失败也可能返回相同工作台页面，应检查 Flash 中是否包含 `分析完成`。批量分析会快速消耗共享月度额度，不建议并发执行。

### 7.2 追问

```http
POST /stock/ai/ask
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `stock_id` | 是 | 订单 ID |
| `question` | 是 | 1～300 字 |
| `model` | 否 | 候选模型清单中的模型 |

该标的必须已经存在至少一次正式分析，追问结果也会保存到历史记录。

### 7.3 保存 AI 参数

```http
POST /stock/ai/config
```

| 字段 | 说明 |
| --- | --- |
| `enabled` | 传 `1` 为开启；不传为关闭。环境变量 `AI_ENABLED` 仍是总开关 |
| `model` | 候选模型；留空表示跟随环境默认 |
| `dimensions` | 重复字段，至少一项 |
| `temperature` | 0～2；留空继承环境配置 |
| `max_tokens` | 100～32000 的整数；留空继承环境配置 |
| `monthly_limit` | 0～100000 的整数，0 表示不限；留空继承环境配置 |
| `data_scope` | 重复字段，至少一项：`quote`、`valuation`、`indicator`、`kline` |
| `stock_id` | 可选，仅用于保存后返回对应标的页面 |

这些参数保存在全局单行配置中，不是每个订单或每个用户一份。批量任务不要在不同任务间反复修改全局配置。

### 7.4 连通测试

```http
POST /stock/ai/test
```

可选字段：

- `model`：要测试的候选模型。
- `api_key`：写入当前服务进程内存并立即用于测试，不落库，重启后失效。
- `clear_key=1`：清除运行时密钥，恢复使用环境变量。
- `stock_id`：仅用于控制回跳页面。

不要把真实 `api_key` 写入脚本、日志或命令历史。自动化环境优先使用服务端环境变量 `AI_API_KEY`。

## 8. 批量操作示例

### 8.1 使用 Python 从 CSV 批量创建订单

CSV 示例 `stocks.csv`：

```csv
stock_name,stock_code,target_pettm,target_pb,sell_rate,stock_valueone,stock_valuetwo,stock_valuethree,memo
贵州茅台,SH600519,25,8,1800,1500,1400,1300,第一只示例标的
中国平安,SH601318,10,1,60,45,42,39,第二只示例标的
```

Python 示例需要 `requests`。脚本逐条创建、检查成功提示，再通过搜索接口获取订单 ID：

```python
import csv
import os
import time

import requests

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
USERNAME = os.environ["STOCK_USERNAME"]
PASSWORD = os.environ["STOCK_PASSWORD"]

ALLOWED_FIELDS = {
    "stock_name", "stock_code", "target_pettm", "target_pb",
    "dividend_yield", "sell_rate",
    "stock_valueone", "stock_valuetwo", "stock_valuethree", "memo",
    "pe_valueone", "pe_valuetwo", "pe_valuethree", "pe_memo",
    "pb_valueone", "pb_valuetwo", "pb_valuethree", "pb_memo",
}

session = requests.Session()


def url(path):
    return f"{BASE_URL}{path}"


def resolve_stock_id(stock_code):
    response = session.get(
        url("/stock/alarm/api/search"),
        params={"q": stock_code},
        timeout=(5, 30),
    )
    response.raise_for_status()
    matches = [
        item for item in response.json().get("items", [])
        if item.get("code") == stock_code
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"代码 {stock_code} 精确匹配到 {len(matches)} 条，无法唯一确定订单 ID"
        )
    return matches[0]["id"]


login = session.post(
    url("/login"),
    data={"username": USERNAME, "password": PASSWORD},
    allow_redirects=False,
    timeout=(5, 30),
)
if login.status_code not in (301, 302, 303):
    raise SystemExit("登录失败，请检查用户名和密码")

created = []
failed = []

with open("stocks.csv", "r", encoding="utf-8-sig", newline="") as file:
    for line_number, row in enumerate(csv.DictReader(file), start=2):
        payload = {
            key: (value or "").strip()
            for key, value in row.items()
            if key in ALLOWED_FIELDS
        }
        code = payload.get("stock_code", "")
        try:
            response = session.post(
                url("/stock/create"),
                data=payload,
                timeout=(5, 30),
            )
            response.raise_for_status()
            if "订单创建成功！" not in response.text:
                raise RuntimeError("返回页面没有成功提示，请检查表单校验或重复代码")

            stock_id = resolve_stock_id(code)
            created.append((code, stock_id))
            print(f"[成功] 第 {line_number} 行：{code}，ID={stock_id}")
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            failed.append((line_number, code, str(exc)))
            print(f"[失败] 第 {line_number} 行：{code}，{exc}")

        time.sleep(0.2)

print(f"完成：成功 {len(created)} 条，失败 {len(failed)} 条")
if failed:
    raise SystemExit(1)
```

运行方式：

```bash
export BASE_URL="http://127.0.0.1:5000"
export STOCK_USERNAME="<your-username>"
read -r -s -p "密码: " STOCK_PASSWORD
echo
export STOCK_PASSWORD
python batch_create.py
unset STOCK_PASSWORD
```

注意：示例代码应保存为 `batch_create.py` 后运行，本文只提供示例，不会自动在项目中生成该脚本。

### 8.2 Python 分批读取行情

以下代码可复用上一示例中已经登录的 `session`：

```python
stock_ids = [1, 2, 3, 4]
quotes = []

for offset in range(0, len(stock_ids), 200):
    chunk = stock_ids[offset:offset + 200]
    response = session.post(
        url("/stock/refresh_quotes"),
        json={"ids": chunk},
        timeout=(5, 30),
    )
    response.raise_for_status()
    quotes.extend(response.json().get("quotes", []))

print(quotes)
```

## 9. 批量任务可靠性与安全建议

1. **先小批验证**：先处理 1～2 条并到页面核对，再扩大批量。
2. **顺序执行**：写操作建议串行并保留日志，不要一开始就做高并发。
3. **不要盲目重试写操作**：网络超时可能发生在服务端已经提交之后。重试前先搜索或到页面核实。
4. **创建重跑**：同一代码重复创建会失败，不会在同一用户下生成重复订单；超时后的状态仍需先核实。
5. **谨慎使用状态切换**：`toggle_status` 不幂等，重试可能把状态再次切回去。
6. **删除单独确认**：批量删除前备份数据库，并单独保存待删除 ID 清单和执行结果。
7. **编辑保留完整字段**：避免可选字段、备注或监控状态被缺省值覆盖。
8. **没有整批事务**：第 N 条失败不会回滚前 N-1 条，调用方需记录每条结果并自行补偿。
9. **管理员注意代码歧义**：管理员可看到多个用户的相同股票代码，按代码解析 ID 时必须确认唯一性。
10. **保护凭据**：不要提交 `.env`、Cookie 文件、包含密码的脚本或命令输出。
11. **限制接口暴露**：当前没有 CSRF 和独立 API 权限令牌，不建议将这些表单接口直接暴露到公网。

## 10. 状态码与故障排查

| 现象 | 常见原因 | 处理建议 |
| --- | --- | --- |
| 请求 JSON 接口却返回 HTML | 未登录、Session 过期 | 重新登录；不要对 `302` 直接调用 `.json()` |
| 表单请求返回 `400` | 缺少代码直接读取的必填字段，如 `stock_name`、`stock_code` | 检查字段名和 Content-Type |
| 表单返回 `200` 但未写入 | 表单校验失败，页面返回错误提示 | 检查返回 HTML 中的 Flash 消息 |
| 表单返回 `302` 但未写入 | 无权访问、目标不存在或模型校验失败 | 跟随重定向并检查 Flash，不要只看状态码 |
| 创建成功但搜索不到 | 搜索词为空、代码不一致、Session 用户不同 | 使用完整代码搜索并精确匹配 `code` |
| 管理员按代码得到多条 | 不同用户可拥有相同代码 | 结合归属信息人工确认，不要任意取第一条 |
| 行情一直为 `null` | 后台尚未采集、订单已暂停或行情源异常 | 检查订单状态及 `/stock/api/system_status` |
| 行情“刷新”后时间变了但价格没变 | 接口只重读数据库，没有请求行情源 | 检查后台监控和最新采集时间 |
| AI 调用未执行 | 环境总开关、参数开关、模型白名单或月度额度限制 | 检查工作台 Flash 和服务端 AI 配置 |

### 推荐的结果记录字段

批量任务建议为每条输入记录以下信息：

```json
{
  "line": 2,
  "stock_code": "SH600519",
  "operation": "create",
  "success": true,
  "stock_id": 1,
  "http_status": 200,
  "final_url": "http://127.0.0.1:5000/stock/list",
  "message": "订单创建成功！"
}
```

其中 `http_status: 200` 是跟随重定向后的最终页面状态；业务是否成功仍以 Flash 消息和后续查询核验为准。
