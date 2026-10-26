"""
指标监控页面与「指标告警」页签的回归用例（006 批次二）。

覆盖：
1. `/stock/indicator` 路由存在、需登录、页面渲染（含缺数据渲染为「— / 未采集」）；
2. 侧栏导航项存在且带 `title`（折叠后只剩图标，title 是唯一功能名来源）；
3. 告警设置「指标告警」页签不再 `disabled`，且 `?tab=indicator` 能直接落在该页签；
4. 阈值表单：留空继承全局（写 NULL）、非法值不落库、保存后回跳到指标页签。

页面渲染一律 mock 数据访问层，不连接真实数据库。
"""
import re
import unittest
from unittest import mock

from app import app
from utils.indicator_rules import DEFAULT_THRESHOLDS
from views.stock_orders import (
    INDICATOR_THRESHOLD_FIELDS,
    _global_indicator_thresholds,
    _parse_indicator_thresholds,
    _range_position,
)


def _stock(id=1, name='测试股', code='SZ000001', alarm_active=0):
    return {
        'id': id,
        'stock_name': name,
        'stock_code': code,
        'current_price': 61.0,
        'current_pe': 12.5,
        'current_pb': 1.8,
        'is_alarm_active': alarm_active,
        'status': 'active',
    }


def _indicator(**overrides):
    row = {
        'stock_master_id': 1,
        'price': 61.0,
        'high52w': 92.0,
        'low52w': 60.0,
        'pct_from_low52w': 1.67,
        'drawdown_52w': -33.70,
        'ret_5d': -2.5,
        'ret_20d': -18.0,
        'rs_20d': -20.0,
        'rs_5d_ratio': 2.6,
        'flag_low52w': 1,
        'flag_drawdown': 0,
        'flag_rs20': 1,
        'flag_rs5': 0,
        'trade_date': '2026-10-22',
    }
    row.update(overrides)
    return row


class _LoggedInCase(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'tester'

    def _body(self, path):
        resp = self.client.get(path)
        self.assertEqual(resp.status_code, 200, path)
        return resp.get_data(as_text=True)


class IndicatorRouteTest(_LoggedInCase):

    def test_route_registered(self):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn('/stock/indicator', rules)

    def test_requires_login(self):
        with self.client.session_transaction() as sess:
            sess.pop('user_id', None)
            sess.pop('username', None)
        resp = self.client.get('/stock/indicator')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_nav_item_rendered_with_title(self):
        """侧栏折叠后只剩图标，title 是唯一功能名来源（也由 test_sidebar 兜底检查）。"""
        body = self._body('/stock/list')
        self.assertIn('href="/stock/indicator"', body)
        self.assertIn('title="指标监控"', body)

    def test_page_renders_snapshot_and_missing_rows(self):
        stocks = [_stock(1, '有数据股', 'SZ000001'), _stock(2, '缺数据股', 'SZ000002')]
        latest = {1: _indicator()}
        with mock.patch('views.stock_orders.StockMaster.get_all', return_value=(stocks, 2)), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch', return_value=latest), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map', return_value={}):
            body = self._body('/stock/indicator')

        # 两只标的都在表里
        self.assertIn('有数据股', body)
        self.assertIn('缺数据股', body)
        # 四条指标名仍在「判定规则」说明里，但不再出现逐项命中角标
        self.assertIn('52 周新低', body)
        self.assertIn('20 日跑输', body)
        self.assertIn('四项同时满足', body)
        # 组合未成立的行显示「未满足」；缺快照的必须显示「未采集」，不能渲染成 0%
        self.assertIn('未满足', body)
        self.assertIn('未采集', body)
        # 四个 KPI 都在
        for label in ('监控标的', '组合命中', '未采集', '最新快照'):
            self.assertIn(label, body)

    def test_kpi_counts_only_combo_hits(self):
        """只有四条全中的那一只计入「组合命中」，单条命中不计（2026-10-23 组合语义）。"""
        stocks = [_stock(1), _stock(2, '第二只', 'SZ000002'), _stock(3, '第三只', 'SZ000003')]
        latest = {
            1: _indicator(flag_low52w=1, flag_drawdown=1, flag_rs20=1, flag_rs5=1),
            2: _indicator(stock_master_id=2, flag_low52w=1, flag_drawdown=0,
                          flag_rs20=1, flag_rs5=1),
            3: _indicator(stock_master_id=3, flag_low52w=1, flag_drawdown=0,
                          flag_rs20=0, flag_rs5=0),
        }
        with mock.patch('views.stock_orders.StockMaster.get_all', return_value=(stocks, 3)), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch', return_value=latest), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map', return_value={}):
            body = self._body('/stock/indicator')

        self.assertRegex(body, r'组合命中</div>\s*<div class="kpi-value num up">1<')
        # 三只都有快照 → 未采集 0（`down` 着色）
        self.assertRegex(body, r'未采集</div>\s*<div class="kpi-value num">0<')
        # 只有全命中的那只显示「满足，已告警」
        self.assertEqual(body.count('满足，已告警'), 1)
        self.assertEqual(body.count('未满足'), 2)

    def test_missing_snapshot_counts_as_not_collected(self):
        stocks = [_stock(1), _stock(2, '缺数据股', 'SZ000002')]
        with mock.patch('views.stock_orders.StockMaster.get_all', return_value=(stocks, 2)), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch',
                           return_value={1: _indicator()}), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map', return_value={}):
            body = self._body('/stock/indicator')

        self.assertRegex(body, r'未采集</div>\s*<div class="kpi-value num">1<')

    def test_empty_state(self):
        with mock.patch('views.stock_orders.StockMaster.get_all', return_value=([], 0)), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch', return_value={}), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map', return_value={}):
            body = self._body('/stock/indicator')
        self.assertIn('暂无监控标的', body)

    def test_db_error_degrades_to_empty_page(self):
        """列表查询失败不能让页面 500（监控线程可能正在采集）。"""
        with mock.patch('views.stock_orders.StockMaster.get_all', side_effect=RuntimeError('db down')), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch', return_value={}), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map', return_value={}):
            body = self._body('/stock/indicator')
        self.assertIn('暂无监控标的', body)
        self.assertIn('加载订单列表失败', body)


