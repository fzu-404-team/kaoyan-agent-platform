"""Catalog plans are deterministic, bounded and never cause provider calls."""

import pytest

from agents.planning import ModelConversationResolution
from agents.resolver import validate_plan
from core.admission_contract import AdmissionSource, load_sources
from core.errors import InvalidModelOutput
from schemas import ConversationRequest, ConversationResolution
from tests.test_conversation import workflow


def request(text: str) -> ConversationRequest:
    """Build a synthetic request without a database or real provider."""
    return ConversationRequest(taskId="catalog-test", userId=1, taskType="CHAT", userInput=text)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", list(load_sources().values()), ids=lambda source: source.code)
async def test_catalog_plan_for_all_registered_schools(source: AdmissionSource) -> None:
    """Every registered school resolves locally without requiring year or major."""
    flow = workflow(enabled=True)
    req = request(f"帮我查询{source.name}的招生信息")
    req.privacy.modelAllowed = True
    req.privacy.provider = "https://open.bigmodel.cn/api/paas/v4"
    plan = await flow.plan(req)
    assert plan.action == "SCHOOL_LOOKUP"
    assert plan.schoolLookup.schoolName == source.name
    assert not plan.reads and not plan.steps and plan.operation == "NONE"
    await flow.run(req.model_copy(update={"preparedPlan": plan}))
    flow.engine.model.generate.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_filters_and_link_only_route_remain_distinct() -> None:
    """Catalog filters come only from this turn; explicit links retain the MCP route."""
    flow = workflow()
    plan = await flow.plan(request("查询北京大学2027年081200专业招生目录"))
    assert plan.schoolLookup.model_dump() == {"schoolName": "北京大学", "year": 2027, "majorCode": "081200"}
    assert (await flow.plan(request("只要北京大学招生官网链接"))).action == "ADMISSION_LINKS"
    for text in ("查询招生信息", "查询北京大学和清华大学招生信息", "查询北京大学2026年和2027年招生信息"):
        plan = await flow.plan(request(text))
        assert plan.clarification and not plan.reads and not plan.steps
    assert (await flow.plan(request("查询未登记测试大学招生信息"))).schoolLookup.schoolName == "未登记测试大学"


def test_model_and_prepared_plans_cannot_invent_catalog_queries() -> None:
    """Neither a model nor a mutated prepared plan can select another institution."""
    parsed = ModelConversationResolution.model_validate({
        "action": "SCHOOL_LOOKUP", "standaloneQuery": "解释TCP", "schoolLookup": {"schoolName": "北京大学"},
    })
    assert parsed.action == "CHAT" and parsed.clarification
    plan = ConversationResolution(action="SCHOOL_LOOKUP", standaloneQuery="查询清华大学招生信息",
                                  schoolLookup={"schoolName": "北京大学"})
    with pytest.raises(InvalidModelOutput):
        validate_plan(plan, request("查询清华大学招生信息"))


# Same inputs and expectations as Java SchoolScoreStatisticsTest (mirrored rules).
SCORE_CASES = [
    ("深圳大学计算机技术2026年复试线多少", {"schoolName": "深圳大学", "year": 2026, "majorCode": None}),
    ("深圳大学人工智能学院的录取分数是多少", {"schoolName": "深圳大学", "year": None, "majorCode": None}),
    ("深圳大学081200中位分", {"schoolName": "深圳大学", "year": None, "majorCode": "081200"}),
    ("南京大学计算机学院2026年录取最低分", {"schoolName": "南京大学", "year": 2026, "majorCode": None}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "lookup"), SCORE_CASES)
async def test_score_questions_use_local_catalog_lookup(text: str, lookup: dict) -> None:
    """Score questions naming one school are local catalog lookups without model calls."""
    flow = workflow(enabled=True)
    req = request(text)
    req.privacy.modelAllowed = True
    req.privacy.provider = "https://open.bigmodel.cn/api/paas/v4"
    plan = await flow.plan(req)
    assert plan.action == "SCHOOL_LOOKUP" and plan.clarification is None
    assert plan.schoolLookup.model_dump() == lookup
    validate_plan(plan, req)
    flow.engine.model.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "推荐复试线低于320的院校", "帮我择校，深圳大学复试线高吗", "如何查询深圳大学复试线",
    "深圳大学复试线官网链接", "复试线一般多少分",
])
async def test_score_trigger_keeps_other_pipelines(text: str) -> None:
    """Compound, guidance, link and school-less turns never become catalog lookups."""
    from agents.planning import school_lookup_plan
    assert school_lookup_plan(request(text)) is None


def test_score_question_with_two_universities_asks_for_one() -> None:
    """Two universities still require choosing one."""
    from agents.planning import school_lookup_plan
    plan = school_lookup_plan(request("北京大学和清华大学复试线"))
    assert plan.action == "SCHOOL_LOOKUP" and plan.clarification == "本轮包含多所院校，请只选择一所。"
