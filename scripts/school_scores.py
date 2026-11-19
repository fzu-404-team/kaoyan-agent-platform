"""Offline cleaning of user-provided admission score statistics.

Maintenance module only: it never connects to a database or the network. CSV
text is untrusted data; values are parsed into typed fields and never executed.
Rows are kept as observations. Only rows identical in every field except the
college / major wording are merged; other suspicious rows are flagged, not fixed.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

HEADER = ["学校", "学院", "专业代码", "专业", "年份", "考试科目", "复试线", "最低分", "中位分", "平均分", "最高分", "公布录取数"]
SCORE_FIELDS = ("retestLine", "minScore", "medianScore", "avgScore", "maxScore")
REVIEW_STATUS = "USER_APPROVED"
SOURCE_LABEL = "用户提供CSV（原始站点未登记），经用户审核批准；非学校官网原文"
POOL_NOTICE = "公布录取数可能为多个专业共用的录取池，不能相加"
MAJOR_CODE = re.compile(r"^\d{4}[0-9A-Z]{2}$")
EXAM_COMBO = re.compile(r"^\d{2}408$")
SUFFIX = re.compile(r"\s*\d{2}改考$")


class ScoreDataError(ValueError):
    """The input cannot be imported without guessing."""


@dataclass
class Observation:
    """One cleaned CSV row; numbers stay exact decimals as written."""

    school: str
    raw_school: str
    college: str
    major_code: str | None
    major: str
    year: int
    exam_combo: str
    retest_line: Decimal | None
    min_score: Decimal
    median_score: Decimal
    avg_score: Decimal | None
    max_score: Decimal | None
    admitted_count: int
    file: str
    line: int
    flags: list[str] = field(default_factory=list)
    merged_from: list[dict[str, object]] = field(default_factory=list)

    def pool_key(self) -> tuple:
        """Fields that identify a shared admission pool despite edited averages."""
        return (self.school, self.year, self.exam_combo, self.min_score, self.median_score, self.admitted_count)

    def filled(self) -> int:
        """Count non-empty optional fields to keep the most complete duplicate."""
        values = (self.college, self.major_code, self.retest_line, self.avg_score, self.max_score)
        return sum(value not in (None, "") for value in values)

    def to_json(self) -> dict[str, object]:
        """Stable JSON shape; decimals are serialized as strings to stay exact."""
        number = lambda value: None if value is None else str(value)
        row = {
            "school": self.school, "rawSchool": self.raw_school, "college": self.college,
            "majorCode": self.major_code, "major": self.major, "year": self.year,
            "examCombo": self.exam_combo, "retestLine": number(self.retest_line),
            "minScore": number(self.min_score), "medianScore": number(self.median_score),
            "avgScore": number(self.avg_score), "maxScore": number(self.max_score),
            "admittedCount": self.admitted_count, "flags": sorted(self.flags),
            "source": {"label": SOURCE_LABEL, "file": self.file, "line": self.line,
                       "mergedFrom": self.merged_from},
            "reviewStatus": REVIEW_STATUS,
        }
        identity = {key: value for key, value in row.items() if key not in {"flags", "source"}}
        row["rowKey"] = hashlib.sha256(canonical(identity).encode("utf-8")).hexdigest()
        return row


def canonical(value: object) -> str:
    """Canonical JSON used for every checksum."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_school(name: str, aliases: dict[str, str]) -> str:
    """Unify brackets, drop exam-change suffixes and apply reviewed aliases."""
    text = SUFFIX.sub("", name.replace("(", "（").replace(")", "）").strip()).strip()
    return aliases.get(text, text)


def decimal(value: str, where: str, required: bool) -> Decimal | None:
    """Parse a 0-500 score; empty only when optional."""
    text = value.strip()
    if not text:
        if required:
            raise ScoreDataError(f"{where} 缺少必填分数")
        return None
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ScoreDataError(f"{where} 分数不是数字") from error
    if not number.is_finite() or not Decimal(0) <= number <= Decimal(500) or number.as_tuple().exponent < -2:
        raise ScoreDataError(f"{where} 分数超出范围")
    return number


