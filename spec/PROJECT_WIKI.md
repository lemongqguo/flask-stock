# Flask Stock 订单监控系统 - 项目Wiki文档

## 1. 项目概述

### 1.1 项目简介
Flask Stock 是一个基于 Flask 框架开发的股票订单监控系统，主要用于：
- 股票订单信息管理
- 实时监控股票价格、PE、PB等指标
- 多档位建仓/卖出告警
- K线数据采集与均线分析（金叉/死叉信号）
- 邮件告警通知

### 1.2 技术栈
| 类别 | 技术 |
|------|------|
| 后端框架 | Flask 2.3.3 |
| 数据库 | MySQL (PyMySQL + DBUtils连接池) |
| 前端 | 自建设计系统（CSS 变量 + 内联 SVG sprite，双主题）；Chart.js 4.4.1（K 线图唯一外部依赖） |
| 数据分析 | Pandas 3.1.0（2026-10-27 由 2.0.3 对齐到实际安装版本） |
| 数据源 | 雪球财经 (pysnowball) |
| 部署 | Python 3.12 + gunicorn 26.2.0（单进程 gthread）；虚拟环境 `stockvenv/` |

### 1.3 项目目录结构
```
flask-stock/
├── app.py                 # 应用入口
├── config.py              # 配置文件
├── database.py            # 数据库初始化
├── requirements.txt       # 依赖清单
├── .gitignore             # 排除虚拟环境 / .env / logs / 缓存
├── gunicorn.conf.py       # gunicorn 启动配置（进程模型 / 日志 / 钩子）
├── start.sh               # 启动脚本（默认 exec gunicorn，USE_GUNICORN=0 可退回）
├── models/                # 数据模型层
│   ├── base.py            # 基础模型类
│   ├── user.py            # 用户模型
│   ├── stock_master.py    # 主订单模型
│   ├── stock_warehouse.py # 仓库(持仓)模型
│   ├── stock_pe.py        # PE阈值模型
│   ├── stock_pb.py        # PB阈值模型
│   ├── stock_alarm.py     # 告警记录模型
│   ├── stock_kline.py     # K线数据模型
│   ├── stock_indicator.py # 指标监控模型（快照/阈值覆盖/基准日线）
│   ├── stock_ai.py        # AI 报告与参数模型（007）
│   └── stock_monitor.py   # 监控服务模型
├── views/                 # 视图控制器
│   ├── auth.py            # 认证相关路由
│   ├── ai_analysis.py     # AI 分析路由（007）
│   └── stock_orders.py    # 股票订单路由
├── utils/                 # 工具类
│   ├── decorators.py      # 装饰器(登录验证)
│   ├── alarm_rules.py     # 告警判定规则（纯函数）
│   ├── alarm_throttle.py  # 告警冷却
│   ├── indicator_rules.py # 指标判定规则（纯函数，006）
│   ├── ai_client.py       # OpenAI 兼容客户端（007）
│   ├── ai_prompt.py       # 提示词组装与解析（007）
│   └── mail_sender.py     # 邮件发送
├── templates/             # HTML模板
│   ├── base.html          # 基础模板（侧栏 + topbar + 双主题）
│   ├── auth.html          # 登录/注册（分栏 + 双页签，独立整页）
│   ├── stock_order_list.html # 订单列表
│   ├── stock_order_form.html # 订单表单
│   ├── alarm_settings.html   # 告警设置（左列表 + 右页签）
│   ├── recent_alarms.html    # 告警历史（时间线）
│   ├── indicator_list.html   # 指标监控（006）
│   ├── ai_analysis.html   # AI 分析（报告 / 追问 / 参数，007）
│   ├── account.html       # 账户设置（资料/改密码/通知偏好合并）
│   └── error.html         # 错误页（独立整页）
├── static/                # 静态资源
│   ├── css/theme.css      # 设计系统（设计令牌 + 组件，深/浅双主题）
│   ├── js/theme.js        # 前端交互（SVG sprite + 主题切换 + 声明式组件）
│   └── favicon.ico        # 网站图标
└── logs/                  # 日志目录
```

---

## 2. 系统架构

