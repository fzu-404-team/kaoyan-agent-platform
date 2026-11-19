"""score-match-v1 (2026-11-19): score-based school matching.

Contract: 考研Agent平台搭建文档.md#按分数择校契约2026-11-19.
"""

import json
from pathlib import Path

import pytest

from intents import IntentResolver
from schemas import ChatRequest, Preferences, ScoreQuery
from score_query import COMBO_FOLLOW_UP, combo_supplement, parse_text, resolve_score, score_school_request
from tests.test_conversation import workflow
from tests.test_multiagent import request as conversation_request
from tests.test_workflows import FakeModel, client, post, request, score_record
from tools.schools import score_tier

FEATURE = Path(__file__).parents[1] / "knowledge/feature-2027-corpus.json"


def stat(record_id: str, school: str, college: str, minimum: str, median: str, year: int = 2026,
         combo: str = "11408", flags: tuple[str, ...] = ()) -> dict:
    """Score statistics row for one school, college and major with given scores."""
    record = score_record(record_id, school, year, combo=combo, flags=flags)
    record["metadata"].update(college=college, minScore=minimum, medianScore=median, retestLine="")
    return record


def corpus(tmp_path: Path, extra: list[dict]) -> str:
    """Write the feature corpus plus extra records and return its path."""
    records = json.loads(FEATURE.read_text()) + extra
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return str(path)


# With a total of 320 (英一数一): REACH 国科大, MATCH 南审 and 上海师大 (score history only),
# SAFE 中传, BELOW 北航, NO_DATA 川大 (conflicting rows), 燕山 (flagged only), 安师 and 华南师范 (none).
TIERED = [
    stat("s-nau", "南京审计大学", "计算机学院", "300", "330"),
    stat("s-ucas", "中国科学院大学", "计算机科学与技术学院", "330", "360"),
    stat("s-cuc", "中国传媒大学", "计算机与网络空间安全学院", "290", "310"),
    stat("s-buaa", "北京航空航天大学", "计算机学院", "360", "380"),
    stat("s-scu-a", "四川大学", "计算机学院（软件学院）", "300", "320"),
    stat("s-scu-b", "四川大学", "计算机学院（软件学院）", "305", "320"),
    stat("s-ysu", "燕山大学", "人工智能学院", "280", "300", flags=("POSSIBLE_SAME_POOL",)),
    stat("s-shnu", "上海师范大学", "计算机学院", "305", "325"),
    stat("s-old", "中国科学院大学", "计算机科学与技术学院", "250", "260", year=2025),
    stat("s-usst", "上海理工大学", "计算机学院", "300", "330", combo="22408"),
]


@pytest.mark.parametrize("text,totals,english,math", [
    ("我估分320，推荐哪些学校", {320}, set(), set()),
    ("数一英一408，估分320", {320}, {"1"}, {"1"}),
    ("考了330分英二数二", {330}, {"2"}, {"2"}),
    ("英语（一）数学（二），模考310分", {310}, {"1"}, {"2"}),
    ("2027年考081200，推荐学校", set(), set(), set()),
    ("408分数一般，2027年考081200", set(), set(), set()),
    ("复试线300分以上的学校", set(), set(), set()),
    ("数学130分，估分330", {330}, set(), set()),
    ("政治70英语65数学110专业课100，总分345", {345}, set(), set()),
    ("320-340分推荐学校", {320, 340}, set(), set()),
    ("分数一般，估分300", {300}, set(), set()),
])
def test_text_parsing_is_deterministic(text, totals, english, math):
    parsed = parse_text(text)
    assert (set(parsed.totals), set(parsed.english), set(parsed.math)) == (totals, english, math)


