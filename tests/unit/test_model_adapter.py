"""Adapter behavior offline via fake transport (A-04); secrets hygiene (SEC-01)."""

import json
import urllib.error
from dataclasses import replace

import pytest

from cascadeshift.agents.model_adapter import (
    MAX_PROVIDER_ERROR_BYTES,
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_PROVIDER_TOOL_ARGUMENT_BYTES,
    MAX_PROVIDER_TOOL_ARGUMENT_DEPTH,
    MAX_PROVIDER_TOOL_ARGUMENT_NODES,
    MAX_PROVIDER_TOOL_CALL_ID_CHARS,
    MAX_PROVIDER_TOOL_CALLS,
    MAX_PROVIDER_TOOL_NAME_CHARS,
    AdapterConfig,
    ModelAdapter,
    ProviderError,
    UrllibTransport,
    _NoRedirectHandler,
    sanitized_provider_error,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body)})
        if not self.responses:
            raise AssertionError("unexpected extra call")
        item = self.responses.pop(0)
        if isinstance(item, int):
            return item, b'{"error":"overloaded"}'
        return 200, json.dumps(item).encode()


class FakeResponse:
    def __init__(self, *, status=200, headers=None, body=b"", chunks=None, ignore_amount=False):
        self.status = status
        self.headers = {} if headers is None else headers
        self.body = body
        self.chunks = [body] if chunks is None else list(chunks)
        self.ignore_amount = ignore_amount
        self.read_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, amount=None):
        self.read_calls.append(amount)
        if not self.chunks:
            return b""
        chunk = self.chunks[0]
        if self.ignore_amount or type(chunk) is not bytes or amount is None or len(chunk) <= amount:
            return self.chunks.pop(0)
        self.chunks[0] = chunk[amount:]
        return chunk[:amount]

    def close(self):
        pass


class FakeOpener:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class TupleTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, url, headers, body):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _valid_response_bytes(size=None):
    body = json.dumps({"model": "test-model", "choices": [{"message": {}}], "usage": {}}).encode()
    return body if size is None else body + (b" " * (size - len(body)))


class BytesSubclass(bytes):
    pass


def _cfg(transport, supports_seed=True):
    return AdapterConfig(
        base_url="https://fake.invalid/v1",
        api_key="sekret",
        model="test-model",
        supports_seed=supports_seed,
        max_retries=3,
        transport=transport,
    )


def test_complete_parses_tool_calls_and_usage():
    body = {
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "search_rules",
                                "arguments": '{"query":"payroll"}',
                            },
                        }
                    ]
                }
            },
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    t = FakeTransport([body])
    res = ModelAdapter(_cfg(t)).complete([{"role": "user", "content": "hi"}], rollout_seed=424242)
    assert res.tool_calls[0].name == "search_rules"
    assert res.prompt_tokens == 100 and res.completion_tokens == 20
    assert res.model == "test-model"
    sent = t.calls[0]["body"]
    assert sent["seed"] is not None  # matched rollout seed forwarded


def _tool_call(*, call_id="c1", name="search_rules", arguments=None):
    return {
        "id": call_id,
        "function": {"name": name, "arguments": {} if arguments is None else arguments},
    }


def _tool_response(calls):
    return {"model": "test-model", "choices": [{"message": {"tool_calls": calls}}], "usage": {}}


def _nested_arguments(depth):
    value = {}
    for _ in range(depth):
        value = {"child": value}
    return value


def test_complete_rejects_tool_call_fanout_before_materializing_calls():
    response = _tool_response(
        [_tool_call(call_id=f"c{index}") for index in range(MAX_PROVIDER_TOOL_CALLS + 1)]
    )

    with pytest.raises(ProviderError, match="^provider_error:tool_call_limit_exceeded$"):
        ModelAdapter(_cfg(FakeTransport([response]))).complete([])