### 2.1 整体架构图
```
┌─────────────────────────────────────────────────────────────┐
│                        用户界面层                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 订单列表 │ │ 告警设置 │ │ 告警历史 │ │ 用户认证 │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        视图控制器层                          │
│  ┌──────────────┐              ┌──────────────────┐         │
│  │   auth_bp    │              │    stock_bp      │         │
│  │ (认证蓝图)   │              │  (订单蓝图)      │         │
│  └──────────────┘              └──────────────────┘         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        业务模型层                            │
│  ┌────────┐ ┌─────────────┐ ┌─────────┐ ┌──────────┐       │
│  │  User  │ │ StockMaster │ │StockPe  │ │StockPb   │       │
│  └────────┘ └─────────────┘ └─────────┘ └──────────┘       │
│  ┌────────────────┐ ┌────────────┐ ┌───────────────────┐   │
│  │ StockWarehouse │ │ StockAlarm │ │   StockMonitor    │   │
│  │   (持仓信息)   │ │ (告警记录) │ │  (监控服务线程)   │   │
│  └────────────────┘ └────────────┐ └───────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    StockKline                        │   │
│  │              (K线数据 & 均线信号分析)                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        数据访问层                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    BaseModel                          │  │
│  │         (通用CRUD操作 + 连接池管理)                   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        数据存储层                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                     MySQL                             │  │
│  │   users / stock_master / stock_warehouse / ...        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        外部服务层                            │
│  ┌──────────────────┐    ┌────────────────────────────┐    │
│  │   雪球财经API     │    │      SMTP邮件服务         │    │
│  │  (pysnowball)    │    │    (告警通知)             │    │
│  └──────────────────┘    └────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 监控服务流程
```
┌─────────────┐     ┌─────────────────┐     ┌───────────────┐
│ 应用启动    │ ──▶ │ StockMonitor    │ ──▶ │ 监控循环线程  │
│ app.py      │     │ start_monitoring│     │ monitor_loop  │
└─────────────┘     └─────────────────┘     └───────────────┘
                                                    │
                                                    ▼
                           ┌────────────────────────────────────┐
                           │     获取活跃状态股票列表           │
                           │   StockMaster.get_active_stocks   │
                           └────────────────────────────────────┘
                                                    │
                                                    ▼
                           ┌────────────────────────────────────┐
                           │     ThreadPoolExecutor并发处理     │
                           │        (max_workers=6)            │
                           └────────────────────────────────────┘
                                                    │
                          ┌─────────────────────────┴───────────┐
                          ▼                                     ▼
            ┌─────────────────────────┐         ┌─────────────────────────┐
            │   获取雪球股票数据      │         │   获取K线数据           │
            │   ball.quote_detail     │         │   ball.kline            │
            └─────────────────────────┘         └─────────────────────────┘
                          │                                     │
                          ▼                                     ▼
            ┌─────────────────────────┐         ┌─────────────────────────┐
            │   更新数据库价格/PE/PB  │         │   计算均线MA5/MA10/MA30 │
            └─────────────────────────┘         │   判断金叉/死叉信号     │
                          │                     └─────────────────────────┘
                          │                                     │
                          └──────────────────────┬──────────────┘
                                                 ▼
                           ┌────────────────────────────────────┐
                           │          告警条件检测              │
                           │  价格档位 / PE档位 / PB档位 / 卖出价│
                           └────────────────────────────────────┘
                                                 │
                                                 ▼
                           ┌────────────────────────────────────┐
                           │          触发告警                  │
                           │  StockAlarm.create + send_mail     │
                           └────────────────────────────────────┘