class IndicatorPaginationTest(_LoggedInCase):
    """
    指标监控页分页（2026-10-23，与订单列表同口径）。

    锁定：默认每页 10 条、翻页真的按 LIMIT/OFFSET 切片、页码链接保留 per_page、
    KPI「监控标的」是全量而不是本页行数（否则翻页后数字会跳）。
    """

    TOTAL = 12
    STOCKS = [_stock(i, f'股票{i}', f'SZ{i:06d}') for i in range(1, TOTAL + 1)]
    LATEST = {i: _indicator(stock_master_id=i) for i in range(1, TOTAL + 1)}

    @staticmethod
    def _fake_get_all(page=1, per_page=10, search_query=None):
        """按 BaseModel.get_all 的真实语义切片（ORDER BY id DESC 不影响行数断言）。"""
        page = max(1, int(page or 1))
        start = (page - 1) * per_page
        return (IndicatorPaginationTest.STOCKS[start:start + per_page],
                IndicatorPaginationTest.TOTAL)

    def _render(self, path='/stock/indicator'):
        with mock.patch('views.stock_orders.StockMaster.get_all',
                        side_effect=self._fake_get_all), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch',
                           return_value=self.LATEST), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map',
                           return_value={}):
            return self._body(path)

    def _row_count(self, body):
        return len(re.findall(r'<tr\b[^>]*>\s*<td\b', body))

    def test_defaults_to_ten_per_page(self):
        body = self._render()
        self.assertEqual(self._row_count(body), 10)
        self.assertIn('class="pager"', body)
        self.assertIn('共 12 只标的', body)

    def test_second_page_shows_remaining(self):
        self.assertEqual(self._row_count(self._render('/stock/indicator?page=2')), 2)
        self.assertEqual(self._row_count(self._render('/stock/indicator?page=3')), 0)

    def test_per_page_option_respected(self):
        self.assertEqual(self._row_count(self._render('/stock/indicator?per_page=20')), 12)
        self.assertEqual(self._row_count(self._render('/stock/indicator?per_page=5')), 5)
        # 非法值回落 10
        self.assertEqual(self._row_count(self._render('/stock/indicator?per_page=999')), 10)

    def test_single_page_hides_pager(self):
        self.assertNotIn('class="pager"', self._render('/stock/indicator?per_page=20'))

    def test_pager_links_keep_per_page(self):
        body = self._render('/stock/indicator?per_page=5')
        for link in re.findall(r'<a class="pg[^"]*" href="([^"]+)"', body):
            self.assertIn('per_page=5', link)

    def test_kpi_total_is_all_stocks_not_page_rows(self):
        """翻到第 2 页（只剩 2 行）时，「监控标的」仍应是全量 12。"""
        body = self._render('/stock/indicator?page=2')
        self.assertEqual(self._row_count(body), 2)
        self.assertRegex(body, r'监控标的</div>\s*<div class="kpi-value num">12<')