def test_complete_accepts_tool_call_boundaries():
    argument_text = json.dumps({"query": "x" * (MAX_PROVIDER_TOOL_ARGUMENT_BYTES - 13)})
    assert len(argument_text.encode("utf-8")) == MAX_PROVIDER_TOOL_ARGUMENT_BYTES
    cases = [
        [_tool_call(call_id=f"c{index}") for index in range(MAX_PROVIDER_TOOL_CALLS)],
        [
            _tool_call(
                call_id="i" * MAX_PROVIDER_TOOL_CALL_ID_CHARS,
                name="n" * MAX_PROVIDER_TOOL_NAME_CHARS,
                arguments=argument_text,
            )
        ],
        [
            _tool_call(
                arguments={
                    str(index): index for index in range(MAX_PROVIDER_TOOL_ARGUMENT_NODES - 1)
                }
            )
        ],
        [_tool_call(arguments=_nested_arguments(MAX_PROVIDER_TOOL_ARGUMENT_DEPTH))],
    ]

    for calls in cases:
        result = ModelAdapter(_cfg(FakeTransport([_tool_response(calls)]))).complete([])
        assert len(result.tool_calls) == len(calls)


@pytest.mark.parametrize(
    "call",
    [
        _tool_call(call_id="i" * (MAX_PROVIDER_TOOL_CALL_ID_CHARS + 1)),
        _tool_call(call_id="call\x1b[31m"),
        _tool_call(name="n" * (MAX_PROVIDER_TOOL_NAME_CHARS + 1)),
        _tool_call(name="search\nrules"),
        _tool_call(arguments=json.dumps({"query": "x" * (MAX_PROVIDER_TOOL_ARGUMENT_BYTES - 12)})),
        _tool_call(
            arguments={str(index): index for index in range(MAX_PROVIDER_TOOL_ARGUMENT_NODES)}
        ),
        _tool_call(arguments=_nested_arguments(MAX_PROVIDER_TOOL_ARGUMENT_DEPTH + 1)),
    ],
)
def test_complete_rejects_oversized_tool_call_fields(call):
    with pytest.raises(ProviderError, match="^provider_error:tool_call_too_complex$"):
        ModelAdapter(_cfg(FakeTransport([_tool_response([call])]))).complete([])


def test_complete_normalizes_deep_argument_json_recursion_failure():
    deeply_nested = "[" * 1_500 + "0" + "]" * 1_500
    assert len(deeply_nested.encode("utf-8")) < MAX_PROVIDER_TOOL_ARGUMENT_BYTES

    with pytest.raises(ProviderError, match="^provider_error:malformed_response$"):
        ModelAdapter(
            _cfg(FakeTransport([_tool_response([_tool_call(arguments=deeply_nested)])]))
        ).complete([])


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (_tool_call(call_id="call-" + chr(0xD800)), "tool_call_too_complex"),
        (_tool_call(name="tool-" + chr(0xD800)), "tool_call_too_complex"),
        (_tool_call(arguments={"query": chr(0xD800)}), "malformed_response"),
    ],
)
def test_complete_normalizes_invalid_tool_call_unicode(call, expected):
    with pytest.raises(ProviderError, match=f"^provider_error:{expected}$"):
        ModelAdapter(_cfg(FakeTransport([_tool_response([call])]))).complete([])


@pytest.mark.parametrize("invalid_count", [-1, 1.5, "2", True])
def test_complete_rejects_invalid_provider_token_counts(invalid_count):
    body = {
        "model": "test-model",
        "choices": [{"message": {}}],
        "usage": {"prompt_tokens": invalid_count, "completion_tokens": 1},
    }

    with pytest.raises(ProviderError, match="provider_error:malformed_response"):
        ModelAdapter(_cfg(FakeTransport([body]))).complete([])


