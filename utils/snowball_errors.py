"""
雪球（Xueqiu）接口错误解析。

pysnowball 在接口返回业务错误时会 `raise Exception(response.content)`，
内容是一段 JSON，例如：

    {"error_description":"遇到错误，请刷新页面或者重新登录账号后再试",
     "error_uri":"/v5/stock/quote.json","error_data":null,"error_code":"400016"}

这类错误属于**外部服务返回的预期内错误**（Token 失效、限流、代码不存在等），
不是程序 bug，不应该打 ERROR + 堆栈淹没日志。本模块负责把异常归类，
让调用方可以只给一条可读的提示，并在必要时做退避。
"""
import json
import re

_CODE_RE = re.compile(r'"?error_code"?\s*[:=]\s*"?([0-9]+)"?')
_DESC_RE = re.compile(r'"?error_description"?\s*[:=]\s*"((?:[^"\\]|\\.)*)"')
_DESC_UNQUOTED_RE = re.compile(r'"?error_description"?\s*[:=]\s*([^,}\s]+)')

# Token 失效 / 未授权 / 需要重新登录
AUTH_ERROR_CODES = {
    '400016',  # 遇到错误，请刷新页面或者重新登录账号后再试（Token 失效最常见）
    '400027',  # 用户未登录 / 鉴权失败
    '10001',   # 未登录
}

# 触发限流，需要退避
RATE_LIMIT_CODES = {
    '400017',  # 请求过于频繁
}

# 目标对象本身不存在（股票代码写错等），不需要退避但也不该打堆栈
NOT_FOUND_CODES = {
    '400015',  # 股票代码不存在
}


def _decode_escapes(text):
    """
    把 bytes repr 里的转义序列还原成可读文本。

    pysnowball 抛出的异常是 `Exception(response.content)`，
    `str(exc)` 得到的是 bytes 的 repr，UTF-8 中文会变成 `\\xe9\\x81\\x87...`：

        b'{"error_description":"\\xe9\\x81\\x87\\xe5\\x88\\xb0...","error_code":"400016"}'

    JSON 不支持 `\\xNN`，直接 json.loads 会失败，因此这里先做转义还原。
    """
    if '\\x' not in text and '\\u' not in text:
        return text
    try:
        raw = text.encode('latin-1', errors='ignore')
        raw = raw.decode('unicode_escape').encode('latin-1', errors='ignore')
        for encoding in ('utf-8', 'gbk'):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
        pass
    return text


def parse_xueqiu_error(exc):
    """
    从异常中解析雪球错误码与描述。

    :param exc: 任意异常（兼容 bytes repr / str / JSON / 非 JSON）
    :return: (error_code, error_description)；无法识别时返回 (None, None)
    """
    raw = str(exc).strip()
    if not raw:
        return None, None

    # 去掉 bytes 字面量的 b'...' / b"..." 外壳
    if raw.startswith("b'") and raw.endswith("'"):
        raw = raw[2:-1]
    elif raw.startswith('b"') and raw.endswith('"'):
        raw = raw[2:-1]

    code = desc = None

    # 首选：能按 JSON 解析就按 JSON 解析
    start, end = raw.find('{'), raw.rfind('}')
    if start >= 0 and end > start:
        try:
            payload = json.loads(raw[start:end + 1])
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            if payload.get('error_code') is not None:
                code = str(payload['error_code'])
            desc = payload.get('error_description') or payload.get('error_msg') or ''

    # 兜底：正则提取（bytes repr 里的 \xNN 转义会导致 JSON 解析失败）
    if code is None:
        match = _CODE_RE.search(raw)
        if match:
            code = match.group(1)

    if not desc:
        unescaped = _decode_escapes(raw)
        for pattern in (_DESC_RE, _DESC_UNQUOTED_RE):
            match = pattern.search(unescaped) or pattern.search(raw)
            if match:
                desc = match.group(1)
                break

    if code is None:
        return None, None
    return code, _decode_escapes(desc or '').strip()


def is_auth_error(code):
    """是否为 Token 失效 / 未授权错误。"""
    return code in AUTH_ERROR_CODES


def is_rate_limit_error(code):
    """是否为限流错误。"""
    return code in RATE_LIMIT_CODES


def should_backoff(code):
    """该错误是否应触发整体退避（Token 失效、限流）。"""
    return is_auth_error(code) or is_rate_limit_error(code)


def describe(code, description):
    """把错误码翻译成人话，便于日志提示。"""
    if is_auth_error(code):
        return f'雪球 Token 无效或已过期（{code}）：{description or "请重新登录雪球账号获取新 Token"}'
    if is_rate_limit_error(code):
        return f'雪球接口限流（{code}）：{description or "请求过于频繁，将自动退避"}'
    if code in NOT_FOUND_CODES:
        return f'雪球无此标的（{code}）：{description or "请检查股票代码是否带交易所前缀"}'
    return f'雪球接口返回错误（{code}）：{description or "无描述"}'
