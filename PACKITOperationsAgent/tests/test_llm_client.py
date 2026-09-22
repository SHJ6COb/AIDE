from types import SimpleNamespace

import pytest
from google.genai import types as genai_types

from app.core.llm_client import (
    GeminiClient,
    LLMUnavailableError,
    Message,
    ModelFarmClient,
    OpenAIClient,
    Response,
    ToolCall,
    ToolSchema,
    _build_anthropic_tools,
    _build_gemini_tools,
    _build_openai_tools,
    _to_gemini_role,
    _to_response,
    _to_response_from_anthropic,
    _to_response_from_openai,
    build_llm_client,
    quick_check,
    wrap_untrusted_data,
)


def test_wrap_untrusted_data_uses_explicit_delimiters():
    wrapped = wrap_untrusted_data({"status": "ERROR"})
    assert wrapped.startswith("<untrusted_tool_data>")
    assert wrapped.rstrip().endswith("</untrusted_tool_data>")
    assert '"status": "ERROR"' in wrapped


def test_wrap_untrusted_data_serializes_non_json_native_types():
    class Custom:
        def __str__(self):
            return "custom-repr"

    wrapped = wrap_untrusted_data({"thing": Custom()})
    assert "custom-repr" in wrapped


def test_assistant_role_maps_to_model_user_role_maps_to_user():
    assert _to_gemini_role("assistant") == "model"
    assert _to_gemini_role("user") == "user"


def test_build_gemini_tools_wraps_function_declarations():
    schema = ToolSchema(name="get_ps_status", description="desc", parameters={"type": "object", "properties": {}})
    tools = _build_gemini_tools([schema])
    assert len(tools) == 1
    assert tools[0].function_declarations[0].name == "get_ps_status"


def _make_response(parts: list[genai_types.Part]) -> genai_types.GenerateContentResponse:
    return genai_types.GenerateContentResponse(
        candidates=[genai_types.Candidate(content=genai_types.Content(role="model", parts=parts))]
    )


def test_to_response_extracts_tool_call():
    raw = _make_response([genai_types.Part(function_call=genai_types.FunctionCall(name="get_ps_status", args={"ps_id": "123"}))])
    response = _to_response(raw)
    assert response.text is None
    assert response.tool_calls == [ToolCall(name="get_ps_status", arguments={"ps_id": "123"})]


def test_to_response_extracts_text():
    raw = _make_response([genai_types.Part(text="the status is healthy")])
    response = _to_response(raw)
    assert response.text == "the status is healthy"
    assert response.tool_calls == []


def test_to_response_no_candidates_returns_empty_response():
    raw = genai_types.GenerateContentResponse(candidates=[])
    response = _to_response(raw)
    assert response.text is None
    assert response.tool_calls == []


def _fake_config(**overrides):
    defaults = dict(gemini_api_key="fake-key", gemini_model="gemini-flash-latest", gemini_timeout_seconds=20)
    return SimpleNamespace(**{**defaults, **overrides})


def test_generate_wraps_underlying_exception_without_leaking_its_message(monkeypatch):
    """Regression test: caught live via QA testing -- a raw proxy exception
    (including its internal hostname/port) propagated uncaught all the way
    to the chat UI. Any failure in the underlying SDK call must become the
    fixed, safe LLMUnavailableError message -- never str(the real exception)."""
    client = GeminiClient(_fake_config())
    monkeypatch.setattr(
        client._client.models,
        "generate_content",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("407 Proxy Authentication Required: internal-host:8080")),
    )

    with pytest.raises(LLMUnavailableError) as exc_info:
        client.generate([Message(role="user", content="hi")], tools=[], system_instruction="sys")

    assert "internal-host" not in str(exc_info.value)
    assert "8080" not in str(exc_info.value)
    assert "temporarily unavailable" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)  # original exception still chained for server logs


def test_generate_passes_through_normally_on_success(monkeypatch):
    client = GeminiClient(_fake_config())
    monkeypatch.setattr(
        client._client.models,
        "generate_content",
        lambda **kwargs: _make_response([genai_types.Part(text="all good")]),
    )

    response = client.generate([Message(role="user", content="hi")], tools=[], system_instruction="sys")

    assert response.text == "all good"


def test_client_configured_with_timeout_in_milliseconds():
    client = GeminiClient(_fake_config(gemini_timeout_seconds=20))
    http_options = client._client.models._api_client._http_options
    assert http_options.timeout == 20_000


def _fake_model_farm_config(**overrides):
    defaults = dict(
        model_farm_api_key="fake-key",
        model_farm_base_url="https://aoai-farm.bosch-temp.com/api",
        model_farm_deployment="google-gemini-3-5-flash",
        model_farm_model="gemini-3.5-flash",
        model_farm_timeout_seconds=20,
    )
    return SimpleNamespace(**{**defaults, **overrides})