def test_seed_omitted_when_provider_lacks_support():
    t = FakeTransport(
        [
            {
                "model": "test-model",
                "choices": [{"message": {}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        ]
    )
    ModelAdapter(_cfg(t, supports_seed=False)).complete([])
    assert "seed" not in t.calls[0]["body"]


def test_retries_on_5xx_then_succeeds():
    ok = {
        "model": "test-model",
        "choices": [{"message": {}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    t = FakeTransport([503, ok])
    res = ModelAdapter(_cfg(t)).complete([])
    assert res.model == "test-model"
    assert len(t.calls) == 2


def test_fails_after_max_retries_without_leaking_key(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)
    t = FakeTransport([500, 500, 500])
    try:
        ModelAdapter(_cfg(t)).complete([])
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "sekret" not in str(e)


def test_transport_and_malformed_response_errors_are_sanitized(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)

    class BrokenTransport:
        def post(self, url, headers, body):
            raise OSError("connection failed for Bearer sekret")

    try:
        ModelAdapter(_cfg(BrokenTransport())).complete([])
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        assert str(exc) == "provider_error:transport_failure"
        assert "sekret" not in str(exc)

    malformed = {
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "approve_request", "arguments": "{not-json"},
                        }
                    ]
                }
            }
        ],
    }
    try:
        ModelAdapter(_cfg(FakeTransport([malformed]))).complete([])
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        assert str(exc) == "provider_error:malformed_response"
        assert "sekret" not in str(exc)


def test_redacted_config_hides_key():
    cfg = _cfg(FakeTransport([]))
    r = cfg.redacted()
    assert r["api_key"] == "***"
    assert "transport" not in r


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/provider",
        "http://provider.example/v1",
        "https://" + "".join(("user", ":", "secret", "@")) + "provider.example/v1",
        "https://provider.example/v1?token=secret",
        "https:///v1",
    ],
)
def test_provider_base_url_rejects_unsafe_or_credential_bearing_locations(base_url):
    with pytest.raises(ProviderError, match="^provider_error:"):
        ModelAdapter(
            AdapterConfig(
                base_url=base_url,
                api_key="secret",
                model="test-model",
                transport=FakeTransport([]),
            )
        )


def test_local_http_provider_is_allowed_and_redirects_are_disabled():
    ModelAdapter(
        AdapterConfig(
            base_url="http://127.0.0.1:1234/v1",
            api_key="local-token",
            model="test-model",
            transport=FakeTransport([]),
        )
    )
    assert any(
        isinstance(handler, _NoRedirectHandler) for handler in UrllibTransport()._opener.handlers
    )


@pytest.mark.parametrize(
    ("provider_model", "expected"),
    [
        ("other-model", "provider_error:model_mismatch"),
        ("test-model\nforged", "provider_error:invalid_provider_model"),
        ("x" * 201, "provider_error:invalid_provider_model"),
    ],
)
def test_provider_model_identity_is_bounded_sanitized_and_exact(provider_model, expected):
    response = {"model": provider_model, "choices": [{"message": {}}], "usage": {}}
    with pytest.raises(ProviderError, match=f"^{expected}$") as excinfo:
        ModelAdapter(_cfg(FakeTransport([response]))).complete([])
    assert provider_model not in str(excinfo.value)


@pytest.mark.parametrize("header_name", ["content-length", "Content-Length", "cOnTeNt-LeNgTh"])
def test_urllib_rejects_announced_oversize_success_before_read(header_name):
    response = FakeResponse(
        headers={header_name: str(MAX_PROVIDER_RESPONSE_BYTES + 1)}, body=b"sekret"
    )
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}")

    assert response.read_calls == []
    assert "sekret" not in str(excinfo.value)


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "not-a-length"}])
def test_urllib_invalid_or_missing_content_length_uses_bounded_read(headers):
    response = FakeResponse(headers=headers, body=b"ok")
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    assert transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}") == (200, b"ok")
    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1, MAX_PROVIDER_RESPONSE_BYTES - 1]


def test_urllib_allows_valid_content_length_within_limit():
    response = FakeResponse(headers={"content-length": "2"}, body=b"ok")
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    assert transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}") == (200, b"ok")
    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1, MAX_PROVIDER_RESPONSE_BYTES - 1]


