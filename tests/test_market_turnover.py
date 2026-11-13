# -*- coding: utf-8 -*-
"""
009 市场成交额：纯逻辑单测（不连数据库、不打真实接口）。

运行：python -m unittest tests.test_market_turnover -v

mock 只用于编排逻辑（auto 降级 / 备源 60 日保护 / 增量编排）与取数 URL 断言，
且返回值类型与真实函数一致（{日期: 成交额(元)} dict / 入库行 dict），不复刻接口内部结构。
"""
import datetime
import os
import tempfile
import unittest
from unittest import mock

from models.market_turnover import (
    CSV_COLUMNS,
    MarketDailyTurnover,
    dashboard_payload,
    parse_csv_rows,
)
from utils import turnover_source


def _make_series(n, end=None):
    """构造 n 条 {日期: 成交额(元)}，最新日期为 end（默认今天），供 validate 通过。"""
    end = end or datetime.date.today()
    return {(end - datetime.timedelta(days=i)).isoformat(): 1e10 + i for i in range(n)}


def _valid_data():
    """能通过 validate 的三市数据（沪/深 8100 条、北证 600 条、最新今天）。"""
    return _make_series(8100), _make_series(8100), _make_series(600)


class BuildRowsTest(unittest.TestCase):
    def test_unit_conversion_and_missing(self):
        sh = {'1990-12-19': 1.23e8, '2026-11-11': 8574.123456e8}
        sz = {'2026-11-11': 10234.5678e8}
        bj = {'2026-11-11': 123.45e8}
        rows = turnover_source.build_rows(sh, sz, bj)
        self.assertEqual([r['trade_date'] for r in rows], ['1990-12-19', '2026-11-11'])
        first, last = rows
        # 早期：深/北缺失保留 None，合计缺失按 0，绝不伪造 0
        self.assertEqual(first['sh_amount'], 1.23)
        self.assertIsNone(first['sz_amount'])
        self.assertIsNone(first['bj_amount'])
        self.assertEqual(first['total_amount'], 1.23)
        # 单位元 → 亿元，4 位小数
        self.assertEqual(last['sh_amount'], 8574.1235)
        self.assertEqual(last['sz_amount'], 10234.5678)
        self.assertEqual(last['bj_amount'], 123.45)
        self.assertEqual(last['total_amount'], round(8574.123456 + 10234.5678 + 123.45, 4))

    def test_empty(self):
        self.assertEqual(turnover_source.build_rows({}, {}, {}), [])


class ValidateTest(unittest.TestCase):
    def test_pass(self):
        turnover_source.validate(*_valid_data())  # 不抛即通过

    def test_too_few_sh(self):
        sh, sz, bj = _valid_data()
        with self.assertRaises(RuntimeError):
            turnover_source.validate(dict(list(sh.items())[:100]), sz, bj)

    def test_too_few_bj(self):
        sh, sz, bj = _valid_data()
        with self.assertRaises(RuntimeError):
            turnover_source.validate(sh, sz, dict(list(bj.items())[:10]))

    def test_stale(self):
        old = datetime.date.today() - datetime.timedelta(days=30)
        with self.assertRaises(RuntimeError):
            turnover_source.validate(_make_series(8100, old), _make_series(8100, old), _make_series(600, old))


class FetchAllTest(unittest.TestCase):
    def test_invalid_source(self):
        with self.assertRaises(ValueError):
            turnover_source.fetch_all('sina')

    def test_auto_fallback_to_tencent(self):
        sh, sz, bj = _valid_data()
        with mock.patch.object(turnover_source, 'fetch_eastmoney', side_effect=RuntimeError('网络不可达')), \
                mock.patch.object(turnover_source, 'fetch_tencent', return_value=(sh, sz, bj)) as tencent:
            result = turnover_source.fetch_all('auto')
        self.assertEqual(result[3], turnover_source.SOURCE_TENCENT)
        tencent.assert_called_once()
        self.assertIs(result[0], sh)

    def test_auto_primary_ok(self):
        sh, sz, bj = _valid_data()
        with mock.patch.object(turnover_source, 'fetch_eastmoney', return_value=(sh, sz, bj)), \
                mock.patch.object(turnover_source, 'fetch_tencent') as tencent:
            result = turnover_source.fetch_all('auto')
        self.assertEqual(result[3], turnover_source.SOURCE_EASTMONEY)
        tencent.assert_not_called()

    def test_explicit_tencent_skips_eastmoney(self):
        sh, sz, bj = _valid_data()
        with mock.patch.object(turnover_source, 'fetch_eastmoney') as eastmoney, \
                mock.patch.object(turnover_source, 'fetch_tencent', return_value=(sh, sz, bj)):
            result = turnover_source.fetch_all('tencent')
        self.assertEqual(result[3], turnover_source.SOURCE_TENCENT)
        eastmoney.assert_not_called()

    def test_auto_fallback_passes_since(self):
        # 增量模式下 auto 降级编排不变：since 透传两源，校验走 validate_recent
        since = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        data = (_make_series(10), _make_series(10), _make_series(10))
        with mock.patch.object(turnover_source, 'fetch_eastmoney', side_effect=RuntimeError('不可达')) as em, \
                mock.patch.object(turnover_source, 'fetch_tencent', return_value=data) as tx:
            result = turnover_source.fetch_all('auto', since=since)
        self.assertEqual(result[3], turnover_source.SOURCE_TENCENT)
        em.assert_called_once_with(since)
        tx.assert_called_once_with(since)


