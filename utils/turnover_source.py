# -*- coding: utf-8 -*-
"""
市场成交额数据源（009 市场成交额）。

采集逻辑复用 `example/fetch_turnover.py`（用户已实测验证）：
- 主源：东方财富 push2his 历史行情接口；
- 备源：腾讯 newfqkline 历史行情接口，主源异常（条数不足 / 数据过旧 / 网络错误）自动切换。

统计口径（与 example 完全一致，取舍见 spec/decisions/006-turnover-source-and-caliber.md）：
- 沪市 = 上证指数（东财 1.000001 / 腾讯 sh000001）；
- 深市 = 深证成指（0.399001 / sz399001）——两个数据源该指数的成交额字段即**全市场口径**；
- 北证 = 北证50（0.899050 / bj899050），2022-04-29 发布前无指数级成交额，对应日期留 None；
- 合计 = 三市之和（缺失按 0），不含基金、债券。

本模块只负责「取数 + 校验 + 组装行」，**不落库**；入库与备源写入保护在
`models/market_turnover.py`。urllib 标准库实现，无新依赖、无需 Token。

2026-11-13 增量改造（ADR-008）：`fetch_all(source, since=...)` 支持增量取数——
since 为库内最新交易日时只取最近约 60 个交易日（东财动态 beg / 北证 lmt / 腾讯 count 单页），
校验走 `validate_recent`；since=None 保持全量行为与校验不变。
"""
import json
import logging
import urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

FIRST_TRADE_DATE = "1990-12-19"
BSE_FIRST_DATE = "2022-04-29"

EASTMONEY_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?klt=101&fqt=1&beg=19900101&end=20500101"
    "&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f56,f57&secid="
)
# 北证50 用 beg 参数会被服务端断开，改用 lmt 取全部历史
EASTMONEY_BSE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?klt=101&fqt=1&lmt=100000&end=20500101"
    "&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f56,f57&secid=0.899050"
)
TENCENT_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param="
TENCENT_PAGE_SIZE = 2000
TENCENT_MAX_PAGES = 20

SOURCE_EASTMONEY = "东方财富"
SOURCE_TENCENT = "腾讯行情"
SOURCE_CHOICES = ("auto", "eastmoney", "tencent")

# 备源写入保护窗口（交易日）：腾讯早年历史与东财口径差异大，
# 库非空时备源只覆盖最近 N 个交易日（对齐 example write_csv 的 protect 语义）
BACKUP_PROTECT_DAYS = 60

# 增量同步窗口（2026-11-13，ADR-008）：与备源保护同值——日常同步只取/只写最近约 60 个交易日
INCREMENTAL_DAYS = BACKUP_PROTECT_DAYS
# 东财 beg 的自然日回看量：60 交易日 ≈ 84 自然日，再留节假日缓冲
INCREMENTAL_LOOKBACK_DAYS = 100
# 库内最新日期距今超过该自然日数 → 增量窗口盖不住缺口，回退全量（编排层判定）
INCREMENTAL_MAX_GAP_DAYS = 100


def http_json(url, headers=None, timeout=30):
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------- 主源：东方财富 ----------------

def parse_eastmoney_klines(url):
    """把东财 klines 转成 {交易日: 成交额(元)}"""
    payload = http_json(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        raise RuntimeError("东财接口未返回数据：" + url.split("secid=")[-1])
    return {line.split(",")[0]: float(line.split(",")[2]) for line in klines}


def _incremental_params(since):
    """把库内最新交易日换算成增量取数参数：(东财 beg, 北证/腾讯条数)。

    beg 前推 100 自然日（≈60 交易日 + 节假日缓冲）；条数 N=max(60, 缺口自然日+10)，
    保证几天没同步 / 长假时缺口仍被窗口覆盖（缺口 >100 自然日由编排层回退全量）。
    """
    since_dt = datetime.strptime(since, "%Y-%m-%d")
    beg = (since_dt - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)).strftime("%Y%m%d")
    gap = (datetime.now() - since_dt).days
    count = max(INCREMENTAL_DAYS, gap + 10)
    return beg, count


def fetch_eastmoney(since=None):
    """返回 (沪市, 深市, 北证)，值均为 {交易日: 成交额(元)}。

    since=None 全量（beg=19900101 / 北证 lmt=100000）；
    since='YYYY-MM-DD'（库内最新交易日）增量：沪深 beg 前推回看量、北证 lmt=N。
    """
    if since is None:
        sh_url = EASTMONEY_URL + "1.000001"
        sz_url = EASTMONEY_URL + "0.399001"
        bj_url = EASTMONEY_BSE_URL
    else:
        beg, count = _incremental_params(since)
        sh_url = EASTMONEY_URL.replace("beg=19900101", "beg=" + beg) + "1.000001"
        sz_url = EASTMONEY_URL.replace("beg=19900101", "beg=" + beg) + "0.399001"
        bj_url = EASTMONEY_BSE_URL.replace("lmt=100000", "lmt=%d" % count)
    shanghai = parse_eastmoney_klines(sh_url)
    shenzhen = parse_eastmoney_klines(sz_url)
    beijing = parse_eastmoney_klines(bj_url)
    return shanghai, shenzhen, beijing


# ---------------- 备源：腾讯 ----------------