def test_urllib_handles_huge_decimal_content_lengths_without_integer_conversion():
    response = FakeResponse(headers={"Content-Length": "9" * 5000}, body=b"sekret")
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}")

    assert opener.calls == 1
    assert response.read_calls == []
    assert "sekret" not in str(excinfo.value)


def test_urllib_allows_huge_leading_zero_content_length_to_fall_back_to_reading():
    response = FakeResponse(headers={"Content-Length": ("0" * 5000) + "2"}, body=b"ok")
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    assert transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}") == (200, b"ok")
    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1, MAX_PROVIDER_RESPONSE_BYTES - 1]


@pytest.mark.parametrize("size", [MAX_PROVIDER_RESPONSE_BYTES, MAX_PROVIDER_RESPONSE_BYTES + 1])
def test_urllib_accumulates_fragmented_body_until_eof_or_oversize(size):
    first_size = size // 2
    first = b"a" * first_size
    second = b"b" * (size - first_size)
    response = FakeResponse(chunks=[first, second])
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    if size == MAX_PROVIDER_RESPONSE_BYTES:
        result = transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}")
        assert result[0] == 200
        assert len(result[1]) == size
        assert result[1].startswith(first[:1]) and result[1].endswith(second[-1:])
        assert response.read_calls[-1] == 1
    else:
        with pytest.raises(ProviderError, match="^provider_error:response_too_large$"):
            transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}")
        assert len(response.read_calls) == 2


def test_urllib_rejects_oversize_tail_after_valid_json_prefix_without_retry(monkeypatch):
    prefix = _valid_response_bytes()
    response = FakeResponse(
        chunks=[prefix, b"sekret" + b"x" * (MAX_PROVIDER_RESPONSE_BYTES - len(prefix) - 5)]
    )
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert opener.calls == 1
    assert len(response.read_calls) == 2
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


def test_urllib_reader_ignoring_amount_is_rejected_without_retry(monkeypatch):
    response = FakeResponse(
        body=b"sekret" + b"x" * (MAX_PROVIDER_RESPONSE_BYTES - 4), ignore_amount=True
    )
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert opener.calls == 1
    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1]
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


@pytest.mark.parametrize("status", [201, 503])
def test_urllib_normal_non_success_status_uses_error_cap_before_retry(status, monkeypatch):
    response = FakeResponse(status=status, body=b"sekret" + b"x" * (MAX_PROVIDER_ERROR_BYTES - 5))
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert opener.calls == 1
    assert response.read_calls == [MAX_PROVIDER_ERROR_BYTES + 1]
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


def test_urllib_normal_error_status_at_exact_error_limit_reaches_status_handling(monkeypatch):
    response = FakeResponse(status=503, body=b"x" * MAX_PROVIDER_ERROR_BYTES)
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:http_503$"):
        ModelAdapter(replace(_cfg(transport), max_retries=1)).complete([])

    assert opener.calls == 1
    assert response.read_calls == [MAX_PROVIDER_ERROR_BYTES + 1, 1]
    assert sleeps == []


def test_urllib_normal_invalid_status_uses_error_cap_then_fails_status(monkeypatch):
    response = FakeResponse(status=200.0, body=b"sekret")
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:invalid_transport_status$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert opener.calls == 1
    assert response.read_calls == [MAX_PROVIDER_ERROR_BYTES + 1, MAX_PROVIDER_ERROR_BYTES - 5]
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


@pytest.mark.parametrize(
    "chunk", [None, "sekret", bytearray(b"sekret"), memoryview(b"sekret"), BytesSubclass(b"sekret")]
)
def test_urllib_rejects_non_exact_bytes_chunks_without_retry(chunk, monkeypatch):
    response = FakeResponse(chunks=[chunk])
    transport = UrllibTransport()
    opener = FakeOpener(response)
    transport._opener = opener
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:invalid_transport_body$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert opener.calls == 1
    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1]
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


def test_urllib_rejects_streamed_success_limit_plus_one_without_leaking_body():
    response = FakeResponse(body=b"sekret" + b"x" * (MAX_PROVIDER_RESPONSE_BYTES - 5))
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}")

    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1]
    assert "sekret" not in str(excinfo.value)


