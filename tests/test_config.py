"""
配置加载与启动自检测试（D-01 / D-02）。

config 在导入时读取环境变量，因此这里通过 patch os.environ + reload 来覆盖各种取值。
"""
import importlib
import os
import tempfile
import unittest
from unittest import mock

import config as config_module


class ParseHelpersTest(unittest.TestCase):
    def test_get_int_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('X_INT', None)
            self.assertEqual(config_module._get_int('X_INT', 7), 7)

    def test_get_int_valid(self):
        with mock.patch.dict(os.environ, {'X_INT': '42'}):
            self.assertEqual(config_module._get_int('X_INT', 7), 42)

    def test_get_int_invalid_falls_back(self):
        with mock.patch.dict(os.environ, {'X_INT': 'abc'}):
            self.assertEqual(config_module._get_int('X_INT', 7), 7)

    def test_get_float_invalid_falls_back(self):
        with mock.patch.dict(os.environ, {'X_FLOAT': 'x'}):
            self.assertEqual(config_module._get_float('X_FLOAT', 1.5), 1.5)

    def test_get_bool_variants(self):
        for raw in ('1', 'true', 'TRUE', 'yes', 'on'):
            with mock.patch.dict(os.environ, {'X_BOOL': raw}):
                self.assertTrue(config_module._get_bool('X_BOOL', False), raw)
        for raw in ('0', 'false', 'no', 'off'):
            with mock.patch.dict(os.environ, {'X_BOOL': raw}):
                self.assertFalse(config_module._get_bool('X_BOOL', True), raw)

    def test_get_bool_empty_value_falls_back_to_default(self):
        """空值按"未设置"处理，与应用其它配置项的语义保持一致。"""
        with mock.patch.dict(os.environ, {'X_BOOL': ''}):
            self.assertTrue(config_module._get_bool('X_BOOL', True))
            self.assertFalse(config_module._get_bool('X_BOOL', False))

    def test_get_list_splits_and_filters(self):
        with mock.patch.dict(os.environ, {'X_LIST': 'a@b.com, c@d.com ,, e@f.com'}):
            self.assertEqual(
                config_module._get_list('X_LIST'),
                ['a@b.com', 'c@d.com', 'e@f.com'],
            )

    def test_get_list_accepts_semicolon(self):
        with mock.patch.dict(os.environ, {'X_LIST': 'a@b.com;c@d.com'}):
            self.assertEqual(config_module._get_list('X_LIST'), ['a@b.com', 'c@d.com'])

    def test_get_list_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('X_LIST', None)
            self.assertEqual(config_module._get_list('X_LIST', ['d@e.com']), ['d@e.com'])

    def test_empty_env_uses_default(self):
        with mock.patch.dict(os.environ, {'X_STR': '   '}, clear=False):
            self.assertEqual(config_module._get_str('X_STR', 'fallback'), 'fallback')


class DotenvLoaderTest(unittest.TestCase):
    def test_loads_key_value_pairs(self):
        content = "# comment\nA=1\nB = two \nC=\"quoted\"\n\nINVALID LINE\n"
        with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False, encoding='utf-8') as fp:
            fp.write(content)
            path = fp.name
        try:
            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = config_module.load_dotenv(path)
                self.assertEqual(loaded['A'], '1')
                self.assertEqual(loaded['B'], 'two')
                self.assertEqual(loaded['C'], 'quoted')
                self.assertNotIn('INVALID LINE', loaded)
                self.assertEqual(os.environ['A'], '1')
        finally:
            os.remove(path)

    def test_does_not_override_existing_env(self):
        with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False, encoding='utf-8') as fp:
            fp.write('KEEP=from_file\n')
            path = fp.name
        try:
            with mock.patch.dict(os.environ, {'KEEP': 'from_env'}, clear=True):
                config_module.load_dotenv(path)
                self.assertEqual(os.environ['KEEP'], 'from_env')
        finally:
            os.remove(path)

    def test_missing_file_is_ignored(self):
        self.assertEqual(config_module.load_dotenv('/nonexistent/path/.env'), {})


class RecipientsTest(unittest.TestCase):
    def test_filters_invalid_entries(self):
        with mock.patch.dict(os.environ, {'ALARM_RECIPIENTS': 'ok@x.com,,bad,nope@y.com '}, clear=True):
            self.assertEqual(config_module.get_alarm_recipients(), ['ok@x.com', 'nope@y.com'])

    def test_empty_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('ALARM_RECIPIENTS', None)
            self.assertEqual(config_module.get_alarm_recipients(), [])