```

---

## 3. 数据库设计

### 3.1 数据表结构

#### users (用户表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键，自增 |
| username | VARCHAR(80) | 用户名，唯一 |
| password_hash | VARCHAR(120) | 密码哈希 |
| email | VARCHAR(120) | 邮箱（告警邮件按订单归属人发，取的就是这一列） |
| role | ENUM('user','admin') | 角色（2026-10-26 新增）。`admin` 见全量订单，`user` 只见自己名下；首个注册用户自动为 admin |
| created_at | TIMESTAMP | 创建时间 |

#### stock_master (主订单表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键，自增 |
| user_id | INT | **归属用户**（2026-10-26 新增），外键 `users(id) ON DELETE RESTRICT`。下游子表靠 `stock_master_id` 继承归属 |
| stock_name | VARCHAR(100) | 股票名称 |
| stock_code | VARCHAR(20) | 股票代码 (如 SZ002027)。**不再全局唯一**，唯一键为 `uk_user_code(user_id, stock_code)`，同一代码可被不同用户各持有一条 |
| target_pettm | DECIMAL(10,2) | 目标PE-TTM |
| current_pe | DECIMAL(10,2) | 当前PE |
| target_pb | DECIMAL(10,2) | 目标PB |
| current_pb | DECIMAL(10,2) | 当前PB |
| status | ENUM | 状态 (active/inactive) |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

索引：`idx_stock_owner(user_id)`、唯一键 `uk_user_code(user_id, stock_code)`、
外键 `fk_stock_master_user(user_id) REFERENCES users(id) ON DELETE RESTRICT`
（`idx_stock_name` / `idx_stock_code` 仍在，供搜索用）。

#### stock_warehouse (仓库/持仓表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| stock_master_id | INT | 外键关联stock_master |
| dividend_yield | DECIMAL(5,2) | 股息率 |
| current_price | DECIMAL(10,2) | 当前价格 |
| sell_rate | DECIMAL(10,2) | 卖出价位 |
| stock_valueone | DECIMAL(10,2) | 第一档建仓价 |
| stock_valuetwo | DECIMAL(10,2) | 第二档建仓价 |
| stock_valuethree | DECIMAL(10,2) | 第三档建仓价 |
| memo | TEXT | 备注 |

#### stock_pe (PE阈值表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| stock_master_id | INT | 外键 |
| pe_valueone | DECIMAL(10,2) | 第一档PE阈值 |
| pe_valuetwo | DECIMAL(10,2) | 第二档PE阈值 |
| pe_valuethree | DECIMAL(10,2) | 第三档PE阈值 |
| memo | TEXT | 备注（编辑入口在「告警设置」页；订单表单只回传原值） |

#### stock_pb (PB阈值表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| stock_master_id | INT | 外键 |
| pb_valueone | DECIMAL(10,2) | 第一档PB阈值 |
| pb_valuetwo | DECIMAL(10,2) | 第二档PB阈值 |
| pb_valuethree | DECIMAL(10,2) | 第三档PB阈值 |
| memo | TEXT | 备注（编辑入口在「告警设置」页；订单表单只回传原值） |

#### stock_alarm (告警记录表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| stock_master_id | INT | 外键 |
| alarm_time | TIMESTAMP | 告警时间 |
| alarm_text | TEXT | 告警内容 |
| alarm_type | VARCHAR(16) | 告警类型：`price` / `sell` / `pe` / `pb` / `indicator` / `unknown`（默认 unknown） |
| alarm_subtype | VARCHAR(16) | 指标类细分：`combo`（当前口径）；历史行另有 `low52w` / `drawdown` / `rs20` / `rs5` |
| alarm_level | TINYINT | 档位 1/2/3（价格与估值用），其余为 NULL |
| notify_status | VARCHAR(16) | 邮件通知状态：`pending` / `sent` / `failed` / `skipped` / `unknown`（默认 unknown） |
| created_at | TIMESTAMP | 创建时间 |

索引：`idx_alarm_time(alarm_time)`、`idx_stock_alarm(stock_master_id, alarm_time)`、`idx_alarm_type(alarm_type, alarm_time)`。

#### stock_kline (K线数据表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| stock_master_id | INT | 外键 |
| stock_code | VARCHAR(20) | 股票代码 |
| trade_date | DATETIME | 交易日期 |
| open_price | DECIMAL(10,2) | 开盘价 |
| high_price | DECIMAL(10,2) | 最高价 |
| low_price | DECIMAL(10,2) | 最低价 |
| close_price | DECIMAL(10,2) | 收盘价 |
| volume | BIGINT | 成交量 |
| ma5 | DECIMAL(10,2) | 5日均线 |
| ma10 | DECIMAL(10,2) | 10日均线 |
| ma30 | DECIMAL(10,2) | 30日均线 |
| signal_type | ENUM | 信号类型 (golden_cross/death_cross/normal) |

#### stock_indicator (指标快照表 · 006 指标监控)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT | 主键 |
| stock_master_id | INT | 外键（**与 stock_master.id 类型保持一致**，否则 MySQL errno 150 拒建外键） |
| trade_date | DATE | 归属交易日；与 stock_master_id 组成唯一键 `uk_stock_indicator_date` |
| price / high52w / low52w | DECIMAL(12,4) | 现价与 52 周高低（雪球 `quote_detail` 原始值，不自行计算窗口） |
| pct_from_low52w | DECIMAL(8,4) | 距 52 周低的百分比 |
| drawdown_52w | DECIMAL(8,4) | 52 周回撤（负值） |
| ret_5d / ret_20d | DECIMAL(8,4) | 个股 5 / 20 交易日涨跌幅，不足交易日时为 NULL |
| bench_code | VARCHAR(16) | 基准指数代码，默认 SH000300 |
| bench_ret_5d / bench_ret_20d | DECIMAL(8,4) | 基准同期涨跌幅 |
| rs_20d | DECIMAL(8,4) | 20 日相对强弱（个股 − 基准，百分点） |
| rs_5d_ratio | DECIMAL(8,4) | 5 日跌幅倍数 |
| flag_low52w / flag_drawdown / flag_rs20 / flag_rs5 | TINYINT | 四类判定是否命中（0/1） |
| notified_at | DATETIME | 邮件通知时间；**不参与 upsert 的 UPDATE**，避免被刷新清掉 |
| created_at / updated_at | TIMESTAMP | 创建 / 更新时间 |

索引：唯一键 `uk_stock_indicator_date(stock_master_id, trade_date)`、`idx_indicator_trade_date(trade_date)`。

#### stock_indicator_config (单标的阈值覆盖表 · 006)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT | 主键 |
| stock_master_id | INT | 外键，**唯一**，一个标的一条配置 |
| low52w_near_pct / drawdown_52w_pct / rs20_pct | DECIMAL(8,4) | 对应判定阈值，**NULL 表示继承全局 `IND_*`** |
| rs5_ratio / rs5_min_drop_pct / rs5_min_bench_drop_pct | DECIMAL(8,4) | 5 日倍数与两道护栏的覆盖值 |

> 编辑入口：告警设置页「指标告警」页签（留空 = 继承全局 `IND_*`）。

#### stock_bench_kline (基准指数日线表 · 006)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT | 主键 |
| bench_code | VARCHAR(16) | 基准指数代码 |
| trade_date | DATE | 交易日；与 bench_code 组成唯一键 `uk_bench_date` |
| close_price | DECIMAL(12,4) | 收盘价 |
| created_at / updated_at | TIMESTAMP | 创建 / 更新时间 |

**为何不用 `stock_kline`**：该表以 `stock_master_id` 关联订单，而基准指数不是订单，无法挂载；相对强弱又必须有基准历史收盘价。

#### stock_ai_report (AI 分析报告表 · 007)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT | 主键 |
| stock_master_id | INT | 关联 `stock_master.id`（FK，CASCADE） |
| model | VARCHAR(64) | 实际调用的模型 ID |
| prompt_version | VARCHAR(16) | 提示词版本（如 `ai-007-v1`），用于事后追溯 |
| verdict | VARCHAR(16) | 五档评级；无法识别记「未知」；**追问记录固定为「问答」** |
| confidence | DECIMAL(5,2) | 置信度 0~100，模型超界时夹紧 |
| content_json | MEDIUMTEXT | 结构化结果（摘要 / 要点 / 支撑 / 风险 / 免责声明 / 原文 / 上下文）；追问存 `{question, answer}` |
| tokens_used | INT | 本次消耗 Token，缺失记 0 |
| created_at | TIMESTAMP | 创建时间；月度额度按此列计数 |
| 索引 | — | `(stock_master_id, created_at)`、`(created_at)` |

> **不含任何凭据**：密钥只在环境变量 `AI_API_KEY` 里，表结构与代码都接触不到明文。

#### stock_ai_config (AI 参数表 · 007)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 固定 `1`（单行表） |
| enabled | TINYINT | 与 `AI_ENABLED` 是**与关系**：环境总闸关闭时表内开启无效 |
| temperature | DECIMAL(3,2) | 采样温度（0~2），覆盖 `AI_TEMPERATURE` |
| max_tokens | INT | 单次输出上限，覆盖 `AI_MAX_TOKENS` |
| monthly_limit | INT | 月度调用上限（0 = 不限），覆盖 `AI_MONTHLY_LIMIT` |
| data_scope | VARCHAR(64) | 引用数据范围：`quote,valuation,indicator,kline` 逗号串 |
| model | VARCHAR(64) | 默认模型（须在候选清单内），覆盖 `AI_MODEL`；NULL = 跟随环境变量。**单个** ID，整串会回退 |
| dimensions | VARCHAR(128) | 默认分析维度：`valuation,technical,relative,position,risk` 逗号串；NULL = 全维度 |
| updated_at | TIMESTAMP | 更新时间（ON UPDATE） |

### 3.2 表关系图
```
┌─────────────┐
│   users     │  role: user / admin
└──────┬──────┘
       │ user_id（归属，RESTRICT：不允许因删用户清空订单）
       ▼
