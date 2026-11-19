"""HelloAgents domain implementation preserving the existing business rules."""

import logging
from collections import Counter

from agents.base import StructuredAgent
from agents.school_input import school_input_issues, school_needs_input
from core.errors import MODEL_FAILURES, InvalidModelOutput, fallback_reason, failure_reason
from core.model import prepare_input
from core.admission_contract import AdmissionLinksResult
from core.mcp_runtime import McpCallError, McpErrorCode
from core.runtime import withhold_model_deltas
from grounding import aggregate, verify
from learning import has_scope, model_allowed, model_messages
from prompts import get
from schemas import (
    AdmissionLinksQuery,
    ChatRequest,
    ConversationRequest,
    ConversationResolution,
    Explanations,
    Preferences,
    Profile,
)
from score_query import combo_subjects, resolve_score
from tools.schools import SCORE_RULE, TIER_QUOTA, school_tools

log = logging.getLogger(__name__)


DEGREE_LABELS = {"academic": "学硕", "professional": "专硕"}
DEGREE_FOLLOW_UP = "请在个人档案选择学硕或专硕（也可在本轮说明）"
DEGREE_SOURCES = {"profile": "来自个人档案", "catalog": "按目标专业代码在院校库中推断"}
CATALOG_LABELS = {
    "CATALOG_CHECKED": "此前已核对目录",
    "USER_APPROVED": "已批准入库，待官网核实",
}



SCORE_NOTICE = (
    "按往年录取最低分／中位分分层，数据为用户提供并经用户审核批准，非学校官网原文；"
    "公布录取数可能为共用录取池；往年分数不代表今年分数线，分层不代表录取概率。"
)
TIER_LABELS = {"REACH": "冲刺", "MATCH": "稳妥", "SAFE": "保底"}
SUBJECT_LABELS = {"1": "一", "2": "二", "3": "三"}


def combo_label(combo: str) -> str:
    """Render "11408" as 英语一＋数学一＋408."""
    return f"英语{SUBJECT_LABELS[combo[0]]}＋数学{SUBJECT_LABELS[combo[1]]}＋408"


def score_counts(statuses: list[list[str]], excluded: list[dict]) -> dict[str, int]:
    """Count schools for scoreFilter: comparable, below, no data, combo mismatch only."""
    by_school: dict[str, set[str]] = {}
    for school, status in statuses:
        by_school.setdefault(school, set()).add(status)
    comparable = {s for s, found in by_school.items() if found & set(TIER_QUOTA)}
    below = {s for s, found in by_school.items() if s not in comparable and "BELOW" in found}
    mismatch = {
        row["school"] for row in excluded if row["reasons"] == ["考试科目不匹配"]
    } - set(by_school)
    return {
        "comparable": len(comparable),
        "below": len(below),
        "noData": len(by_school) - len(comparable) - len(below),
        "comboMismatch": len(mismatch),
    }


def score_answer(combo: str, candidates: list[dict], counts: dict[str, int], *, has_catalog: bool) -> str:
    """Rule answer for score-based matching; never repeats the raw total."""
    tiers = Counter(c["scoreMatch"]["tier"] for c in candidates)
    skipped = (
        f"另有{counts['below']}所低于往年范围、{counts['noData']}所缺可比分数、"
        f"{counts['comboMismatch']}所科目组合不符或未登记，未列入。"
    )
    if not candidates:
        empty = (
            "未找到符合分数条件的正式候选。下方目录线索有可比的往年分数。"
            if has_catalog else "未找到处于冲刺范围（最低分−15分）以上的可比院校。"
        )
        return f"按往年录取最低分／中位分（{combo_label(combo)}），{empty}{skipped}"
    shown = "、".join(f"{TIER_LABELS[t]}{tiers[t]}所" for t in TIER_QUOTA if tiers[t])
    return (
        f"按往年录取最低分／中位分（{combo_label(combo)}）分层：{shown}。{skipped}"
        "分层只是历史对照，不代表录取概率。"
    )


def candidate_answer(candidates: list[dict]) -> str:
    """Return the rule answer, noting catalog-level evidence when present."""
    answer = "以下为满足条件的候选清单，不代表录取概率。"
    if any(c.get("evidenceLevel") != "OFFICIAL_VERIFIED" for c in candidates):
        answer += "部分候选来自院校目录记录或往年录取统计，报考年招生目录未逐条复核，请以学校官网为准。"
    return answer