def test_resolution_order_conflicts_and_follow_up():
    none = Preferences()
    assert resolve_score(None, "推荐学校", [], none) == (None, [])
    assert resolve_score(None, "我估分320，推荐哪些学校", [], none) == (None, [COMBO_FOLLOW_UP])
    assert resolve_score(None, "估分320，英一数一", [], none)[0] == ScoreQuery(total=320, examCombo="11408")
    # A follow-up that only adds the combo reuses the latest user message's total.
    assert resolve_score(None, "英一数一", ["你好", "我估分320，推荐哪些学校"], none)[0].total == 320
    form = ScoreQuery(total=320, examCombo="22408")
    assert resolve_score(form, "推荐学校", [], none) == (form, [])
    assert resolve_score(form, "估分330", [], none)[1] == ["表单填写的总分与原话不一致，请确认。"]
    assert resolve_score(form, "估分320，英一", [], none)[1] == ["表单与原话中的英语科目不一致，请确认。"]
    assert resolve_score(None, "320-340分推荐学校", [], none)[1] == ["本轮出现多个总分，请只给出一个估分。"]
    inferred = Preferences(examSubjects=["101", "201", "302", "408"])
    assert resolve_score(None, "估分320", [], inferred)[0].examCombo == "12408"
    assert resolve_score(None, "估分320，数一", [], inferred)[1] == ["所选考试科目与分数对应的数学科目不一致，请确认。"]


def test_tier_boundaries():
    assert score_tier(330, 300, 330) == "SAFE"
    assert score_tier(329, 300, 330) == "MATCH"
    assert score_tier(300, 300, 330) == "MATCH"
    assert score_tier(285, 300, 330) == "REACH"
    assert score_tier(284, 300, 330) == "BELOW"


def test_chat_routing_recognizes_score_questions():
    for text in ("我估分320，推荐哪些学校", "模考330分，英一数一，有什么学校推荐", "估分320能上岸吗", "英一数一"):
        assert IntentResolver.fallback_action(text, ()) == "SCHOOL_RECOMMEND", text
    assert not score_school_request("我估分320")
    assert not combo_supplement("数一考什么")
    assert IntentResolver.fallback_action("TCP三次握手", ()) != "SCHOOL_RECOMMEND"


def test_schema_accepts_score_only_for_school_recommendation():
    ChatRequest.model_validate(request(scoreQuery={"total": 320, "examCombo": "11408"}))
    for change in ({"total": 501, "examCombo": "11408"}, {"total": 320, "examCombo": "408"}):
        with pytest.raises(ValueError):
            ChatRequest.model_validate(request(scoreQuery=change))
    with pytest.raises(ValueError):
        ChatRequest.model_validate(request("KNOWLEDGE_QA", userInput="TCP", scoreQuery={"total": 320, "examCombo": "11408"}))


def test_tiers_counts_order_and_rule_only_answer(tmp_path):
    model = FakeModel()
    body = request(scoreQuery={"total": 320, "examCombo": "11408"},
                   preferences={"degreeType": "academic", "explainWithAi": True})
    with client(model=model, enabled=True, RAG_DATA=corpus(tmp_path, TIERED)) as c:
        result = post(c, body)["result"]
    assert model.calls == 0 and result["explanationMode"] == "rules"
    assert [(c["school"], c["scoreMatch"]["tier"]) for c in result["candidates"]] == [
        ("中国科学院大学", "REACH"), ("南京审计大学", "MATCH"), ("上海师范大学", "MATCH"), ("中国传媒大学", "SAFE")]
    nau = result["candidates"][1]
    assert nau["evidenceLevel"] == "OFFICIAL_VERIFIED" and nau["scoreMatch"] == {
        "ruleVersion": "score-match-v1", "tier": "MATCH", "statYear": 2026, "college": "计算机学院",
        "examCombo": "11408", "minScore": 300, "medianScore": 330, "gapToMin": 20}
    assert result["candidates"][2]["evidenceLevel"] == "SCORE_HISTORY"
    assert result["scoreFilter"]["counts"] == {"comparable": 4, "below": 1, "noData": 4, "comboMismatch": 0}
    assert result["scoreFilter"]["ruleVersion"] == "score-match-v1" and "不代表录取概率" in result["scoreFilter"]["notice"]
    assert "冲刺1所、稳妥2所、保底1所" in result["answer"] and "320" not in result["answer"]
    assert "scoreQuery" not in json.dumps(result, ensure_ascii=False)