class IndicatorTableLayoutTest(unittest.TestCase):
    """
    表格列宽（2026-10-23）：七列全定宽，且定宽之和 == CSS 的 min-width。

    两者不一致就会在窄屏反向压列宽，把标的名称 / 组合信号挤没（订单列表 D-13 的同款教训）。
    """

    def test_all_columns_fixed_and_match_min_width(self):
        with open('templates/indicator_list.html', encoding='utf-8') as fh:
            tpl = fh.read()
        table = re.search(r'<table class="table-indicator">(.*?)</table>', tpl, re.S)
        self.assertIsNotNone(table, '指标表应带 .table-indicator 类')
        widths = [int(w) for w in re.findall(r'<col style="width:(\d+)px">', table.group(1))]
        self.assertEqual(len(widths), 7, '七列必须全部定宽（<col> 无 width 会变自适应）')

        with open('static/css/theme.css', encoding='utf-8') as fh:
            css = fh.read()
        min_width = re.search(r'table\.table-indicator\s*\{\s*min-width:\s*(\d+)px', css)
        self.assertIsNotNone(min_width)
        self.assertEqual(sum(widths), int(min_width.group(1)),
                         'colgroup 定宽之和必须等于 min-width，否则窄屏会被压缩')


class RowAiColorTest(unittest.TestCase):
    """
    行内 AI 入口的配色变体（2026-10-23）：订单页保持紫色默认，指标页用蓝色变体。

    锁定两条：1) `.row-ai` 默认仍是紫，`.row-ai.blue` 才是蓝（改一处不该波及另一页）；
    2) 指标页按钮带 `blue`、订单页不带。
    """

    def _css(self):
        with open('static/css/theme.css', encoding='utf-8') as fh:
            return fh.read()

    def test_default_variant_is_purple_blue_is_opt_in(self):
        css = self._css()
        base = re.search(r'\.row-ai\s*\{[^}]*\}', css)
        self.assertIsNotNone(base, 'theme.css 里找不到 .row-ai 基础规则')
        self.assertIn('--ai-hue: var(--violet)', base.group(0))

        blue = re.search(r'\.row-ai\.blue\s*\{[^}]*\}', css)
        self.assertIsNotNone(blue, '缺少 .row-ai.blue 变体')
        self.assertIn('--ai-hue: var(--info)', blue.group(0))
        self.assertIn('--ai-soft: var(--info-soft)', blue.group(0))

    def test_hover_rule_reads_the_variant_variable(self):
        """hover 必须读变量而不是写死颜色，否则变体类加不上。"""
        css = self._css()
        hover = re.search(r'\.row-ai:hover[^{]*\{[^}]*\}', css)
        self.assertIsNotNone(hover)
        self.assertIn('var(--ai-hue)', hover.group(0))
        self.assertIn('var(--ai-soft)', hover.group(0))
        self.assertNotIn('var(--violet)', hover.group(0))

    def test_indicator_page_uses_blue_orders_stay_purple(self):
        with open('templates/indicator_list.html', encoding='utf-8') as fh:
            indicator = fh.read()
        with open('templates/stock_order_list.html', encoding='utf-8') as fh:
            orders = fh.read()
        self.assertIn('row-ai blue', indicator)
        self.assertIn('row-ai"', orders)
        self.assertNotIn('row-ai blue', orders)


