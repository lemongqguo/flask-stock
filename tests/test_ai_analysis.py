"""
AI 个股分析（007）的回归用例。

分四层，全部不发真实网络请求：
1. `utils/ai_client`：未配置 →「未启用」、超时 / HTTP 错误 → 可判定失败值、**密钥不进日志与返回值**；
2. `utils/ai_prompt`：上下文组装（缺失数据不写 0）、结构化解析（代码块 / 夹杂话术 / 纯文本兜底）、免责声明以本地为准；
3. `models/stock_ai`：参数与环境变量的合并语义（关只能更关）、脏 JSON 不炸页面；
4. 视图：未启用拦截、月度上限拦截、成功路径落库带上 model / prompt_version、追问留痕、参数校验。
"""
import datetime
import json
import re
import unittest
from unittest import mock

import requests

from app import app
from config import Config
from models.stock_ai import (
    DIMENSIONS,
    StockAiConfig,
    StockAiReport,
    parse_dimensions,
    parse_scope,
)
from utils import ai_client
from utils.ai_prompt import (
    DISCLAIMER,
    PROMPT_VERSION,
    build_context,
    build_followup_messages,
    build_messages,
    parse_report,
)

SECRET = 'sk-unit-test-secret-should-never-leak'


class _FakeResponse:
    """复刻 requests.Response 的最小接口（json / status_code / text）。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError('not json')
        return self._payload


def _ai_env(**overrides):
    """把 Config 上的 AI_* 换成测试值（类属性，用 mock.patch.object 可自动还原）。"""
    values = {
        'AI_ENABLED': True,
        'AI_API_BASE': 'https://api.example.com/v1',
        'AI_MODEL': 'test-model',
        'AI_API_KEY': SECRET,
        'AI_API_STYLE': 'responses',
        'AI_TEMPERATURE': 0.3,
        'AI_MAX_TOKENS': 256,
        'AI_MONTHLY_LIMIT': 10,
        'AI_TIMEOUT': 7,
    }
    values.update(overrides)
    return [mock.patch.object(Config, key, value) for key, value in values.items()]


class AiClientBase(unittest.TestCase):

    def setUp(self):
        self.enter_config(**{})

    def enter_config(self, **overrides):
        for patcher in _ai_env(**overrides):
            patcher.start()
            self.addCleanup(patcher.stop)


class AiClientConfigTest(AiClientBase):

    def test_not_configured_returns_disabled_without_http(self):
        self.enter_config(AI_API_KEY='')
        with mock.patch('utils.ai_client.requests.post') as post:
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['status'], 'disabled')
        self.assertFalse(result['ok'])
        self.assertIn('AI_API_KEY', result['error'])
        post.assert_not_called()

    def test_disabled_switch_wins(self):
        self.enter_config(AI_ENABLED=False)
        ready, reason = ai_client.is_ready()
        self.assertFalse(ready)
        self.assertIn('AI_ENABLED', reason)

    def test_describe_settings_masks_key(self):
        info = ai_client.describe_settings()
        self.assertTrue(info['configured'])
        self.assertNotIn(SECRET, json.dumps(info, ensure_ascii=False))
        self.assertEqual(info['key_masked'], SECRET[:3] + '***' + SECRET[-2:])

    def test_mask_key_short_values(self):
        self.assertEqual(ai_client.mask_key(''), '未配置')
        self.assertEqual(ai_client.mask_key('abc'), '***')

    def test_endpoint_per_style(self):
        self.assertEqual(ai_client._endpoint('https://x/v1', 'responses'), 'https://x/v1/responses')
        self.assertEqual(ai_client._endpoint('https://x/v1/', 'chat'), 'https://x/v1/chat/completions')

    def test_available_models_puts_default_first_and_dedupes(self):
        self.enter_config(AI_MODEL='m-default', AI_MODELS='m-alt, m-default ,,m-second')
        self.assertEqual(ai_client.available_models(),
                         ['m-default', 'm-alt', 'm-second'])

    def test_available_models_splits_ai_model_list(self):
        """AI_MODEL 填逗号分隔的清单时，必须拆成多个模型而不是整串当一个 ID。"""
        self.enter_config(AI_MODEL='m-a,m-b,m-c', AI_MODELS='')
        self.assertEqual(ai_client.available_models(), ['m-a', 'm-b', 'm-c'])
        self.assertEqual(ai_client.default_model(), 'm-a')

    def test_available_models_accepts_semicolon(self):
        self.enter_config(AI_MODEL='', AI_MODELS='m-a;m-b,m-c')
        self.assertEqual(ai_client.available_models(), ['m-a', 'm-b', 'm-c'])
        self.assertEqual(ai_client.default_model(), 'm-a')

    def test_default_model_is_single_id_not_whole_list(self):
        """真正发出去的必须是单个模型 ID：整串没有网关认。"""
        self.enter_config(AI_MODEL='m-a,m-b', AI_MODELS='')
        self.assertEqual(ai_client.describe_settings()['model'], 'm-a')
        self.assertTrue(ai_client.is_allowed_model('m-a'))
        self.assertFalse(ai_client.is_allowed_model('m-a,m-b'))

    def test_available_models_empty_when_unset(self):
        self.enter_config(AI_MODEL='', AI_MODELS='')
        self.assertEqual(ai_client.available_models(), [])
        self.assertFalse(ai_client.is_allowed_model(''))
        self.assertFalse(ai_client.is_allowed_model('whatever'))

    def test_is_allowed_model_respects_whitelist(self):
        self.enter_config(AI_MODEL='m-default', AI_MODELS='m-alt')
        self.assertTrue(ai_client.is_allowed_model('m-alt'))
        self.assertFalse(ai_client.is_allowed_model('m-evil'))


class AiClientCallTest(AiClientBase):

    def test_responses_style_success(self):
        payload = {'output_text': '{"verdict": "买入"}', 'usage': {'total_tokens': 42}}
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse(payload)) as post:
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])

        self.assertTrue(result['ok'])
        self.assertEqual(result['tokens'], 42)
        self.assertEqual(result['model'], 'test-model')
        body = post.call_args.kwargs['json']
        self.assertIn('input', body)
        self.assertEqual(body['max_output_tokens'], 256)

    def test_responses_style_walks_output_array(self):
        payload = {'output': [{'content': [{'type': 'output_text', 'text': '第一段'},
                                           {'type': 'output_text', 'text': '第二段'}]}]}
        with mock.patch('utils.ai_client.requests.post', return_value=_FakeResponse(payload)):
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertTrue(result['ok'])
        self.assertIn('第一段', result['text'])
        self.assertIn('第二段', result['text'])
        self.assertEqual(result['tokens'], 0)  # usage 缺失记 0，不报错

    def test_chat_style_success(self):
        self.enter_config(AI_API_STYLE='chat')
        payload = {'choices': [{'message': {'content': 'OK'}}], 'usage': {'total_tokens': 5}}
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse(payload)) as post:
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertTrue(result['ok'])
        self.assertEqual(post.call_args.args[0], 'https://api.example.com/v1/chat/completions')
        self.assertIn('messages', post.call_args.kwargs['json'])

    def test_timeout_returns_timeout_status(self):
        with mock.patch('utils.ai_client.requests.post', side_effect=requests.Timeout('slow')):
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['status'], 'timeout')
        self.assertFalse(result['ok'])

    def test_request_exception_returns_error(self):
        with mock.patch('utils.ai_client.requests.post',
                        side_effect=requests.ConnectionError('boom')):
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['status'], 'error')
        self.assertIn('ConnectionError', result['error'])

    def test_http_error_returns_error(self):
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse({'error': 'bad'}, status_code=401)):
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['status'], 'error')
        self.assertIn('401', result['error'])

    def test_non_json_body_returns_error(self):
        with mock.patch('utils.ai_client.requests.post', return_value=_FakeResponse('<html>')):
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['status'], 'error')

    def test_empty_text_returns_error(self):
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse({'output_text': '   '})):
            result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['status'], 'error')
        self.assertIn('为空', result['error'])

    def test_secret_never_in_result_or_logs(self):
        with self.assertLogs('utils.ai_client', level='DEBUG') as logs:
            with mock.patch('utils.ai_client.requests.post', side_effect=requests.Timeout('x')):
                result = ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))
        self.assertNotIn(SECRET, '\n'.join(logs.output))

    def test_timeout_is_passed_to_requests(self):
        payload = {'output_text': 'ok'}
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse(payload)) as post:
            ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(post.call_args.kwargs['timeout'], 7)

    def test_test_connection_uses_tiny_budget(self):
        payload = {'output_text': 'OK', 'usage': {'total_tokens': 3}}
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse(payload)) as post:
            result = ai_client.test_connection()
        self.assertTrue(result['ok'])
        self.assertIn('latency_ms', result)
        self.assertEqual(post.call_args.kwargs['json']['max_output_tokens'], 16)


class AiPromptContextTest(unittest.TestCase):

    def _stock(self):
        return {'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001',
                'current_pe': '12.50', 'target_pettm': '20.00',
                'current_pb': '1.80', 'target_pb': '3.00'}

    def test_missing_data_is_none_not_zero(self):
        context = build_context(self._stock(), None, None, None)
        self.assertIsNone(context['price'])
        self.assertIsNone(context['ret_20d'])
        self.assertFalse(context['has_indicator'])
        text = build_messages(context)[1]['content']
        self.assertIn('数据不足', text)
        self.assertNotIn('0.00%', text)

    def test_indicator_values_and_hits(self):
        indicator = {'price': '61.00', 'high52w': '92.00', 'low52w': '60.00',
                     'pct_from_low52w': '1.67', 'drawdown_52w': '-33.70',
                     'ret_5d': '-2.50', 'ret_20d': '-18.00', 'rs_20d': '-20.00',
                     'rs_5d_ratio': '2.60', 'trade_date': datetime.date(2026, 10, 22),
                     'flag_low52w': 1, 'flag_drawdown': 0, 'flag_rs20': 1, 'flag_rs5': 0}
        context = build_context(self._stock(), {'current_price': '61.00'}, indicator, None)
        self.assertEqual(context['price'], 61.0)
        self.assertEqual(context['ret_20d'], -18.0)
        self.assertEqual(context['indicator_hits'], ['52 周新低', '20 日跑输基准'])
        self.assertEqual(context['trade_date'], '2026-10-22')

    def test_closes_fill_missing_returns(self):
        closes = [100.0] * 20 + [90.0]
        context = build_context(self._stock(), None, None, closes)
        self.assertAlmostEqual(context['ret_5d'], -10.0, places=2)

    def test_scope_prunes_out_of_scope_fields(self):
        """页面「引用数据范围」必须真的裁剪，不能只当摆设。"""
        indicator = {'price': '61.00', 'high52w': '92.00', 'low52w': '60.00',
                     'pct_from_low52w': '1.67', 'drawdown_52w': '-33.70',
                     'ret_5d': '-2.50', 'ret_20d': '-18.00', 'rs_20d': '-20.00',
                     'rs_5d_ratio': '2.60', 'flag_low52w': 1}
        context = build_context(self._stock(), {'current_price': '61.00'}, indicator,
                                None, scope=['quote'])
        self.assertEqual(context['price'], 61.0)
        self.assertIsNone(context['pe'], '未勾选估值时 PE 不应喂给模型')
        self.assertIsNone(context['drawdown_52w'])
        self.assertIsNone(context['ret_5d'])
        self.assertEqual(context['indicator_hits'], [])
        self.assertIn('本次仅允许引用', build_messages(context)[1]['content'])

    def test_messages_start_with_system(self):
        messages = build_messages(build_context(self._stock()))
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertIn('测试股', messages[1]['content'])


class AiPromptParseTest(unittest.TestCase):

    def test_fenced_json_with_english_verdict(self):
        text = ('```json\n' + json.dumps({
            'verdict': 'buy', 'confidence': 150, 'summary': '低估',
            'points': ['PE 低于目标', '回撤充分'],
            'supports': ['距 52 周低 1.7%'], 'risks': ['行业下行'],
            'disclaimer': '模型自己改的免责声明',
        }, ensure_ascii=False) + '\n```')
        report = parse_report(text)
        self.assertTrue(report['parsed'])
        self.assertEqual(report['verdict'], '买入')
        self.assertEqual(report['confidence'], 100.0)  # 超界被夹紧
        self.assertEqual(report['points'], ['PE 低于目标', '回撤充分'])
        self.assertEqual(report['disclaimer'], DISCLAIMER)  # 以本地常量为准

    def test_json_with_surrounding_chatter(self):
        text = '好的，以下是结论：{"verdict": "持有", "confidence": 55, "summary": "震荡"} 以上。'
        report = parse_report(text)
        self.assertTrue(report['parsed'])
        self.assertEqual(report['verdict'], '持有')

    def test_plain_text_fallback(self):
        report = parse_report('这只股票看起来还行。')
        self.assertFalse(report['parsed'])
        self.assertEqual(report['verdict'], '未知')
        self.assertIn('还行', report['summary'])
        self.assertEqual(report['disclaimer'], DISCLAIMER)

    def test_unknown_verdict_normalized(self):
        report = parse_report(json.dumps({'verdict': 'strongly-agree', 'summary': 'x'}))
        self.assertEqual(report['verdict'], '未知')

    def test_string_lists_are_split(self):
        report = parse_report(json.dumps({'verdict': '减持',
                                          'points': '- 第一点\n- 第二点\n',
                                          'risks': None}))
        self.assertEqual(report['points'], ['第一点', '第二点'])
        self.assertEqual(report['risks'], [])

    def test_followup_messages_include_question_and_previous(self):
        context = build_context({'stock_name': '测试股', 'stock_code': 'SZ000001'})
        messages = build_followup_messages(context, '该在哪档建仓？', {'summary': '上一轮结论'})
        joined = '\n'.join(m['content'] for m in messages)
        self.assertIn('该在哪档建仓？', joined)
        self.assertIn('上一轮结论', joined)

    def test_followup_keeps_data_block_not_system_prompt(self):
        """回归：追问曾误把 system 全文当数据块拼进去，真正的标的/数据反而丢了。"""
        context = build_context({'stock_name': '测试股', 'stock_code': 'SZ000001',
                                 'current_pe': '12.5'})
        messages = build_followup_messages(context, '还能拿吗？')
        user_msg = messages[-1]['content']
        self.assertEqual(messages[0]['role'], 'system')
        self.assertTrue(user_msg.startswith('标的：'), user_msg[:40])
        self.assertIn('PE', user_msg)
        self.assertIn('还能拿吗？', user_msg)
        # 数据块只出现一次，不该在 user 消息里再贴一遍完整 system 提示词
        self.assertEqual(user_msg.count('你是一名 A 股个股分析助手'), 0)

    def test_dimensions_injected_into_prompt(self):
        context = build_context({'stock_name': '测试股', 'stock_code': 'SZ000001'})
        user_msg = build_messages(context, ['估值', '风险'])[-1]['content']
        self.assertIn('本次要求的分析维度：估值、风险', user_msg)
        self.assertIn('每个维度至少给一条结论', user_msg)
        # 不传维度时不出现该段，避免干扰默认行为
        self.assertNotIn('本次要求的分析维度', build_messages(context)[-1]['content'])


class StockAiModelTest(unittest.TestCase):

    def test_parse_scope_filters_unknown(self):
        self.assertEqual(parse_scope('quote, bad ,kline,quote'), ['quote', 'kline'])
        self.assertEqual(parse_scope(None), [])

    def test_effective_merges_row_over_env(self):
        with mock.patch.object(Config, 'AI_ENABLED', True), \
                mock.patch.object(Config, 'AI_TEMPERATURE', 0.6), \
                mock.patch.object(Config, 'AI_MONTHLY_LIMIT', 200), \
                mock.patch.object(StockAiConfig, 'get',
                                  return_value={'enabled': 1, 'temperature': '0.20',
                                                'max_tokens': 900, 'monthly_limit': 5,
                                                'data_scope': 'quote'}):
            config = StockAiConfig.effective()

        self.assertEqual(config['temperature'], 0.2)
        self.assertEqual(config['max_tokens'], 900)
        self.assertEqual(config['monthly_limit'], 5)
        self.assertEqual(config['scope'], ['quote'])
        self.assertEqual(config['enabled'], 1)

    def test_table_can_only_turn_off(self):
        with mock.patch.object(Config, 'AI_ENABLED', False), \
                mock.patch.object(Config, 'AI_TEMPERATURE', 0.6), \
                mock.patch.object(Config, 'AI_MAX_TOKENS', 1200), \
                mock.patch.object(Config, 'AI_MONTHLY_LIMIT', 200), \
                mock.patch.object(StockAiConfig, 'get', return_value={'enabled': 1}):
            config = StockAiConfig.effective()
        self.assertEqual(config['enabled'], 0, '环境总闸关闭时表内开启无效')

    def test_effective_carries_model_and_dimensions(self):
        with mock.patch.object(Config, 'AI_ENABLED', True), \
                mock.patch.object(Config, 'AI_MODEL', 'env-model'), \
                mock.patch.object(StockAiConfig, 'get',
                                  return_value={'model': 'row-model',
                                                'dimensions': 'risk,valuation'}):
            config = StockAiConfig.effective()

        self.assertEqual(config['model'], 'row-model')
        self.assertEqual(config['dimension_keys'], ['risk', 'valuation'])
        self.assertEqual(config['dimension_labels'], ['风险', '估值'])

    def test_effective_falls_back_to_env_model_and_all_dimensions(self):
        with mock.patch.object(Config, 'AI_ENABLED', True), \
                mock.patch.object(Config, 'AI_MODEL', 'env-model'), \
                mock.patch.object(StockAiConfig, 'get', return_value={}):
            config = StockAiConfig.effective()

        self.assertEqual(config['model'], 'env-model')
        self.assertEqual(len(config['dimension_keys']), len(DIMENSIONS))

    def test_parse_dimensions_ignores_junk_and_defaults(self):
        self.assertEqual(parse_dimensions('risk, ,unknown,risk'), ['risk'])
        self.assertEqual(parse_dimensions(None), list(DIMENSIONS))
        self.assertEqual(parse_dimensions([], default=['valuation']), ['valuation'])

    def test_bad_json_content_degrades(self):
        rows = [{'id': 1, 'content_json': 'not-json', 'verdict': '买入'}]
        parsed = StockAiReport._rows_to_dicts(rows)
        self.assertEqual(parsed[0]['content'], {})

    def test_count_since_returns_none_on_error(self):
        with mock.patch.object(StockAiReport, 'execute_query', side_effect=RuntimeError('db')):
            self.assertIsNone(StockAiReport.count_since(datetime.datetime(2026, 10, 1)))

    def test_upsert_ignores_unknown_fields(self):
        with mock.patch.object(StockAiConfig, 'execute_update', return_value=1) as update:
            self.assertFalse(StockAiConfig.upsert(api_key='leak'))
        update.assert_not_called()


class _AiViewSetup:
    """视图层用例的公共夹具：**刻意不是 TestCase**，否则会被 unittest 当成一个类重复收集。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'tester'
        self.config = {'enabled': 1, 'temperature': 0.3, 'max_tokens': 256,
                       'monthly_limit': 10, 'data_scope': 'quote,indicator',
                       'scope': ['quote', 'indicator'], 'scope_labels': ['行情', '指标'],
                       'model': 'test-model',
                       'dimensions': 'valuation,technical',
                       'dimension_keys': ['valuation', 'technical'],
                       'dimension_labels': ['估值', '技术面']}

        # 模型候选清单来自环境变量：不钉住的话「模型是否可选」会随部署环境漂移
        for key, value in (('AI_MODEL', 'test-model'),
                           ('AI_MODELS', 'test-model,alt-model')):
            patcher = mock.patch.object(Config, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # 可用模型/维度校验走真实实现（只 mock 掉 HTTP 与数据访问）
        # 默认把「数据访问 + 配置 + 额度」都钉住，单个用例只覆盖自己关心的那一个
        # get_all 只用于「标的总数」判定，默认给"至少有一只"，需要空库的用例各自覆盖
        self._patch('StockMaster.get_all',
                    return_value=([{'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001'}], 1))
        self._patch('StockMaster.get_by_id',
                    return_value={'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001'})
        self._patch('StockWarehouse.get_by_stock_master_id', return_value=None)
        self._patch('StockIndicator.get_latest', return_value=None)
        self._patch('StockIndicator.get_latest_batch', return_value={})
        self._patch('StockKline.get_recent_closes', return_value=[])
        self._patch('StockKline.get_latest_signal', return_value='normal')
        self._patch('StockAiConfig.effective', return_value=self.config)
        self._patch('StockAiReport.count_since', return_value=0)
        # describe_settings 同时被 ai_client.is_ready() 内部调用，字段必须齐全，否则会 KeyError
        self._patch('ai_client.describe_settings',
                    return_value={'enabled': True, 'configured': True, 'reason': '',
                                  'model': 'test-model', 'style': 'responses',
                                  'base': 'https://api.example.com/v1',
                                  'key_masked': 'sk-***ey', 'key_source': '',
                                  'timeout': 7,
                                  'temperature': 0.3, 'max_tokens': 256})

    def _patch(self, target, **kwargs):
        """在 `views.ai_analysis` 上打补丁，并登记到 cleanup。"""
        patcher = mock.patch('views.ai_analysis.' + target, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _ok_result(self, text=None):
        return {'ok': True, 'status': 'ok',
                'text': text or json.dumps({'verdict': '增持', 'confidence': 66,
                                            'summary': '估值偏低', 'points': ['要点一'],
                                            'supports': ['支撑一'], 'risks': ['风险一']},
                                           ensure_ascii=False),
                'tokens': 123, 'model': 'test-model', 'error': ''}

    def _patch_ready(self, ready=True, reason=''):
        return mock.patch('views.ai_analysis.ai_client.is_ready', return_value=(ready, reason))


class AiViewTest(_AiViewSetup, unittest.TestCase):
    """视图层：一律 mock 数据访问与客户端，不连库、不发请求。"""

    def test_route_registered_and_login_required(self):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn('/stock/ai/', rules)
        self.assertIn('/stock/ai/analyze', rules)

        with self.client.session_transaction() as sess:
            sess.pop('user_id', None)
            sess.pop('username', None)
        resp = self.client.get('/stock/ai/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_page_renders_disabled_hint(self):
        with mock.patch('views.ai_analysis.StockMaster.get_all', return_value=([], 0)), \
                self._patch_ready(False, 'AI 分析未启用（AI_ENABLED=0）'):
            body = self.client.get('/stock/ai/').get_data(as_text=True)

        self.assertIn('AI 分析未启用', body)
        # 一只标的都没有时，明确告知用户先去录入，而不是给个空搜索框让人干瞪眼
        self.assertIn('暂无监控标的', body)

    def test_page_renders_report_card(self):
        """报告卡的每一块都得真的渲染出来：评级徽标 / 要点 / 支撑 / 风险 / 免责声明。"""
        stocks = [{'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001'}]
        report = {
            'id': 9, 'stock_master_id': 1, 'model': 'test-model',
            'prompt_version': PROMPT_VERSION, 'verdict': '增持', 'confidence': 66,
            'tokens_used': 123, 'created_at': '2026-10-22 10:00:00',
            'content': {'summary': '估值偏低但趋势未确认', 'points': ['要点甲', '要点乙'],
                        'supports': ['支撑甲'], 'risks': ['风险甲'],
                        'disclaimer': DISCLAIMER, 'parsed': True,
                        'dimensions': ['估值', '技术面']},
        }
        with mock.patch('views.ai_analysis.StockMaster.get_all', return_value=(stocks, 1)), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[report]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        for text in ('增持', '估值偏低但趋势未确认', '要点甲', '支撑甲', '风险甲', DISCLAIMER):
            self.assertIn(text, body)
        # 工作台结构与报告头：标的条 / 评级大字 / 置信度条 / 本次使用的维度
        self.assertIn('ai-work', body)
        self.assertIn('ai-target', body)
        self.assertIn('report-head', body)
        self.assertIn('class="v up"', body)
        self.assertIn('置信度', body)
        self.assertIn('分析维度', body)
        # 页面不再渲染全量标的列表：只有搜索框，没有标的列表容器
        self.assertIn('data-ai-search', body)
        self.assertNotIn('ai-stock-list', body)

    def test_page_renders_qa_record(self):
        """追问记录走问答分支（问题 + 原文回答），不应渲染成评级报告。"""
        stocks = [{'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001'}]
        report = {
            'id': 10, 'stock_master_id': 1, 'model': 'test-model',
            'prompt_version': PROMPT_VERSION, 'verdict': '问答', 'confidence': None,
            'tokens_used': 50, 'created_at': '2026-10-22 11:00:00',
            'content': {'question': '该在哪档建仓？', 'answer': '建议分三档，第一档不要超过三成。'},
        }
        with mock.patch('views.ai_analysis.StockMaster.get_all', return_value=(stocks, 1)), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[report]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        self.assertIn('该在哪档建仓？', body)
        self.assertIn('第一档不要超过三成', body)
        self.assertIn('ai-qa-a', body)

    def test_page_has_search_box_and_rail_markup(self):
        """顶部搜索框必须存在且指向服务端搜索接口；右栏要能选模型和维度。"""
        snapshot = {'price': '21.5'}
        with mock.patch('views.ai_analysis.StockIndicator.get_latest',
                           return_value=snapshot), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        # 搜索框：容器 + 输入框 + 下拉容器 + 接口地址（服务端真搜索，不是前端过滤）
        self.assertIn('data-ai-search', body)
        self.assertIn('data-ai-input', body)
        self.assertIn('data-ai-menu', body)
        self.assertIn('data-url="/stock/ai/api/search"', body)
        self.assertIn('ai-combo', body)
        # 标的条渲染选中标的与最新价（来自指标快照），缺失位渲染 —
        self.assertIn('测试股', body)
        self.assertIn('SZ000001', body)
        self.assertIn('21.50', body)
        # 模型候选（AI_MODEL + AI_MODELS）都要出现在下拉里
        self.assertIn('name="model"', body)
        self.assertIn('value="test-model"', body)
        self.assertIn('value="alt-model"', body)
        # 维度 chips：保存的默认维度要被勾上
        self.assertIn('name="dimensions" value="valuation"', body)
        self.assertRegex(body, r'name="dimensions" value="valuation"[\s\S]{0,80}checked')
        self.assertIn('name="dimensions" value="risk"', body)

    def test_model_select_splits_comma_separated_ai_model(self):
        """AI_MODEL 填「a,b,c」时，下拉必须是多个独立选项，不能整串当一个模型。"""
        with mock.patch.object(Config, 'AI_MODEL', 'm-a,m-b,m-c'), \
                mock.patch.object(Config, 'AI_MODELS', ''), \
                mock.patch('views.ai_analysis.StockAiConfig.effective',
                           return_value=dict(self.config, model='')), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        for name in ('m-a', 'm-b', 'm-c'):
            self.assertIn('value="%s"' % name, body)
        # 默认选中第一项，页面显示的就是实际会发出去的那个
        self.assertIn('value="m-a" selected', body)
        self.assertIn('m-a · 默认', body)

    def test_stale_saved_model_falls_back_to_default(self):
        """库里存了清单外的模型（历史遗留的整串）→ 回退到默认模型，并在页面上说清楚。"""
        stale = dict(self.config, model='m-old,m-older')
        with mock.patch.object(Config, 'AI_MODEL', 'm-a,m-b'), \
                mock.patch('views.ai_analysis.StockAiConfig.effective', return_value=stale), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        self.assertIn('value="m-a" selected', body)
        self.assertIn('已回退', body)
        self.assertIn('不在候选清单内', body)

    def test_page_without_stock_shows_empty_state_not_full_list(self):
        """不带 ?stock_id= 时不再默认选中第一只，而是进入「未选标的」空态。"""
        with mock.patch('views.ai_analysis.StockMaster.get_all',
                        return_value=([{'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001'}], 1)), \
                mock.patch('views.ai_analysis.StockAiReport.list_recent', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/').get_data(as_text=True)

        self.assertIn('先选一只标的', body)
        self.assertIn('ai-catalog', body)
        # 能力卡片：五个维度各一张
        for label in ('估值', '技术面', '相对强弱', '52 周位置', '风险'):
            self.assertIn(label, body)
        # 空态下不渲染标的条，也不渲染历史 / 快照
        self.assertNotIn('ai-target', body)
        self.assertNotIn('历史分析', body)
        self.assertNotIn('指标快照', body)
        # 参数面板仍要渲染（未启用时用户得能保存参数）
        self.assertIn('id="ai-params"', body)

    def test_page_renders_recent_when_no_stock_selected(self):
        """未选标的时展示跨标的「最近分析」快捷入口。"""
        recent = [{'id': 7, 'stock_master_id': 3, 'verdict': '增持', 'confidence': 70,
                   'created_at': '2026-10-22 09:00:00',
                   'stock_name': '最近股', 'stock_code': 'SZ000009'}]
        with mock.patch('views.ai_analysis.StockAiReport.list_recent',
                           return_value=recent), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/').get_data(as_text=True)

        self.assertIn('最近分析', body)
        self.assertIn('最近股', body)
        self.assertIn('/stock/ai/?stock_id=3', body)

    def test_page_renders_snapshot_rail(self):
        """右栏快照：缺字段显示 —，K 线信号要有文案与语义色。"""
        snapshot = {'price': '21.00', 'pct_from_low52w': '1.67', 'drawdown_52w': None,
                    'rs_20d': '-18.00', 'rs_5d_ratio': '2.60', 'trade_date': '2026-10-22'}
        with mock.patch('views.ai_analysis.StockIndicator.get_latest',
                           return_value=snapshot), \
                mock.patch('views.ai_analysis.StockKline.get_latest_signal',
                           return_value='death_cross'), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        self.assertIn('指标快照', body)
        self.assertIn('距 52 周低', body)
        self.assertIn('死叉', body)
        self.assertIn('<b class="down">死叉</b>', body)
        # 52 周回撤缺失 → —，不能显示成 0.00%
        self.assertNotIn('0.00%', body)

    def test_target_bar_price_falls_back_to_warehouse(self):
        """指标快照没有 price 时，最新价取 stock_warehouse（与订单列表同一口径）。"""
        warehouse = mock.Mock(current_price=1310.05)   # 真实返回的是模型对象（属性访问）
        with mock.patch('views.ai_analysis.StockWarehouse.get_by_stock_master_id',
                        return_value=warehouse), \
                mock.patch('views.ai_analysis.StockIndicator.get_latest',
                           return_value={'trade_date': '2026-10-22', 'price': None}), \
                mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        self.assertIn('1310.05', body)

    def test_page_invalid_stock_id_falls_back_to_empty_state(self):
        """?stock_id= 指向不存在的标的时不 500，回到空态。"""
        with mock.patch('views.ai_analysis.StockMaster.get_by_id', return_value=None), \
                mock.patch('views.ai_analysis.StockAiReport.list_recent', return_value=[]), \
                self._patch_ready(True):
            resp = self.client.get('/stock/ai/?stock_id=999')

        self.assertEqual(resp.status_code, 200)
        self.assertIn('先选一只标的', resp.get_data(as_text=True))

    def test_action_buttons_disabled_when_not_ready(self):
        """未启用时按钮必须 disabled——点了必然失败的操作不该让用户白点一次。"""
        with mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(False, 'AI 分析未启用（AI_ENABLED=0）'):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        # 会发请求的入口必须禁用：生成分析
        self.assertIn('生成分析', body)
        analyze_btn = re.search(r'<button[^>]*formaction="/stock/ai/analyze"[^>]*>', body)
        self.assertIsNotNone(analyze_btn)
        self.assertIn('disabled', analyze_btn.group(0))

        # 连通测试按钮已从参数卡移除：入口唯一在 Composer，两处都放就不知道该点哪个
        params_card = body.split('id="ai-params"')[1].split('</form>')[0]
        self.assertNotIn('/stock/ai/test', params_card)
        self.assertNotIn('连通测试', params_card)

        # Composer：发送键禁用，但**密钥 / 测试入口必须一直可点**——
        # 没有密钥时正是要靠它录入，禁了就成了死锁（2026-10-23 变更）
        composer = body.split('class="ask-box"')[1].split('</form>')[0]
        send_btn = re.search(r'class="ask-send"[^>]*>', composer)
        self.assertIsNotNone(send_btn)
        self.assertIn('disabled', send_btn.group(0))
        comp_test = re.search(r'<button[^>]*formaction="/stock/ai/test"[^>]*>', composer)
        self.assertIsNotNone(comp_test)
        self.assertNotIn('disabled', comp_test.group(0))
        # 保存参数是纯写库操作，未启用也得能保存
        save_btn = re.search(r'<button[^>]*formaction="/stock/ai/config"[^>]*>', body)
        self.assertIsNotNone(save_btn)
        self.assertNotIn('disabled', save_btn.group(0))

    def test_analyze_blocked_when_not_ready(self):
        with mock.patch('views.ai_analysis.StockAiConfig.effective', return_value=self.config), \
                self._patch_ready(False, 'AI 未配置'), \
                mock.patch('views.ai_analysis.ai_client.call_ai') as call, \
                mock.patch('views.ai_analysis.StockAiReport.create') as create:
            resp = self.client.post('/stock/ai/analyze', data={'stock_id': '1'})

        self.assertEqual(resp.status_code, 302)
        call.assert_not_called()
        create.assert_not_called()

    def test_analyze_blocked_by_monthly_limit(self):
        with mock.patch('views.ai_analysis.StockAiConfig.effective', return_value=self.config), \
                self._patch_ready(True), \
                mock.patch('views.ai_analysis.StockAiReport.count_since', return_value=10), \
                mock.patch('views.ai_analysis.ai_client.call_ai') as call:
            resp = self.client.post('/stock/ai/analyze', data={'stock_id': '1'}, follow_redirects=True)

        call.assert_not_called()
        self.assertIn('本月调用已达上限', resp.get_data(as_text=True))

    def test_analyze_success_saves_report(self):
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.ai_client.call_ai',
                           return_value=self._ok_result()) as call, \
                mock.patch('views.ai_analysis.StockAiReport.create',
                           return_value=77) as create:
            resp = self.client.post('/stock/ai/analyze', data={
                'stock_id': '1', 'model': 'alt-model',
                'dimensions': ['valuation', 'risk'],
            })

        self.assertEqual(resp.status_code, 302)
        self.assertIn('report_id=77', resp.headers['Location'])
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['verdict'], '增持')
        self.assertEqual(kwargs['confidence'], 66.0)
        self.assertEqual(kwargs['model'], 'test-model')
        self.assertEqual(kwargs['prompt_version'], PROMPT_VERSION)
        self.assertEqual(kwargs['tokens_used'], 123)
        self.assertEqual(kwargs['content']['summary'], '估值偏低')
        # 页面选的模型与维度必须真的作用到本次调用，而不是只写在界面上
        self.assertEqual(call.call_args.kwargs['model'], 'alt-model')
        self.assertEqual(call.call_args.kwargs['max_tokens'], 256)
        user_prompt = call.call_args.args[0][-1]['content']
        self.assertIn('本次要求的分析维度：估值、风险', user_prompt)
        self.assertEqual(kwargs['content']['dimension_keys'], ['valuation', 'risk'])
        self.assertEqual(kwargs['content']['dimensions'], ['估值', '风险'])

    def test_analyze_rejects_unknown_model(self):
        """模型是环境变量白名单：伪造的 model 不能把请求打到未知模型。"""
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.ai_client.call_ai') as call, \
                mock.patch('views.ai_analysis.StockAiReport.create') as create:
            resp = self.client.post('/stock/ai/analyze', data={
                'stock_id': '1', 'model': 'evil-model'}, follow_redirects=True)

        call.assert_not_called()
        create.assert_not_called()
        self.assertIn('模型不可用', resp.get_data(as_text=True))

    def test_analyze_defaults_to_saved_model_and_dimensions(self):
        """表单没带模型/维度时，用参数面板里保存的默认值，不硬编码。"""
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.ai_client.call_ai',
                           return_value=self._ok_result()) as call, \
                mock.patch('views.ai_analysis.StockAiReport.create', return_value=1):
            self.client.post('/stock/ai/analyze', data={'stock_id': '1'})

        self.assertEqual(call.call_args.kwargs['model'], 'test-model')
        self.assertIn('本次要求的分析维度：估值、技术面', call.call_args.args[0][-1]['content'])

    def test_analyze_unparsed_response_still_saved(self):
        result = self._ok_result(text='模型没有按格式返回')
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.ai_client.call_ai', return_value=result), \
                mock.patch('views.ai_analysis.StockAiReport.create', return_value=88) as create:
            resp = self.client.post('/stock/ai/analyze', data={'stock_id': '1'},
                                    follow_redirects=True)

        self.assertEqual(create.call_args.kwargs['verdict'], '未知')
        self.assertIn('未按约定格式返回', resp.get_data(as_text=True))

    def test_analyze_failure_does_not_write(self):
        failure = {'ok': False, 'status': 'timeout', 'text': '', 'tokens': 0,
                   'model': 'test-model', 'error': '调用超时（60 秒）'}
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.ai_client.call_ai', return_value=failure), \
                mock.patch('views.ai_analysis.StockAiReport.create') as create:
            resp = self.client.post('/stock/ai/analyze', data={'stock_id': '1'},
                                    follow_redirects=True)

        create.assert_not_called()
        self.assertIn('调用超时', resp.get_data(as_text=True))

    def test_ask_requires_previous_analysis(self):
        with mock.patch('views.ai_analysis.StockAiConfig.effective', return_value=self.config), \
                self._patch_ready(True), \
                mock.patch('views.ai_analysis.StockAiReport.latest_analysis', return_value=None), \
                mock.patch('views.ai_analysis.ai_client.call_ai') as call:
            resp = self.client.post('/stock/ai/ask', data={'stock_id': '1', 'question': '加仓吗？'},
                                    follow_redirects=True)
        call.assert_not_called()
        self.assertIn('请先生成一次分析', resp.get_data(as_text=True))

    def test_ask_saves_qa_record(self):
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.StockAiReport.latest_analysis',
                           return_value={'id': 5, 'verdict': '增持', 'content': {'summary': 'x'}}), \
                mock.patch('views.ai_analysis.ai_client.call_ai',
                           return_value=self._ok_result(text='建议分三档建仓')), \
                mock.patch('views.ai_analysis.StockAiReport.create', return_value=99) as create:
            resp = self.client.post('/stock/ai/ask',
                                    data={'stock_id': '1', 'question': '该在哪档建仓？'})

        self.assertIn('report_id=99', resp.headers['Location'])
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['verdict'], '问答')
        self.assertEqual(kwargs['content']['question'], '该在哪档建仓？')
        self.assertIn('分三档建仓', kwargs['content']['answer'])

    def test_ask_rejects_empty_question(self):
        with mock.patch('views.ai_analysis.StockAiConfig.effective', return_value=self.config), \
                self._patch_ready(True), \
                mock.patch('views.ai_analysis.ai_client.call_ai') as call:
            resp = self.client.post('/stock/ai/ask', data={'stock_id': '1', 'question': '  '},
                                    follow_redirects=True)
        call.assert_not_called()
        self.assertIn('不能为空', resp.get_data(as_text=True))

    def test_config_saved(self):
        with mock.patch('views.ai_analysis.StockAiConfig.upsert', return_value=True) as upsert:
            resp = self.client.post('/stock/ai/config', data={
                'stock_id': '1', 'enabled': '1', 'temperature': '0.4',
                'max_tokens': '800', 'monthly_limit': '50',
                'data_scope': ['quote', 'kline'],
                'model': 'alt-model', 'dimensions': ['valuation', 'risk'],
            })
        self.assertEqual(resp.status_code, 302)
        payload = upsert.call_args.kwargs
        self.assertEqual(payload['temperature'], 0.4)
        self.assertEqual(payload['max_tokens'], 800)
        self.assertEqual(payload['data_scope'], 'quote,kline')
        self.assertEqual(payload['enabled'], 1)
        self.assertEqual(payload['model'], 'alt-model')
        self.assertEqual(payload['dimensions'], 'valuation,risk')

    def test_config_rejects_unknown_model(self):
        with mock.patch('views.ai_analysis.StockAiConfig.upsert', return_value=True) as upsert:
            resp = self.client.post('/stock/ai/config', data={
                'temperature': '0.4', 'data_scope': ['quote'],
                'model': 'evil-model', 'dimensions': ['risk'],
            }, follow_redirects=True)
        upsert.assert_not_called()
        self.assertIn('所选模型不在可选清单内', resp.get_data(as_text=True))

    def test_config_rejects_out_of_range(self):
        with mock.patch('views.ai_analysis.StockAiConfig.upsert', return_value=True) as upsert:
            resp = self.client.post('/stock/ai/config', data={
                'temperature': '5', 'max_tokens': '10', 'monthly_limit': 'x',
                'data_scope': ['quote'], 'dimensions': ['risk'],
            }, follow_redirects=True)

        upsert.assert_not_called()
        body = resp.get_data(as_text=True)
        self.assertIn('温度需在', body)
        self.assertIn('单次最大 Token需在', body)
        self.assertIn('月度调用上限必须是整数', body)

    def test_config_requires_scope(self):
        with mock.patch('views.ai_analysis.StockAiConfig.upsert', return_value=True) as upsert:
            resp = self.client.post('/stock/ai/config', data={
                'temperature': '0.5', 'dimensions': ['risk']}, follow_redirects=True)
        upsert.assert_not_called()
        self.assertIn('至少选择一项引用数据范围', resp.get_data(as_text=True))

    def test_config_requires_dimension(self):
        with mock.patch('views.ai_analysis.StockAiConfig.upsert', return_value=True) as upsert:
            resp = self.client.post('/stock/ai/config', data={
                'temperature': '0.5', 'data_scope': ['quote']}, follow_redirects=True)
        upsert.assert_not_called()
        self.assertIn('至少选择一个分析维度', resp.get_data(as_text=True))

    def test_connectivity_test_reports_result(self):
        ok = {'ok': True, 'status': 'ok', 'text': 'OK', 'tokens': 4,
              'model': 'test-model', 'error': '', 'latency_ms': 321}
        with mock.patch('views.ai_analysis.ai_client.test_connection', return_value=ok):
            resp = self.client.post('/stock/ai/test', data={'stock_id': '1'},
                                    follow_redirects=True)
        body = resp.get_data(as_text=True)
        self.assertIn('连通正常', body)
        self.assertIn('321 ms', body)

    def test_connectivity_test_failure_shows_status(self):
        bad = {'ok': False, 'status': 'disabled', 'text': '', 'tokens': 0,
               'model': '', 'error': 'AI 分析未启用', 'latency_ms': 0}
        with mock.patch('views.ai_analysis.ai_client.test_connection', return_value=bad):
            resp = self.client.post('/stock/ai/test', data={}, follow_redirects=True)
        self.assertIn('连通失败（disabled）', resp.get_data(as_text=True))

    def test_page_shows_secret_masked_only(self):
        with mock.patch('views.ai_analysis.StockAiReport.list_by_stock', return_value=[]), \
                self._patch_ready(True):
            body = self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

        self.assertIn('sk-***ey', body)
        self.assertNotIn(SECRET, body)