┌─────────────────────────────────────────────────────────────┐
│                      stock_master                            │
│                    (主订单 · 归属某人)                        │
└─────────────────────────────────────────────────────────────┘
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
┌────────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐
│stock_ware- │ │ stock_pe │ │ stock_pb │ │stock_alarm│ │stock_kline│
│  house     │ │          │ │          │ │           │ │           │
│ (持仓信息) │ │ (PE阈值) │ │ (PB阈值) │ │ (告警记录)│ │ (K线数据) │
└────────────┘ └──────────┘ └──────────┘ └───────────┘ └───────────┘
```

---

## 4. 功能模块详解

### 4.1 用户认证模块 (auth_bp)
| 路由 | 方法 | 功能 |
|------|------|------|
| /register | GET/POST | 用户注册 |
| /login | GET/POST | 用户登录 |
| /logout | GET | 用户登出 |
| /profile | GET | 个人资料页 |
| /change_password | GET/POST | 修改密码 |

**认证机制：**
- Session会话管理 (`session['user_id']`)
- Werkzeug密码哈希 (`generate_password_hash/check_password_hash`)
- `@login_required` 装饰器保护路由

### 4.2 股票订单模块 (stock_bp)
| 路由 | 方法 | 功能 |
|------|------|------|
| /stock/ | GET | 订单主页(重定向) |
| /stock/list | GET | 订单列表(分页/搜索) |
| /stock/create | GET/POST | 创建订单 |
| /stock/edit/<id> | GET/POST | 编辑订单 |
| /stock/delete/<id> | POST | 删除订单 |
| /stock/alarm_settings | GET/POST | 告警设置（价格 / PE / PB / 指标 四个页签） |
| /stock/recent_alarms | GET | 告警历史 |
| /stock/indicator | GET | 指标监控总览（006） |
| /stock/api/kline/<id> | GET | K线数据API |

### 4.2.1 订单列表 → AI 分析快捷入口

每行「标的」列右端有「AI 分析」按钮（`templates/stock_order_list.html`，样式 `.cell-with-action` / `.row-ai`），
点击跳 `/stock/ai/?stock_id=<本行 id>`，直接打开该标的的 AI 分析工作台。

- **不新增列**：该列本来就吸收剩余宽度（`<colgroup>` 里唯一的空 `<col>`），入口放在列右端空档里；
- **宽度**：订单表十列全定宽（标的列 300px，其余 992px），`table.table-orders { min-width: 1292px }`
  等于定宽之和 —— 窗口再窄也只是 `.table-wrap` 横向滚动，**列宽不会反压**；
  另有三层 `min-width: 0` + 名称 `nowrap + ellipsis` 兜超长名称（D-13：靠压缩躲重叠会把名称压到 0 宽）；
- **GET 链接**，不是表单：列表不做任何写入，只是导航；
- 列表侧不预判 AI 启停，未启用时落到 AI 页按既有规则提示并禁用提交。

### 4.3 监控服务模块 (StockMonitor)
**核心功能：**
1. **后台监控线程** - 独立线程持续运行
2. **并发数据获取** - ThreadPoolExecutor (max_workers=6)
3. **雪球数据同步** - 价格/PE/PB实时更新
4. **K线分析** - MA均线计算，金叉/死叉信号识别
5. **告警检测** - 三档位阈值判断
6. **邮件通知** - SMTP邮件发送

**告警触发条件：**
- **价格档位告警**：当前价 <= 第一档/第二档/第三档建仓价
- **卖出告警**：当前价 >= 卖出价位
- **PE告警**：当前PE <= PE阈值档位
- **PB告警**：当前PB <= PB阈值档位
- **指标告警**（006，见 4.4）：**52 周新低 + 52 周回撤 + 20 日跑输 + 5 日倍数四项同时成立**才触发（2026-10-23 起）

**冷却机制：** 价格 / 估值同 key 默认 4 小时（`ALARM_COOLDOWN_SECONDS`）；
**指标类独立 24 小时**（`IND_COOLDOWN_HOURS`），冷却 key 为单值 `indicator:combo`。

### 4.4 指标监控模块（StockIndicator · 006）
**执行顺序**（在 `StockMonitor.check_and_alert` 内）：行情快照 → 回写 PE/PB 与现价 → K 线采集 → **指标采集与判定** → 价格 / 估值告警。
基准指数日线在每轮监控入口 `_maybe_sync_bench()` 同步，每交易日一次。

| 指标 | 类型 | 判定式 | 参数（默认） |
|------|------|--------|--------------|
| 52 周新低 | 长期 | `(现价 − low52w) / low52w ≤ 阈值` | `IND_LOW52W_NEAR_PCT = 5.0` |
| 52 周回撤 | 长期 | `(现价 − high52w) / high52w ≤ −35%` | `IND_DRAWDOWN_52W_PCT = 35` |
| 20 日跑输 | 短期 | `ret20(个股) − ret20(基准) ≤ −15%` | `IND_RS20_PCT = 15` |
| 5 日倍数 | 短期 | 两者均跌，且 `\|ret5股\| ≥ 2.5 × \|ret5基准\|`，且 `\|ret5股\| ≥ 3%`、`\|ret5基准\| ≥ 0.5%` | `IND_RS5_RATIO` / `IND_RS5_MIN_DROP_PCT` / `IND_RS5_MIN_BENCH_DROP_PCT` |

**组合约定（告警口径）**：四条之间是 **AND**，`utils/indicator_rules.is_combo_hit(flags)` 全真才告警，
一次只写一条 `alarm_type='indicator'` / `alarm_subtype='combo'` 的告警并发一封总览邮件（正文列出四项实测值与阈值）。
单条件命中不再单独告警——单条件筛出来的标的太多，不符合策略（见 ADR-004）。
四条 flag 仍逐项落库以便排查，**页面不再展示其命中角标**。

**降级约定**：52 周高低取雪球 `quote_detail`，不自行计算窗口；上市不足 20 个交易日或基准未采集到时，
对应涨跌幅为 NULL，**该指标不参与判定**（组合因此必然不成立，宁可不报，不可误报）；
单只标的异常只记日志计入错误计数，不中断整轮。

**页面与配置入口（批次二）**：
- `/stock/indicator` → `templates/indicator_list.html`：4 个 KPI（监控标的 / 组合命中 / 未采集 / 最新快照）
  + 每标的最新快照表（52 周区间条、回撤、5/20 日收益、**组合信号**列）。只读库、不请求雪球；
  缺数据的单元格渲染「—」「未采集」，**不渲染成 0%**。
- 告警设置「指标告警」页签：6 个阈值字段按长期 / 短期分组，占位提示显示当前全局值，
  **留空写 NULL = 继承全局**；越界 / 非数字不落库。保存后重定向回 `?tab=indicator`。
- 数据访问：`StockIndicator.get_latest_batch()` + `StockIndicatorConfig.get_map()` 两次批量查询（无 N+1）。

### 4.5 AI 个股分析（ai_bp，007）

**定位**：把系统已采集的行情 / 估值 / 指标 / K 线压成一段确定性文本交给 LLM，产出**结构化报告**并留痕。
不抓外部数据、不做投资建议、不接流式输出。

| 路由 | 方法 | 说明 |
|------|------|------|
| `/stock/ai/` | GET | **搜索式工作台**：顶部 hero 搜索框（服务端真搜索）+ 主区「标的条 + 报告（评级大字 + 置信度条 + 维度 chips + 要点 / 支撑 / 风险 / 追问 / 免责声明）」+ 右栏「参数 + 指标快照 + 历史」；**不渲染全量标的列表**，标的由 `?stock_id=` 或搜索确定 |
| `/stock/ai/api/search` | GET | 标的搜索 `?q=`：服务端参数化 `LIKE` 命中名称 / 代码，返回 ≤12 条 `{items:[{id,name,code,price,url}],total,truncated}`；`q` 为空返回空列表 |
| `/stock/ai/analyze` | POST | 生成分析（可带 `model`、`dimensions[]`）→ 落库 → 回跳带 `report_id` |
| `/stock/ai/ask` | POST | 基于最近一次正式分析追问（≤300 字），回答同样落库（`verdict='问答'`） |
| `/stock/ai/config` | POST | 保存参数：开关 / **模型** / **分析维度** / 温度 / 单次上限 / 月度上限 / 引用范围 |
| `/stock/ai/test` | POST | 连通测试（真实请求，`max_output_tokens=16`） |

**模块分层**（改这块前先看这张表，别把逻辑塞进视图）：

| 层 | 文件 | 职责 |
|----|------|------|
| 客户端 | `utils/ai_client.py` | 双风格调用、超时、`{ok,status,...}` 结果、`mask_key()` 脱敏 |
| 提示词 | `utils/ai_prompt.py` | `SYSTEM_PROMPT`、上下文组装（按引用范围裁剪）、JSON 解析与兜底 |
| 模型 | `models/stock_ai.py` | 报告落库/查询/月度计数、参数读写与合并语义 |
| 视图 | `views/ai_analysis.py` | 校验（启用 / 额度 / 长度 / **模型白名单**）→ 调客户端 → 落库 → 重定向 |

**关键约定**：
- 未配置 / 未启用 → `status='disabled'`，页面只显示原因且**会发请求**的按钮 `disabled`（保存参数仍可点），**不抛异常**；
- 超时 → `status='timeout'`；接口错 / 返回非 JSON / 正文为空 → `status='error'`，都 `logger.exception`；
- 模型返回不是合法 JSON → 退化为「未知评级 + 原文摘要」并标注，**报告不丢**；
- 免责声明以 `ai_prompt.DISCLAIMER` 为准（模型改写无效）；
- `AI_API_KEY` 只在环境变量，页面只显示 `sk-***ab` 这类脱敏值；
- **模型**：候选 = `AI_MODEL` + `AI_MODELS`（两个变量**都**按逗号 / 分号拆分，`AI_MODEL` 第一项排最前且是默认模型），
  `analyze` / `ask` / `config` 都做白名单校验，选中模型随请求下发并落库 `stock_ai_report.model`；
  清单**不校验网关是否真支持**，靠「连通测试」暴露；真正发出去的永远是**单个** ID（`default_model()`）；
- **分析维度**（`models/stock_ai.DIMENSIONS`）：`valuation` 估值 / `technical` 技术面 / `relative` 相对强弱 /
  `position` 52 周位置 / `risk` 风险。**每维都必须有本地数据支撑**，设计稿的「基本面 / 消息面」不提供；
  维度以中文标签进提示词（每维至少一条结论、缺数据就写「数据不足」），并落库 `content_json.dimensions`；
- **标的搜索**在前端：`initTextFilters`（`theme.js`）按 `data-search`（名称 + 代码小写）即时过滤，不发请求、
  不改 URL；只覆盖页面已加载的前 200 只。

**真实环境验证（2026-10-22）**：已在 OpenAI 兼容网关（`responses` 与 `chat` 两种风格）实跑
连通测试、正式分析、追问与超时失败路径；单次输出 3k+ tokens 的**推理型模型建议把 `AI_TIMEOUT` 调到 120~180**。

### 4.6 K线信号分析
**信号判断逻辑：**
```python
# 金叉：MA5 > MA30 * 1.03 (MA5明显高于MA30)
if ma5 > ma30 * 1.03:
    return 'golden_cross'

