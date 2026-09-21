"""OpenAI-compatible model adapter.

Stdlib-only HTTP (urllib). Retries: exponential backoff with jitter,
max 3 attempts, transport/5xx only. Credentials come from the environment
and are never logged or written to artifacts.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


class Transport(Protocol):
    def post(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]: ...


class ProviderError(RuntimeError):
    """A concise error safe to persist in an episode record."""


class _HeaderItems(Protocol):
    def items(self) -> Iterable[tuple[str, str]]: ...


class HTTPResponseLike(Protocol):
    @property
    def headers(self) -> _HeaderItems: ...

    def read(self, amount: int) -> bytes: ...


MAX_PROVIDER_RESPONSE_BYTES = 4_194_304
MAX_PROVIDER_ERROR_BYTES = 65_536
MAX_PROVIDER_TOOL_CALLS = 16
MAX_PROVIDER_TOOL_CALL_ID_CHARS = 128
MAX_PROVIDER_TOOL_NAME_CHARS = 128
MAX_PROVIDER_TOOL_ARGUMENT_BYTES = 8_192
MAX_PROVIDER_TOOL_ARGUMENT_NODES = 128
MAX_PROVIDER_TOOL_ARGUMENT_DEPTH = 8


def _decimal_exceeds_limit(value: str, limit: int) -> bool:
    normalized = value.lstrip("0") or "0"
    maximum = str(limit)
    return len(normalized) > len(maximum) or (
        len(normalized) == len(maximum) and normalized > maximum
    )


def _read_bounded(response: HTTPResponseLike, limit: int) -> bytes:
    for name, value in response.headers.items():
        if (
            isinstance(name, str)
            and name.lower() == "content-length"
            and isinstance(value, str)
            and value.isascii()
            and value.isdecimal()
            and _decimal_exceeds_limit(value, limit)
        ):
            raise ProviderError("provider_error:response_too_large")
    body = bytearray()
    while True:
        remaining = (limit + 1) - len(body)
        chunk = response.read(remaining)
        if type(chunk) is not bytes:
            raise ProviderError("provider_error:invalid_transport_body")
        if len(chunk) > remaining:
            raise ProviderError("provider_error:response_too_large")
        body.extend(chunk)
        if len(body) > limit:
            raise ProviderError("provider_error:response_too_large")
        if not chunk:
            return bytes(body)


def _token_count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _validated_provider_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise ProviderError("provider_error:invalid_base_url") from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderError("provider_error:invalid_base_url")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ProviderError("provider_error:insecure_remote_base_url")
    return value


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def post(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        req = urllib.request.Request(
            _validated_provider_url(url), data=body, headers=headers, method="POST"
        )
        try:
            with self._opener.open(req, timeout=120) as resp:
                status = resp.status
                limit = (
                    MAX_PROVIDER_RESPONSE_BYTES
                    if type(status) is int and status == 200
                    else MAX_PROVIDER_ERROR_BYTES
                )
                return status, _read_bounded(resp, limit)
        except urllib.error.HTTPError as e:
            return e.code, _read_bounded(e, MAX_PROVIDER_ERROR_BYTES)


@dataclass(frozen=True)
class AdapterConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = 1024
    supports_seed: bool = False
    max_retries: int = 3
    transport: Transport = field(default_factory=UrllibTransport)

    @classmethod
    def from_env(cls) -> AdapterConfig:
        missing = [
            k
            for k in ("CASCADESHIFT_BASE_URL", "CASCADESHIFT_API_KEY", "CASCADESHIFT_MODEL")
            if not os.environ.get(k)
        ]
        if missing:
            raise RuntimeError(f"missing environment variables for live model access: {missing}")
        return cls(
            base_url=os.environ["CASCADESHIFT_BASE_URL"].rstrip("/"),
            api_key=os.environ["CASCADESHIFT_API_KEY"],
            model=os.environ["CASCADESHIFT_MODEL"],
            supports_seed=os.environ.get("CASCADESHIFT_PROVIDER_SUPPORTS_SEED", "false").lower()
            == "true",
        )

    def redacted(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d.pop("transport", None)
        d["api_key"] = "***" if self.api_key else ""
        return d


@dataclass(frozen=True)
class ToolCallOut:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class CompletionResult:
    tool_calls: tuple[ToolCallOut, ...]
    content: str | None
    prompt_tokens: int
    completion_tokens: int
    model: str


def _bounded_tool_arguments(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        encoded = serialized.encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        raise ValueError from None
    if len(encoded) > MAX_PROVIDER_TOOL_ARGUMENT_BYTES:
        raise ProviderError("provider_error:tool_call_too_complex")

    nodes = [0]

    def visit(item: object, depth: int) -> None:
        if depth > MAX_PROVIDER_TOOL_ARGUMENT_DEPTH:
            raise ProviderError("provider_error:tool_call_too_complex")
        nodes[0] += 1
        if nodes[0] > MAX_PROVIDER_TOOL_ARGUMENT_NODES:
            raise ProviderError("provider_error:tool_call_too_complex")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) not in {str, int, float, bool, type(None)}:
            raise ValueError

    visit(value, 0)
    return value


def _bounded_identifier(value: object, *, max_chars: int) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ProviderError("provider_error:tool_call_too_complex") from None
    has_control = any(ord(character) < 32 or ord(character) == 127 for character in value)
    if len(value) > max_chars or has_control:
        raise ProviderError("provider_error:tool_call_too_complex")
    return value


def _validated_tool_call(call_id: object, name: object, arguments: object) -> ToolCallOut:
    call_id = _bounded_identifier(call_id, max_chars=MAX_PROVIDER_TOOL_CALL_ID_CHARS)
    name = _bounded_identifier(name, max_chars=MAX_PROVIDER_TOOL_NAME_CHARS)
    return ToolCallOut(call_id=call_id, name=name, arguments=_bounded_tool_arguments(arguments))


def validate_provider_tool_calls(calls: Sequence[ToolCallOut]) -> tuple[ToolCallOut, ...]:
    """Reject provider calls that exceed the bounded live-run protocol."""
    if len(calls) > MAX_PROVIDER_TOOL_CALLS:
        raise ProviderError("provider_error:tool_call_limit_exceeded")
    validated: list[ToolCallOut] = []
    for call in calls:
        if not isinstance(call, ToolCallOut):
            raise ProviderError("provider_error:malformed_response")
        try:
            validated.append(_validated_tool_call(call.call_id, call.name, call.arguments))
        except ValueError:
            raise ProviderError("provider_error:malformed_response") from None
    return tuple(validated)


RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
MAX_MODEL_IDENTIFIER_CHARS = 200


def sanitized_provider_error(exc: BaseException) -> str:
    """Return a persistence-safe provider error without external details."""
    if isinstance(exc, ProviderError):
        return str(exc)
    return "provider_error:adapter_failure"


def _valid_model_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_MODEL_IDENTIFIER_CHARS
        and all(" " <= character <= "~" for character in value)
    )


class ModelAdapter:
    """Thin chat-completions client; no agent logic lives here."""

    def __init__(self, config: AdapterConfig) -> None:
        if not _valid_model_identifier(config.model):
            raise ProviderError("provider_error:invalid_configured_model")
        base_url = config.base_url.rstrip("/")
        _validated_provider_url(f"{base_url}/chat/completions")
        self._cfg = config
        self._base_url = base_url

    @property
    def model_name(self) -> str:
        return self._cfg.model

    @property
    def supports_seed(self) -> bool:
        return self._cfg.supports_seed

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        rollout_seed: int | None = None,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature,
            "top_p": self._cfg.top_p,
            "max_tokens": self._cfg.max_tokens,
        }
        if tools:
            payload["tools"] = tools
        seed: int | None = rollout_seed if self._cfg.supports_seed else None
        if seed is not None:
            payload["seed"] = seed

        attempt = 0
        last_error = "provider_error:transport_failure"
        while attempt < self._cfg.max_retries:
            attempt += 1
            try:
                status, body = self._cfg.transport.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._cfg.api_key}",
                    },
                    body=json.dumps(payload).encode(),
                )
            except ProviderError:
                raise
            except Exception:
                if attempt < self._cfg.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise ProviderError("provider_error:transport_failure") from None
            if type(status) is not int:
                raise ProviderError("provider_error:invalid_transport_status")
            if type(body) is not bytes:
                raise ProviderError("provider_error:invalid_transport_body")
            body_limit = MAX_PROVIDER_RESPONSE_BYTES if status == 200 else MAX_PROVIDER_ERROR_BYTES
            if len(body) > body_limit:
                raise ProviderError("provider_error:response_too_large")
            if status == 200:
                return self._parse(body)
            last_error = f"provider_error:http_{status}"
            if status not in RETRYABLE_STATUS:
                break
            if attempt < self._cfg.max_retries:
                self._sleep_before_retry(attempt)
        raise ProviderError(last_error)

    @staticmethod
    def _sleep_before_retry(attempt: int) -> None:
        delay = min(8.0, (0.5 * (2 ** (attempt - 1))) * (0.8 + 0.4 * random.random()))
        time.sleep(delay)

    def _parse(self, body: bytes) -> CompletionResult:
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError
            msg = choices[0].get("message", {})
            if not isinstance(msg, dict):
                raise ValueError
            content = msg.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError
            raw_calls = msg.get("tool_calls", [])
            if raw_calls is None:
                raw_calls = []
            if not isinstance(raw_calls, list):
                raise ValueError
            if len(raw_calls) > MAX_PROVIDER_TOOL_CALLS:
                raise ProviderError("provider_error:tool_call_limit_exceeded")
            calls: list[ToolCallOut] = []
            for call in raw_calls:
                if not isinstance(call, dict):
                    raise ValueError
                call_id = call.get("id")
                fn = call.get("function")
                if not isinstance(call_id, str) or not call_id or not isinstance(fn, dict):
                    raise ValueError
                name = fn.get("name")
                args_raw = fn.get("arguments")
                if isinstance(args_raw, str):
                    try:
                        encoded_args = args_raw.encode("utf-8")
                    except UnicodeError:
                        raise ValueError from None
                    if len(encoded_args) > MAX_PROVIDER_TOOL_ARGUMENT_BYTES:
                        raise ProviderError("provider_error:tool_call_too_complex")
                    args_raw = json.loads(args_raw)
                calls.append(_validated_tool_call(call_id, name, args_raw))
            usage = data.get("usage", {})
            if usage is None:
                usage = {}
            if not isinstance(usage, dict):
                raise ValueError
            model = data.get("model")
            if not _valid_model_identifier(model):
                raise ProviderError("provider_error:invalid_provider_model")
            if model != self._cfg.model:
                raise ProviderError("provider_error:model_mismatch")
            return CompletionResult(
                tool_calls=tuple(calls),
                content=content,
                prompt_tokens=_token_count(usage.get("prompt_tokens", 0)),
                completion_tokens=_token_count(usage.get("completion_tokens", 0)),
                model=model,
            )
        except ProviderError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError, OverflowError, RecursionError):
            raise ProviderError("provider_error:malformed_response") from None