def fetch_tencent_one(secid, count=None):
    """向前翻页取全历史，返回 {交易日: 成交额(元)}；count 给定时只取最近 count 条（单页，增量用）。"""
    result = {}
    end_date = ""
    pages = 1 if count is not None else TENCENT_MAX_PAGES
    page_size = count if count is not None else TENCENT_PAGE_SIZE
    for _ in range(pages):
        url = TENCENT_URL + "%s,day,,%s,%d,qfq" % (secid, end_date, page_size)
        payload = http_json(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        node = (payload.get("data") or {}).get(secid) or {}
        rows = node.get("qfqday") or node.get("day") or []
        if not rows:
            break

        for row in rows:
            # 第 9 个字段是成交额，单位万元
            if len(row) > 8 and row[8] not in ("", None):
                result[row[0]] = float(row[8]) * 1e4

        if count is not None:
            break  # 增量单页即返，不向前翻页
        earliest = min(row[0] for row in rows)
        if earliest <= FIRST_TRADE_DATE:
            break
        end_date = (datetime.strptime(earliest, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        if end_date < FIRST_TRADE_DATE:
            break

    return result


def fetch_tencent(since=None):
    """返回 (沪市, 深市, 北证)，值均为 {交易日: 成交额(元)}；since 给定走增量单页。"""
    count = None if since is None else _incremental_params(since)[1]
    return (
        fetch_tencent_one("sh000001", count),
        fetch_tencent_one("sz399001", count),
        fetch_tencent_one("bj899050", count),
    )


# ---------------- 校验与组装 ----------------

def validate(shanghai, shenzhen, beijing):
    """数据量或新鲜度不达标就判定该源不可用"""
    for name, data in (("沪市", shanghai), ("深市", shenzhen)):
        if len(data) < 8000:
            raise RuntimeError("%s数据条数异常：%d" % (name, len(data)))
    if len(beijing) < 500:
        raise RuntimeError("北证数据条数异常：%d" % len(beijing))
    latest = max(shanghai)
    gap = (datetime.now() - datetime.strptime(latest, "%Y-%m-%d")).days
    if gap > 10:
        raise RuntimeError("数据过旧，最新日期：%s" % latest)


def validate_recent(shanghai, shenzhen, beijing, since):
    """增量校验：三市各 ≥1 条、沪市最新距今 ≤10 天、源最新 ≥ 库最新、窗口覆盖库最新日期。"""
    for name, data in (("沪市", shanghai), ("深市", shenzhen), ("北证", beijing)):
        if not data:
            raise RuntimeError("%s增量数据为空" % name)
    latest = max(shanghai)
    gap = (datetime.now() - datetime.strptime(latest, "%Y-%m-%d")).days
    if gap > 10:
        raise RuntimeError("数据过旧，最新日期：%s" % latest)
    if latest < since:
        raise RuntimeError("数据源最新日期 %s 早于库内最新日期 %s" % (latest, since))
    if min(shanghai) > since:
        raise RuntimeError("增量窗口未覆盖库内最新日期：%s" % since)


def _validate(shanghai, shenzhen, beijing, since):
    """按取数模式分流校验：全量 validate / 增量 validate_recent。"""
    if since is None:
        validate(shanghai, shenzhen, beijing)
    else:
        validate_recent(shanghai, shenzhen, beijing, since)


def all_dates(shanghai, shenzhen, beijing):
    return sorted(set(shanghai) | set(shenzhen) | set(beijing))


def fetch_all(source="auto", since=None):
    """
    按指定数据源取数并校验。

    :param source: auto（东财优先失败切腾讯）/ eastmoney / tencent
    :param since: None 全量；'YYYY-MM-DD'（库内最新交易日）增量，只取最近约 60 个交易日
    :return: (沪市, 深市, 北证, 数据源中文名)，前三个值均为 {交易日: 成交额(元)}
    :raises ValueError: source 非法
    :raises RuntimeError: 取数失败或校验不通过（auto 模式两源都失败时）
    """
    if source not in SOURCE_CHOICES:
        raise ValueError("未知数据源：%s（可选 %s）" % (source, "/".join(SOURCE_CHOICES)))

    if source == "tencent":
        shanghai, shenzhen, beijing = fetch_tencent(since)
        label = SOURCE_TENCENT
    elif source == "eastmoney":
        shanghai, shenzhen, beijing = fetch_eastmoney(since)
        label = SOURCE_EASTMONEY
    else:
        try:
            shanghai, shenzhen, beijing = fetch_eastmoney(since)
            _validate(shanghai, shenzhen, beijing, since)
            label = SOURCE_EASTMONEY
        except Exception as error:
            logger.warning("主源东方财富不可用：%s；切换到备用源腾讯行情", error)
            shanghai, shenzhen, beijing = fetch_tencent(since)
            label = SOURCE_TENCENT

    _validate(shanghai, shenzhen, beijing, since)
    return shanghai, shenzhen, beijing, label


def build_rows(shanghai, shenzhen, beijing):
    """
    把三市 {交易日: 成交额(元)} 组装成入库行（单位**亿元**，4 位小数，与 CSV 一致）。

    缺失值保留 None（北证早期 / 深市 1991-07 前），合计按缺失为 0 求和——
    与 example write_csv 的口径逐一对应，绝不把「没采到」伪造成 0。
    """
    rows = []
    for day in all_dates(shanghai, shenzhen, beijing):
        sh = shanghai.get(day)
        sz = shenzhen.get(day)
        bj = beijing.get(day)
        total = (sh or 0.0) + (sz or 0.0) + (bj or 0.0)
        rows.append({
            "trade_date": day,
            "sh_amount": None if sh is None else round(sh / 1e8, 4),
            "sz_amount": None if sz is None else round(sz / 1e8, 4),
            "bj_amount": None if bj is None else round(bj / 1e8, 4),
            "total_amount": round(total / 1e8, 4),
        })
    return rows