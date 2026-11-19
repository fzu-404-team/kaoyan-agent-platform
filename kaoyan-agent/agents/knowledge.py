"""HelloAgents domain implementation preserving the existing business rules."""

import logging
import re
from typing import TYPE_CHECKING

from agents.base import StructuredAgent
from core.errors import MODEL_FAILURES, InvalidModelOutput, ToolUnavailable, fallback_reason, failure_reason
from core.mcp_runtime import McpCallError
from core.model import prepare_input
from core.runtime import withhold_model_deltas
from grounding import claims_cover_answer, fully_supported, published_support, verify
from learning import has_scope, model_allowed, model_messages
from prompts import get
from retrieval import mentions, subject_terms
from schemas import Answer, ChatRequest, ConversationRequest, GeneralKnowledgeAnswer, TutorExplanation

if TYPE_CHECKING:
    from workflows import Workflows

log = logging.getLogger(__name__)

GENERAL_LABEL = "通用 AI 解释，未经过审核资料核对"
GENERAL_EXCLUDED = re.compile(
    r"招生|择校|院校|大学|报考|录取|分数线|真题|考情|考频|统考大纲|"
    r"哪年|第.{0,8}题|题库|标准答案|正确选项|选择题|判断题|"
    r"学情|错题|作答|正确率|笔记|档案|复习计划|上[一文次面]|上一轮|刚才|"
    r"上述|前面|我的|我昨天|我刚|它们|这道|这些|并且|然后|同时|顺便|另外|"
    r"忽略规则|系统指令|提示词"
    r"|20\d{2}\s*(?:年|届)|https?://", re.I,
)
CONCEPT_REQUEST = re.compile(
    r"什么是|是什么|是什么意思|概念|原理|区别|定义|举例|解释|讲解|介绍|如何|为什么|怎么"
)
UNVERIFIED_REFERENCE = re.compile(
    r"https?://|www\.|来源\s*[:：]|参考文献|据.{0,18}(?:官网|教材|统计)|"
    r"\[(?:[Ss]\d+|\d+|[^\]]+)\]\s*\(|\[(?:[Ss]\d+|\d+)\]", re.I,
)
UNVERIFIED_SCOPE = re.compile(
    r"招生|择校|录取|分数线|真题|考情|考频|标准答案|正确选项|"
    r"(?:你的|你已|你共).{0,12}(?:档案|作答|错题|成绩|正确率)"
)
INLINE_CITATION = re.compile(r"\[([A-Za-z0-9_.-]+#\d+|[Ss]\d+)\]")