# 死叉：MA5 < MA30 * 0.97 (MA5明显低于MA30)  
elif ma5 < ma30 * 0.97:
    return 'death_cross'

# 震荡：其他情况
else:
    return 'normal'
```

---

## 5. API接口文档

### 5.1 K线数据接口
**URL:** `/stock/api/kline/<stock_id>`
**方法:** GET
**认证:** 需要登录

**响应示例：**
```json
{
  "success": true,
  "klines": [
    {
      "trade_date": "2024-01-15",
      "close_price": 15.32,
      "ma5": 15.10,
      "ma10": 14.85,
      "ma30": 14.50,
      "signal_type": "golden_cross"
    }
  ]
}
```

---

## 6. 配置说明

### 6.1 环境变量清单（config.py 读取）

> 所有敏感项一律从环境变量读取，`config.py` 内**不得出现明文凭据**；示例一律占位符。
> 开发时把根目录 `.env.example` 复制为 `.env` 后填写（`.env` 已被 `.gitignore` 排除）。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| **必填** `MYSQL_PASSWORD` | 数据库密码 | 无（缺失即启动报错） |
| **必填** `SECRET_KEY` | Flask 会话密钥 | 无 |
| **必填** `XUEQIU_TOKEN` | 雪球行情 Token | 无 |
| **必填** `MAIL_USERNAME` / `MAIL_PASSWORD` | 发件邮箱与 SMTP 授权码 | 无 |
| **必填** `ALARM_RECIPIENTS` | 告警收件人，逗号分隔 | 无 |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_DATABASE` | 数据库连接信息 | `127.0.0.1` / `3306` / `root` / `stockdb` |
| `FLASK_DEBUG` / `FLASK_HOST` / `FLASK_PORT` | Flask 运行参数 | `0` / `0.0.0.0` / `5000` |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USE_SSL` / `MAIL_TIMEOUT` | SMTP 参数 | `smtp.qq.com` / `465` / `1` / `10` |
| `ALARM_COOLDOWN_SECONDS` | 价格 / 估值告警冷却秒数 | `14400`（4 小时） |
| `MONITOR_ENABLED` / `MONITOR_MAX_WORKERS` / `MONITOR_MAX_STOCKS` | 监控线程参数 | `1` / `6` / `100` |
| `MONITOR_OFF_HOURS_SLEEP` / `MONITOR_ERROR_SLEEP` | 非交易时段 / 异常退避秒数 | `300` / `5` |
| `FETCH_MIN_DELAY` / `FETCH_MAX_DELAY` | 行情拉取节流区间（秒） | `30` / `300` |
| `IND_ENABLED` | 指标监控总开关（006） | `1` |
| `IND_BENCH` | 相对强弱基准指数（006） | `SH000300`（沪深300） |
| `IND_LOW52W_NEAR_PCT` | 距 52 周最低 ≤ 该百分比即告警（006） | `5.0` |
| `IND_DRAWDOWN_52W_PCT` | 52 周回撤达到该百分比即告警（006） | `35.0` |
| `IND_RS20_PCT` | 20 日跑输基准的百分点（006） | `15.0` |
| `IND_RS5_RATIO` | 5 日跌幅达基准的倍数（006） | `2.5` |
| `IND_RS5_MIN_DROP_PCT` / `IND_RS5_MIN_BENCH_DROP_PCT` | 5 日倍数护栏：个股 / 基准最小跌幅（006） | `3.0` / `0.5` |
| `IND_COOLDOWN_HOURS` | 指标类告警冷却小时数（006） | `24` |
| `IND_BENCH_WINDOW_DAYS` | 基准日线采集窗口（自然日，006） | `40` |
| `AI_ENABLED` | AI 分析总开关（007） | `0`（默认关闭） |
| `AI_API_BASE` | OpenAI 兼容接口 Base URL，末尾不带斜杠（007） | 无 |
| `AI_MODEL` | 默认模型：单个 ID 或逗号 / 分号分隔清单（**第一项 = 默认**）（007） | 无 |
| `AI_MODELS` | 可选模型清单，逗号 / 分号分隔（007）；推荐把候选放这里 | 无 |
| `AI_API_KEY` | **仅环境变量**，不入库 / 不回显 / 不写日志（007） | 无 |
| `AI_API_STYLE` | `responses` 或 `chat`（兼容自建网关，007） | `responses` |
| `AI_TEMPERATURE` / `AI_MAX_TOKENS` | 采样温度 / 单次输出上限（007） | `0.6` / `1200` |
| `AI_MONTHLY_LIMIT` | 月度调用上限，达限拒绝（0 = 不限，007） | `200` |
| `AI_TIMEOUT` | 外部调用超时秒数（必传，007）；**推理型模型建议 120~180** | `60` |

> 说明：`IND_*` 为全局默认值，可按标的在 `stock_indicator_config` 中覆盖（字段留空即继承）。

### 6.2 生产环境配置建议
1. **数据库**：修改为生产环境MySQL地址
2. **SECRET_KEY**：生成强随机密钥
3. **邮件配置**：使用企业邮箱服务
4. **雪球Token**：更新有效Token
5. **日志级别**：设置INFO/WARNING

---

## 7. 部署指南

### 7.1 环境准备
```bash
# 1. 确认 Python 3.12（numpy 2.5 / pandas 3.1 的最低要求；旧组合已在 2026-10-27 对齐）
python --version

