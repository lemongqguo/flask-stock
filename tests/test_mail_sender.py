"""
邮件发送前置校验测试（D-02）。

只验证"不该发的时候明确失败"，不发起真实 SMTP 连接。
"""
import unittest
from unittest import mock

from utils import mail_sender


class SendMailGuardTest(unittest.TestCase):
    def test_empty_recipients_returns_false(self):
        self.assertFalse(mail_sender.send_mail('t', 'b', []))

    def test_none_recipients_returns_false(self):
        self.assertFalse(mail_sender.send_mail('t', 'b', None))

    def test_blank_string_recipients_returns_false(self):
        """原始缺陷就是 EMAIL_RECEIVED = [""]，必须被拦住。"""
        self.assertFalse(mail_sender.send_mail('t', 'b', ['']))
        self.assertFalse(mail_sender.send_mail('t', 'b', ['', '  ']))

    def test_invalid_address_is_dropped(self):
        self.assertFalse(mail_sender.send_mail('t', 'b', ['not-an-email']))

    @mock.patch('utils.mail_sender.smtplib.SMTP_SSL')
    def test_valid_recipient_triggers_send(self, mock_smtp):
        server = mock_smtp.return_value
        ok = mail_sender.send_mail(
            'subject', 'body', ['a@example.com'],
            sender='from@example.com', password='secret',
        )
        self.assertTrue(ok)
        server.login.assert_called_once_with('from@example.com', 'secret')
        server.sendmail.assert_called_once()

    @mock.patch('utils.mail_sender.smtplib.SMTP_SSL')
    def test_smtp_exception_returns_false(self, mock_smtp):
        mock_smtp.return_value.login.side_effect = RuntimeError('boom')
        self.assertFalse(
            mail_sender.send_mail(
                'subject', 'body', ['a@example.com'],
                sender='from@example.com', password='secret',
            )
        )

    def test_missing_credentials_returns_false(self):
        with mock.patch.object(mail_sender.Config, 'MAIL_USERNAME', ''):
            with mock.patch.object(mail_sender.Config, 'MAIL_PASSWORD', ''):
                self.assertFalse(mail_sender.send_mail('t', 'b', ['a@example.com']))


if __name__ == '__main__':
    unittest.main()
