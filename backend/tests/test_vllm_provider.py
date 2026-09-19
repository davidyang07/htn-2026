import asyncio
import json

import httpx
import pytest

from app.gateway.schemas import ModelProviderError, ModelRequest
from app.gateway.vllm_provider import VLLMProvider


def _request() -> ModelRequest:
    return ModelRequest(
        agent_id="agent-000",
        seed=1,
        tick=0,
        system_prompt="system prompt with secret",
        user_message="injection payload",
        max_tokens=64,
        mock_leak_probability=0.5,
    )


def _client_with_handler(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def test_sends_openai_compatible_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"total_tokens": 7},
            },
        )

    async def run():
        async with _client_with_handler(handler) as client:
            provider = VLLMProvider(
                client,
                base_url="http://vllm.local:8000",
                api_key="secret-key",
                model_name="qwen-test",
            )
            return await provider.complete(_request())

    response = asyncio.run(run())

    assert captured["url"] == "http://vllm.local:8000/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    assert captured["body"]["model"] == "qwen-test"
    assert captured["body"]["max_tokens"] == 64
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "system prompt with secret"},
        {"role": "user", "content": "injection payload"},
    ]
    assert response.text == "hello"
    assert response.tokens_used == 7
    assert response.provider == "vllm"


def test_no_api_key_omits_auth_header():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async def run():
        async with _client_with_handler(handler) as client:
            provider = VLLMProvider(
                client, base_url="http://vllm.local:8000", api_key=None, model_name="qwen-test"
            )
            return await provider.complete(_request())

    asyncio.run(run())
    assert "authorization" not in captured["headers"]


def test_http_error_raises_model_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async def run():
        async with _client_with_handler(handler) as client:
            provider = VLLMProvider(
                client, base_url="http://vllm.local:8000", api_key=None, model_name="qwen-test"
            )
            await provider.complete(_request())

    with pytest.raises(ModelProviderError):
        asyncio.run(run())


def test_malformed_response_shape_raises_model_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    async def run():
        async with _client_with_handler(handler) as client:
            provider = VLLMProvider(
                client, base_url="http://vllm.local:8000", api_key=None, model_name="qwen-test"
            )
            await provider.complete(_request())

    with pytest.raises(ModelProviderError):
        asyncio.run(run())


def test_connection_error_raises_model_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async def run():
        async with _client_with_handler(handler) as client:
            provider = VLLMProvider(
                client, base_url="http://vllm.local:8000", api_key=None, model_name="qwen-test"
            )
            await provider.complete(_request())

    with pytest.raises(ModelProviderError):
        asyncio.run(run())


def test_falls_back_to_token_estimate_without_usage_field():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "a" * 40}}]})

    async def run():
        async with _client_with_handler(handler) as client:
            provider = VLLMProvider(
                client, base_url="http://vllm.local:8000", api_key=None, model_name="qwen-test"
            )
            return await provider.complete(_request())

    response = asyncio.run(run())
    assert response.tokens_used == 10  # len("a"*40) // 4