def read_rows(directory: Path, aliases: dict[str, str]) -> tuple[list[Observation], list[dict[str, str]]]:
    """Read every CSV in a directory, checking the exact header of each file."""
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise ScoreDataError("目录中没有CSV文件")
    rows, inputs = [], []
    for path in files:
        data = path.read_bytes()
        inputs.append({"file": path.name, "sha256": hashlib.sha256(data).hexdigest()})
        reader = csv.reader(data.decode("utf-8-sig").splitlines())
        header = next(reader, None)
        if header != HEADER:
            raise ScoreDataError(f"{path.name} 表头不符")
        for line, values in enumerate(reader, start=2):
            where = f"{path.name} 第{line}行"
            if len(values) != len(HEADER):
                raise ScoreDataError(f"{where} 列数不符")
            item = dict(zip(HEADER, (value.strip() for value in values)))
            code = item["专业代码"] or None
            if code is not None and not MAJOR_CODE.fullmatch(code):
                raise ScoreDataError(f"{where} 专业代码格式不符")
            if not EXAM_COMBO.fullmatch(item["考试科目"]):
                raise ScoreDataError(f"{where} 考试科目组合格式不符")
            if not re.fullmatch(r"20\d{2}", item["年份"]) or not item["公布录取数"].isdigit():
                raise ScoreDataError(f"{where} 年份或录取数格式不符")
            if not item["学校"] or not (item["专业"] or code):
                raise ScoreDataError(f"{where} 缺少学校或专业名称及代码")
            rows.append(Observation(
                school=normalize_school(item["学校"], aliases), raw_school=item["学校"],
                college=item["学院"], major_code=code, major=item["专业"], year=int(item["年份"]),
                exam_combo=item["考试科目"], retest_line=decimal(item["复试线"], where, False),
                min_score=decimal(item["最低分"], where, True), median_score=decimal(item["中位分"], where, True),
                avg_score=decimal(item["平均分"], where, False), max_score=decimal(item["最高分"], where, False),
                admitted_count=int(item["公布录取数"]), file=path.name, line=line))
    return rows, inputs


OPTIONAL = ("major_code", "retest_line", "avg_score", "max_score")


def covered(kept: Observation, other: Observation, field_names: tuple[str, ...]) -> bool:
    """Every non-blank value of `other` equals the kept row, so dropping it loses nothing."""
    return all(getattr(other, name) is None or getattr(other, name) == getattr(kept, name)
               for name in field_names)


def agree(left: Observation, right: Observation, field_names: tuple[str, ...]) -> bool:
    """No field holds two different non-blank values."""
    return all(None in (getattr(left, name), getattr(right, name)) or getattr(left, name) == getattr(right, name)
               for name in field_names)


def merge_duplicates(rows: list[Observation]) -> tuple[list[Observation], list[dict[str, object]]]:
    """Merge a row into a kept row that already holds every one of its values.

    Required scores, year, exam combination and admitted count must be equal.
    Rows that would be duplicates except for two different non-empty major codes
    are kept apart and flagged instead.
    """
    groups: dict[tuple, list[Observation]] = defaultdict(list)
    for row in rows:
        groups[row.pool_key()].append(row)
    kept, removed = [], []
    for members in groups.values():
        winners: list[Observation] = []
        for row in sorted(members, key=lambda item: (-item.filled(), -len(item.college), item.file, item.line)):
            winner = next((item for item in winners if covered(item, row, OPTIONAL)), None)
            if winner is None:
                for item in winners:
                    if item.major_code and row.major_code and item.major_code != row.major_code \
                            and agree(item, row, OPTIONAL[1:]):
                        item.flags.append("SAME_SCORES_DIFFERENT_CODES")
                        row.flags.append("SAME_SCORES_DIFFERENT_CODES")
                winners.append(row)
                continue
            winner.merged_from.append({"file": row.file, "line": row.line,
                                       "college": row.college, "major": row.major})
            removed.append({"keptFile": winner.file, "keptLine": winner.line, "file": row.file, "line": row.line})
        kept.extend(winners)
    return kept, removed


def flag_rows(rows: list[Observation]) -> None:
    """Mark contradictions and shared pools without changing any value."""
    pools: dict[tuple, list[Observation]] = defaultdict(list)
    for row in rows:
        pools[row.pool_key()].append(row)
        if row.max_score is not None and row.max_score < row.median_score:
            row.flags.append("MAX_BELOW_MEDIAN")
        if row.min_score > row.median_score:
            row.flags.append("MIN_ABOVE_MEDIAN")
        if row.avg_score is not None and (row.avg_score < row.min_score
                                          or (row.max_score is not None and row.avg_score > row.max_score)):
            row.flags.append("AVG_OUT_OF_RANGE")
        if row.retest_line is not None and row.retest_line > row.min_score:
            row.flags.append("LINE_ABOVE_MIN")
    for members in pools.values():
        if len(members) > 1:
            for row in members:
                row.flags.append("POSSIBLE_SAME_POOL")
    for row in rows:
        row.flags = sorted(set(row.flags))


