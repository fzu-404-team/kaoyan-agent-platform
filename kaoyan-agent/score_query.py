"""Deterministic total-score parsing for score-based school matching (score-match-v1).

Scores never reach a model: the standalone form score arrives validated from Java
as `ScoreQuery`, and free text is parsed here with fixed rules. See
考研Agent平台搭建文档.md#按分数择校契约2026-11-19.
"""

import re
from dataclasses import dataclass

from schemas import Preferences, ScoreQuery

ENGLISH_CODES = {"1": "201", "2": "204"}
MATH_CODES = {"1": "301", "2": "302", "3": "303"}
DIGITS = {"一": "1", "二": "2", "三": "3", "1": "1", "2": "2", "3": "3"}
COMBO_FOLLOW_UP = "请说明英语一／二与数学一／二／三，例如“英一数一”。"

# Three digits within 200–500, not part of a longer number such as 2027 or 081200.
SCORE_NUMBER = re.compile(r"(?<![\d.])([2-4]\d{2}|500)(?![\d.])")
SCORE_TRIGGER = re.compile(r"估分|预估|预计|模考|考了|总分|初试|能考|分数")
SINGLE_SUBJECT = re.compile(r"政治|英语|英一|英二|数学|数一|数二|数三|专业课|408")
TOTAL_WORD = re.compile(r"总分|总共|加起来|合计")
HISTORIC_LINE = re.compile(r"复试线|分数线|国家线|录取线|最低分|中位分|平均分|最高分")
CLAUSE_BREAK = re.compile(r"[，,。；;！!？?、\n]")
# “分数一般”“数一下”“一些” are ordinary words, not subject choices; an Arabic
# digit must not start a longer number (“数130分” is a math score).
NOT_SUBJECT_TAIL = r"(?![般下些点样定直共起半])"
ENGLISH = re.compile(r"英(?:语)?\s*[（(]?\s*([一二]|[12](?!\d))\s*[)）]?" + NOT_SUBJECT_TAIL)
MATH = re.compile(r"(?<![分人次个])数(?:学)?\s*[（(]?\s*([一二三]|[123](?!\d))\s*[)）]?" + NOT_SUBJECT_TAIL)
# “分” directly followed by 数/线 is “分数…/分数线”, not “N分”.
POINTS = re.compile(r"\s*分(?![数线])")
SCORE_RANGE = re.compile(r"(?<![\d.])([2-4]\d{2}|500)\s*(?:-|~|～|—|–|到|至)\s*([2-4]\d{2}|500)(?![\d.])")
SCHOOL_TARGET = re.compile(r"学校|院校|大学|能上|上岸")
COMBO_FILLER = re.compile(r"[\s，,。.、；;！!和与及跟是的我考选]|科目|组合|初试|还有|就")


@dataclass(frozen=True)
class ScoreText:
    """Totals and exam-combo digits literally stated in one text."""

    totals: frozenset[int]
    english: frozenset[str]
    math: frozenset[str]


def _clause_before(text: str, start: int, width: int) -> str:
    """Return up to `width` characters before `start`, cut at the last clause break."""
    window = text[max(0, start - width):start]
    parts = CLAUSE_BREAK.split(window)
    return parts[-1]


def parse_text(text: str) -> ScoreText:
    """Extract stated totals and English/math choices without any model call."""
    totals = set()
    for match in SCORE_NUMBER.finditer(text):
        value, start, end = match.group(1), match.start(), match.end()
        followed = bool(POINTS.match(text[end:]))
        if value == "408" and not followed:
            continue
        near = _clause_before(text, start, 6)
        if HISTORIC_LINE.search(near):
            continue
        if SINGLE_SUBJECT.search(near) and not TOTAL_WORD.search(near):
            continue
        if followed or SCORE_TRIGGER.search(text[max(0, start - 8):start]):
            totals.add(int(value))
    # A range (“320-340分”) states two totals, which then asks for one.
    for match in SCORE_RANGE.finditer(text):
        low, high = int(match.group(1)), int(match.group(2))
        if low in totals or high in totals:
            totals.update((low, high))
    english = {DIGITS[m.group(1)] for m in ENGLISH.finditer(text)} & set(ENGLISH_CODES)
    math = {DIGITS[m.group(1)] for m in MATH.finditer(text)}
    return ScoreText(frozenset(totals), frozenset(english), frozenset(math))


