"""Interpret only conditions grounded in the current school recommendation request."""

import re
from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from intents import REGIONS, ConditionExtractor
from retrieval import Document
from schemas import ChatRequest, ConversationConditions, Preferences, StrictModel
from tools.schools import Admission

SCHOOL_COMMAND = re.compile(
    r"择校|推荐[^，,。；;]{0,42}(?:院校|学校|大学|专业)|(?:想|打算|准备)报考|目标院校"
)
NATURAL_CONDITION = re.compile(
    r"明年|后年|今年|本届|下届|[2-9]\d届|[二〇零一三四五六七八九]{4}年|"
    r"学术型|专业型|学术硕士|专业硕士|学术学位|专业学位|计专|计学|"
    r"江浙|长三角|华东|华南|珠三角|工作之余|在职|同等学力|跨考|不考虑|排除|限制|"
    r"想(?:去|留|读|考)|希望(?:在|去|留|读|考)|只(?:接受|去|看)|必须|双非|双一流|985|211|不脱产"
)
CONDITION_NEGATION = re.compile(
    r"不(?:考虑|报考|报|要|想|需要|打算|准备|是|选|去|读|看|接受)|"
    r"别(?:推荐|报|选)|排除|除外|以外|除了|"
    r"(?:学硕|专硕|非全日制|全日制).{0,3}不(?:考|读|要)|"
    r"(?:同学|朋友|室友|家人).{0,8}(?:报考|考|读|选)"
)
RELATIVE_YEAR = re.compile(r"明年|后年|今年|本届|下届")
YEAR_ALIAS = re.compile(r"(?<!\d)([2-9]\d)届|([二〇零一三四五六七八九]{4})年")
CHINESE_DIGITS = str.maketrans("〇零一二三四五六七八九", "00123456789")
DEGREE_TERMS = {
    "academic": r"学硕|学术(?:型(?:硕士)?|硕士|学位)",
    "professional": r"专硕|专业(?:型(?:硕士)?|硕士|学位)",
}
REGION_GROUPS = {"江浙沪": ("江苏", "浙江", "上海"), "江浙": ("江苏", "浙江")}
MAJOR_ALIASES = {r"(?<![设统会审估预总])计专(?!业)": "085404", r"(?<![统会审])计学": "081200"}
OPEN_REGIONS = re.compile(r"地区不限|不限地区|省份不限|不限省份|全国都可以|全国都行")
SUBJECTS = {"政治": "101", "英语一": "201", "英语二": "204", "数学一": "301",
            "数学二": "302", "数学三": "303", "计算机统考": "408"}
FORM_FIELDS = {
    "majorCodes": "专业", "degreeType": "学位类型", "regions": "地区",
    "regionConstraint": "地区限制", "studyMode": "学习方式", "examSubjects": "考试科目",
}
ProgramCatalog = Sequence[tuple[Admission, Document]]
OTHER_TASK = re.compile(
    r"解释|讲解|知识问答|复习计划|学习计划|分析.{0,8}(?:学情|薄弱点|错题)|练习|笔记|出题|刷题|收藏"
)


class SchoolConditionQuotes(StrictModel):
    """Original phrases containing conditions selected by the model."""

    phrases: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=12,
    )


def school_route(plan_action: str, experts: set[str]) -> bool:
    """Identify plans whose condition patches are allowed to affect school matching."""
    return plan_action == "SCHOOL_RECOMMEND" or "SCHOOL" in experts


def school_condition_text(text: str) -> str:
    """Keep recommendation and standalone condition clauses in a compound turn."""
    clauses = re.split(r"[，,。；;\n]|(?:并且|同时|另外|顺便)", text)
    return "，".join(
        clause for clause in clauses
        if SCHOOL_COMMAND.search(clause) or not OTHER_TASK.search(clause)
    )


def _alias_years(text: str) -> set[int]:
    return {
        int("20" + short if short else chinese.translate(CHINESE_DIGITS))
        for short, chinese in YEAR_ALIAS.findall(text)
    }