def test_build_openai_tools_wraps_function_schema():
    schema = ToolSchema(name="get_ps_status", description="desc", parameters={"type": "object", "properties": {}})
    tools = _build_openai_tools([schema])
    assert tools == [{"type": "function", "function": {"name": "get_ps_status", "description": "desc", "parameters": {"type": "object", "properties": {}}}}]


def _fake_openai_response(*, content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _fake_tool_call(name: str, arguments: dict):
    import json as _json

    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=_json.dumps(arguments)))


def test_to_response_from_openai_extracts_text():
    raw = _fake_openai_response(content="the status is healthy")
    response = _to_response_from_openai(raw)
    assert response.text == "the status is healthy"
    assert response.tool_calls == []


def test_to_response_from_openai_extracts_tool_call_and_parses_json_arguments():
    """Confirmed real: unlike Gemini's function_call.args (already a dict),
    OpenAI's tool_calls carry .function.arguments as a JSON *string* --
    must be parsed, not used as-is."""
    raw = _fake_openai_response(tool_calls=[_fake_tool_call("get_ps_status", {"ps_id": "123"})])
    response = _to_response_from_openai(raw)
    assert response.text is None
    assert response.tool_calls == [ToolCall(name="get_ps_status", arguments={"ps_id": "123"})]


def test_model_farm_client_base_url_and_auth_header():
    """Confirmed real (modelFarm Docupedia export, "Python OpenAI SDK for
    Gemini" example): base_url must include the deployment path, and the
    real auth is the genaiplatform-farm-subscription-key header -- the
    openai SDK's own Authorization: Bearer (from api_key) is a required
    placeholder for this gateway, not the actual check."""
    client = ModelFarmClient(_fake_model_farm_config())
    assert client._client.base_url == "https://aoai-farm.bosch-temp.com/api/openai/deployments/google-gemini-3-5-flash/"
    assert client._client.default_headers["genaiplatform-farm-subscription-key"] == "fake-key"


def test_model_farm_generate_wraps_underlying_exception_without_leaking_its_message(monkeypatch):
    client = ModelFarmClient(_fake_model_farm_config())
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("407 Proxy Authentication Required: internal-host:8080")),
    )

    with pytest.raises(LLMUnavailableError) as exc_info:
        client.generate([Message(role="user", content="hi")], tools=[], system_instruction="sys")

    assert "internal-host" not in str(exc_info.value)
    assert "temporarily unavailable" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_model_farm_generate_passes_through_normally_on_success(monkeypatch):
    client = ModelFarmClient(_fake_model_farm_config())
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        lambda **kwargs: _fake_openai_response(content="all good"),
    )

    response = client.generate([Message(role="user", content="hi")], tools=[], system_instruction="sys")

    assert response.text == "all good"


def test_model_farm_generate_includes_system_message_and_model_name(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_openai_response(content="ok")

    client = ModelFarmClient(_fake_model_farm_config(model_farm_model="gemini-3.5-flash"))
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)

    client.generate([Message(role="user", content="hi")], tools=[], system_instruction="be helpful")

    assert captured["model"] == "gemini-3.5-flash"
    assert captured["messages"][0] == {"role": "system", "content": "be helpful"}
    assert captured["messages"][1] == {"role": "user", "content": "hi"}


def _fake_openai_personal_config(**overrides):
    defaults = dict(openai_api_key="sk-test", openai_model="gpt-4o", openai_timeout_seconds=20)
    return SimpleNamespace(**{**defaults, **overrides})


def test_openai_client_talks_to_the_public_api_not_a_gateway():
    """The personal-key path must not inherit ModelFarmClient's deployment
    path segment or subscription header -- those are Azure-gateway concerns
    and would 404 against api.openai.com."""
    client = OpenAIClient(_fake_openai_personal_config())
    assert "aoai-farm" not in str(client._client.base_url)
    assert "genaiplatform-farm-subscription-key" not in client._client.default_headers


def test_openai_client_shares_the_chat_completions_request_shape(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_openai_response(content="ok")

    client = OpenAIClient(_fake_openai_personal_config(openai_model="gpt-4o"))
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)

    client.generate([Message(role="user", content="hi")], tools=[], system_instruction="be helpful")

    assert captured["model"] == "gpt-4o"
    assert captured["messages"][0] == {"role": "system", "content": "be helpful"}


def test_openai_client_wraps_underlying_exception(monkeypatch):
    client = OpenAIClient(_fake_openai_personal_config())
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("407 Proxy Authentication Required: internal-host:8080")),
    )
    with pytest.raises(LLMUnavailableError) as exc_info:
        client.generate([Message(role="user", content="hi")], tools=[], system_instruction="sys")
    assert "internal-host" not in str(exc_info.value)


