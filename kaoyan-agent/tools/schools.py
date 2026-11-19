"""Admission filtering and stable ranking as separate registered tools."""

from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from retrieval import Document
from schemas import Preferences, Profile, StrictModel
from score_query import ENGLISH_CODES, MATH_CODES, subjects_combo
from tools.registry import StrictToolRegistry, ValidatedTool


EvidenceLevel = Literal["OFFICIAL_VERIFIED", "CATALOG_CHECKED", "USER_APPROVED", "SCORE_HISTORY"]
LEVEL_RANK = {"OFFICIAL_VERIFIED": 4, "CATALOG_CHECKED": 3, "USER_APPROVED": 2, "SCORE_HISTORY": 1}
UNREVIEWED_CHECK = "2027招生目录未逐条复核，请以学校官网为准"

# score-match-v1 (2026-11-19): tiers against last admitted minimum / median scores.
SCORE_RULE = "score-match-v1"
ScoreTier = Literal["REACH", "MATCH", "SAFE"]
TIER_ORDER: tuple[ScoreTier, ...] = ("REACH", "MATCH", "SAFE")
TIER_QUOTA = {"REACH": 2, "MATCH": 2, "SAFE": 1}
FILL_ORDER: tuple[ScoreTier, ...] = ("MATCH", "SAFE", "REACH")
REACH_WINDOW = 15
MAX_SELECTED = 5
Number = int | float


class ScoreMatch(StrictModel):
    """Rule comparison of one candidate with its historical admission scores."""

    ruleVersion: Literal["score-match-v1"]
    tier: ScoreTier
    statYear: int = Field(ge=2000, le=2100)
    college: str
    examCombo: str = Field(pattern=r"^[12][123]408$")
    minScore: Number = Field(ge=0, le=500)
    medianScore: Number = Field(ge=0, le=500)
    retestLine: Number | None = Field(default=None, ge=0, le=500)
    gapToMin: Number


class Admission(StrictModel):
    """Validated admissions metadata from the active versioned corpus."""

    programId: str
    school: str
    college: str
    major: str
    majorCode: str
    year: int = Field(ge=2000, le=2100)
    degreeType: str
    region: str
    studyMode: str
    examSubjects: list[str]
    updatedAt: str
    track: str | None = None
    admissionCategory: Literal["ordinary", "special"] | None = None
    catalogReview: Literal["CATALOG_CHECKED", "USER_APPROVED"] | None = None


class FilterParameters(StrictModel):
    """Only typed profile and preferences can influence filtering."""

    profile: Profile
    preferences: Preferences


class RankedCandidate(Admission):
    """Rule-generated candidate fields accepted at the ranking boundary."""

    matchedConditions: list[str]
    pendingChecks: list[str]
    sourceIds: list[str]
    explanation: str
    evidenceLevel: EvidenceLevel | None = None
    scoreMatch: ScoreMatch | None = None


RankedRow = tuple[int, str, RankedCandidate, Document]
SerializedRow = tuple[int, str, dict[str, object], dict[str, object]]


class RankParameters(StrictModel):
    """Rows are produced by the trusted filter tool."""

    rows: list[RankedRow]
    task_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    preferred_school: str | None = Field(default=None, max_length=255)
    shown_schools: list[str] = Field(default_factory=list, max_length=5)
    tiered: bool = False


class ScoreParameters(StrictModel):
    """Filtered rows and the student's total; the total never leaves rule code."""

    rows: list[RankedRow]
    total: int = Field(ge=0, le=500)
    exam_combo: str = Field(pattern=r"^[12][123]408$")


PROVINCES_FILE = Path(__file__).resolve().parents[2] / "config/school-score-provinces-20261118.json"


def school_regions(
    programs: list[tuple[Admission, Document]], path: Path = PROVINCES_FILE
) -> dict[str, str]:
    """Map school names to regions: admission records first, then the maintained province list."""
    regions: dict[str, str] = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        regions.update({row["name"]: row["province"] for row in data.get("schools", [])})
        for alias, name in data.get("aliases", {}).items():
            if name in regions:
                regions.setdefault(alias, regions[name])
    regions.update({p.school: p.region for p, _ in programs})
    return regions