class IndicatorAiShortcutTest(_LoggedInCase):
    """
    指标页「AI 分析」快捷入口（2026-10-23，与订单列表同款）。

    锁定三件事：
    1. 每行入口指向**本行**的 stock_id（不串标的）；
    2. 不新增列：入口复用「标的」列的空档；
    3. 入口落在第一个 `<td>`（标的列）内，且是纯 GET 链接（不是表单）。
    """

    STOCK_COUNT = 2

    def _render(self):
        stocks = [_stock(i, f'股票{i}', f'SZ00000{i}') for i in range(1, self.STOCK_COUNT + 1)]
        latest = {i: _indicator(stock_master_id=i) for i in range(1, self.STOCK_COUNT + 1)}
        with mock.patch('views.stock_orders.StockMaster.get_all',
                        return_value=(stocks, self.STOCK_COUNT)), \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch',
                           return_value=latest), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map',
                           return_value={}):
            return self._body('/stock/indicator')

    def _rows(self, body):
        return re.findall(r'<tr\b[^>]*>\s*<td\b.*?</tr>', body, re.S)

    def test_every_row_has_entry_to_its_own_stock(self):
        body = self._render()
        rows = self._rows(body)
        self.assertTrue(rows, '没有渲染出任何指标行，无法验证入口')
        for row in rows:
            stock_id = re.search(r'SZ00000(\d)', row).group(1)
            targets = set(re.findall(r'/stock/ai/\?stock_id=(\d+)', row))
            self.assertEqual(targets, {stock_id}, '指标行的 AI 入口串了标的')
            self.assertEqual(row.count('row-ai'), 1, '每行应恰好一个 AI 入口')

    def test_entry_sits_in_stock_cell_without_new_column(self):
        body = self._render()
        heads = re.findall(r'<th\b[^>]*>', body)
        self.assertEqual(len(heads), 7, '列数变了：入口应复用标的列的空档，不新增列')
        rows = self._rows(body)
        self.assertTrue(rows)
        for row in rows:
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)
            self.assertEqual(len(cells), len(heads))
            self.assertIn('row-ai', cells[0], 'AI 入口不在「标的」单元格内')

    def test_entry_is_a_plain_link_not_a_form(self):
        """快捷入口只做跳转：GET 链接，不要塞表单（避免误提交）。"""
        body = self._render()
        for row in self._rows(body):
            anchor = re.search(r'<a[^>]*row-ai[^>]*>', row)
            self.assertIsNotNone(anchor)
            self.assertIn('/stock/ai/?stock_id=', anchor.group(0))
            self.assertNotIn('<form', row)


class RangePositionTest(unittest.TestCase):

    def test_middle(self):
        self.assertAlmostEqual(_range_position(_indicator()), (61.0 - 60.0) / (92.0 - 60.0) * 100)

    def test_clamped_to_bounds(self):
        self.assertEqual(_range_position(_indicator(price=200.0)), 100.0)
        self.assertEqual(_range_position(_indicator(price=1.0)), 0.0)

    def test_missing_or_degenerate(self):
        self.assertIsNone(_range_position({'price': 61.0, 'high52w': None, 'low52w': 60.0}))
        self.assertIsNone(_range_position({'price': 61.0, 'high52w': 60.0, 'low52w': 60.0}))