class SchoolAgent(StructuredAgent):
    """One request-scoped domain expert."""

    def resolve_degree(
        self, profile: Profile, pref: Preferences, majors: list[str]
    ) -> tuple[str | None, str | None]:
        """Return the degree type and its source: this turn, the profile, then the catalog.

        The catalog is used only when every program of the target majors (in the
        exam year when such programs exist) has one and the same degree type.
        """
        if pref.degreeType:
            return pref.degreeType, None
        if profile.degreeType:
            return profile.degreeType, "profile"
        matching = [p for p, _ in self.programs if p.majorCode in majors]
        same_year = [p for p in matching if p.year == profile.examYear]
        degrees = {p.degreeType for p in same_year or matching}
        if len(degrees) == 1:
            return degrees.pop(), "catalog"
        return None, None

    def explain_empty(
        self, profile: Profile, pref: Preferences, majors: list[str], excluded: list[dict]
    ) -> tuple[str, list[str]]:
        """Summarize why no program of the exam year passed the hard filters.

        Returns the answer and follow-up hints; it never replaces the user's major
        or year, it only names the conditions that conflict in the current data.
        """
        year = profile.examYear
        same_year = [p for p, _ in self.programs if p.year == year]
        if not same_year:
            return f"当前资料没有{year}年的招生项目，未替换为往年数据。", []
        ids = {p.programId for p in same_year}
        reasons = Counter(
            reason
            for row in excluded
            if row["programId"] in ids
            for reason in row["reasons"]
        )
        degree = DEGREE_LABELS.get(pref.degreeType or "", "未选学位类型")
        answer = (
            f"{year}年资料共{len(same_year)}个项目，均未满足当前条件。排除原因："
            + "、".join(f"{reason}{count}个" for reason, count in reasons.most_common())
            + f"（同一项目可有多项原因）；当前条件为专业{'/'.join(majors)}、{degree}，未替换为往年数据。"
        )
        hints = []
        offered = sorted(
            {(p.majorCode, p.major) for p in same_year if p.degreeType == pref.degreeType}
        )
        if offered and not any(code in majors for code, _ in offered):
            names = "、".join(f"{code}（{name}）" for code, name in offered)
            other = "学硕" if pref.degreeType == "professional" else "专硕"
            hints.append(
                f"资料中{year}年的{degree}专业为{names}，与当前专业条件不同；如需比较请改为该专业代码，或改选{other}。"
            )
        return answer, hints

    async def check_links(self, query: AdmissionLinksQuery) -> dict:
        """Use only the native registered MCP tool; never fall back to local links."""
        if self.engine.admission_links is None:
            return {
                "outcome": "UNSUPPORTED",
                "answer": "招生官网链接查询尚未启用，请联系维护者启用后重试。",
                "notice": "招生链接 MCP 未启用。",
                "references": [],
                "explanationMode": "rules",
            }
        try:
            result = await self.engine.admission_links.ainvoke(query.model_dump())
        except (McpCallError, TimeoutError) as error:
            messages = {
                McpErrorCode.START_FAILED: "招生链接工具启动失败，请联系维护者检查后重启Agent。",
                McpErrorCode.CATALOG_CHANGED: "招生链接工具清单不符合约定，已停用；请联系维护者。",
                McpErrorCode.SCHEMA_CHANGED: "招生链接工具接口不符合约定，已停用；请联系维护者。",
                McpErrorCode.CONNECTION_CLOSED: "招生链接工具连接不可用，请稍后重试或联系维护者。",
                McpErrorCode.TIMEOUT: "招生链接查询超时，本轮未完成；请稍后重试。",
                McpErrorCode.CALL_LIMIT: "本轮招生链接查询已达到一次调用上限，请下一轮明确查询。",
                McpErrorCode.TOOL_FAILED: "招生链接工具执行失败，请稍后重试。",
                McpErrorCode.RESULT_INVALID: "招生链接结果未通过校验，已拒绝使用。",
            }
            message = (
                messages.get(error.code, "招生链接处理失败，请稍后重试。")
                if isinstance(error, McpCallError)
                else "招生链接查询未完成，请稍后重试。"
            )
            return {
                "outcome": "UNSUPPORTED",
                "answer": message,
                "notice": message,
                "references": [],
                "explanationMode": "rules",
            }
        links = AdmissionLinksResult.model_validate(result)
        return {
            "outcome": "COMPLETED",
            "answer": (
                f"已找到{links.schoolName}登记的招生官网链接（登记年份 {links.registeredYear}）；"
                "请自行确认招生年份、专业及报考条件。"
            ),
            "admissionLinks": links.model_dump(mode="json"),
            "references": [],
            "explanationMode": "rules",
        }

    async def handle(
        self, req: ChatRequest | tuple[ConversationRequest, ConversationResolution]
    ) -> dict:
        """Apply unchanged admission constraints and optionally explain verified candidates."""
        if isinstance(req, tuple):
            request, resolution = req
            if resolution.admissionLinks is None:
                raise ValueError("ADMISSION_LINKS_REQUIRED")
            return await self.check_links(resolution.admissionLinks)
        profile, pref = (req.profile, req.preferences)
        majors = pref.majorCodes or []
        if not majors and profile.targetMajor:
            majors = sorted(
                {
                    p.majorCode
                    for p, _ in self.programs
                    if profile.targetMajor in {p.majorCode, p.major}
                }
            )
        degree, degree_source = self.resolve_degree(profile, pref, majors)
        if degree_source:
            pref = pref.model_copy(update={"degreeType": degree})
        missing = school_input_issues(req.userInput or "", profile.examYear, pref)
        if not profile.examYear:
            missing.append("请说明报考年份（例如2027年），也可在个人档案中填写。")
        if not majors:
            missing.append("请说明目标专业名称或六位专业代码。")
        if not degree:
            missing.append(DEGREE_FOLLOW_UP)
        # score-match-v1: the form score (via Java) or this turn's text; a turn that
        # only adds the combo reuses the latest user message's total.
        history = [message.content for message in req.messages if message.role == "user"]
        score, score_issues = resolve_score(req.scoreQuery, req.userInput or "", history, pref)
        missing.extend(score_issues)
        if missing:
            return school_needs_input(missing)
        filter_pref = pref
        if score is not None:
            # The student's four exam subjects become a hard condition.
            subjects = sorted(set(pref.examSubjects or []) | set(combo_subjects(score.examCombo)))
            filter_pref = pref.model_copy(update={"examSubjects": subjects})
        registry = school_tools(self.programs, getattr(self.engine, "score_programs", []))
        selection = await registry.execute_async(
            "filter_programs",
            {"profile": profile.model_dump(), "preferences": filter_pref.model_dump()},
        )
        excluded = selection["excluded"]
        # Formal candidates carry an evidence level (2026-11-19); the rest stay catalog clues.
        formal_rows = [row for row in selection["accepted"] if row[2].get("evidenceLevel")]
        catalog_rows = [
            row
            for row in selection["accepted"]
            if not row[2].get("evidenceLevel") and row[2].get("catalogReview")
        ]
        ranking = {"task_id": req.taskId, "preferred_school": profile.targetSchool}
        statuses: list[list[str]] = []
        if score is not None:
            scoring = {"total": score.total, "exam_combo": score.examCombo}
            formal_scored = await registry.execute_async("match_scores", {"rows": formal_rows, **scoring})
            catalog_scored = await registry.execute_async("match_scores", {"rows": catalog_rows, **scoring})
            statuses = formal_scored["statuses"] + catalog_scored["statuses"]
            formal_rows, catalog_rows = formal_scored["matched"], catalog_scored["matched"]
            ranking["tiered"] = True
        selected = await registry.execute_async("rank_programs", {"rows": formal_rows, **ranking})
        candidates = [row[2].model_dump(exclude_none=True) for row in selected]
        catalog_selection = await registry.execute_async(
            "rank_programs",
            {
                "rows": catalog_rows,
                **ranking,
                "shown_schools": [candidate["school"] for candidate in candidates],
            },
        )
        catalog = [
            row[2].model_dump(
                exclude_none=True,
                exclude={"sourceIds", "matchedConditions", "explanation", "pendingChecks", "evidenceLevel"},
            )
            for row in catalog_selection
        ]
        empty_answer, empty_hints = self.explain_empty(profile, pref, majors, excluded)
        score_filter = None
        answer = candidate_answer(candidates) if candidates else empty_answer
        if score is not None:
            counts = score_counts(statuses, excluded)
            score_filter = {
                "ruleVersion": SCORE_RULE,
                "examCombo": score.examCombo,
                "counts": counts,
                "notice": SCORE_NOTICE,
            }
            answer = score_answer(score.examCombo, candidates, counts, has_catalog=bool(catalog))
            if candidates:
                answer += "\n" + candidate_answer(candidates)
            empty_hints = ["可以放宽地区要求或更换专业后再试。", "请确认英语与数学科目组合是否正确。"]
        result = {
            "outcome": "COMPLETED" if candidates or catalog else "UNSUPPORTED",
            "answer": answer,
            "candidates": candidates,
            "unverifiedCandidates": catalog,
            "excluded": excluded[:50],
            # Score statistics have no public link and never become references.
            "references": [
                row[3].reference().model_dump()
                for row in selected
                if row[2].evidenceLevel != "SCORE_HISTORY"
            ],
            "explanationMode": "rules",
            "profileSnapshot": profile.model_dump(),
            "preferences": pref.model_dump(),
            "coverage": "、".join(sorted({p.school for p, _ in self.programs}))
            + "；年份："
            + "、".join((str(y) for y in sorted({p.year for p, _ in self.programs})))
            + "；专业："
            + "/".join(sorted({p.majorCode for p, _ in self.programs})),
        }
        if catalog:
            lines = [
                f"院校目录中有 {len(catalog_rows)} 条登记匹配本轮条件，展示 {len(catalog)} 所。"
                "请在院校库查看原始来源，并以当年官网目录确认报考条件。"
            ]
            for row in catalog:
                label = CATALOG_LABELS[row["catalogReview"]]
                scope = "专项，资格需单独核对" if row["admissionCategory"] == "special" else "普通统考"
                mode = "非全日制" if row["studyMode"] == "part_time" else "全日制"
                direction = f" · {row['track']}" if row.get("track") else ""
                subjects = " · 登记初试 " + "/".join(row["examSubjects"]) if row["examSubjects"] else ""
                lines.append(f"- {row['school']} · {row['college']}{direction} · "
                             f"{row['year']} {row['majorCode']} · {mode} · {scope}{subjects}（{label}）")
            result["answer"] = "\n".join([result["answer"], *lines] if candidates or score is not None else lines)
        if degree_source:
            result["answer"] = (
                f"学位类型：{DEGREE_LABELS[degree]}（{DEGREE_SOURCES[degree_source]}，可在本轮说明改选）。\n"
                + result["answer"]
            )
        if not candidates and not catalog and empty_hints:
            result["followUp"] = empty_hints
        if score_filter is not None:
            result["scoreFilter"] = score_filter
        if req.learningSnapshot is not None:
            result["learningSnapshot"] = req.learningSnapshot.model_dump()
            result["resultSchemaVersion"] = 2
        if (
            candidates
            and not catalog
            # Score-based matching is rule-only; the total never reaches a model.
            and score is None
            # Only officially rechecked evidence may be sent for model explanation.
            and all(c.get("evidenceLevel") == "OFFICIAL_VERIFIED" for c in candidates)
            and pref.explainWithAi
            and model_allowed(req, self.settings)
            and has_scope(req, "profile")
        ):
            try:
                prepared = prepare_input(
                    self.settings,
                    get("tuijian_yuanxiao"),
                    {
                        "input": req.userInput,
                        "messages": model_messages(req),
                        "profile": profile.model_dump(exclude={"background"})
                        if has_scope(req, "profile")
                        else {},
                        "learningSnapshot": req.learningSnapshot.model_dump()
                        if req.learningSnapshot is not None and has_scope(req, "stats")
                        else {},
                        "candidates": candidates,
                        "sources": [
                            {**row[3].reference().model_dump(), "content": row[3].content}
                            for row in selected
                        ],
                    },
                    Explanations,
                )
                # Admission prose is shown only after each explanation is checked
                # against its sources; the stream stays open and cancellable.
                with withhold_model_deltas():
                    answer = await self.model.generate(get("tuijian_yuanxiao"), prepared.payload, Explanations)
                mapping = {e.programId: e for e in answer.explanations}
                if len(mapping) != len(answer.explanations) or set(mapping) != {
                    c["programId"] for c in candidates
                }:
                    raise InvalidModelOutput("candidate_mismatch")
                for c in candidates:
                    if not set(mapping[c["programId"]].sourceIds) <= set(
                        c["sourceIds"]
                    ):
                        raise InvalidModelOutput("unknown_source")
                by_id = {key: dict(value, excerpt=value["content"]) for key, value in prepared.sources("sources").items()}
                items = []
                adopted = 0
                for c in candidates:
                    explanation = mapping[c["programId"]]
                    item = verify(explanation.text, list(explanation.sourceIds), by_id)
                    c["citationSupport"] = item
                    items.append(item)
                    # Admission facts are high risk: unchecked or unsupported prose
                    # never replaces the rule explanation of a candidate.
                    if item["status"] in {"SUPPORTED", "PARTIAL"}:
                        c["explanation"] = explanation.text
                        adopted += 1
                result["citationSupport"] = aggregate(items)
                if not adopted:
                    result.update(
                        explanationMode="fallback",
                        fallbackReason="EVIDENCE_MISMATCH",
                        notice="AI解释未能与招生资料原文充分对齐，已保留规则候选说明。",
                    )
                else:
                    result["explanationMode"] = "ai"
                    if adopted < len(candidates):
                        result["notice"] = (
                            "部分AI解释未能与招生资料原文充分对齐，相应候选保留规则说明，请以来源为准。"
                        )
                    elif result["citationSupport"]["status"] != "SUPPORTED":
                        result["notice"] = (
                            "部分解释未能与招生资料原文充分对齐，请核对来源。"
                        )
            except MODEL_FAILURES as e:
                log.warning("schoolModelFailure=%s reason=%s", type(e).__name__, failure_reason(e))
                result.update(
                    explanationMode="fallback",
                    fallbackReason=fallback_reason(e),
                    notice="AI解释不可用，规则候选及来源已保留。",
                )
        return result