def score_programs(
    documents: list[Document], regions: dict[str, str]
) -> list[tuple[Admission, Document]]:
    """Project unflagged score statistics into SCORE_HISTORY programs.

    Keeps every statistics year; the filter picks the latest year before the
    exam year per school, college and major. Rows with quality flags, unknown
    major codes or unparseable subject combinations are skipped.
    """
    out: list[tuple[Admission, Document]] = []
    for doc in documents:
        meta = doc.metadata
        if doc.domain != "school" or meta.get("kind") != "score_statistics" or meta.get("flags"):
            continue
        code, combo = meta.get("majorCode"), str(meta.get("examCombo") or "")
        if not code or len(combo) != 5 or not combo.endswith("408"):
            continue
        english, math = ENGLISH_CODES.get(combo[0]), MATH_CODES.get(combo[1])
        if english is None or math is None:
            continue
        out.append((
            Admission(
                programId=doc.id,
                school=meta["school"],
                college=meta["college"],
                major=meta["major"],
                majorCode=code,
                year=meta["year"],
                degreeType="professional" if code.startswith("0854") else "academic",
                region=regions.get(meta["school"], ""),
                studyMode="unknown",
                examSubjects=["101", english, math, "408"],
                updatedAt=doc.retrievedAt,
            ),
            doc,
        ))
    return out


StatKey = tuple[str, str, str, str]
StatRow = tuple[int, Number | None, Number | None, Number | None]