def test_urllib_allows_exact_success_limit_for_downstream_handling():
    response = FakeResponse(body=_valid_response_bytes(MAX_PROVIDER_RESPONSE_BYTES))
    transport = UrllibTransport()
    transport._opener = FakeOpener(response)

    assert transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}") == (
        200,
        response.body,
    )
    assert response.read_calls == [MAX_PROVIDER_RESPONSE_BYTES + 1, 1]


def test_urllib_rejects_oversized_http_error_body_before_status_handling():
    response = FakeResponse(body=b"sekret" + b"x" * (MAX_PROVIDER_ERROR_BYTES - 5))
    error = urllib.error.HTTPError("https://fake.invalid", 503, "error", {}, response)
    transport = UrllibTransport()
    transport._opener = FakeOpener(error)

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        transport.post("https://fake.invalid/v1/chat/completions", {}, b"{}")

    assert response.read_calls == [MAX_PROVIDER_ERROR_BYTES + 1]
    assert "sekret" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "size"),
    [(200, MAX_PROVIDER_RESPONSE_BYTES + 1), (503, MAX_PROVIDER_ERROR_BYTES + 1)],
)
def test_injected_oversize_body_is_terminal_without_retry(status, size, monkeypatch):
    transport = TupleTransport([(status, b"sekret" + b"x" * (size - 6))])
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert transport.calls == 1
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


@pytest.mark.parametrize(
    "body", ["sekret", bytearray(b"sekret"), memoryview(b"sekret"), BytesSubclass(b"sekret")]
)
def test_injected_non_bytes_body_is_terminal_without_retry(body, monkeypatch):
    transport = TupleTransport([(200, body)])
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:invalid_transport_body$") as excinfo:
        ModelAdapter(_cfg(transport)).complete([])

    assert transport.calls == 1
    assert sleeps == []
    assert "sekret" not in str(excinfo.value)


@pytest.mark.parametrize("status", [True, "200", 200.0])
def test_injected_invalid_transport_status_is_terminal(status, monkeypatch):
    transport = TupleTransport([(status, b"{}")])
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:invalid_transport_status$"):
        ModelAdapter(_cfg(transport)).complete([])

    assert transport.calls == 1
    assert sleeps == []


def test_provider_error_from_transport_is_never_retried(monkeypatch):
    transport = TupleTransport([ProviderError("provider_error:response_too_large")])
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:response_too_large$"):
        ModelAdapter(_cfg(transport)).complete([])

    assert transport.calls == 1
    assert sleeps == []


def test_provider_error_from_response_parsing_is_never_retried(monkeypatch):
    transport = TupleTransport(
        [(200, json.dumps({"model": "other-model", "choices": [{"message": {}}]}).encode())]
    )
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    with pytest.raises(ProviderError, match="^provider_error:model_mismatch$"):
        ModelAdapter(_cfg(transport)).complete([])

    assert transport.calls == 1
    assert sleeps == []


def test_exact_body_limits_proceed_to_normal_status_or_parse_handling(monkeypatch):
    success = TupleTransport([(200, _valid_response_bytes(MAX_PROVIDER_RESPONSE_BYTES))])
    assert ModelAdapter(_cfg(success)).complete([]).model == "test-model"

    error = TupleTransport([(503, b"x" * MAX_PROVIDER_ERROR_BYTES)])
    monkeypatch.setattr(ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: None))
    with pytest.raises(ProviderError, match="^provider_error:http_503$"):
        ModelAdapter(replace(_cfg(error), max_retries=1)).complete([])
    assert error.calls == 1


def test_retryable_ordinary_5xx_still_retries(monkeypatch):
    transport = TupleTransport([(503, b"temporary"), (200, _valid_response_bytes())])
    sleeps = []
    monkeypatch.setattr(
        ModelAdapter, "_sleep_before_retry", staticmethod(lambda attempt: sleeps.append(attempt))
    )

    assert ModelAdapter(_cfg(transport)).complete([]).model == "test-model"
    assert transport.calls == 2
    assert sleeps == [1]