class AiComposerTest(_AiViewSetup, unittest.TestCase):
    """Composer（追问框）：模型选择真实下发、密钥就地录入与连通测试（2026-10-23）。"""

    def _report(self):
        return {
            'id': 9, 'stock_master_id': 1, 'model': 'test-model',
            'prompt_version': PROMPT_VERSION, 'verdict': '增持', 'confidence': 66,
            'tokens_used': 123, 'created_at': '2026-10-23 10:00:00',
            'content': {'summary': '估值偏低', 'points': ['要点甲'],
                        'supports': ['支撑甲'], 'risks': ['风险甲'],
                        'disclaimer': DISCLAIMER, 'parsed': True},
        }

    def _body(self):
        with mock.patch('views.ai_analysis.StockAiReport.list_by_stock',
                        return_value=[self._report()]), self._patch_ready(True):
            return self.client.get('/stock/ai/?stock_id=1').get_data(as_text=True)

    def test_composer_structure(self):
        body = self._body()
        # 输入 + 底部工具条（模型 pill / 测试连通性 pill）+ 圆形发送 + 密钥面板
        self.assertIn('class="ask-box"', body)
        self.assertIn('class="ask-input"', body)
        self.assertIn('给 test-model 发送消息', body)
        self.assertIn('class="ask-select" name="model"', body)
        self.assertIn('class="ask-send"', body)
        self.assertIn('data-ask-key-panel', body)
        self.assertIn('name="api_key"', body)
        # 连通测试的入口只有一个：Composer 里名为「测试连通性」的 pill
        pill = re.search(r'<button[^>]*data-ask-key[^>]*>(.*?)</button>', body, re.S)
        self.assertIsNotNone(pill)
        self.assertIn('测试连通性', pill.group(1))
        self.assertIn('#i-refresh', pill.group(1))
        # 追问框不再用旧的一行式 input
        self.assertNotIn('class="ask-bar"', body)

    def test_key_panel_shows_masked_key(self):
        """密钥脱敏值随入口一起显示，不用再跑到右栏找。"""
        body = self._body()
        self.assertIn('当前密钥 sk-***ey', body)
        self.assertNotIn(SECRET, body)

    def test_test_entry_only_in_composer(self):
        """参数卡不再放连通测试按钮——两处都放会让人不知道该点哪个（2026-10-23）。"""
        body = self._body()
        params_card = body.split('id="ai-params"')[1].split('</form>')[0]
        self.assertNotIn('/stock/ai/test', params_card)
        self.assertNotIn('连通测试', params_card)
        self.assertIn('测试在底部对话框', params_card)

    def test_model_options_come_from_config(self):
        body = self._body()
        for name in ('test-model', 'alt-model'):
            self.assertIn('value="%s"' % name, body)
        self.assertRegex(body, r'<option value="test-model"\s+selected')

    def test_ask_uses_composer_model(self):
        """Composer 选的模型必须真的发出去，并记进历史（不是只写在界面上）。"""
        result = dict(self._ok_result(text='建议分三档建仓'), model='alt-model')
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.StockAiReport.latest_analysis',
                           return_value={'id': 5, 'verdict': '增持', 'content': {'summary': 'x'}}), \
                mock.patch('views.ai_analysis.ai_client.call_ai', return_value=result) as call, \
                mock.patch('views.ai_analysis.StockAiReport.create', return_value=99) as create:
            self.client.post('/stock/ai/ask', data={
                'stock_id': '1', 'question': '加仓吗？', 'model': 'alt-model'})

        self.assertEqual(call.call_args.kwargs['model'], 'alt-model')
        self.assertEqual(create.call_args.kwargs['model'], 'alt-model')

    def test_ask_rejects_unknown_model(self):
        with self._patch_ready(True), \
                mock.patch('views.ai_analysis.StockAiReport.latest_analysis',
                           return_value={'id': 5, 'verdict': '增持', 'content': {}}), \
                mock.patch('views.ai_analysis.ai_client.call_ai') as call:
            resp = self.client.post('/stock/ai/ask', data={
                'stock_id': '1', 'question': '加仓吗？', 'model': 'evil-model'},
                follow_redirects=True)

        call.assert_not_called()
        self.assertIn('模型不可用', resp.get_data(as_text=True))

    def test_test_route_saves_runtime_key_and_uses_model(self):
        ok = {'ok': True, 'status': 'ok', 'text': 'OK', 'tokens': 4,
              'model': 'alt-model', 'error': '', 'latency_ms': 120}
        with mock.patch('views.ai_analysis.ai_client.test_connection', return_value=ok) as test, \
                mock.patch('views.ai_analysis.ai_client.set_runtime_key') as set_key:
            resp = self.client.post('/stock/ai/test', data={
                'api_key': 'sk-runtime-secret-123', 'model': 'alt-model'},
                follow_redirects=True)

        set_key.assert_called_once_with('sk-runtime-secret-123')
        self.assertEqual(test.call_args.kwargs['model'], 'alt-model')
        body = resp.get_data(as_text=True)
        self.assertIn('已保存密钥到本次运行', body)
        self.assertIn('连通正常', body)
        # 录入的密钥绝不回显
        self.assertNotIn('sk-runtime-secret-123', body)

    def test_test_route_without_key_only_tests(self):
        """不填密钥就只是测当前配置，不能顺手把已有密钥清空。"""
        ok = {'ok': True, 'status': 'ok', 'text': 'OK', 'tokens': 4,
              'model': 'test-model', 'error': '', 'latency_ms': 90}
        with mock.patch('views.ai_analysis.ai_client.test_connection', return_value=ok), \
                mock.patch('views.ai_analysis.ai_client.set_runtime_key') as set_key:
            self.client.post('/stock/ai/test', data={'stock_id': '1'}, follow_redirects=True)

        set_key.assert_not_called()

    def test_test_route_clear_key(self):
        with mock.patch('views.ai_analysis.ai_client.clear_runtime_key') as clear, \
                mock.patch('views.ai_analysis.ai_client.test_connection') as test:
            resp = self.client.post('/stock/ai/test', data={'clear_key': '1'},
                                    follow_redirects=True)

        clear.assert_called_once_with()
        test.assert_not_called()
        self.assertIn('恢复使用环境变量', resp.get_data(as_text=True))

    def test_test_route_rejects_unknown_model(self):
        """Composer 里被篡改成清单外的模型名时，连测试都不发。"""
        with mock.patch('views.ai_analysis.ai_client.test_connection') as test:
            resp = self.client.post('/stock/ai/test', data={'model': 'evil-model'},
                                    follow_redirects=True)

        test.assert_not_called()
        self.assertIn('所选模型不在可选清单内', resp.get_data(as_text=True))