# 2. 创建虚拟环境（本机已自带 stockvenv，可直接用）
python -m venv stockvenv
source stockvenv/bin/activate  # Linux
stockvenv\Scripts\activate     # Windows

# 3. 安装依赖
pip install -r requirements.txt
```

### 7.2 数据库初始化
```bash
# 运行database.py初始化表结构
python database.py
```

### 7.3 启动应用

**必须单进程运行**（`gunicorn.conf.py` 已写死 `workers = 1`）：告警冷却（`utils/alarm_throttle`）、
运行时 AI 密钥、后台监控线程都是**进程内内存状态**，多进程会让冷却失效、雪球请求翻倍，
且每个进程各起一个监控线程。并发靠 gthread 线程池（默认 8）。

```bash
# 生产（推荐）：访问日志 / 错误日志 / 应用日志全部打到终端
cd /opt/src/flask-stock
./stockvenv/bin/gunicorn -c gunicorn.conf.py app:app     # 已装好依赖的虚拟环境
# 或直接用 PATH 里的解释器
gunicorn -c gunicorn.conf.py app:app

# 常用覆盖
BIND=0.0.0.0:8000 LOG_LEVEL=DEBUG GUNICORN_THREADS=16 gunicorn -c gunicorn.conf.py app:app

# 容器 / 服务化入口（等数据库就绪 → 建表 → exec gunicorn）
chmod +x start.sh
./start.sh
USE_GUNICORN=0 ./start.sh     # 排障时退回开发服务器

