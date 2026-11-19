#!/usr/bin/env python3
"""Create a versioned RAG copy from a read-only public school catalog export."""

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kaoyan-agent"))

from retrieval import Corpus
from tools.schools import Admission

ORIGINAL_MARKERS = ("【官方招生事实】", "【2027官方来源核验摘要】")
PENDING_MARKER = "【采集待核实】"
REVIEWED_LABEL = "CATALOG_CHECKED"
APPROVED_LABEL = "USER_APPROVED"
DEGREE_BY_CODE = {"081200": "academic", "085404": "professional"}


def required_text(pattern: str, value: str, record_id: int) -> str:
    """Extract a recorded value or reject the incomplete export row."""
    match = re.search(pattern, value)
    if match is None or not match[1].strip():
        raise ValueError(f"缺少招生来源字段，专业记录 {record_id}")
    return match[1].strip()


def admission_identity(fields: dict) -> tuple[str, str, int, str]:
    """Identify the originals by school, code, year and college."""
    return fields["school"], fields["majorCode"], fields["year"], fields["college"]


def build_catalog_row(row: dict) -> dict:
    """Preserve source fields and transfer only structured catalog facts."""
    record_id = row["id"]
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("无效的学校专业记录编号")
    remark = row["remark"]
    pending = remark.startswith(PENDING_MARKER)
    date_pattern = r"接入日期：(\d{4}-\d{2}-\d{2})" if pending else r"(\d{4}-\d{2}-\d{2}) AI辅助核对"
    recorded = date.fromisoformat(required_text(date_pattern, remark, record_id)).isoformat()
    version = (
        "collection-v" + required_text(r"采集版本：(\d+)", remark, record_id)
        if pending
        else "catalog-review-" + recorded
    )
    url = required_text(r"来源(?:链接[^：]*)?：(https?://[^；\s]+)", remark, record_id)
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError(f"非法招生来源链接，专业记录 {record_id}")
    locator = required_text(r"原文(?:位置|定位)：(.+?)(?:；采集版本：|。\d{4}-\d{2}-\d{2} AI辅助核对)", remark, record_id)
    exam = required_text(r"(?:原登记)?初试：(.+?)(?:（|。)" if pending else r"初试：(.+?)。", remark, record_id)
    exam_codes = list(dict.fromkeys(re.findall(r"(?<!\d)\d{3}(?!\d)", exam)))
    if len(exam_codes) != 4 or any(code == "000" for code in exam_codes):
        exam_codes = []
    context = row["context"]
    expected_degree = DEGREE_BY_CODE[row["majorCode"]]
    degree_text = "学术学位" if expected_degree == "academic" else "专业学位"
    if degree_text not in remark or (not pending and "AI辅助核对" not in remark):
        raise ValueError(f"招生记录学位或来源状态不一致，专业记录 {record_id}")
    program = Admission(
        programId=f"catalog-detail-{record_id:08d}",
        school=row["school"],
        college=context["college"],
        major=row["major"],
        majorCode=row["majorCode"],
        year=row["year"],
        degreeType=expected_degree,
        region=row["region"],
        studyMode=context["studyMode"],
        examSubjects=exam_codes,
        updatedAt=recorded,
        track=context["track"],
        admissionCategory=context["admissionCategory"],
        catalogReview=APPROVED_LABEL if pending else REVIEWED_LABEL,
    )
    title = f"{program.school}{program.year}年{program.major} · {program.college}"
    status = "用户批准接入，原登记待官网核实" if pending else "此前核对过官方目录，以当年官方文件为准"
    if pending:
        locator += "；日期为旧记录接入日期"
    return {
        "id": program.programId,
        "domain": "school",
        "title": title,
        "url": url,
        "locator": locator,
        "version": version,
        "retrievedAt": recorded,
        "license": "保存招生目录短字段和出处供院校查询，原文版权归来源方。",
        "content": f"{title}，专业代码{program.majorCode}，方向{program.track or '未登记'}。{status}。",
        "reviewStatus": "catalog_approved",
        "metadata": program.model_dump(exclude_none=True),
    }


def main() -> None:
    """Validate the export and write a new release file without modifying originals."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    snapshot = [json.loads(line) for line in args.snapshot.read_text(encoding="utf-8").splitlines()]
    school_rows = [row for row in snapshot if row["kind"] == "school"]
    if not school_rows or len({row["id"] for row in school_rows}) != len(school_rows):
        raise SystemExit("学校专业快照为空或编号重复")
    base = Corpus(args.base)
    base_records = [
        row for row, document in zip(base.records, base.documents, strict=True)
        if document.source_review_status == "verified"
    ]
    originals = {
        admission_identity(row["metadata"]) for row in base_records if row["domain"] == "school"
    }
    retained = set()
    extra = []
    for row in sorted(school_rows, key=lambda item: item["id"]):
        if row["remark"].startswith(ORIGINAL_MARKERS):
            identity = admission_identity({**row, "college": row["context"]["college"]})
            if identity in retained or identity not in originals:
                raise ValueError(f"原版语料与数据库项目映射不唯一，专业记录 {row['id']}")
            retained.add(identity)
        else:
            extra.append(build_catalog_row(row))
    if retained != originals:
        raise ValueError("公开目录快照缺少原正式推荐记录")
    records = [*base_records, *extra]
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    out = args.output_dir / f"school-catalog-corpus-{checksum}.json"
    if out.exists():
        if json.loads(out.read_text(encoding="utf-8")) != records:
            raise ValueError("同名版本内容不一致")
    else:
        with out.open("x", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(json.dumps({
        "file": str(out),
        "releaseId": Corpus(out).release_id,
        "schools": len({row["school"] for row in school_rows}),
        "schoolRows": len(school_rows),
        "verifiedSchool": len(retained),
        "catalogReview": dict(Counter(row["metadata"]["catalogReview"] for row in extra)),
        "knowledge": len(base_records) - len(retained),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