class IndicatorThresholdFormTest(_LoggedInCase):

    def test_field_list_matches_config(self):
        """表单字段必须与 config 的 IND_* 一一对应，否则页面填了也不会生效。"""
        from config import Config
        for key, _label, _low, _high in INDICATOR_THRESHOLD_FIELDS:
            self.assertTrue(hasattr(Config, 'IND_' + key.upper()), key)

    def test_global_thresholds_fall_back_to_defaults(self):
        values = _global_indicator_thresholds()
        self.assertEqual(set(values), {key for key, *_ in INDICATOR_THRESHOLD_FIELDS})
        for key, value in values.items():
            self.assertIsInstance(value, (int, float), key)

    def _parse(self, data):
        with app.test_request_context('/stock/alarm_settings', method='POST', data=data):
            return _parse_indicator_thresholds()

    def test_blank_means_inherit(self):
        payload, errors = self._parse({})
        self.assertEqual(errors, [])
        self.assertTrue(all(value is None for value in payload.values()),
                        '留空必须写 NULL（继承全局），不能写成 0')

    def test_valid_values_parsed_as_float(self):
        payload, errors = self._parse({'low52w_near_pct': '3.5', 'rs5_ratio': '3'})
        self.assertEqual(errors, [])
        self.assertEqual(payload['low52w_near_pct'], 3.5)
        self.assertEqual(payload['rs5_ratio'], 3.0)
        self.assertIsNone(payload['drawdown_52w_pct'])

    def test_non_numeric_rejected(self):
        _, errors = self._parse({'low52w_near_pct': 'abc'})
        self.assertTrue(any('必须是数字' in e for e in errors))

    def test_out_of_range_rejected(self):
        _, errors = self._parse({'rs5_ratio': '99', 'low52w_near_pct': '-1'})
        self.assertEqual(len(errors), 2)

    def test_post_saves_and_returns_to_indicator_tab(self):
        with mock.patch('views.stock_orders.StockIndicatorConfig.upsert',
                        return_value=True) as upsert:
            resp = self.client.post('/stock/alarm_settings', data={
                'stock_id': '1',
                'alarm_type': 'indicator',
                'low52w_near_pct': '4',
                'drawdown_52w_pct': '',
            })

        self.assertEqual(resp.status_code, 302)
        self.assertIn('tab=indicator', resp.headers['Location'])
        kwargs = upsert.call_args[1]
        self.assertEqual(kwargs['low52w_near_pct'], 4.0)
        self.assertIsNone(kwargs['drawdown_52w_pct'])

    def test_post_invalid_does_not_write(self):
        with mock.patch('views.stock_orders.StockIndicatorConfig.upsert',
                        return_value=True) as upsert:
            resp = self.client.post('/stock/alarm_settings', data={
                'stock_id': '1',
                'alarm_type': 'indicator',
                'low52w_near_pct': 'oops',
            })
        upsert.assert_not_called()
        self.assertEqual(resp.status_code, 302)

    def test_post_without_stock_id_does_not_write(self):
        with mock.patch('views.stock_orders.StockIndicatorConfig.upsert',
                        return_value=True) as upsert:
            self.client.post('/stock/alarm_settings', data={'alarm_type': 'indicator'})
        upsert.assert_not_called()

    def test_save_failure_flashes_error(self):
        with mock.patch('views.stock_orders.StockIndicatorConfig.upsert', return_value=False):
            resp = self.client.post('/stock/alarm_settings', data={
                'stock_id': '1',
                'alarm_type': 'indicator',
                'rs20_pct': '12',
            }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('保存失败', resp.get_data(as_text=True))


class AlarmSettingsIndicatorTabTest(_LoggedInCase):

    def _render(self, query=''):
        stocks = [_stock()]
        with mock.patch('views.stock_orders.StockMaster.get_all', return_value=(stocks, 1)), \
                mock.patch('views.stock_orders.StockWarehouse.get_by_stock_master_id', return_value=None), \
                mock.patch('views.stock_orders.StockPe.get_by_stock_master_id', return_value=None), \
                mock.patch('views.stock_orders.StockPb.get_by_stock_master_id', return_value=None), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map', return_value={}):
            return self.client.get('/stock/alarm_settings' + query)

    def test_tab_is_enabled(self):
        resp = self._render()
        body = resp.get_data(as_text=True)
        tab = re.search(r'<button[^>]*data-tab="indicator"[^>]*>', body)
        self.assertIsNotNone(tab)
        self.assertNotIn('disabled', tab.group(0), '指标告警页签不应再是占位')

    def test_form_fields_present(self):
        body = self._render().get_data(as_text=True)
        self.assertIn('alarm_type" value="indicator', body)
        for name, *_ in INDICATOR_THRESHOLD_FIELDS:
            self.assertIn('name="%s"' % name, body)
        self.assertIn('保存指标告警', body)

    def test_default_tab_is_price(self):
        body = self._render().get_data(as_text=True)
        price_form = re.search(r'<form[^>]*data-body="price"[^>]*>', body)
        self.assertNotIn('hidden', price_form.group(0))
        indicator_form = re.search(r'<form[^>]*data-body="indicator"[^>]*>', body)
        self.assertIn('hidden', indicator_form.group(0))

    def test_tab_query_switches_panel(self):
        body = self._render('?tab=indicator').get_data(as_text=True)
        indicator_form = re.search(r'<form[^>]*data-body="indicator"[^>]*>', body)
        self.assertNotIn('hidden', indicator_form.group(0))
        price_form = re.search(r'<form[^>]*data-body="price"[^>]*>', body)
        self.assertIn('hidden', price_form.group(0))

    def test_placeholder_shows_global_default(self):
        body = self._render().get_data(as_text=True)
        self.assertIn('全局 %s' % DEFAULT_THRESHOLDS['low52w_near_pct'], body)

    def test_prefilled_config_renders_trimmed_decimal(self):
        """DECIMAL 列是 '4.5000' 这种定长字符串，表单里要显示成 '4.5'，不能直接灌进去。"""
        from decimal import Decimal
        config = {
            1: {'stock_master_id': 1,
                'low52w_near_pct': Decimal('4.5000'),
                'drawdown_52w_pct': Decimal('30.0000'),
                'rs20_pct': None, 'rs5_ratio': None,
                'rs5_min_drop_pct': None, 'rs5_min_bench_drop_pct': None},
        }
        with mock.patch('views.stock_orders.StockMaster.get_by_id', return_value=_stock()), \
                mock.patch('views.stock_orders.StockWarehouse.get_by_stock_master_id', return_value=None), \
                mock.patch('views.stock_orders.StockPe.get_by_stock_master_id', return_value=None), \
                mock.patch('views.stock_orders.StockPb.get_by_stock_master_id', return_value=None), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_by_stock_master_id',
                           return_value=config[1]):
            body = self.client.get('/stock/alarm_settings?stock_id=1').get_data(as_text=True)

        self.assertIn('value="4.5"', body)
        self.assertIn('value="30"', body)
        # 未覆盖的字段留空才表示继承全局
        self.assertIn('name="rs20_pct"', body)


if __name__ == '__main__':
    unittest.main()