# 开发模式
python app.py
```

> gunicorn 只做 `import app`，不会执行 `app.py` 的 `__main__` 块；
> 监控线程等运行时副作用统一收在 `app.prepare_runtime()`，由 `post_fork` 钩子调用。

### 7.4 Docker部署 (推荐)
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
# 日志不再重定向到文件，直接进容器输出，方便 docker logs 查看
CMD ["/bin/sh", "-c", "mkdir -p /app/logs && exec /app/start.sh"]
```

```bash
docker build -t flask-stock .
docker run -d -p 5000:5000 --name stock-monitor flask-stock
```

### 7.5 常见问题排查

#### pandas/numpy版本冲突

> **本机唯一受支持的解释器是项目根目录下的 `stockvenv/`**（Python 3.12 + numpy 2.5.4 + pandas 3.1.0，
> 与 `requirements.txt` 完全对齐）：**开发与跑测试都请用 `./stockvenv/bin/python`**。
> `requirements.txt` 里原本锁的 numpy 1.24.3 / pandas 2.0.3 是 Python 3.9 时代的组合，
> 在 3.12 上无预编译 wheel，会退回源码编译并失败；2026-10-27 已对齐到实际安装版本。
> 若用其他解释器，混装 numpy 2.x 与 pandas 1.x 系编译版本会报
> `ValueError: numpy.dtype size changed, may indicate binary incompatibility`。

```bash
# 重建一版干净环境（仅供参考；勿改动 stockvenv/ 的内容）
python -m venv stockvenv
./stockvenv/bin/python -m pip install -r requirements.txt
```