class RuntimeKeyTest(AiClientBase):
    """运行时密钥：只存进程内存，录入即生效；不落库、不回显、不进日志。"""

    def setUp(self):
        super().setUp()
        ai_client.clear_runtime_key()
        self.addCleanup(ai_client.clear_runtime_key)

    def test_runtime_key_makes_ready(self):
        self.enter_config(AI_API_KEY='')
        self.assertFalse(ai_client.is_ready()[0])

        ai_client.set_runtime_key('sk-runtime-key-123')
        self.assertTrue(ai_client.is_ready()[0])
        info = ai_client.describe_settings()
        self.assertEqual(info['key_source'], 'runtime')
        self.assertEqual(info['key_masked'], 'sk-***23')

    def test_runtime_key_overrides_env_key(self):
        self.enter_config(AI_API_KEY='env-key-value')
        ai_client.set_runtime_key('runtime-key-value')

        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse({'output_text': 'OK', 'usage': {}})) as post:
            ai_client.call_ai([{'role': 'user', 'content': 'hi'}])

        auth = post.call_args.kwargs['headers']['Authorization']
        self.assertEqual(auth, 'Bearer runtime-key-value')

    def test_clear_runtime_key_restores_env(self):
        self.enter_config(AI_API_KEY='env-key-value')
        ai_client.set_runtime_key('runtime-key-value')
        ai_client.clear_runtime_key()

        self.assertFalse(ai_client.runtime_key_configured())
        self.assertEqual(ai_client.describe_settings()['key_source'], 'env')
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse({'output_text': 'OK', 'usage': {}})) as post:
            ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'],
                         'Bearer env-key-value')

    def test_runtime_key_never_leaks_in_return_value(self):
        self.enter_config(AI_API_KEY='')
        secret = 'sk-runtime-should-not-leak'
        ai_client.set_runtime_key(secret)
        info = ai_client.describe_settings()
        self.assertNotIn(secret, json.dumps(info, ensure_ascii=False))

    def test_runtime_key_never_leaks_in_logs(self):
        self.enter_config(AI_API_KEY='')
        secret = 'sk-runtime-should-not-leak'
        ai_client.set_runtime_key(secret)
        with mock.patch('utils.ai_client.requests.post',
                        return_value=_FakeResponse('boom', status_code=401)):
            with self.assertLogs('utils.ai_client', level='ERROR') as logs:
                ai_client.call_ai([{'role': 'user', 'content': 'hi'}])
        self.assertTrue(logs.output)
        self.assertNotIn(secret, '\n'.join(logs.output))

    def test_test_connection_passes_model(self):
        self.enter_config(AI_API_KEY='env-key-value')
        with mock.patch('utils.ai_client.call_ai',
                        return_value={'ok': True, 'status': 'ok', 'text': 'OK',
                                      'tokens': 4, 'model': 'alt', 'error': ''}) as call:
            ai_client.test_connection(model='alt')
        self.assertEqual(call.call_args.kwargs['model'], 'alt')
        self.assertEqual(call.call_args.kwargs['max_tokens'], 16)