def school_input_issues(text: str, profile_year: int | None, prefs: Preferences) -> list[str]:
    """Name explicit conflicts or conditions the current catalog cannot express."""
    issues = []
    text = school_condition_text(text)
    degrees = [kind for kind, pattern in DEGREE_TERMS.items() if re.search(pattern, text)]
    explicit_years = {int(year) for year in ConditionExtractor.years(text)}
    aliases = _alias_years(text)
    if len(explicit_years | aliases) > 1:
        issues.append("本轮出现多个报考年份，请指定一个年份。")
    elif aliases and profile_year not in aliases:
        issues.append("请明确写出报考年份，例如2027年。")
    if len(degrees) > 1:
        issues.append("本轮出现多种学位类型，请明确选择学硕或专硕。")
    if RELATIVE_YEAR.search(text) and not ConditionExtractor.years(text):
        issues.append("请把相对时间补充为明确的报考年份，例如2027年。")
    if CONDITION_NEGATION.search(text):
        issues.append("请直接说明你本人希望保留的条件，例如目标专业或可报考的地区。")
    if re.search(r"长三角|华东|华南|珠三角", text) and not (
        OPEN_REGIONS.search(text) or any(region in text for region in REGIONS)
    ):
        issues.append("请列出希望筛选的具体省市。")
    if not OPEN_REGIONS.search(text) and any(
        group in text and not set(regions) <= set(prefs.regions or [])
        for group, regions in REGION_GROUPS.items() if group != "江浙" or "江浙沪" not in text
    ):
        issues.append("请明确列出要考虑的省市，例如江苏、浙江。")
    if degrees and prefs.degreeType not in degrees and not re.search(r"学硕|专硕", text):
        issues.append("请明确选择学硕或专硕。")
    if any(re.search(alias, text) and code not in (prefs.majorCodes or [])
           for alias, code in MAJOR_ALIASES.items()):
        issues.append("请把专业简称补充为完整专业名称或六位代码。")
    if re.search(r"同等学力|跨考", text):
        issues.append("当前条件推荐无法判定跨考或同等学力资格，请按目标专业核对院校要求。")
    if "全日制" in text.replace("非全日制", "") and "非全日制" in text:
        issues.append("请明确选择全日制或非全日制。")
    if re.search(r"工作之余|在职|不脱产", text) and prefs.studyMode is None:
        issues.append("请明确希望比较全日制还是非全日制。")
    if re.search(r"双非|双一流|985|211", text):
        issues.append("条件推荐暂不支持按院校层次筛选，可在院校列表选择层次。")
    return issues


def stated_conditions(
    text: str, programs: ProgramCatalog, quotes: SchoolConditionQuotes | None = None,
) -> ConversationConditions:
    """Normalize literals and approved aliases. Only exact current-turn quotes may add values."""
    text = school_condition_text(text)
    if CONDITION_NEGATION.search(text):
        # A quote such as “江苏” alone cannot turn “不报江苏” into a preference.
        text = "，".join(
            clause for clause in re.split(r"[，,。；;！？!?\n]", text)
            if not CONDITION_NEGATION.search(clause)
        )
    explicit = ConditionExtractor.extract(text).model_dump(exclude_unset=True)
    if len(ConditionExtractor.years(text)) > 1:
        explicit.pop("examYear", None)
    degree = [kind for kind, pattern in DEGREE_TERMS.items() if re.search(pattern, text)]
    if len(degree) != 1:
        explicit.pop("degreeType", None)
    explicit.pop("majorCodes", None)
    codes = set(re.findall(r"(?<!\d)[0-9]{6}(?!\d)", text)) if ConditionExtractor.condition_context(text) else set()
    codes.update(p.majorCode for p, _ in programs if p.major and p.major in text)
    if 0 < len(codes) <= 10:
        explicit["majorCodes"] = sorted(codes)
    if OPEN_REGIONS.search(text):
        explicit.update(regions=[], regionConstraint="preferred")
    elif explicit.get("regions") and re.search(
        r"(?<!不)(?:只接受|只去|只看|必须在|必须是)[^，。；,;]{0,8}(?:"
        + "|".join(explicit["regions"]) + ")", text,
    ):
        explicit["regionConstraint"] = "required"
    if "非全日制" in text and "全日制" not in text.replace("非全日制", ""):
        explicit["studyMode"] = "part_time"
    if "全日制" in text and "非全日制" not in text:
        explicit["studyMode"] = "full_time"
    subjects = {code for name, code in SUBJECTS.items() if name in text}
    if re.search(r"(?:考|科目|统考|初试|要求).{0,5}(?<!\d)408(?!\d)", text):
        subjects.add("408")
    if 0 < len(subjects) <= 4:
        explicit["examSubjects"] = sorted(subjects)
    if quotes is not None:
        _add_quoted_conditions(text, explicit, quotes, degree, programs)
    return ConversationConditions.model_validate(explicit)