#### 数据库连接问题
- 检查MySQL服务状态
- 验证用户名/密码/端口
- 确认数据库已创建

#### gunicorn 启动后看不到应用日志
现象：容器/终端里只有 `[INFO] Booting worker`，之后一行应用日志都没有。
排查顺序：
1. 是否用 `gunicorn -c gunicorn.conf.py app:app` 启动？直接 `gunicorn app:app` 不会执行 `app.py` 的
   `__main__`，监控线程根本没起来（也就没有持续日志）；
2. 级别是不是 INFO：监控"在干活"的日志多是 `DEBUG`，临时用 `LOG_LEVEL=DEBUG` 看一轮；
3. 是否还有校验失败导致 worker 反复重启：`prepare_runtime(strict=True)` 缺配置会抛错，看 error log 第一行；
4. 日志仍会落盘到项目根目录下的 `logs/stock_app.log`（可用 `LOG_DIR` 改位置）。

#### 雪球Token失效
- 登录雪球网站获取新Token
- 更新config.py中的xueQiutoken

---

## 8. 使用指南

### 8.1 添加监控股票
1. 点击「添加订单」按钮
2. 填写股票名称、代码(如SZ002027)
3. 设置PE/PB目标值
4. 设置建仓档位价格
5. 设置卖出价位
6. 点击保存

### 8.2 设置告警阈值
1. 在订单列表点击告警图标(铃铛)
2. 进入告警设置页面
3. 配置各档位阈值：
   - **价格档位**：三档建仓价位
   - **PE档位**：三档PE阈值
   - **PB档位**：三档PB阈值
   - **指标告警**：52 周新低 / 回撤、20 日跑输、5 日倍数与两道护栏；**留空 = 继承全局 `IND_*`**
4. 保存设置（保存指标阈值后仍停留在「指标告警」页签）

### 8.3 查看告警历史
1. 导航栏点击「告警历史」
2. 可按日期/关键词筛选
3. 查看历史告警记录

### 8.4 查看指标监控
1. 导航栏点击「指标监控」（`/stock/indicator`）
2. 顶部 4 个 KPI：监控标的 / 长期命中 / 短期命中 / 最新快照日期
3. 表格按标的展示 52 周区间位置、回撤、5 / 20 日收益与四类指标徽标
4. 「—」「未采集」表示该指标缺数据、**不参与判定**，不是 0%

### 8.5 K线信号解读
| 信号 | 图标 | 含义 |
|------|------|------|
| 金叉 | 黄色向上箭头 | MA5上穿MA30，看涨信号 |
| 死叉 | 红色向下箭头 | MA5下穿MA30，看跌信号 |
| 震荡 | 灰色横线 | 均线缠绕，趋势不明 |

### 8.6 AI 个股分析
1. 先在 `.env` 配置 `AI_ENABLED=1`、`AI_API_BASE`、`AI_MODEL`、`AI_API_KEY`（密钥只在环境变量）；
   想把多个模型放进下拉就填 `AI_MODELS=qwen3.5-plus,gpt-4o-mini`（推荐）；
   直接把清单填进 `AI_MODEL` 也可以，会按逗号 / 分号拆分，**第一项是默认模型**
2. 入口二选一：导航栏「AI 分析」→ 在**顶部搜索框**输入名称或代码（服务端真搜索，下拉可选）；
   或直接在**订单列表**点该行「标的」列右端的「AI 分析」按钮直达（`/stock/ai/?stock_id=<id>`）。
   页面不铺标的列表，未选标的时显示能力卡片与「最近分析」
3. 右栏「分析参数」选**模型**（候选来自 `AI_MODEL` + `AI_MODELS`）、勾**分析维度**（估值 / 技术面 / 相对强弱 / 52 周位置 / 风险）
4. 点「连通测试」确认配置可用（会消耗极少量 Token）
5. 点「生成分析」：报告含评级（五档）、置信度、**本次维度 chips**、核心结论、关键要点、支撑依据、风险与免责声明
6. 可在「追问」里就最近一次分析继续提问；问答同样落库并计入月度额度
7. 「保存参数」把模型 / 维度 / 温度 / 单次上限 / 月度上限 / 引用范围存为默认（未勾选的数据段不进提示词）

> 未启用时页面只显示原因并禁用「生成 / 追问 / 连通测试」（保存参数仍可点）；`AI_API_KEY` 只显示 `sk-***ab` 这类脱敏值。

---

## 9. 扩展开发(暂时不需要添加扩展组件)

### 9.1 添加新数据源
可扩展支持其他财经API：
- 东方财富API
- 同花顺API
- 腾讯财经API

### 9.2 增强告警方式
当前支持邮件告警，可扩展：
- 微信通知 (企业微信机器人)
- 钉钉通知
- SMS短信通知
- Webhook推送

### 9.3 技术指标扩展
当前支持MA均线，可添加：
- MACD指标
- KDJ指标
- RSI指标
- BOLL布林带

---

## 10. 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v1.0 | 2023 | 基础订单管理功能 |
| v1.1 | 2023 | 添加PE/PB告警 |
| v1.2 | 2023 | 添加K线数据采集 |
| v1.3 | 2023 | 均线信号分析功能 |
| v1.4 | 2024 | 实时告警状态判断优化 |

---

## 11. 联系与支持

- **项目路径**：`D:\flask-stock`
- **技术支持**：请提交Issue或联系开发团队

---

*文档生成日期：2026年4月24日*