"""Exercise the actual assistant and synchronous task entry points."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from agents.knowledge import GENERAL_LABEL
from agents.planning import ModelConversationResolution
from agents.school_input import SchoolConditionQuotes
from conversation import ConversationWorkflow
from core.errors import ModelBudgetExceeded, ToolUnavailable
from core.model import ModelClient
from grounding import score_claim
from main import create_app
from schemas import ChatRequest, GeneralKnowledgeAnswer
from tests.test_answer_trust import FACT, SOURCE, analyze, enrichment
from tests.test_learning_privacy import engine, request
from tests.test_review_fixes import HEADERS, consent


@pytest.mark.asyncio
async def test_rule_conditions_survive_missing_field_and_next_turn():
    """A missing major asks for only that field and retains other accepted facts."""
    service = engine()
    flow = ConversationWorkflow(service)
    req = request(userInput="推荐2027年学硕院校", privacy={"modelAllowed": True})
    first = await flow.run(req)
    assert first["outcome"] == "NEEDS_INPUT"
    assert first["followUp"] == ["请说明目标专业名称或六位专业代码。"]
    assert first["conditions"]["examYear"] == 2027
    assert first["conditions"]["degreeType"] == "academic"
    second = await flow.run(request(userInput="081200", conditions=first["conditions"],
                                    privacy={"modelAllowed": True}))
    assert second["outcome"] == "COMPLETED"
    assert all(item["year"] == 2027 for item in second["candidates"])
    service.model.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_quotes_are_verified_against_the_current_turn():
    """Quoted language can resolve aliases while fabricated values have no effect."""
    service = engine()
    text = "请推荐27届专业型院校，只考虑江浙沪，想读计专"
    service.model.generate.return_value = ModelConversationResolution(
        action="SCHOOL_RECOMMEND", standaloneQuery=text,
        conditionPatch={"majorCodes": ["999999"], "examYear": 2099},
        schoolQuotes={"phrases": ["27届", "专业型", "江浙沪", "计专", "广东", "2099年"]},
    )
    plan = await ConversationWorkflow(service).plan(request(
        userInput=text, privacy={"modelAllowed": True},
    ))
    assert plan.conditionPatch.model_dump(exclude_unset=True) == {
        "examYear": 2027, "majorCodes": ["085404"], "degreeType": "professional",
        "regions": ["江苏", "浙江", "上海"], "regionConstraint": "required",
    }
    service.model.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_major_name_and_year_need_no_router():
    """An exact catalog title and explicit conditions can be resolved locally."""
    service = engine()
    req = request(userInput="推荐2027年计算机科学与技术学硕院校",
                  privacy={"modelAllowed": True})
    plan = await ConversationWorkflow(service).plan(req)
    assert plan.action == "SCHOOL_RECOMMEND"
    assert plan.conditionPatch.majorCodes == ["081200"]
    assert plan.conditionPatch.examYear == 2027
    service.model.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_quoted_region_cannot_turn_a_negation_into_a_preference():
    """An exact quote still has to be valid in its original context."""
    service = engine()
    text = "请推荐2027年085404专硕院校，不需要江浙沪"
    service.model.generate.return_value = ModelConversationResolution(
        action="SCHOOL_RECOMMEND", standaloneQuery=text, schoolQuotes={"phrases": ["江浙沪"]},
    )
    result = await ConversationWorkflow(service).run(request(
        userInput=text, privacy={"modelAllowed": True},
    ))
    assert result["conditions"]["regions"] is None
    assert result["outcome"] == "NEEDS_INPUT" and not result["candidates"]
    service.model.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_recommendation_parses_only_once_and_asks_about_form_conflict():
    """A current form choice cannot be silently overwritten by a text extraction."""
    service = engine()
    service.model.generate.return_value = SchoolConditionQuotes(phrases=["27届", "计专"])
    req = ChatRequest(
        taskId="school-test", userId=1, taskType="SCHOOL_RECOMMEND",
        userInput="想读27届计专，请推荐院校", preferences={"majorCodes": ["081200"]},
        privacy=consent(service.settings, "profile"),
    )
    result = await service.run(req)
    assert result["outcome"] == "NEEDS_INPUT"
    assert result["followUp"] == ["表单与文字中的专业不一致，请确认采用哪个条件。"]
    service.model.generate.assert_awaited_once()
    assert service.model.generate.call_args.args[1] == {"input": req.userInput}


@pytest.mark.asyncio
async def test_sync_recommendation_ignores_unquoted_assumptions_on_budget_failure():
    """An unparsed relative year still needs clarification even with an old profile."""
    service = engine()
    service.model.generate.side_effect = ModelBudgetExceeded("model_limit")
    req = ChatRequest(
        taskId="school-budget", userId=1, taskType="SCHOOL_RECOMMEND",
        userInput="明年想读计算机技术，请推荐院校", profile={"examYear": 2025},
        privacy=consent(service.settings),
    )
    result = await service.run(req)
    assert result["outcome"] == "NEEDS_INPUT" and "明确的报考年份" in result["answer"]
    assert not result["candidates"]
    service.model.generate.assert_awaited_once()


def test_sync_recommendation_uses_one_router_attempt_then_one_explanation():
    """Exercise the locked SDK, both model phases and the original sync envelope."""
    service = engine()
    config = service.settings.model_copy(update={"LLM_MODEL_ROUTER": "router", "LLM_MODEL_MAIN": "main"})
    calls = []

    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = body["model"]
        calls.append(name)
        value = {"phrases": ["27届", "计专"]} if name == "router" else {"explanations": []}
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": name,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(value)}}],
        })

    model = ModelClient(config)
    model.client = AsyncOpenAI(
        api_key="test-only", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    with TestClient(create_app(config, model=model)) as client:
        response = client.post("/internal/rag/chat", headers=HEADERS, json={
            "taskId": "sync-school", "userId": 1, "taskType": "SCHOOL_RECOMMEND",
            "userInput": "想读27届计专，推荐院校", "privacy": consent(config, "profile"),
        })
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["outcome"] == "COMPLETED"
    assert result["candidates"] and {row["year"] for row in result["candidates"]} == {2027}
    assert calls == ["router", "main"]


@pytest.mark.asyncio
async def test_compound_preserves_knowledge_when_school_conditions_conflict():
    """An incomplete school branch must not erase an independent answer."""
    flow = ConversationWorkflow(engine())
    result = await flow.run(request(
        userInput="讲解TCP可靠传输，并推荐2027年或2028年的081200学硕院校",
    ))
    assert result["partial"]
    assert {section["agent"]: section["outcome"] for section in result["sections"]} == {
        "KNOWLEDGE": "COMPLETED", "SCHOOL": "NEEDS_INPUT",
    }
    assert "多个报考年份" in result["answer"]


def test_stream_shows_label_before_uncited_prose_and_keeps_it_in_the_result():
    """The final result and staged text carry the same label, with no citations."""
    service = engine()
    service.model.generate.return_value = GeneralKnowledgeAnswer(answer="DNS 可解析域名。")
    app = create_app(service.settings, model=service.model)
    app.state.engine.knowledge_search.ainvoke = AsyncMock(return_value=[])
    question = "DNS 是什么？"
    req = request(userInput=question, privacy={"modelAllowed": True}, preparedPlan={
        "action": "KNOWLEDGE_QA", "standaloneQuery": question,
    })
    with TestClient(app) as client:
        response = client.post("/internal/rag/conversation/stream", headers=HEADERS,
                               json=req.model_dump(by_alias=True))
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    delta = "".join(item["text"] for item in events if item["type"] == "delta")
    final = events[-1]["response"]["result"]
    assert delta.startswith(GENERAL_LABEL) and delta == final["answer"]
    assert final["outcome"] == "COMPLETED" and final["references"] == []
    assert service.model.generate.call_args.args[1] == {"input": question}


@pytest.mark.asyncio
@pytest.mark.parametrize("text,authorized,unavailable", [
    ("DNS 是什么？", False, False),
    ("DNS 是什么？", True, True),
    ("2027年DNS真题的标准答案是什么？", True, False),
    ("我错题本里 DNS 的正确答案是什么？", True, False),
    ("DNS 的招生分数线是什么？", True, False),
    ("408 里地球是什么？", True, False),
])
async def test_uncited_model_is_only_for_public_concepts_with_a_working_retriever(
    text, authorized, unavailable, monkeypatch,
):
    """A failed dependency or an out-of-scope question makes zero model calls."""
    service = engine()
    search = AsyncMock(side_effect=ToolUnavailable("test")) if unavailable else AsyncMock(return_value=[])
    monkeypatch.setattr(service.knowledge_search, "ainvoke", search)
    req = ChatRequest(taskId="knowledge-test", userId=1, taskType="KNOWLEDGE_QA",
                      userInput=text, privacy=consent(service.settings) if authorized else {})
    result = await service.run(req)
    assert result["outcome"] == "UNSUPPORTED"
    assert ("暂时不可用" in result["answer"]) is unavailable
    service.model.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_model_cannot_return_an_uncited_link(monkeypatch):
    """Provider-produced URLs cause a single failed fallback attempt."""
    service = engine()
    monkeypatch.setattr(service.knowledge_search, "ainvoke", AsyncMock(return_value=[]))
    service.model.generate.return_value = GeneralKnowledgeAnswer(answer="见 https://example.invalid/。")
    result = await service.run(ChatRequest(
        taskId="knowledge-link", userId=1, taskType="KNOWLEDGE_QA",
        userInput="DNS 是什么？", privacy=consent(service.settings),
    ))
    assert result["outcome"] == "UNSUPPORTED"
    assert result["references"] == [] and "example.invalid" not in json.dumps(result)
    service.model.generate.assert_awaited_once()


def test_direct_negation_flip_is_rejected_even_when_all_terms_match():
    """A high lexical score cannot hide a directly reversed statement."""
    ratio, reason = score_claim("UDP 保证可靠传输。", [{"content": "UDP 不保证可靠传输。"}])
    assert ratio == 1.0 and reason == "polarity_mismatch"


@pytest.mark.asyncio
async def test_learning_retains_only_the_supported_public_concept():
    """An unsupported concept must stay out of both the answer and citation details."""
    unsupported = "TCP默认端口是99999。"
    result, _ = await analyze(enrichment(explanations=[
        {"text": FACT, "sourceIds": [SOURCE]}, {"text": unsupported, "sourceIds": [SOURCE]},
    ]), text="分析我的TCP学情")
    assert result["explanationMode"] == "fallback"
    assert FACT in result["answer"] and "有效作答12次" in result["answer"]
    assert unsupported not in json.dumps(result, ensure_ascii=False)
    assert result["citationSupport"]["status"] == "PARTIAL"
