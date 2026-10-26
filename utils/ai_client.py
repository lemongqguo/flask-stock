"""
OpenAI 兼容 API 客户端（007 AI 个股分析）。

设计约束（见 `spec/rules/development-standards.md`）：
- 只用 `requests`，不引入厂商 SDK，避免为一个接口增加依赖；
- **不绑定厂商**：Base URL + Model ID + Key 由环境变量决定；`AI_API_STYLE` 区分
  `responses`（OpenAI Responses API）与 `chat`（/chat/completions，兼容更多自建网关）；
- 外部调用**必须传超时**，且超时/失败都要返回**可判定的失败值**（不抛异常给视图层）；
- `AI_API_KEY` 只在请求头里出现，**绝不进日志、不进返回值、不进数据库**。

返回值统一为 dict：

    {'ok': bool, 'status': 'ok|disabled|error|timeout', 'text': str,
     'tokens': int, 'model': str, 'error': str}

视图层只判断 `status`，不解析异常类型。
"""
import logging

import requests

from config import Config

logger = logging.getLogger(__name__)

STATUS_OK = 'ok'
STATUS_DISABLED = 'disabled'
STATUS_ERROR = 'error'
STATUS_TIMEOUT = 'timeout'

# 外部响应正文写进日志时的截断长度：够定位问题，又不至于把整段报告灌进日志
_ERROR_BODY_LIMIT = 300


def _setting(name, default=None):
    """读 `Config` 上的配置。做成函数便于测试替换配置。"""
    return getattr(Config, name, default)


# 页面「密钥」里临时录入的 Key：**只活在当前进程内存**。
# 不落库、不落文件、不进日志、不回显——`development-standards.md` §1 禁止明文凭据落盘，
# 「页面能填、填完立刻能用」唯一不破坏该约束的落点就是内存（重启即失效，回退环境变量）。
_RUNTIME_KEY = {'value': ''}


def set_runtime_key(key):
    """
    录入运行时密钥（空串 = 清除）。返回值只表示"是否非空"，不返回密钥本身。

    :param key: 页面提交的密钥
    :return: bool
    """
    value = (key or '').strip()
    _RUNTIME_KEY['value'] = value
    return bool(value)


def clear_runtime_key():
    """清除运行时密钥，恢复使用环境变量 `AI_API_KEY`。"""
    _RUNTIME_KEY['value'] = ''
    return True


def runtime_key_configured():
    """当前是否有页面录入的密钥（用于页面提示"本次运行有效"）。"""
    return bool(_RUNTIME_KEY['value'])


def _api_key():
    """
    当前生效的密钥：页面录入（进程内存）优先，否则环境变量。

    :return: str（可能为空）
    """
    return _RUNTIME_KEY['value'] or (_setting('AI_API_KEY', '') or '').strip()


def mask_key(key):
    """
    脱敏展示密钥：只留前 3 位与后 2 位，长度不足时全遮。

    :return: 形如 `sk-***ab` 的字符串；未配置返回 '未配置'
    """
    key = (key or '').strip()
    if not key:
        return '未配置'
    if len(key) <= 6:
        return '***'
    return f'{key[:3]}***{key[-2:]}'


def _split_models(raw):
    """
    把配置值拆成模型清单：逗号 / 分号都算分隔符，去空、保序去重。

    `AI_MODEL` 也会被当成清单拆——用户按直觉把多个模型填进去时，
    整串当一个 ID 发出去必然失败（见 changes/2026-10-22-ai-model-list.md）。

    :return: list[str]
    """
    items = str(raw or '').replace(';', ',').split(',')
    names = []
    for item in items:
        name = item.strip()
        if name and name not in names:
            names.append(name)
    return names


def available_models():
    """
    页面「模型」下拉的候选项。

    来源：`AI_MODEL`（默认模型清单，**第一项是默认模型**）+ `AI_MODELS`（候选清单）；
    两个变量都按逗号 / 分号拆分，`AI_MODEL` 的第一项始终排最前，去重保序。
    两者都没配时返回空列表（页面只显示「未配置」）。

    :return: list[str]
    """
    candidates = _split_models(_setting('AI_MODEL', ''))
    for name in _split_models(_setting('AI_MODELS', '')):
        if name not in candidates:
            candidates.append(name)
    return candidates


