"""Small OpenAI-compatible explanation client; credentials stay server-side."""

import asyncio
import base64
import json
import logging
import os
import ssl
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from .models import CoachRequest, PlanExplanation
from .coach_notation import normalize_coach_notation
from .xiangqi import Position
from .vision import VisionPosition, parse_vision_position
from . import settings  # noqa: F401  # Load the project .env before reading LLM variables.
from .logging_config import get_logger


logger = get_logger(__name__)


def _error_category(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return "http_error"
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    if isinstance(error, URLError):
        if isinstance(error.reason, (ssl.SSLError, ssl.CertificateError)):
            return "tls_error"
        return "network_error"
    if isinstance(error, (json.JSONDecodeError,)):
        return "invalid_json"
    if isinstance(error, (KeyError, IndexError, TypeError)):
        return "invalid_response"
    if isinstance(error, ValueError):
        return "invalid_response"
    return "unknown"


def _provider_request(operation: str, base_url: str, model: str, request: Request, timeout: float, parse):
    host = urlsplit(base_url).hostname or "unknown"
    started = time.monotonic()
    fields = {"operation": operation, "model": model, "provider_host": host}
    logger.info(
        "llm.request.started operation=%s model=%s provider_host=%s",
        operation, model, host, extra={"event": "llm.request.started", **fields},
    )
    status = "-"
    try:
        with urlopen(request, timeout=timeout, context=_tls_context()) as response:
            status = getattr(response, "status", None) or getattr(response, "code", None) or "-"
            result = parse(response.read())
    except Exception as exc:
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if isinstance(exc, HTTPError):
            status = exc.code
        logger.warning(
            "llm.request.failed operation=%s model=%s provider_host=%s error_class=%s error_category=%s",
            operation, model, host, type(exc).__name__, _error_category(exc),
            extra={"event": "llm.request.failed", **fields, "duration_ms": duration_ms,
                   "status": status, "error_class": type(exc).__name__,
                   "error_category": _error_category(exc)},
        )
        raise
    logger.info(
        "llm.request.succeeded operation=%s model=%s provider_host=%s",
        operation, model, host,
        extra={"event": "llm.request.succeeded", **fields,
               "duration_ms": round((time.monotonic() - started) * 1000, 2), "status": status},
    )
    return result


class LLMUnavailable(RuntimeError):
    pass


class VisionRecognitionError(ValueError):
    pass


class VisionResponseFormatError(ValueError):
    """The vision provider returned a response that cannot be validated."""


def _json_headers(api_key: str) -> dict[str, str]:
    # Some OpenAI-compatible gateways reject urllib's default Python-urllib UA.
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "xiangqi-coach/1.0",
    }


def _chat_unavailable_message(error: Exception) -> str:
    if isinstance(error, HTTPError):
        if error.code in {401, 403}:
            return f"大语言模型不可用（上游 HTTP {error.code}，请检查模型服务鉴权配置）；棋盘、引擎分析和复盘仍可使用"
        if error.code == 429:
            return "大语言模型暂时不可用（上游 HTTP 429，服务繁忙）；棋盘、引擎分析和复盘仍可使用"
        if 500 <= error.code <= 599:
            return f"大语言模型暂时不可用（上游 HTTP {error.code}，模型服务网关异常）；棋盘、引擎分析和复盘仍可使用"
        return f"大语言模型不可用（上游 HTTP {error.code}）；棋盘、引擎分析和复盘仍可使用"
    return "大语言模型暂时不可用；棋盘、引擎分析和复盘仍可使用"


def _tls_context() -> ssl.SSLContext:
    """Use a maintained CA bundle when the Python install has no system CA path."""
    return ssl.create_default_context(cafile=certifi.where())


def _timeout_seconds(operation: str) -> float:
    key = f"AGENT_OPENAI_{operation.upper()}_TIMEOUT_SECONDS"
    # Explanation requests include a structured Chinese coaching prompt and can
    # legitimately take longer than interactive chat on the shared gateway.
    default = {"vision": "180", "explain": "120"}.get(operation, "60")
    fallback = os.getenv("AGENT_OPENAI_TIMEOUT_SECONDS", default)
    try:
        value = float(os.getenv(key, fallback))
    except ValueError:
        value = float(fallback)
    maximum = 600.0 if operation == "vision" else 120.0
    return max(5.0, min(value, maximum))