class ParseCsvTest(unittest.TestCase):
    HEADER = ','.join(CSV_COLUMNS)

    def _write(self, *lines):
        fp = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, encoding='utf-8')
        fp.write('\n'.join(lines))
        fp.close()
        self.addCleanup(os.unlink, fp.name)
        return fp.name

    def test_valid_with_missing_bj(self):
        path = self._write(
            self.HEADER,
            '2026-11-10,8000.1234,9000.5678,100.0000,17100.6912',
            '2026-11-11,8100.0000,9100.0000,,17200.0000',
        )
        rows = parse_csv_rows(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['sh_amount'], 8000.1234)
        self.assertEqual(rows[0]['total_amount'], 17100.6912)
        self.assertIsNone(rows[1]['bj_amount'])
        self.assertEqual(rows[1]['total_amount'], 17200.0)

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            parse_csv_rows('/nonexistent/turnover.csv')

    def test_bad_header(self):
        path = self._write('日期,沪市,深市,北证,合计', '2026-11-11,1,2,3,6')
        with self.assertRaises(ValueError):
            parse_csv_rows(path)

    def test_bad_date(self):
        path = self._write(self.HEADER, '2026/11/11,1,2,3,6')
        with self.assertRaises(ValueError):
            parse_csv_rows(path)

    def test_duplicate_date(self):
        path = self._write(self.HEADER, '2026-11-11,1,2,3,6', '2026-11-11,1,2,3,6')
        with self.assertRaises(ValueError):
            parse_csv_rows(path)

    def test_negative(self):
        path = self._write(self.HEADER, '2026-11-11,-1,2,3,4')
        with self.assertRaises(ValueError):
            parse_csv_rows(path)

    def test_non_numeric(self):
        path = self._write(self.HEADER, '2026-11-11,abc,2,3,6')
        with self.assertRaises(ValueError):
            parse_csv_rows(path)

    def test_total_mismatch(self):
        path = self._write(self.HEADER, '2026-11-11,1,2,3,999')
        with self.assertRaises(ValueError):
            parse_csv_rows(path)

    def test_total_within_tolerance(self):
        # 四位小数舍入造成的 0.0001 差异应放行
        path = self._write(self.HEADER, '2026-11-11,1.0000,2.0000,3.0000,6.0001')
        rows = parse_csv_rows(path)
        self.assertEqual(rows[0]['total_amount'], 6.0001)

    def test_header_only(self):
        path = self._write(self.HEADER)
        with self.assertRaises(ValueError):
            parse_csv_rows(path)