def test_adapter_configuration_helpers_and_redirect_behavior(monkeypatch):
    for name in ("CASCADESHIFT_BASE_URL", "CASCADESHIFT_API_KEY", "CASCADESHIFT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="missing environment variables"):
        AdapterConfig.from_env()

    monkeypatch.setenv("CASCADESHIFT_BASE_URL", "https://fake.invalid/v1/")
    monkeypatch.setenv("CASCADESHIFT_API_KEY", "sekret")
    monkeypatch.setenv("CASCADESHIFT_MODEL", "test-model")
    monkeypatch.setenv("CASCADESHIFT_PROVIDER_SUPPORTS_SEED", "true")
    cfg = AdapterConfig.from_env()
    adapter = ModelAdapter(replace(cfg, transport=FakeTransport([])))

    assert cfg.base_url == "https://fake.invalid/v1"
    assert cfg.redacted()["api_key"] == "***"
    assert adapter.model_name == "test-model"
    assert adapter.supports_seed is True
    assert _NoRedirectHandler().redirect_request(None, None, 302, "", None, "") is None
    assert sanitized_provider_error(ProviderError("provider_error:known")) == "provider_error:known"
    assert sanitized_provider_error(RuntimeError("sekret")) == "provider_error:adapter_failure"


@pytest.mark.parametrize(
    "base_url", ["https://fake.invalid:bad", "https://fake.invalid/v1#fragment"]
)
def test_adapter_rejects_invalid_configured_urls(base_url):
    with pytest.raises(ProviderError, match="^provider_error:invalid_base_url$"):
        ModelAdapter(replace(_cfg(FakeTransport([])), base_url=base_url))


def test_adapter_rejects_invalid_configured_model():
    with pytest.raises(ProviderError, match="^provider_error:invalid_configured_model$"):
        ModelAdapter(replace(_cfg(FakeTransport([])), model=""))


def test_tools_are_forwarded_to_provider():
    transport = FakeTransport([json.loads(_valid_response_bytes())])

    ModelAdapter(_cfg(transport)).complete([], tools=[{"type": "function", "function": {}}])

    assert transport.calls[0]["body"]["tools"] == [{"type": "function", "function": {}}]


def test_non_retryable_status_stops_after_one_call():
    transport = TupleTransport([(400, b"bad request")])

    with pytest.raises(ProviderError, match="^provider_error:http_400$"):
        ModelAdapter(_cfg(transport)).complete([])

    assert transport.calls == 1


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        json.dumps({"model": "test-model", "choices": []}).encode(),
        json.dumps({"model": "test-model", "choices": [{"message": []}]}).encode(),
        json.dumps({"model": "test-model", "choices": [{"message": {"content": 1}}]}).encode(),
        json.dumps({"model": "test-model", "choices": [{"message": {"tool_calls": {}}}]}).encode(),
        json.dumps(
            {
                "model": "test-model",
                "choices": [{"message": {"tool_calls": [{"id": "", "function": {}}]}}],
            }
        ).encode(),
        json.dumps({"model": "test-model", "choices": [{"message": {}}], "usage": []}).encode(),
    ],
)
def test_malformed_response_shapes_are_sanitized(body):
    with pytest.raises(ProviderError, match="^provider_error:malformed_response$"):
        ModelAdapter(_cfg(TupleTransport([(200, body)]))).complete([])


def test_none_tool_calls_and_usage_are_accepted():
    transport = TupleTransport(
        [
            (
                200,
                json.dumps(
                    {
                        "model": "test-model",
                        "choices": [{"message": {"tool_calls": None}}],
                        "usage": None,
                    }
                ).encode(),
            )
        ]
    )

    result = ModelAdapter(_cfg(transport)).complete([])

    assert result.tool_calls == ()
    assert result.prompt_tokens == result.completion_tokens == 0