def _required_config() -> tuple[str, str, str]:
    base_url = os.getenv("AGENT_OPENAI_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("AGENT_OPENAI_API_KEY", "").strip()
    model = os.getenv("AGENT_OPENAI_MODEL", "").strip()
    if not base_url or not api_key or not model:
        raise LLMUnavailable("大语言模型尚未配置；当前仅显示 Pikafish 引擎对比")
    return base_url, api_key, model


def _parse_json_object_content(content: object) -> dict:
    """Parse structured model output with tolerant transport-level wrappers."""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty structured response")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("structured response is not an object")
    return parsed


def _request_explanation(payload: dict) -> PlanExplanation:
    base_url, api_key, model = _required_config()
    system = (
        "你是中国象棋复盘教练。以引擎给出的评估和主变化为事实依据，结合用户计划解释着法。"
        "不得虚构棋盘事实；评估差距很小时不要夸大优劣。只返回 JSON 对象，字段为："
        "advantages（字符串数组）、risks（字符串数组）、engine_assessment（字符串）、suggestion（字符串）。"
        "用简明中文回答，明确说明分数是引擎估值而非胜率。"
    )
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=body,
        headers=_json_headers(api_key),
        method="POST",
    )
    timeout = _timeout_seconds("explain")
    try:
        def parse(raw):
            result = json.loads(raw)
            content = result["choices"][0]["message"]["content"]
            return PlanExplanation.model_validate(_parse_json_object_content(content))

        return _provider_request("explain", base_url, model, request, timeout, parse)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        # Do not expose provider responses or request details that could contain secrets.
        raise LLMUnavailable("大语言模型暂时不可用；仍可查看 Pikafish 引擎对比") from exc


async def explain(payload: dict) -> PlanExplanation:
    return await asyncio.to_thread(_request_explanation, payload)


def _request_chat(payload: dict) -> str:
    base_url, api_key, model = _required_config()
    system = (
        "你是一位严谨、耐心的中国象棋教练。回答必须依据用户提供的棋盘 FEN、走法和引擎分析；"
        "不要虚构棋盘上的攻击、威胁或开局事实。引擎分值是搜索评估，不是胜率；没有引擎数据时明确说明。"
        "棋局字段约定：fen 是本局起始局面时，moves 是从该 FEN 开始依次走出的 UCI 着法；"
        "fen 也可能已经是浏览中的当前局面，此时 moves 为空。后端在调用教练前已按象棋规则校验 fen 和 moves 可合法重建；"
        "current_position 是后端按同一规则模块重建的权威当前棋盘，board 从黑方一侧到红方一侧按 10 行、每行 9 列排列，"
        "side_to_move 表示当前行棋方。分析当前局面时优先依据 current_position。不得仅因 fen 显示初始局面就断言与 moves 不一致，"
        "也不得要求用户重复提供当前局面的 FEN；只有明确的校验错误才报告棋局数据无效。"
        "结合用户的学习目标给出简洁、可执行的解释，存在多种判断时说明不确定性。"
        "所有面向用户的着法和变化必须使用中国象棋常用记谱：红方使用中文数字一至九，黑方使用阿拉伯数字1至9，"
        "使用炮二平五、马8进7、车九平八等格式；禁止使用坐标记法或 UCI 记法，例如 e6-e5、e6e5、a0a1。"
        "输入棋谱中的 UCI 坐标可以理解，但输出时必须转换为中文棋谱；同类棋子有歧义时使用前、后或中等标准区分。"
    )
    messages = [{"role": "system", "content": system}]
    messages.extend({"role": item["role"], "content": item["content"]} for item in payload["messages"])
    messages.append({"role": "user", "content": json.dumps({
        "question": payload["question"], "fen": payload["fen"],
        "moves": payload["moves"], "selected_context": payload["context"],
        "current_position": payload.get("current_position"),
    }, ensure_ascii=False)})
    body = json.dumps({"model": model, "temperature": 0.3, "messages": messages}).encode("utf-8")
    request = Request(f"{base_url}/chat/completions", data=body,
                      headers=_json_headers(api_key), method="POST")
    timeout = _timeout_seconds("chat")
    try:
        def parse(raw):
            result = json.loads(raw)
            content = result["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty assistant response")
            return normalize_coach_notation(content.strip(), payload["fen"], payload["moves"])[:8000]

        return _provider_request("chat", base_url, model, request, timeout, parse)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMUnavailable(_chat_unavailable_message(exc)) from exc