class DashboardPayloadTest(unittest.TestCase):
    ROWS = [
        {'trade_date': '2026-11-10', 'sh_amount': 8000.0, 'sz_amount': 9000.0,
         'bj_amount': None, 'total_amount': 17000.0, 'source': 'CSV导入'},
        {'trade_date': datetime.date(2026, 11, 11), 'sh_amount': 8100.0, 'sz_amount': 9100.0,
         'bj_amount': 100.0, 'total_amount': 17300.0, 'source': '腾讯行情'},
        {'trade_date': '2026-11-12', 'sh_amount': 7500.0, 'sz_amount': 8500.0,
         'bj_amount': 90.0, 'total_amount': 16090.0, 'source': '腾讯行情'},
    ]

    def test_empty(self):
        self.assertIsNone(dashboard_payload([]))

    def test_stats_and_history(self):
        payload = dashboard_payload(self.ROWS, updated_at='2026-11-12 15:00:00')
        self.assertEqual(payload['updated_at'], '2026-11-12 15:00:00')
        self.assertEqual(payload['source'], '腾讯行情')
        self.assertEqual(payload['latest'], {
            'date': '2026-11-12', 'sh': 7500.0, 'sz': 8500.0, 'bj': 90.0, 'total': 16090.0,
        })
        stats = payload['stats']
        self.assertEqual(stats['rank'], 3)          # 17000 / 17300 都比 16090 大
        self.assertEqual(stats['days'], 3)
        self.assertEqual(stats['peak_date'], '2026-11-11')
        self.assertEqual(stats['peak_total'], 17300.0)
        self.assertEqual(stats['avg20'], round((17000 + 17300 + 16090) / 3, 2))
        # date 对象统一转 YYYY-MM-DD；缺失保留 None；展示值 round 2
        self.assertEqual(payload['history'][0], ['2026-11-10', 8000.0, 9000.0, None, 17000.0])
        self.assertEqual(payload['history'][1][0], '2026-11-11')


class SyncProtectionTest(unittest.TestCase):
    """备源 60 日写入保护（mock 仅替换取数与落库，返回类型与真实一致）。

    get_latest=None 走全量路径——保护语义只在全量 + 备源 + 库非空时生效（ADR-008）。
    """

    def _sync(self, source_label, existing_count):
        sh, sz, bj = _valid_data()
        with mock.patch.object(MarketDailyTurnover, 'get_latest', return_value=None), \
                mock.patch.object(turnover_source, 'fetch_all', return_value=(sh, sz, bj, source_label)), \
                mock.patch.object(MarketDailyTurnover, 'count', return_value=existing_count), \
                mock.patch.object(MarketDailyTurnover, 'upsert_rows', return_value=0) as upsert:
            summary = MarketDailyTurnover.sync_from_source('auto')
        return summary, upsert

    def test_tencent_with_existing_protects(self):
        summary, upsert = self._sync(turnover_source.SOURCE_TENCENT, existing_count=100)
        rows = upsert.call_args[0][0]
        self.assertEqual(len(rows), turnover_source.BACKUP_PROTECT_DAYS)
        self.assertEqual(summary['protected_before'], rows[0]['trade_date'])
        self.assertEqual(upsert.call_args[0][1], turnover_source.SOURCE_TENCENT)

    def test_tencent_empty_db_full_write(self):
        summary, upsert = self._sync(turnover_source.SOURCE_TENCENT, existing_count=0)
        rows = upsert.call_args[0][0]
        self.assertGreater(len(rows), turnover_source.BACKUP_PROTECT_DAYS)
        self.assertIsNone(summary['protected_before'])
        self.assertEqual(summary['mode'], 'full')

    def test_eastmoney_no_protection(self):
        summary, upsert = self._sync(turnover_source.SOURCE_EASTMONEY, existing_count=100)
        rows = upsert.call_args[0][0]
        self.assertGreater(len(rows), turnover_source.BACKUP_PROTECT_DAYS)
        self.assertIsNone(summary['protected_before'])


class IncrementalParamsTest(unittest.TestCase):
    """增量参数换算（ADR-008）：beg 前推 100 自然日，条数 N=max(60, 缺口自然日+10)。"""

    def test_recent_since(self):
        today = datetime.date.today()
        beg, count = turnover_source._incremental_params(today.isoformat())
        self.assertEqual(beg, (today - datetime.timedelta(days=100)).strftime('%Y%m%d'))
        self.assertEqual(count, turnover_source.INCREMENTAL_DAYS)

    def test_gap_widens_count(self):
        since = (datetime.date.today() - datetime.timedelta(days=95)).isoformat()
        _, count = turnover_source._incremental_params(since)
        self.assertEqual(count, 105)  # max(60, 95+10)：长假/漏同步缺口自动放大