def score_school_request(text: str) -> bool:
    """Recognize “我估分320，推荐哪些学校”: a stated total plus a school target."""
    return bool(parse_text(text).totals) and bool(SCHOOL_TARGET.search(text))


def combo_supplement(text: str) -> bool:
    """Recognize a turn that only supplies English and math choices, e.g. “英一数一”."""
    parsed = parse_text(text)
    if not parsed.english or not parsed.math:
        return False
    rest = MATH.sub("", ENGLISH.sub("", text))
    return not COMBO_FILLER.sub("", rest)


def combo_subjects(combo: str) -> list[str]:
    """Return the four exam subject codes of a combo such as "11408"."""
    return ["101", ENGLISH_CODES[combo[0]], MATH_CODES[combo[1]], "408"]


def subjects_combo(subjects: list[str]) -> str | None:
    """Return the combo of a four-subject 101/English/math/408 list, else None."""
    if len(subjects) != 4 or "101" not in subjects or "408" not in subjects:
        return None
    english = [k for k, code in ENGLISH_CODES.items() if code in subjects]
    math = [k for k, code in MATH_CODES.items() if code in subjects]
    if len(english) != 1 or len(math) != 1:
        return None
    return english[0] + math[0] + "408"


def _choose(
    name: str, form: str | None, stated: frozenset[str], preferred: set[str], issues: list[str]
) -> str | None:
    """Pick one English or math digit: form, then text, then preferences."""
    if form is not None:
        if stated and stated != {form}:
            issues.append(f"表单与原话中的{name}科目不一致，请确认。")
        chosen = form
    elif len(stated) > 1:
        issues.append(f"本轮出现多个{name}科目，请只选择一个。")
        return None
    elif stated:
        chosen = next(iter(stated))
    elif len(preferred) == 1:
        chosen = next(iter(preferred))
    else:
        return None
    if preferred and chosen not in preferred:
        issues.append(f"所选考试科目与分数对应的{name}科目不一致，请确认。")
    return chosen


def resolve_score(
    form: ScoreQuery | None, text: str, history: list[str], pref: Preferences
) -> tuple[ScoreQuery | None, list[str]]:
    """Combine the form score, this turn's text and preferences into one query.

    Returns (None, []) when no total is stated, so ordinary matching is unchanged.
    `history` holds earlier user messages, newest last; it is used only when this
    turn supplies a combo but no total. Issues mean NEEDS_INPUT.
    """
    parsed = parse_text(text)
    totals = set(parsed.totals)
    if form is None and not totals and (parsed.english or parsed.math) and history:
        previous = parse_text(history[-1])
        totals = set(previous.totals)
        if totals:
            parsed = ScoreText(
                frozenset(totals),
                parsed.english or previous.english,
                parsed.math or previous.math,
            )
    issues: list[str] = []
    if len(totals) > 1:
        issues.append("本轮出现多个总分，请只给出一个估分。")
        return None, issues
    if form is not None and totals and form.total not in totals:
        issues.append("表单填写的总分与原话不一致，请确认。")
    total = form.total if form is not None else next(iter(totals), None)
    if total is None:
        return None, issues
    codes = set(pref.examSubjects or [])
    english = _choose(
        "英语",
        form.examCombo[0] if form else None,
        parsed.english,
        {k for k, code in ENGLISH_CODES.items() if code in codes},
        issues,
    )
    math = _choose(
        "数学",
        form.examCombo[1] if form else None,
        parsed.math,
        {k for k, code in MATH_CODES.items() if code in codes},
        issues,
    )
    if english is None or math is None:
        issues.append(COMBO_FOLLOW_UP)
    if issues:
        return None, issues
    return ScoreQuery(total=total, examCombo=english + math + "408"), []