def build_dataset(directory: Path, provinces: dict[str, object]) -> dict[str, object]:
    """Read, merge, flag and checksum the observations."""
    aliases = provinces["aliases"]
    rows, inputs = read_rows(directory, aliases)
    kept, removed = merge_duplicates(rows)
    flag_rows(kept)
    observations = sorted((row.to_json() for row in kept), key=lambda row: (row["school"], -row["year"], row["rowKey"]))
    if len({row["rowKey"] for row in observations}) != len(observations):
        raise ScoreDataError("清洗后出现内容完全相同的观测")
    new_schools = provinces["schools"]
    names = [entry["name"] for entry in new_schools]
    if len(set(names)) != len(names) or any(not entry["province"] for entry in new_schools):
        raise ScoreDataError("省份映射校名重复或缺省份")
    body = {
        "version": "school-scores-20261118",
        "reviewStatus": REVIEW_STATUS,
        "sourceLabel": SOURCE_LABEL,
        "notice": POOL_NOTICE,
        "inputs": inputs,
        "provinceMapping": {"version": provinces["version"], "basis": provinces["basis"]},
        "newSchools": sorted(new_schools, key=lambda entry: entry["name"]),
        "observations": observations,
        "mergedDuplicates": removed,
        "counts": {"inputRows": len(rows), "observations": len(observations), "merged": len(removed),
                   "schools": len({row["school"] for row in observations})},
    }
    body["datasetSha256"] = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
    return body


def load_dataset(path: Path) -> dict[str, object]:
    """Load a reviewed dataset and recompute its checksum."""
    body = json.loads(path.read_text(encoding="utf-8"))
    claimed = body.pop("datasetSha256", None)
    actual = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
    if claimed != actual:
        raise ScoreDataError("清单摘要与内容不一致")
    body["datasetSha256"] = actual
    return body


FLAG_LABELS = {
    "POSSIBLE_SAME_POOL": "可能与其他专业同一录取池",
    "SAME_SCORES_DIFFERENT_CODES": "与其他专业代码分数完全相同",
    "MAX_BELOW_MEDIAN": "最高分低于中位分",
    "MIN_ABOVE_MEDIAN": "最低分高于中位分",
    "AVG_OUT_OF_RANGE": "平均分超出最低至最高范围",
    "LINE_ABOVE_MIN": "复试线高于录取最低分",
}


def corpus_document(row: dict[str, object], version: str, retrieved_at: str) -> dict[str, object]:
    """One self-contained retrieval document per observation."""
    def value(key: str, unit: str = "") -> str:
        return "未登记" if row[key] is None else f"{row[key]}{unit}"

    code = f"{row['majorCode']} " if row["majorCode"] else ""
    college = row["college"] or "学院未登记"
    major = row["major"] or "专业名称未登记"
    title = f"{row['school']}{row['year']}年{row['major'] or row['majorCode']}录取分数统计"
    flags = "；".join(FLAG_LABELS[flag] for flag in row["flags"])
    content = (
        f"{row['school']} · {college} · {code}{major} · {row['year']}年 · 初试科目组合{row['examCombo']}："
        f"复试线{value('retestLine')}，录取最低分{value('minScore')}，中位分{value('medianScore')}，"
        f"平均分{value('avgScore')}，最高分{value('maxScore')}，公布录取{row['admittedCount']}人。"
        f"数据为用户提供并经用户审核批准，非学校官网原文；{POOL_NOTICE}。"
        + (f"数据提示：{flags}。" if flags else "")
    )
    keywords = [row["school"], str(row["year"])] + [value for value in (row["major"], row["majorCode"]) if value]
    metadata = {key: row[key] for key in ("school", "college", "majorCode", "major", "year", "examCombo",
                                          *SCORE_FIELDS, "admittedCount", "flags", "rowKey")}
    metadata.update(kind="score_statistics", review=REVIEW_STATUS)
    return {
        "id": "school-score-" + str(row["rowKey"])[:16],
        "domain": "school",
        "title": title,
        "url": "",
        "locator": f"{row['source']['file']} 第{row['source']['line']}行",
        "version": version,
        "retrievedAt": retrieved_at,
        "license": SOURCE_LABEL + "，仅供本项目参考。",
        "content": content,
        "reviewStatus": "user_approved",
        "metadata": metadata,
        "keywords": list(dict.fromkeys(keywords)),
    }