class StartupSelfCheckTest(unittest.TestCase):
    """生产启动自检：缺凭据必须报错而不是带空值继续跑。"""

    REQUIRED = (
        'MYSQL_PASSWORD', 'SECRET_KEY', 'XUEQIU_TOKEN',
        'MAIL_USERNAME', 'MAIL_PASSWORD', 'ALARM_RECIPIENTS',
    )

    def test_missing_all_reports_every_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            missing = config_module.missing_required_settings()
            for key in self.REQUIRED:
                self.assertTrue(any(key in item for item in missing), key)

    def test_all_present_reports_nothing(self):
        env = {
            'MYSQL_PASSWORD': 'x', 'SECRET_KEY': 'y', 'XUEQIU_TOKEN': 'z',
            'MAIL_USERNAME': 'a@b.com', 'MAIL_PASSWORD': 'p',
            'ALARM_RECIPIENTS': 'r@e.com',
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config_module.missing_required_settings(), [])

    def test_strict_raises_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                config_module.validate_runtime_settings(strict=True)

    def test_non_strict_passes_when_complete(self):
        env = {
            'MYSQL_PASSWORD': 'x', 'SECRET_KEY': 'y', 'XUEQIU_TOKEN': 'z',
            'MAIL_USERNAME': 'a@b.com', 'MAIL_PASSWORD': 'p',
            'ALARM_RECIPIENTS': 'r@e.com',
        }
        with mock.patch.dict(os.environ, env, clear=True):
            ok, problems = config_module.validate_runtime_settings(strict=False)
            self.assertTrue(ok)
            self.assertEqual(problems, [])

    def test_empty_recipients_flagged_even_if_key_present(self):
        env = {
            'MYSQL_PASSWORD': 'x', 'SECRET_KEY': 'y', 'XUEQIU_TOKEN': 'z',
            'MAIL_USERNAME': 'a@b.com', 'MAIL_PASSWORD': 'p',
            'ALARM_RECIPIENTS': ',,',
        }
        with mock.patch.dict(os.environ, env, clear=True):
            ok, problems = config_module.validate_runtime_settings(strict=False)
            self.assertFalse(ok)
            self.assertTrue(any('收件人' in p for p in problems))


class NoHardcodedSecretTest(unittest.TestCase):
    """D-01 红线：源码中不得再出现历史明文凭据。"""

    FORBIDDEN = ('YourStrongPassword123', 'tlwbbckrwafceiij', 'ca35d6d2fa5e735759056fc62797546c18062188')

    def test_config_source_has_no_plaintext_secret(self):
        source_path = config_module.__file__
        with open(source_path, 'r', encoding='utf-8') as fp:
            source = fp.read()
        for secret in self.FORBIDDEN:
            self.assertNotIn(secret, source, f'config.py 仍包含明文凭据: {secret[:6]}***')

    def test_secret_key_default_is_placeholder(self):
        """未配置 SECRET_KEY 时必须是明显的占位值，而不是可用的随机密钥。

        注意：本进程可能已通过 .env 注入真实 SECRET_KEY，因此这里直接断言源码中的默认值，
        而不是读取运行时的 Config.SECRET_KEY。
        """
        with open(config_module.__file__, 'r', encoding='utf-8') as fp:
            source = fp.read()
        self.assertIn('dev-insecure-secret-key-please-override', source)
        self.assertNotIn('eb55d0212571d3c4a30e0dbefd256a78006bf88314834289e84f921a8185e1e2', source)


class ReloadWithEnvTest(unittest.TestCase):
    """确认配置确实来自环境变量而不是硬编码。"""

    def test_config_class_reads_env(self):
        env = {
            'MYSQL_PASSWORD': 'x', 'SECRET_KEY': 'from-env-secret',
            'XUEQIU_TOKEN': 'tok', 'MAIL_USERNAME': 'a@b.com',
            'MAIL_PASSWORD': 'p', 'ALARM_RECIPIENTS': 'r@e.com',
            'MONITOR_MAX_WORKERS': '3', 'ALARM_COOLDOWN_SECONDS': '600',
            'FLASK_DEBUG': '1',
        }
        with mock.patch.dict(os.environ, env, clear=True):
            reloaded = importlib.reload(config_module)
            try:
                self.assertEqual(reloaded.Config.SECRET_KEY, 'from-env-secret')
                self.assertEqual(reloaded.Config.MONITOR_MAX_WORKERS, 3)
                self.assertEqual(reloaded.Config.ALARM_COOLDOWN_SECONDS, 600)
                self.assertTrue(reloaded.Config.DEBUG)
                self.assertEqual(reloaded.XueqiuToken.TOKEN, 'tok')
            finally:
                importlib.reload(config_module)


if __name__ == '__main__':
    unittest.main()
