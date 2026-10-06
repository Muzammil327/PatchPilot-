from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.llm import get_llm_client
from app.config import Settings
from app.llm.client import LLMClient
from app.main import app

client = TestClient(app)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "nebius_api_key": "test-key",
        "nebius_base_url": "https://llm.test/v1",
        "model_planner": "planner-model",
        "model_worker": "worker-model",
        "llm_max_retries": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def use_llm(handler: httpx.MockTransport | None, **overrides: object) -> None:
    app.dependency_overrides[get_llm_client] = lambda: LLMClient(
        make_settings(**overrides), transport=handler
    )


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_prompt_returns_model_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "model": "worker-model",
                "choices": [{"message": {"content": "Hello from Nemotron"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    use_llm(httpx.MockTransport(handler))

    response = client.post("/api/prompt", json={"prompt": "Say hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["output"] == "Hello from Nemotron"
    assert body["model"] == "worker-model"
    assert isinstance(body["latencyMs"], int)


def test_prompt_rejects_blank_prompt() -> None:
    use_llm(None)

    response = client.post("/api/prompt", json={"prompt": "   "})

    assert response.status_code == 422


def test_prompt_reports_unconfigured_provider() -> None:
    use_llm(None, nebius_api_key="")

    response = client.post("/api/prompt", json={"prompt": "Say hello"})

    assert response.status_code == 503
    assert response.json() == {"detail": "The model provider is not configured"}


def test_prompt_hides_provider_error_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal provider trace"})

    use_llm(httpx.MockTransport(handler))

    response = client.post("/api/prompt", json={"prompt": "Say hello"})

    assert response.status_code == 502
    assert "trace" not in response.text