def _add_quoted_conditions(
    text: str, explicit: dict, quotes: SchoolConditionQuotes, degree: list[str],
    programs: ProgramCatalog,
) -> None:
    valid = [phrase for phrase in quotes.phrases if phrase in text]
    years = set().union(*(_alias_years(phrase) for phrase in valid))
    if len(years) == 1 and 2000 <= min(years) <= 2100 and not ConditionExtractor.years(text):
        explicit["examYear"] = years.pop()
    if len(degree) == 1 and any(re.search(DEGREE_TERMS[degree[0]], phrase) for phrase in valid):
        explicit.setdefault("degreeType", degree[0])
    known_codes = {program.majorCode for program, _ in programs}
    aliased = {code for alias, code in MAJOR_ALIASES.items()
               if code in known_codes and re.search(alias, text)
               and any(re.search(alias, phrase) for phrase in valid)}
    if aliased and not explicit.get("majorCodes"):
        explicit["majorCodes"] = sorted(aliased)
    if any("不脱产" in phrase or "在职读研" in phrase for phrase in valid):
        explicit.setdefault("studyMode", "part_time")
    for group, regions in REGION_GROUPS.items():
        if any(group in phrase for phrase in valid):
            if not OPEN_REGIONS.search(text):
                explicit["regions"] = list(dict.fromkeys([*explicit.get("regions", []), *regions]))
                if re.search(r"(?<!不)(?:只|仅|限定|必须)[^，。；,;]{0,8}" + group, text):
                    explicit["regionConstraint"] = "required"
                else:
                    explicit.setdefault("regionConstraint", "preferred")
            break


def merge_form_conditions(
    request: ChatRequest, patch: ConversationConditions,
) -> tuple[ChatRequest, list[str]]:
    """Check the two current input sources before adding fields supplied only in prose."""
    fields = patch.model_dump(exclude_none=True, exclude_unset=True)
    form = request.preferences.model_dump(exclude_none=True, exclude_unset=True)
    if (form.get("regionConstraint") == "required" and fields.get("regions")
            and fields.get("regionConstraint") == "preferred"
            and not re.search(r"优先|倾向|偏好|不只|都可以|都行", request.userInput or "")):
        fields.pop("regionConstraint")
    conflicts = [
        f"表单与文字中的{label}不一致，请确认采用哪个条件。"
        for name, label in FORM_FIELDS.items()
        if name in form and name in fields
        and (name not in {"regionConstraint", "regions"} or form.get("regions"))
        and not _equivalent(form[name], fields[name])
    ]
    if conflicts:
        return request, conflicts
    if not fields:
        return request, []
    year = fields.pop("examYear", None)
    profile = request.profile.model_copy(update={"examYear": year}) if year is not None else request.profile
    preferences = Preferences.model_validate({**form, **fields})
    return request.model_copy(update={"profile": profile, "preferences": preferences}), []


def _equivalent(left: object, right: object) -> bool:
    if isinstance(left, list) and isinstance(right, list):
        return sorted(left) == sorted(right)
    return left == right


def school_needs_input(missing: list[str]) -> dict:
    """Return actionable clarifications through the existing recommendation envelope."""
    return {
        "outcome": "NEEDS_INPUT",
        "answer": "推荐条件尚不完整。\n\n" + "\n".join(f"- {message}" for message in missing),
        "followUp": missing,
        "candidates": [],
        "unverifiedCandidates": [],
    }
