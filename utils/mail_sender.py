"""
邮件发送工具。

D-02 / D-11 修复：
- 发送前校验收件人，收件人为空时明确失败并记录日志，不再静默 print；
- 连接加超时，避免 SMTP 卡死拖住监控线程；
- 用 logger 替代 print，异常记录堆栈。
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import Config

logger = logging.getLogger(__name__)


def send_mail(subject, body, recipients, sender=None, password=None):
    """
    发送邮件。

    :param subject: 邮件主题
    :param body: 邮件正文（纯文本）
    :param recipients: 收件人列表，不能为空
    :param sender: 发件人邮箱，缺省取配置 MAIL_USERNAME
    :param password: 发件人授权码，缺省取配置 MAIL_PASSWORD
    :return: True 发送成功 / False 失败
    """
    recipients = [addr for addr in (recipients or []) if addr and '@' in addr]
    if not recipients:
        logger.error('邮件发送失败：收件人为空，请检查 ALARM_RECIPIENTS 配置（主题=%s）', subject)
        return False

    sender = sender or Config.MAIL_USERNAME
    password = password or Config.MAIL_PASSWORD
    if not sender or not password:
        logger.error('邮件发送失败：MAIL_USERNAME / MAIL_PASSWORD 未配置（主题=%s）', subject)
        return False

    server = None
    try:
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        if Config.MAIL_USE_SSL:
            server = smtplib.SMTP_SSL(
                Config.MAIL_SERVER, Config.MAIL_PORT, timeout=Config.MAIL_TIMEOUT
            )
        else:
            server = smtplib.SMTP(
                Config.MAIL_SERVER, Config.MAIL_PORT, timeout=Config.MAIL_TIMEOUT
            )
            if Config.MAIL_USE_TLS:
                server.starttls()

        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())

        logger.info('邮件发送成功：%s -> %s（主题=%s）', sender, ','.join(recipients), subject)
        return True
    except Exception:
        logger.exception('邮件发送失败（主题=%s）', subject)
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:  # noqa: BLE001 - 关闭失败不影响已完成的发送
                logger.debug('SMTP 连接关闭异常（可忽略）', exc_info=True)