def test_build_anthropic_tools_renames_parameters_to_input_schema():
    """Anthropic's only structural difference from the other two tool
    schemas -- getting this wrong means tool calling silently never fires."""
    schema = ToolSchema(name="get_ps_status", description="desc", parameters={"type": "object", "properties": {}})
    assert _build_anthropic_tools([schema]) == [
        {"name": "get_ps_status", "description": "desc", "input_schema": {"type": "object", "properties": {}}}
    ]


def test_to_response_from_anthropic_reads_peer_content_blocks():
    """Anthropic returns text and tool use as peer blocks in one list, not a
    message with a separate tool_calls array -- and tool input arrives as a
    dict, unlike OpenAI's JSON string."""
    raw = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="checking that now"),
            SimpleNamespace(type="tool_use", name="get_ps_status", input={"ps_id": "123"}),
        ]
    )
    response = _to_response_from_anthropic(raw)
    assert response.text == "checking that now"
    assert response.tool_calls == [ToolCall(name="get_ps_status", arguments={"ps_id": "123"})]


def test_build_llm_client_dispatches_on_provider():
    client = build_llm_client(_fake_model_farm_config(llm_provider="model_farm"))
    assert isinstance(client, ModelFarmClient)


def test_build_llm_client_rejects_unknown_provider_with_the_fix_in_the_message():
    with pytest.raises(ValueError, match="packit-agent init"):
        build_llm_client(SimpleNamespace(llm_provider="mistral"))


class _StubClient:
    def __init__(self, *, text=None, error=None):
        self._text = text
        self._error = error

    def generate(self, messages, tools, *, system_instruction):
        if self._error is not None:
            raise self._error
        return Response(text=self._text)


def _patch_built_client(monkeypatch, client):
    monkeypatch.setattr("app.core.llm_client.build_llm_client", lambda config: client)


def test_quick_check_reports_success_with_the_models_own_reply(monkeypatch):
    _patch_built_client(monkeypatch, _StubClient(text=" OK "))
    result = quick_check(SimpleNamespace(llm_provider="openai"))
    assert result.ok
    assert result.detail == "OK"


def test_quick_check_surfaces_the_real_cause_not_the_safe_end_user_message(monkeypatch):
    """Deliberate inversion of the runtime rule: the wizard's audience is the
    person configuring their own machine, and "invalid api key" vs. "proxy
    refused" are completely different fixes. The generic message would make
    the check useless."""
    cause = RuntimeError("401 invalid api key")
    _patch_built_client(monkeypatch, _StubClient(error=LLMUnavailableError("unavailable")))
    result = quick_check(SimpleNamespace(llm_provider="openai"))
    assert not result.ok

    error = LLMUnavailableError("The AI service is temporarily unavailable. Please try again.")
    error.__cause__ = cause
    _patch_built_client(monkeypatch, _StubClient(error=error))
    result = quick_check(SimpleNamespace(llm_provider="openai"))
    assert "401 invalid api key" in result.detail


def test_quick_check_treats_an_empty_reply_as_failure(monkeypatch):
    """A 200 with no text still breaks the harness, which composes its answer
    from response.text -- so it can't count as a passing setup check."""
    _patch_built_client(monkeypatch, _StubClient(text=""))
    result = quick_check(SimpleNamespace(llm_provider="openai"))
    assert not result.ok
    assert "no text content" in result.detail


def test_quick_check_never_raises_on_an_unexpected_error(monkeypatch):
    _patch_built_client(monkeypatch, _StubClient(error=ValueError("something odd")))
    result = quick_check(SimpleNamespace(llm_provider="openai"))
    assert not result.ok
    assert "ValueError" in result.detail


def test_quota_exhaustion_is_not_reported_as_temporary():
    """A 403 quota rejection and a network outage need opposite responses, and
    were previously indistinguishable to every caller.

    On 2026-08-07 the Model Farm returned `403 Token quota is exceeded. Try
    again in 24 days, 14 hours` and the app said "temporarily unavailable,
    please try again" -- wording that invites retrying for three and a half
    weeks.
    """
    from app.core.llm_client import _llm_unavailable

    class _Response:
        status_code = 403

    class _QuotaError(Exception):
        response = _Response()
        message = "Token quota is exceeded."

    message = str(_llm_unavailable(_QuotaError()))
    assert "quota" in message.lower()
    assert "temporarily unavailable" not in message.lower()


def test_an_ordinary_failure_still_reads_as_temporary():
    from app.core.llm_client import _llm_unavailable

    assert "temporarily unavailable" in str(_llm_unavailable(TimeoutError("connect timed out")))


def test_no_failure_message_ever_quotes_the_underlying_exception():
    """The fixed wording exists because a corporate proxy's hostname and port
    once reached the chat UI verbatim. Inspecting the exception to *choose* a
    message must never become quoting it into one."""
    from app.core.llm_client import _llm_unavailable

    secret = "proxy.internal.example.com:3128"
    for exc in (TimeoutError(secret), ConnectionError(secret)):
        assert secret not in str(_llm_unavailable(exc))