class AiSearchApiTest(unittest.TestCase):
    """标的搜索接口：必须真查库，且空关键字不能退化成"返回全部"。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'tester'
        # 现价批量查询默认给空（走指标快照兜底），需要覆盖的用例自己 patch
        patcher = mock.patch('views.ai_analysis.StockMaster.get_quotes_by_ids', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_login_required(self):
        with self.client.session_transaction() as sess:
            sess.pop('user_id', None)
            sess.pop('username', None)
        resp = self.client.get('/stock/ai/api/search?q=600')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_empty_keyword_returns_nothing_without_query(self):
        """q 为空直接返回空：否则又变回"页面铺全量标的"。"""
        with mock.patch('views.ai_analysis.StockMaster.get_all') as get_all:
            resp = self.client.get('/stock/ai/api/search?q=')

        get_all.assert_not_called()
        self.assertEqual(resp.get_json(), {'items': [], 'total': 0, 'truncated': False})

    def test_keyword_hits_name_and_code_via_parameterized_search(self):
        rows = [{'id': 3, 'stock_name': '贵州茅台', 'stock_code': 'SH600519'}]
        with mock.patch('views.ai_analysis.StockMaster.get_all',
                        return_value=(rows, 1)) as get_all, \
                mock.patch('views.ai_analysis.StockIndicator.get_latest_batch',
                           return_value={3: {'price': '1688.00'}}):
            resp = self.client.get('/stock/ai/api/search?q=600519')

        # 关键字必须原样传给模型层（LIKE 参数化在那里完成），不走字符串拼接
        self.assertEqual(get_all.call_args.kwargs['search_query'], '600519')
        data = resp.get_json()
        self.assertEqual(data['total'], 1)
        self.assertFalse(data['truncated'])
        self.assertEqual(data['items'], [{
            'id': 3, 'name': '贵州茅台', 'code': 'SH600519',
            'price': 1688.0, 'url': '/stock/ai/?stock_id=3',
        }])

    def test_price_prefers_warehouse_over_indicator_snapshot(self):
        """现价以 stock_warehouse 为准（与订单列表一致），指标快照只作兜底。"""
        rows = [{'id': 3, 'stock_name': '贵州茅台', 'stock_code': 'SH600519'}]
        with mock.patch('views.ai_analysis.StockMaster.get_all', return_value=(rows, 1)), \
                mock.patch('views.ai_analysis.StockIndicator.get_latest_batch',
                           return_value={3: {'price': '1600.00'}}), \
                mock.patch('views.ai_analysis.StockMaster.get_quotes_by_ids',
                           return_value=[{'id': 3, 'current_price': '1688.00'}]):
            data = self.client.get('/stock/ai/api/search?q=茅台').get_json()

        self.assertEqual(data['items'][0]['price'], 1688.0)

    def test_price_missing_is_null_not_zero(self):
        rows = [{'id': 4, 'stock_name': '无快照股', 'stock_code': 'SZ000004'}]
        with mock.patch('views.ai_analysis.StockMaster.get_all', return_value=(rows, 1)), \
                mock.patch('views.ai_analysis.StockIndicator.get_latest_batch', return_value={}):
            data = self.client.get('/stock/ai/api/search?q=无').get_json()

        self.assertIsNone(data['items'][0]['price'])

    def test_truncated_flag_when_more_than_page(self):
        rows = [{'id': i, 'stock_name': f'股{i}', 'stock_code': f'SZ00000{i}'} for i in range(1, 13)]
        with mock.patch('views.ai_analysis.StockMaster.get_all', return_value=(rows, 91)), \
                mock.patch('views.ai_analysis.StockIndicator.get_latest_batch', return_value={}):
            data = self.client.get('/stock/ai/api/search?q=股').get_json()

        self.assertTrue(data['truncated'])
        self.assertEqual(data['total'], 91)

    def test_search_failure_returns_deterministic_error(self):
        """查询失败要可判定：记日志 + 500 + error 字段，不能静默返回空。"""
        with mock.patch('views.ai_analysis.StockMaster.get_all',
                        side_effect=RuntimeError('db down')):
            resp = self.client.get('/stock/ai/api/search?q=600')

        self.assertEqual(resp.status_code, 500)
        self.assertIn('搜索失败', resp.get_json()['error'])

    def test_long_keyword_is_truncated(self):
        with mock.patch('views.ai_analysis.StockMaster.get_all',
                        return_value=([], 0)) as get_all:
            self.client.get('/stock/ai/api/search?q=' + ('A' * 100))

        self.assertEqual(len(get_all.call_args.kwargs['search_query']),
                         len('A' * 32))


if __name__ == '__main__':
    unittest.main()