async def coach_chat(request: CoachRequest) -> str:
    position = Position.from_fen(request.fen)
    for move in request.moves:
        position.apply_uci(move)
    messages = [item.model_dump() for item in request.messages[-20:]]
    # Bound total history size as well as per-message size before sending it upstream.
    bounded = []
    size = 0
    for item in reversed(messages):
        size += len(item["content"])
        if size > 12000:
            break
        bounded.append(item)
    payload = {"question": request.question.strip(), "fen": request.fen,
               "moves": request.moves, "context": request.context,
               "current_position": {
                   "board": ["".join(row) for row in position.board],
                   "side_to_move": "red" if position.red_to_move else "black",
               },
               "messages": list(reversed(bounded))}
    return await asyncio.to_thread(_request_chat, payload)


def _request_vision_payload(image: bytes, mime_type: str, system: str) -> dict:
    base_url, api_key, model = _required_config()
    data_url = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": "请识别这张中国象棋棋盘照片，返回当前局面。"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
    }).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=body,
        headers=_json_headers(api_key),
        method="POST",
    )
    timeout = _timeout_seconds("vision")
    try:
        def parse(raw):
            result = json.loads(raw)
            content = result["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return json.loads(content)

        return _provider_request("vision", base_url, model, request, timeout, parse)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, (KeyError, IndexError, TypeError, json.JSONDecodeError)):
            raise VisionResponseFormatError("视觉模型返回的 JSON 格式无效") from exc
        if isinstance(exc, URLError) and isinstance(exc.reason, ssl.SSLCertVerificationError):
            message = "棋盘图片识别服务的 TLS 证书验证失败，请检查视觉服务证书配置"
        elif isinstance(exc, HTTPError) and exc.code in {400, 404, 415}:
            message = "视觉模型不支持当前图片请求，请检查视觉模型配置"
        elif (isinstance(exc, HTTPError) and exc.code in {408, 409, 425, 429}) or isinstance(exc, TimeoutError):
            message = "视觉服务响应超时或暂时繁忙，请稍后重试"
        else:
            message = "棋盘图片识别暂时不可用；可以继续手动摆棋"
        raise LLMUnavailable(message) from exc


def _request_vision(image: bytes, mime_type: str) -> VisionPosition:
    system = (
        "你是中国象棋棋盘识别器。只识别图片中当前可见的棋盘局面，不识别文字棋谱。"
        "棋盘必须从黑方一侧到红方一侧按 10 行、每行 9 列返回。"
        "棋子使用 FEN 字符：黑方 r n b a k c p，红方 R N B A K C P，空格使用 .。"
        "只能返回 JSON 对象，不要 Markdown，字段必须是 board（10 个长度为 9 的字符串）和 "
        "red_to_move（red 或 black）。看不清的格子使用 .，并尽量在 warnings 字段说明不确定位置。"
    )
    prompts = [
        system,
        system + (
            "上一次识别结果未通过棋盘校验。请重新逐格复核图片，只返回完整的 10 行×9 列矩阵；"
            "确认红方恰好一个帅、黑方恰好一个将，且每行恰好 9 格。"
        ),
    ]
    last_error: ValueError | None = None
    for attempt, prompt in enumerate(prompts, start=1):
        try:
            parsed = _request_vision_payload(image, mime_type, prompt)
            recognized = parse_vision_position(parsed)
        except (VisionResponseFormatError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "vision.validation.failed attempt=%s validation_category=%s",
                attempt,
                "invalid_json" if isinstance(exc, VisionResponseFormatError) else "invalid_board",
                extra={"event": "vision.validation.failed", "attempt": attempt,
                       "validation_category": "invalid_json" if isinstance(exc, VisionResponseFormatError) else "invalid_board"},
            )
            continue
        warnings = parsed.get("warnings", [])
        if isinstance(warnings, list):
            recognized = VisionPosition(recognized.fen, recognized.red_to_move, recognized.piece_count, [str(item) for item in warnings][:10])
        return recognized
    detail = str(last_error) if last_error else "视觉模型返回结果无效"
    raise VisionRecognitionError(f"图片中的棋盘未能完整识别：{detail}。请换一张清晰、完整的棋盘图片") from last_error


async def recognize_board_image(image: bytes, mime_type: str) -> VisionPosition:
    return await asyncio.to_thread(_request_vision, image, mime_type)