def default_model():
    """
    实际会发出去的默认模型：**单个** ID。

    `AI_MODEL` 可能是「a,b,c」这种清单，取第一项；`AI_MODEL` 没配则取候选清单第一项。
    页面显示、真正调用、`StockAiConfig.effective()` 都用它，避免"显示的"和"发出去的"不是一个。

    :return: str；未配置返回 ''
    """
    models = available_models()
    return models[0] if models else ''


def is_allowed_model(model):
    """模型是否在候选项内（用于拒绝伪造的 `model` 参数，避免把请求打到未知模型）。"""
    name = (model or '').strip()
    return bool(name) and name in available_models()


def describe_settings():
    """
    当前 AI 配置的**脱敏**快照，供页面与日志使用。

    :return: dict(enabled, style, model, models, base, key_masked, timeout, temperature, max_tokens, configured, reason)
    """
    base = (_setting('AI_API_BASE', '') or '').strip().rstrip('/')
    model = default_model()
    key = _api_key()
    enabled = bool(_setting('AI_ENABLED', False))

    missing = []
    if not base:
        missing.append('AI_API_BASE')
    if not model:
        missing.append('AI_MODEL')
    if not key:
        missing.append('AI_API_KEY')

    configured = not missing
    if not enabled:
        reason = 'AI 分析未启用（AI_ENABLED=0）'
    elif not configured:
        reason = '缺少配置项：' + '、'.join(missing)
    else:
        reason = ''

    return {
        'enabled': enabled,
        'configured': configured,
        'reason': reason,
        'style': (_setting('AI_API_STYLE', 'responses') or 'responses').lower(),
        'model': model,
        'models': available_models(),
        'base': base,
        'key_masked': mask_key(key),
        # 密钥来源：runtime（页面录入，仅本次运行）/ env（环境变量）/ ''（未配置）
        'key_source': ('runtime' if _RUNTIME_KEY['value']
                       else 'env' if key else ''),
        'timeout': _setting('AI_TIMEOUT', 60),
        'temperature': _setting('AI_TEMPERATURE', 0.6),
        'max_tokens': _setting('AI_MAX_TOKENS', 1200),
    }


def is_ready():
    """
    是否可以发起调用。

    :return: (ready, reason)；未启用或缺少配置时 ready=False，reason 为可直接展示的中文原因
    """
    info = describe_settings()
    if not info['enabled']:
        return False, info['reason'] or 'AI 分析未启用'
    if not info['configured']:
        return False, info['reason'] or 'AI 未配置'
    return True, ''


def _endpoint(base, style):
    """按风格拼出完整 URL：`responses` → `/responses`，`chat` → `/chat/completions`。"""
    base = (base or '').strip().rstrip('/')
    if style == 'chat':
        return base + '/chat/completions'
    return base + '/responses'