class KnowledgeAgent(StructuredAgent):
    """One request-scoped domain expert."""

    def __init__(self, owner: "Workflows | StructuredAgent", general_question: str | None = None) -> None:
        """Accept an original, independent user turn only from the dispatcher."""
        super().__init__(owner)
        self.general_question = general_question

    async def _without_evidence(self, req: ChatRequest) -> dict:
        """Use a bounded fallback for a recognizable standalone public concept."""
        result = {
            "outcome": "UNSUPPORTED",
            "answer": "当前审核资料未覆盖该问题，请缩小问题范围或补充资料。",
        }
        question = self.general_question
        if not question and not isinstance(req, ConversationRequest) and req.taskType == "KNOWLEDGE_QA":
            question = req.userInput
        if not question or not model_allowed(req, self.settings):
            return result
        subject, anchors = subject_terms(question)
        if not CONCEPT_REQUEST.search(question) or GENERAL_EXCLUDED.search(question):
            return result
        if not (subject or anchors):
            return result
        try:
            with withhold_model_deltas():
                answer = await self.model.generate(
                    get("zhishi_general"), {"input": question}, GeneralKnowledgeAnswer
                )
            if (UNVERIFIED_REFERENCE.search(answer.answer) or UNVERIFIED_SCOPE.search(answer.answer)
                    or answer.answer == "本轮无法提供通用概念解释。"):
                raise InvalidModelOutput("unverified_concept_scope")
        except MODEL_FAILURES as error:
            log.warning("generalQaFailure=%s reason=%s", type(error).__name__, failure_reason(error))
            return {**result, "notice": "本轮未能生成通用 AI 解释。",
                    "explanationMode": "fallback", "fallbackReason": fallback_reason(error)}
        return {
            "outcome": "COMPLETED",
            "answer": f"{GENERAL_LABEL}\n\n{answer.answer}",
            "notice": f"{GENERAL_LABEL}。",
            "references": [],
            "explanationMode": "fallback",
        }

    async def handle(self, req: ChatRequest) -> dict:
        """Retrieve versioned knowledge and validate the original answer contract."""
        if req.attempt is not None:
            return await self.tutor(req)
        subject, anchors = subject_terms(req.userInput or "")

        async def search(scope: str | None) -> list:
            # A chunk that shares only weak words ("栈" for "TCP协议栈") is not
            # evidence for the question; it must mention a recognized topic term.
            found = [
                d.metadata["chunk"]
                for d in await self.knowledge_search.ainvoke(
                    {"query": req.userInput, "subject": scope}
                )
            ]
            return [
                d for d in found
                if not anchors or any(
                    mentions(" ".join((d.title, d.content, *d.keywords)), term) for term in anchors
                )
            ]

        try:
            docs = await search(subject)
            if not docs and subject:
                docs = await search(None)
        except (McpCallError, ToolUnavailable, TimeoutError) as error:
            # An unavailable index or tool is not "no coverage"; say so and stop
            # before any model request instead of failing the whole task.
            log.warning("qaRetrievalFailure=%s", type(error).__name__)
            return {
                "outcome": "UNSUPPORTED",
                "answer": "审核资料检索暂时不可用，本轮未生成回答；请稍后重试。",
                "notice": "资料检索不可用，未调用模型。",
                "explanationMode": "rules",
            }
        if not docs:
            return await self._without_evidence(req)
        result = {
            "outcome": "COMPLETED",
            "answer": "以下为来源摘要：\n" + "\n".join((d.content for d in docs)),
            "references": [d.reference().model_dump() for d in docs],
            "explanationMode": "rules",
        }
        if model_allowed(req, self.settings):
            try:
                prepared = prepare_input(
                    self.settings,
                    get("zhishi_wenda"),
                    {
                        "input": req.userInput,
                        "messages": model_messages(req),
                        "references": [
                            {**d.reference().model_dump(), "content": d.content} for d in docs
                        ],
                    },
                    Answer,
                )
                with withhold_model_deltas():
                    answer = await self.model.generate(get("zhishi_wenda"), prepared.payload, Answer)
                ids = set(answer.sourceIds)
                claim_ids = {
                    source for claim in answer.claims for source in claim.sourceIds
                }
                visible = prepared.sources()
                inline_ids = set(INLINE_CITATION.findall(answer.answer))
                if not ids | claim_ids | inline_ids <= visible.keys():
                    raise InvalidModelOutput("unknown_source")
                if any(not set(INLINE_CITATION.findall(claim.text)) <= set(claim.sourceIds)
                       for claim in answer.claims):
                    raise InvalidModelOutput("unknown_source")
                claims = [claim.model_dump() for claim in answer.claims]
                support = verify(
                    answer.answer,
                    list(ids),
                    visible,
                    claims=claims or None,
                    strict=True,
                )
                result["citationSupport"] = published_support(support)
                # An answer with no checkable conclusion is not evidence of support.
                if fully_supported(support):
                    result.update(
                        answer=answer.answer,
                        explanationMode="ai",
                        references=[d.reference().model_dump() for d in docs if d.id in ids | claim_ids],
                    )
                elif (claims and support["supported"] and support["checked"] == len(claims)
                      and claims_cover_answer(answer.answer, claims, list(visible))):
                    accepted = [
                        claim for claim, item in zip(answer.claims, support["items"], strict=True)
                        if item["supported"]
                    ]
                    accepted_ids = {source for claim in accepted for source in claim.sourceIds}
                    result.update(
                        answer="\n\n".join(claim.text for claim in accepted),
                        explanationMode="fallback",
                        fallbackReason="EVIDENCE_MISMATCH",
                        notice="部分结论的依据不足，已保留通过核对的内容。",
                        references=[d.reference().model_dump() for d in docs if d.id in accepted_ids],
                    )
                else:
                    result["citationSupport"]["items"] = []
                    result.update(
                        explanationMode="fallback",
                        fallbackReason="EVIDENCE_MISMATCH",
                        notice="模型回答未能与引用原文充分对齐，已保留来源摘要。"
                        if support["status"] != "NOT_CHECKED"
                        else "模型回答缺少可核对的结论，已保留来源摘要。",
                    )
            except MODEL_FAILURES as e:
                log.warning("qaModelFailure=%s reason=%s", type(e).__name__, failure_reason(e))
                result.update(
                    explanationMode="fallback", fallbackReason=fallback_reason(e),
                    notice="AI解释不可用，已保留来源摘要。",
                )
        return result

    async def tutor(self, req: ChatRequest) -> dict:
        """Explain only an authorized graded snapshot; never change its answer."""
        attempt = req.attempt
        analysis = attempt.analysis or "此版本未保存解析，无法从已有解析解释原因。"
        result = {
            "outcome": "COMPLETED",
            "recordId": attempt.recordId,
            "standardAnswer": attempt.answer,
            "userAnswer": attempt.userAnswer,
            "questionVersion": attempt.version,
            "answer": f"你的选择：{attempt.userAnswer}；此版本标准答案：{attempt.answer}。\n原题解析：{analysis[:3500]}",
            "explanationMode": "rules",
            "notice": "未启用 AI，当前仅展示原题解析，尚未生成个性化解释或追问回答。",
        }
        if self.settings.LLM_ENABLED and not (
            model_allowed(req, self.settings) and has_scope(req, "wrong")
        ):
            result["notice"] = (
                "尚未授权将错题发送给当前模型，仅展示原题解析；请在 Agent 助手的隐私设置中开启模型与错题授权。"
            )
        if model_allowed(req, self.settings) and has_scope(req, "wrong"):
            try:
                output = await self.model.generate(
                    get("wrong_question_tutor"),
                    {
                        "attempt": attempt.model_dump(exclude={"id", "recordId"}),
                        "query": req.userInput,
                        "messages": model_messages(req),
                    },
                    TutorExplanation,
                )
                # Revalidate even a custom provider adapter's output.
                output = TutorExplanation.model_validate(output.model_dump())
                if output.standardAnswer != attempt.answer:
                    raise InvalidModelOutput("standard_answer_mismatch")
                result.update(
                    answer=output.explanation,
                    explanationMode="ai",
                    notice="AI 辅助解释可能有误，标准答案和判分以已保存作答为准。",
                )
            except MODEL_FAILURES as e:
                log.warning("tutorModelFailure=%s reason=%s", type(e).__name__, failure_reason(e))
                result.update(
                    explanationMode="fallback",
                    fallbackReason=fallback_reason(e),
                    notice="AI 解释或追问暂不可用，已保留原题解析，可稍后重试。",
                )
        return result