def score_number(value: object) -> Number | None:
    """Parse a stored score ("275", 275.5 or "") into a number within 0–500."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= number <= 500:
        return None
    return int(number) if number.is_integer() else number


def score_index(history: list[tuple[Admission, Document]]) -> dict[StatKey, list[StatRow]]:
    """Index unflagged statistics by school, college, major code and exam combo."""
    index: dict[StatKey, list[StatRow]] = {}
    for program, doc in history:
        combo = subjects_combo(program.examSubjects)
        if combo is None:
            continue
        meta = doc.metadata
        index.setdefault((program.school, program.college, program.majorCode, combo), []).append((
            program.year,
            score_number(meta.get("minScore")),
            score_number(meta.get("medianScore")),
            score_number(meta.get("retestLine")),
        ))
    return index


def score_tier(total: int, minimum: Number, median: Number) -> str:
    """Apply score-match-v1: SAFE ≥ median, MATCH ≥ min, REACH ≥ min−15, else BELOW."""
    if total >= median:
        return "SAFE"
    if total >= minimum:
        return "MATCH"
    if total >= minimum - REACH_WINDOW:
        return "REACH"
    return "BELOW"


def school_tools(
    programs: list[tuple[Admission, Document]],
    history: list[tuple[Admission, Document]] | None = None,
) -> StrictToolRegistry:
    """Create request-local tools sharing only the immutable admissions copy."""
    stats = score_index(history or [])

    def filter_programs(profile: dict, preferences: dict) -> dict:
        """Apply the existing hard constraints without model judgments."""
        profile = Profile.model_validate(profile)
        pref = Preferences.model_validate(preferences)
        majors = pref.majorCodes or []
        if not majors and profile.targetMajor:
            majors = sorted(
                {
                    p.majorCode
                    for p, _ in programs
                    if profile.targetMajor in {p.majorCode, p.major}
                }
            )
        accepted, excluded = ([], [])
        for p, doc in programs:
            reasons = []
            for mismatch, reason in (
                (p.year != profile.examYear, "年份不匹配"),
                (p.majorCode not in majors, "专业不匹配"),
                (p.degreeType != pref.degreeType, "学位类型不匹配"),
                (
                    bool(pref.studyMode) and p.studyMode != pref.studyMode,
                    "学习方式不匹配",
                ),
                (
                    bool(pref.examSubjects)
                    and (not set(pref.examSubjects) <= set(p.examSubjects)),
                    "考试科目不匹配",
                ),
                (
                    bool(pref.regions)
                    and pref.regionConstraint == "required"
                    and (p.region not in pref.regions),
                    "地区不匹配",
                ),
            ):
                if mismatch:
                    reasons.append(reason)
            if reasons:
                excluded.append(
                    {"programId": p.programId, "school": p.school, "reasons": reasons}
                )
                continue
            region_match = bool(pref.regions) and p.region in pref.regions
            level = doc.evidence_level()
            candidate = p.model_dump(exclude_none=True)
            candidate.update(
                matchedConditions=["招生年份一致", "专业一致", "学位类型一致"]
                + (["地区偏好匹配"] if region_match else []),
                pendingChecks=[
                    "报考资格、方向及最新调整请核对招生章程；未据本科背景推定资格"
                ]
                + ([UNREVIEWED_CHECK] if level not in {None, "OFFICIAL_VERIFIED"} else []),
                sourceIds=[doc.id],
                explanation="；".join(
                    ["招生年份、专业和学位类型符合条件"]
                    + (["地区符合偏好"] if region_match else [])
                ),
            )
            if level is not None:
                candidate["evidenceLevel"] = level
            accepted.append((int(region_match), p.updatedAt, candidate, doc))
        accepted.extend(history_rows(profile, pref, majors))
        return {"accepted": accepted, "excluded": excluded}

    def history_rows(profile: Profile, pref: Preferences, majors: list[str]) -> list:
        """Return SCORE_HISTORY rows: latest year before the exam year per program."""
        latest: dict[tuple[str, str, str], tuple[Admission, Document]] = {}
        for p, doc in history or []:
            if (
                not profile.examYear
                or p.year >= profile.examYear
                or p.majorCode not in majors
                or p.degreeType != pref.degreeType
                or pref.studyMode == "part_time"
                or (pref.examSubjects and not set(pref.examSubjects) <= set(p.examSubjects))
                or (pref.regions and pref.regionConstraint == "required" and p.region not in pref.regions)
            ):
                continue
            key = (p.school, p.college, p.majorCode)
            if key not in latest or (p.year, p.programId) > (latest[key][0].year, latest[key][0].programId):
                latest[key] = (p, doc)
        rows = []
        for p, doc in latest.values():
            region_match = bool(pref.regions) and p.region in pref.regions
            candidate = p.model_dump(exclude_none=True)
            candidate.update(
                matchedConditions=["专业一致", "学位类型一致"] + (["地区偏好匹配"] if region_match else []),
                pendingChecks=[
                    "报考资格、方向及最新调整请核对招生章程；未据本科背景推定资格",
                    f"仅有{p.year}年录取统计（用户提供），{profile.examYear}年是否招生及学习方式未核实",
                ],
                sourceIds=[],
                explanation=f"{p.year}年有该专业录取统计；专业和学位类型符合条件",
                evidenceLevel="SCORE_HISTORY",
            )
            rows.append((int(region_match), p.updatedAt, candidate, doc))
        return rows

    def comparison_rows(candidate: dict, combo: str) -> list[StatRow]:
        """Return the statistics rows score-match-v1 compares one candidate with."""
        rows = stats.get((candidate["school"], candidate["college"], candidate["majorCode"], combo), [])
        if candidate.get("evidenceLevel") == "SCORE_HISTORY":
            # The candidate is itself a statistics row of that year.
            return [row for row in rows if row[0] == candidate["year"]]
        earlier = [row for row in rows if row[0] < candidate["year"]]
        if not earlier:
            return []
        latest = max(row[0] for row in earlier)
        return [row for row in earlier if row[0] == latest]

    def match_scores(rows: list[SerializedRow], total: int, exam_combo: str) -> dict:
        """Tier each filtered row against its historical scores (score-match-v1).

        Returns in-range rows carrying `scoreMatch`, plus one status per row
        (a tier, BELOW or NO_DATA) for school-level counts.
        """
        matched, statuses = [], []
        for region, updated, candidate, doc in rows:
            status, match = "NO_DATA", None
            if subjects_combo(candidate.get("examSubjects") or []) == exam_combo:
                found = comparison_rows(candidate, exam_combo)
                pairs = {(row[1], row[2]) for row in found}
                retests = {row[3] for row in found}
                if len(pairs) == 1:
                    minimum, median = next(iter(pairs))
                    if minimum is not None and median is not None and minimum <= median:
                        status = score_tier(total, minimum, median)
                        retest = next(iter(retests)) if len(retests) == 1 else None
                        match = {
                            "ruleVersion": SCORE_RULE,
                            "tier": status,
                            "statYear": found[0][0],
                            "college": candidate["college"],
                            "examCombo": exam_combo,
                            "minScore": minimum,
                            "medianScore": median,
                            "gapToMin": total - minimum,
                            **({"retestLine": retest} if retest is not None else {}),
                        }
            statuses.append((candidate["school"], status))
            if match is not None and status in TIER_QUOTA:
                matched.append((region, updated, {**candidate, "scoreMatch": match}, doc))
        return {"matched": matched, "statuses": statuses}

    def rank_programs(
        rows: list[SerializedRow],
        task_id: str,
        preferred_school: str | None,
        shown_schools: list[str],
        tiered: bool,
    ) -> list[RankedRow]:
        """Choose one eligible program per school and sample oversized priority groups.

        With `tiered`, rows must carry `scoreMatch`; up to 2 REACH, 2 MATCH and
        1 SAFE schools are sampled, free slots filled by MATCH, SAFE, then REACH.
        """
        ranked = sorted(decode(rows), key=lambda row: row[2].programId)
        ranked.sort(key=lambda row: row[1], reverse=True)
        ranked.sort(key=lambda row: (level_rank(row), row[2].catalogReview == "CATALOG_CHECKED"), reverse=True)
        ranked.sort(key=lambda row: row[0], reverse=True)

        by_school: dict[str, RankedRow] = {}
        for row in ranked:
            by_school.setdefault(row[2].school, row)
        shown = set(shown_schools)

        def priority(row: RankedRow) -> tuple[int, bool, bool]:
            school = row[2].school
            return row[0], school == preferred_school, school not in shown

        def sample(pool: list[RankedRow], limit: int) -> list[RankedRow]:
            """Take `limit` rows by priority; task-ID hashing orders oversized peers."""
            ordered = sorted(pool, key=priority, reverse=True)
            chosen: list[RankedRow] = []
            for _, group in groupby(ordered, key=priority):
                remaining = limit - len(chosen)
                if remaining <= 0:
                    break
                peers = list(group)
                if len(peers) > remaining:
                    peers.sort(
                        key=lambda row: sha256(
                            f"{task_id}:{row[2].school}".encode()
                        ).digest()
                    )
                chosen.extend(peers[:remaining])
            return chosen

        if not tiered:
            selected = sample(list(by_school.values()), MAX_SELECTED)
        else:
            pools = {
                tier: [row for row in by_school.values() if row[2].scoreMatch and row[2].scoreMatch.tier == tier]
                for tier in TIER_ORDER
            }
            counts = {tier: min(TIER_QUOTA[tier], len(pools[tier])) for tier in TIER_ORDER}
            free = MAX_SELECTED - sum(counts.values())
            for tier in FILL_ORDER:
                extra = min(free, len(pools[tier]) - counts[tier])
                counts[tier] += extra
                free -= extra
            # A larger limit extends the same deterministic order, so quotas compose.
            selected = [row for tier in TIER_ORDER for row in sample(pools[tier], counts[tier])]
        # Evidence level picks each school's representative and the display order,
        # never which schools are sampled (2026-11-19).
        selected.sort(key=lambda row: (row[0], row[2].school == preferred_school, level_rank(row)), reverse=True)
        if tiered:
            selected.sort(key=lambda row: TIER_ORDER.index(row[2].scoreMatch.tier))
        return selected

    def level_rank(row: RankedRow) -> int:
        """Rank formal evidence levels; clue-only rows rank lowest."""
        return LEVEL_RANK.get(row[2].evidenceLevel or "", 0)

    def decode(rows: list[SerializedRow]) -> list[RankedRow]:
        """Restore validated rows after the registry serializes tool arguments."""
        return [
            (region, updated, RankedCandidate.model_validate(candidate), Document.model_validate(doc))
            for region, updated, candidate, doc in rows
        ]

    registry = StrictToolRegistry()
    registry.add(
        ValidatedTool(
            "filter_programs",
            "按年份、专业、学位及硬条件筛选院校",
            FilterParameters,
            filter_programs,
        )
    )
    registry.add(
        ValidatedTool(
            "rank_programs",
            "按地区偏好和意向院校排序，同级候选按任务编号取样，每校取证据等级最高的项目，最多5所；"
            "按分数时冲2稳2保1并依次补位",
            RankParameters,
            rank_programs,
            decode,
        )
    )
    registry.add(
        ValidatedTool(
            "match_scores",
            "按往年录取最低分与中位分把候选分为冲、稳、保（score-match-v1），低于范围或缺数据的不入选",
            ScoreParameters,
            match_scores,
        )
    )
    return registry