def test_other_combo_counts_mismatch_and_empty_tier_is_unsupported(tmp_path):
    with client(RAG_DATA=corpus(tmp_path, TIERED)) as c:
        other = post(c, request(scoreQuery={"total": 320, "examCombo": "22408"}))["result"]
        low = post(c, request(scoreQuery={"total": 200, "examCombo": "11408"}))["result"]
    assert [c["school"] for c in other["candidates"]] == ["上海理工大学"]
    assert other["scoreFilter"]["counts"]["comboMismatch"] == 8
    assert low["outcome"] == "UNSUPPORTED" and low["candidates"] == []
    assert low["scoreFilter"]["counts"] == {"comparable": 0, "below": 5, "noData": 4, "comboMismatch": 0}
    assert low["followUp"] and "未找到" in low["answer"]


def test_matching_catalog_clue_is_acknowledged_when_no_formal_candidates_match(tmp_path: Path) -> None:
    documents = json.loads(FEATURE.read_text(encoding="utf-8"))
    example = next(row for row in documents if row["domain"] == "school")
    name = "目录示例大学"
    clue = dict(example, id="part-time-clue", reviewStatus="catalog_approved", metadata=dict(
        example["metadata"], programId="part-time-clue", school=name, college="计算机学院",
        region="北京", year=2027, majorCode="081200", degreeType="academic", studyMode="part_time",
        examSubjects=["101", "201", "301", "408"], admissionCategory="special", catalogReview="USER_APPROVED",
    ))
    body = request(scoreQuery={"total": 320, "examCombo": "11408"},
                   preferences={"degreeType": "academic", "studyMode": "part_time"})
    with client(RAG_DATA=corpus(tmp_path, [clue, stat("clue-score", name, "计算机学院", "300", "330")])) as c:
        result = post(c, body)["result"]

    assert result["outcome"] == "COMPLETED"
    assert result["candidates"] == []
    assert [row["school"] for row in result["unverifiedCandidates"]] == [name]
    assert "目录线索有可比的往年分数" in result["answer"]
    assert "未找到处于冲刺范围" not in result["answer"]


def test_quota_fills_from_other_tiers_and_rotates_by_task(tmp_path):
    reach = [stat(f"r{i}", f"冲刺样例大学{i}", "计算机学院", "330", "350") for i in range(8)]
    safe = [stat("safe", "保底样例大学", "计算机学院", "280", "300")]
    tiers, chosen = set(), set()
    with client(RAG_DATA=corpus(tmp_path, reach + safe)) as c:
        for index in range(6):
            # The feature corpus's verified schools have no statistics here, so they are NO_DATA.
            body = request(taskId=f"quota-{index}", scoreQuery={"total": 320, "examCombo": "11408"})
            result = post(c, body)["result"]
            rows = [(c["school"], c["scoreMatch"]["tier"]) for c in result["candidates"]]
            tiers.add(tuple(tier for _, tier in rows))
            chosen.update(school for school, tier in rows if tier == "REACH")
    # No MATCH school: the free slots go to SAFE (none left), then REACH.
    assert tiers == {("REACH", "REACH", "REACH", "REACH", "SAFE")}
    assert len(chosen) > 4


def test_without_score_results_are_unchanged(tmp_path):
    with client(RAG_DATA=corpus(tmp_path, TIERED)) as c:
        result = post(c, request(preferences={"degreeType": "academic", "explainWithAi": False}))["result"]
    assert "scoreFilter" not in result
    assert all("scoreMatch" not in c for c in result["candidates"])
    assert len(result["candidates"]) == 5


@pytest.mark.asyncio
async def test_chat_score_question_reaches_the_school_rules():
    flow = workflow()
    plan = await flow.plan(conversation_request("我估分320，英一数一，推荐哪些学校"))
    assert plan.action == "SCHOOL_RECOMMEND"
    flow.engine.model.generate.assert_not_awaited()
    result = await flow.run(conversation_request(
        "我估分320，英一数一，推荐哪些学校",
        profile={"examYear": 2027, "targetMajor": "081200", "degreeType": "academic"}))
    # The default corpus has no score statistics: every school lacks comparable data.
    assert result["scoreFilter"]["counts"]["comparable"] == 0 and result["scoreFilter"]["counts"]["noData"] > 0
    asked = await flow.run(conversation_request(
        "我估分320，推荐哪些学校", profile={"examYear": 2027, "targetMajor": "081200", "degreeType": "academic"}))
    assert asked["outcome"] == "NEEDS_INPUT" and COMBO_FOLLOW_UP in json.dumps(asked, ensure_ascii=False)