class IncrementalFetchTest(unittest.TestCase):
    """增量取数 URL 契约：东财动态 beg / 北证 lmt / 腾讯 count 单页（mock http_json，不打真实接口）。"""

    @staticmethod
    def _em_payload(day):
        # 东财 klines 行：日期,成交量,成交额(元)
        return {'data': {'klines': ['%s,1,10000000000' % day]}}

    @staticmethod
    def _tx_payload(secid, day):
        # 腾讯行第 9 列成交额（万元）
        return {'data': {secid: {'qfqday': [[day, '1', '2', '3', '4', '5', '6', '7', '1000000']]}}}

    def test_eastmoney_incremental_urls(self):
        today = datetime.date.today()
        since = today.isoformat()
        beg = (today - datetime.timedelta(days=turnover_source.INCREMENTAL_LOOKBACK_DAYS)).strftime('%Y%m%d')
        with mock.patch.object(turnover_source, 'http_json',
                               side_effect=lambda url, *a, **k: self._em_payload(since)) as http:
            sh, sz, bj = turnover_source.fetch_eastmoney(since=since)
        urls = [c.args[0] for c in http.call_args_list]
        self.assertEqual(len(urls), 3)
        self.assertIn('beg=' + beg, urls[0])
        self.assertTrue(urls[0].endswith('secid=1.000001'))
        self.assertIn('beg=' + beg, urls[1])
        self.assertTrue(urls[1].endswith('secid=0.399001'))
        self.assertIn('lmt=%d' % turnover_source.INCREMENTAL_DAYS, urls[2])
        self.assertTrue(urls[2].endswith('secid=0.899050'))
        self.assertEqual(sh, {since: 1e10})
        self.assertEqual(sz, {since: 1e10})
        self.assertEqual(bj, {since: 1e10})

    def test_eastmoney_full_urls_unchanged(self):
        with mock.patch.object(turnover_source, 'http_json',
                               side_effect=lambda url, *a, **k: self._em_payload('2026-11-13')) as http:
            turnover_source.fetch_eastmoney()
        urls = [c.args[0] for c in http.call_args_list]
        self.assertIn('beg=19900101', urls[0])
        self.assertIn('beg=19900101', urls[1])
        self.assertIn('lmt=100000', urls[2])

    def test_tencent_incremental_single_page(self):
        since = datetime.date.today().isoformat()

        def fake_http(url, *a, **k):
            secid = url.split('param=')[-1].split(',')[0]
            return self._tx_payload(secid, since)

        with mock.patch.object(turnover_source, 'http_json', side_effect=fake_http) as http:
            sh, sz, bj = turnover_source.fetch_tencent(since=since)
        urls = [c.args[0] for c in http.call_args_list]
        # 三个指数各一次请求：count 单页即返，即使未到 1990 也不向前翻页
        self.assertEqual(len(urls), 3)
        for url, secid in zip(urls, ('sh000001', 'sz399001', 'bj899050')):
            self.assertTrue(url.endswith('%s,day,,,%d,qfq' % (secid, turnover_source.INCREMENTAL_DAYS)))
        self.assertEqual(sh, {since: 1e10})
        self.assertEqual(sz, {since: 1e10})
        self.assertEqual(bj, {since: 1e10})

    def test_tencent_full_keeps_pagination(self):
        # 全量仍 2000/页；翻到 1990-12-19 即停
        def fake_http(url, *a, **k):
            secid = url.split('param=')[-1].split(',')[0]
            return self._tx_payload(secid, turnover_source.FIRST_TRADE_DATE)

        with mock.patch.object(turnover_source, 'http_json', side_effect=fake_http) as http:
            sh, _, _ = turnover_source.fetch_tencent()
        self.assertEqual(http.call_count, 3)
        self.assertTrue(http.call_args_list[0].args[0].endswith('sh000001,day,,,2000,qfq'))
        self.assertEqual(sh, {turnover_source.FIRST_TRADE_DATE: 1e10})


class ValidateRecentTest(unittest.TestCase):
    """增量校验（ADR-008）：三市各 ≥1、沪市最新 ≤10 天、源最新 ≥ 库最新、窗口覆盖库最新。"""

    def test_pass(self):
        since = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        turnover_source.validate_recent(_make_series(10), _make_series(10), _make_series(10), since)

    def test_empty_market(self):
        since = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        with self.assertRaises(RuntimeError):
            turnover_source.validate_recent(_make_series(10), _make_series(10), {}, since)

    def test_stale(self):
        old = datetime.date.today() - datetime.timedelta(days=30)
        with self.assertRaises(RuntimeError):
            turnover_source.validate_recent(_make_series(10, old), _make_series(10, old),
                                            _make_series(10, old), old.isoformat())

    def test_source_behind_library(self):
        end = datetime.date.today() - datetime.timedelta(days=5)
        with self.assertRaises(RuntimeError):
            turnover_source.validate_recent(_make_series(10, end), _make_series(10, end),
                                            _make_series(10, end), datetime.date.today().isoformat())

    def test_window_not_covering(self):
        since = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        with self.assertRaises(RuntimeError):
            turnover_source.validate_recent(_make_series(3), _make_series(3), _make_series(3), since)