def _build_payload(style, model, messages, temperature, max_tokens):
    """按风格组装请求体。messages 为 [{'role','content'}]，system 放在最前。"""
    if style == 'chat':
        return {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
    # Responses API：input 直接接受 role/content 消息数组
    return {
        'model': model,
        'input': messages,
        'temperature': temperature,
        'max_output_tokens': max_tokens,
    }


def _extract_responses_text(data):
    """从 Responses API 的返回里取正文：优先 `output_text`，否则遍历 `output[].content[].text`。"""
    text = data.get('output_text')
    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks = []
    for item in data.get('output') or []:
        if not isinstance(item, dict):
            continue
        for part in item.get('content') or []:
            if isinstance(part, dict) and isinstance(part.get('text'), str):
                chunks.append(part['text'])
    return '\n'.join(chunks).strip()


def _extract_chat_text(data):
    """从 /chat/completions 的返回里取正文。"""
    choices = data.get('choices') or []
    if not choices or not isinstance(choices[0], dict):
        return ''
    message = choices[0].get('message') or {}
    content = message.get('content')
    if isinstance(content, str):
        return content.strip()
    # 部分网关把 content 返回成分段数组
    if isinstance(content, list):
        return '\n'.join(part.get('text', '') for part in content
                         if isinstance(part, dict)).strip()
    return ''


def _extract_tokens(data):
    """Token 用量：各厂商字段不一致，缺失记 0（规格 007 §8）。"""
    usage = data.get('usage') or {}
    for key in ('total_tokens', 'total_token_count'):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    total = 0
    for key in ('input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens'):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def _fail(status, error, model=''):
    """构造失败结果。"""
    return {'ok': False, 'status': status, 'text': '', 'tokens': 0,
            'model': model, 'error': error}


def call_ai(messages, temperature=None, max_tokens=None, timeout=None, model=None):
    """
    发起一次对话补全请求。

    :param messages: [{'role': 'system'|'user', 'content': str}]
    :param temperature: 采样温度，缺省取 `Config.AI_TEMPERATURE`
    :param max_tokens: 输出上限，缺省取 `Config.AI_MAX_TOKENS`
    :param timeout: 超时秒数，缺省取 `Config.AI_TIMEOUT`（**必传，不允许无限等待**）
    :param model: 覆盖模型 ID（连通测试可传小模型）
    :return: 见模块头的统一结果 dict；任何异常都不抛出
    """
    ready, reason = is_ready()
    if not ready:
        return _fail(STATUS_DISABLED, reason)

    info = describe_settings()
    base = info['base']
    style = 'chat' if info['style'] == 'chat' else 'responses'
    model = (model or info['model']).strip()
    temperature = info['temperature'] if temperature is None else temperature
    max_tokens = info['max_tokens'] if max_tokens is None else max_tokens
    timeout = info['timeout'] if timeout is None else timeout

    url = _endpoint(base, style)
    payload = _build_payload(style, model, messages, temperature, max_tokens)
    headers = {
        'Authorization': 'Bearer ' + _api_key(),
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        # 失败状态的响应体对定位问题很关键，但只截断记录，且打码 Authorization 之外的内容本就不含密钥
        if response.status_code >= 400:
            body = (response.text or '')[:_ERROR_BODY_LIMIT]
            logger.error('AI 接口返回错误状态 status=%s model=%s body=%s',
                         response.status_code, model, body)
            return _fail(STATUS_ERROR,
                         f'接口返回 HTTP {response.status_code}', model=model)
        data = response.json()
    except requests.Timeout:
        logger.exception('AI 调用超时 timeout=%ss model=%s', timeout, model)
        return _fail(STATUS_TIMEOUT, f'调用超时（{timeout} 秒）', model=model)
    except requests.RequestException as exc:
        logger.exception('AI 调用失败 model=%s url=%s', model, url)
        return _fail(STATUS_ERROR, f'调用失败：{exc.__class__.__name__}', model=model)
    except ValueError:
        # 返回体不是 JSON：多半是网关错误页
        logger.exception('AI 返回不是合法 JSON model=%s', model)
        return _fail(STATUS_ERROR, '返回内容无法解析', model=model)

    if not isinstance(data, dict):
        logger.error('AI 返回结构异常 model=%s type=%s', model, type(data).__name__)
        return _fail(STATUS_ERROR, '返回结构异常', model=model)

    text = _extract_chat_text(data) if style == 'chat' else _extract_responses_text(data)
    tokens = _extract_tokens(data)

    if not text:
        logger.error('AI 返回正文为空 model=%s style=%s', model, style)
        return {**_fail(STATUS_ERROR, '返回正文为空', model=model), 'tokens': tokens}

    return {'ok': True, 'status': STATUS_OK, 'text': text,
            'tokens': tokens, 'model': model, 'error': ''}


def test_connection(model=None):
    """
    连通测试：发一次极短请求验证配置是否可用（会消耗少量 Token）。

    :param model: 指定模型（Composer 里选的那个）；缺省用默认模型
    :return: 与 `call_ai` 同结构，另加 `latency_ms`
    """
    import time as _time

    started = _time.time()
    result = call_ai(
        [{'role': 'user', 'content': '连通测试：请只回复 OK'}],
        temperature=0,
        max_tokens=16,
        model=model,
    )
    result['latency_ms'] = int((_time.time() - started) * 1000)
    return result
