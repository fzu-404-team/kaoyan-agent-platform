"""Regressions for the 2026-11-13 Agent review: tokenizer cache, retrieval and provider degradation, logging."""

import base64
import hashlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import core.tokens as tokens
from config import Settings
from core.errors import InvalidModelOutput, ModelUnavailable, ToolUnavailable, fallback_reason
from core.logs import PROJECT_ROOT, ProjectRecords, configure_logging
from core.mcp_runtime import McpCallError, McpErrorCode
from core.model import AsyncHelloAgentsLLM
from main import create_app
from retrieval import Corpus, Retriever
from schemas import ChatRequest
from tools.knowledge import SearchParameters
from tools.registry import ValidatedTool
from workflows import Workflows

KEY = "test-only-internal-key-123456"
AGENT_ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "https://open.bigmodel.cn/api/paas/v4"


def settings(**changes) -> Settings:
    return Settings(_env_file=None, AGENT_INTERNAL_KEY=KEY, **changes)


class CountingModel:
    """Fails loudly if a degraded retrieval path still reaches the provider."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        raise ModelUnavailable("model_disabled")

    async def close(self) -> None:
        pass


@pytest.fixture
def vocabulary(tmp_path, monkeypatch):
    """A tiny checksum-matching vocabulary and isolated cache locations."""
    raw = b"\n".join(base64.b64encode(bytes([value])) + b" " + str(value).encode() for value in range(256))
    project, temporary = tmp_path / "project", tmp_path / "temporary"
    monkeypatch.setattr(tokens, "TOKENIZER_SHA", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(tokens, "PROJECT_CACHE", project)
    monkeypatch.setattr(tokens.tempfile, "gettempdir", lambda: str(temporary))
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    tokens.local_encoding.cache_clear()
    yield SimpleNamespace(raw=raw, project=project, temporary=temporary / "data-gym-cache")
    tokens.local_encoding.cache_clear()


def store(directory, raw: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / tokens.TOKENIZER_FILE).write_bytes(raw)


def test_missing_vocabulary_keeps_the_conservative_estimate(vocabulary):
    counter = tokens.TokenCounter()
    assert counter.mode == tokens.FALLBACK_MODE and counter.count("中文") == 6


def test_project_cache_vocabulary_is_used_without_the_temp_directory(vocabulary):
    store(vocabulary.project, vocabulary.raw)
    counter = tokens.TokenCounter()
    assert counter.mode == tokens.EXACT_MODE
    assert counter.count("ab") == 2


def test_corrupt_explicit_cache_falls_through_to_the_verified_project_copy(vocabulary, tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    store(explicit, b"tampered")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(explicit))
    assert tokens.verified_vocabulary() is None
    store(vocabulary.project, vocabulary.raw)
    assert tokens.verified_vocabulary() == vocabulary.raw


def test_legacy_temp_cache_still_works(vocabulary):
    store(vocabulary.temporary, vocabulary.raw)
    assert tokens.TokenCounter().mode == tokens.EXACT_MODE


def test_health_reports_the_counting_mode(vocabulary):
    with TestClient(create_app(settings(), model=CountingModel())) as client:
        assert client.get("/health").json()["tokenCounting"] == tokens.FALLBACK_MODE
    tokens.local_encoding.cache_clear()
    store(vocabulary.project, vocabulary.raw)
    with TestClient(create_app(settings(), model=CountingModel())) as client:
        health = client.get("/health").json()
    assert health["tokenCounting"] == tokens.EXACT_MODE and health["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    ToolUnavailable("向量索引尚未构建"),
    McpCallError(McpErrorCode.CONNECTION_CLOSED),
    McpCallError(McpErrorCode.CALL_LIMIT),
])
async def test_single_knowledge_answer_degrades_when_retrieval_is_unavailable(error):
    config = settings(LLM_ENABLED=True, LLM_API_KEY="test-only")
    corpus = Corpus(config.RAG_DATA, config.RAG_SOURCE_POLICY_FILE)

    async def unavailable(query: str, subject: str | None = None):
        raise error

    model = CountingModel()
    tool = ValidatedTool("retrieve_knowledge", "不可用的检索", SearchParameters, unavailable)
    engine = Workflows(config, corpus, Retriever(config, corpus), model, tool)
    result = await engine.run(ChatRequest.model_validate({
        "taskId": "review-1113", "userId": 1, "taskType": "KNOWLEDGE_QA", "userInput": "TCP拥塞控制是什么",
        "privacy": {"modelAllowed": True, "scopes": [], "provider": PROVIDER},
    }))
    assert result["outcome"] == "UNSUPPORTED" and result["explanationMode"] == "rules"
    assert "检索暂时不可用" in result["answer"] and result["references"] == []
    assert model.calls == 0


@pytest.mark.asyncio
async def test_provider_response_without_choices_is_an_expected_model_failure():
    class Completions:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    model = AsyncHelloAgentsLLM(client, model="m", api_key="k", base_url="https://provider.invalid/v1",
                                temperature=0, max_tokens=16, timeout=5)
    with pytest.raises(InvalidModelOutput) as raised:
        await model.ainvoke([{"role": "user", "content": "{}"}])
    assert fallback_reason(raised.value) == "INVALID_OUTPUT"


def record(level: int, pathname: str) -> logging.LogRecord:
    return logging.LogRecord("name", level, pathname, 1, "message", (), None)


def test_only_project_records_pass_below_warning():
    passes = ProjectRecords().filter
    assert passes(record(logging.INFO, PROJECT_ROOT + "agents/coordinator.py"))
    assert not passes(record(logging.INFO, PROJECT_ROOT + ".venv/lib/site-packages/httpx/_client.py"))
    assert not passes(record(logging.INFO, "/opt/site-packages/qdrant_client/local.py"))
    assert passes(record(logging.WARNING, "/opt/site-packages/qdrant_client/local.py"))


def test_logging_is_installed_once_and_never_over_existing_handlers():
    root = logging.Logger("isolated-root")
    assert configure_logging("INFO", root) is True
    assert configure_logging("DEBUG", root) is False
    assert len(root.handlers) == 1 and root.level == logging.INFO
    configured = logging.Logger("externally-configured")
    existing = logging.NullHandler()
    configured.addHandler(existing)
    assert configure_logging("INFO", configured) is False
    assert configured.handlers == [existing] and configured.level == logging.NOTSET


def test_application_factory_leaves_configured_root_logging_untouched():
    root = logging.getLogger()
    # pytest installs its capture handlers on the root logger for every test.
    assert root.handlers
    handlers, level = list(root.handlers), root.level
    create_app(settings(LOG_LEVEL="debug"), model=CountingModel())
    assert root.handlers == handlers and root.level == level


def test_entrypoint_owns_log_output_in_a_fresh_process():
    """The framework import must not configure logging; the factory applies LOG_LEVEL once."""
    code = (
        "import logging\n"
        "import core.framework\n"
        "root = logging.getLogger()\n"
        "assert not root.handlers and root.level == logging.WARNING, (root.handlers, root.level)\n"
        "from config import Settings\n"
        "from main import create_app\n"
        "settings = Settings(_env_file=None)\n"
        "create_app(settings)\n"
        "create_app(settings)\n"
        "assert len(root.handlers) == 1 and root.level == logging.INFO, (root.handlers, root.level)\n"
        "from core.model import prepare_input\n"
        "from schemas import Answer\n"
        "prepare_input(settings, 'x', {'input': 'x'}, Answer)\n"
        "logging.getLogger('third.party').info('third-party-info-hidden')\n"
        "logging.getLogger('third.party').warning('third-party-warning-visible')\n"
    )
    environment = {**os.environ, "AGENT_INTERNAL_KEY": KEY, "LOG_LEVEL": "info", "LLM_ENABLED": "false"}
    done = subprocess.run([sys.executable, "-c", code], cwd=AGENT_ROOT, env=environment,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    lines = done.stderr.splitlines()
    # The record comes from a project module, so INFO passes with a timestamp.
    assert any(re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO core\.context context mode=", line) for line in lines)
    assert any(line.endswith("WARNING third.party third-party-warning-visible") for line in lines)
    assert "third-party-info-hidden" not in done.stderr


def test_log_level_is_normalized_and_validated():
    assert settings(LOG_LEVEL=" info ").LOG_LEVEL == "INFO"
    with pytest.raises(ValidationError):
        settings(LOG_LEVEL="verbose")