class IncrementalSyncTest(unittest.TestCase):
    """同步编排（ADR-008）：库非空增量 / 空库全量 / 超窗回退 / full=True 强制全量。"""

    def _sync(self, latest, full=False, label=turnover_source.SOURCE_EASTMONEY):
        data = (_make_series(70), _make_series(70), _make_series(70))
        with mock.patch.object(MarketDailyTurnover, 'get_latest', return_value=latest) as get_latest, \
                mock.patch.object(MarketDailyTurnover, 'count', return_value=100), \
                mock.patch.object(turnover_source, 'fetch_all', return_value=(*data, label)) as fetch, \
                mock.patch.object(MarketDailyTurnover, 'upsert_rows', return_value=0) as upsert:
            summary = MarketDailyTurnover.sync_from_source('auto', full=full)
        return summary, fetch, upsert, get_latest

    def test_recent_library_incremental(self):
        # get_latest 返回 date 对象（真实 DB 类型），编排层统一 str()[:10]
        latest_day = datetime.date.today() - datetime.timedelta(days=3)
        summary, fetch, _, _ = self._sync({'trade_date': latest_day})
        self.assertEqual(summary['mode'], 'incremental')
        self.assertEqual(fetch.call_args.kwargs['since'], latest_day.isoformat())
        self.assertEqual(summary['days'], 70)

    def test_incremental_no_backup_trim(self):
        # 增量窗口本身即保护：备源增量也不叠加 60 日裁剪
        latest_day = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        summary, _, upsert, _ = self._sync({'trade_date': latest_day}, label=turnover_source.SOURCE_TENCENT)
        self.assertEqual(summary['mode'], 'incremental')
        self.assertIsNone(summary['protected_before'])
        self.assertEqual(len(upsert.call_args[0][0]), 70)

    def test_empty_library_full(self):
        summary, fetch, _, _ = self._sync(None)
        self.assertEqual(summary['mode'], 'full')
        self.assertIsNone(fetch.call_args.kwargs['since'])

    def test_over_gap_falls_back_full(self):
        old = (datetime.date.today() - datetime.timedelta(days=101)).isoformat()
        summary, fetch, _, _ = self._sync({'trade_date': old})
        self.assertEqual(summary['mode'], 'full')
        self.assertIsNone(fetch.call_args.kwargs['since'])

    def test_gap_boundary_incremental(self):
        edge = (datetime.date.today() - datetime.timedelta(days=100)).isoformat()
        summary, fetch, _, _ = self._sync({'trade_date': edge})
        self.assertEqual(summary['mode'], 'incremental')
        self.assertEqual(fetch.call_args.kwargs['since'], edge)

    def test_full_flag_forces_full(self):
        today = datetime.date.today().isoformat()
        summary, fetch, _, get_latest = self._sync({'trade_date': today}, full=True)
        self.assertEqual(summary['mode'], 'full')
        self.assertIsNone(fetch.call_args.kwargs['since'])
        get_latest.assert_not_called()


class DashboardTemplateContractTest(unittest.TestCase):
    """看板模板契约（009 改版 + D-16）：六档区间 / 缩放平移悬停 / 主题重绘 / 零外部图表依赖。

    纯静态断言，不连库不起 app：锁死用户模板移植后的核心交互不回归。
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'market_turnover.html')
        with open(path, encoding='utf-8') as f:
            cls.html = f.read()

    def test_six_range_buttons(self):
        # 1月/3月/6月/1年/3年/全部 六档交易日区间
        self.assertEqual(self.html.count('data-days='), 6)

    def test_zoom_pan_hover(self):
        # 滚轮缩放 / 拖拽平移 / 悬停明细 tooltip 三件套
        self.assertIn("addEventListener('wheel'", self.html)
        self.assertIn("addEventListener('mousedown'", self.html)
        self.assertIn('mkTip', self.html)

    def test_redraw_on_theme_change(self):
        # 监听 data-theme 属性变化重绘，切主题后画布不残留旧主题配色（D-16）
        self.assertIn('MutationObserver', self.html)
        self.assertIn("attributeFilter: ['data-theme']", self.html)

    def test_no_external_chart_lib(self):
        # 自绘 canvas，零 CDN 依赖（离线可用，无加载失败降级路径）
        self.assertNotIn('chart.umd.min.js', self.html)
        self.assertNotIn('cdn.jsdelivr', self.html)


if __name__ == '__main__':
    unittest.main()