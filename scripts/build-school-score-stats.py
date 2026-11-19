#!/usr/bin/env python3
"""Build the reviewed score-statistics dataset and a new versioned RAG copy.

Offline only: reads user-provided CSV files as data, never edits them, never
connects to MySQL, Qdrant or a model, and writes new files with exclusive create.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kaoyan-agent"))
sys.path.insert(0, str(ROOT / "scripts"))

from retrieval import Corpus  # noqa: E402
from school_scores import FLAG_LABELS, build_dataset, canonical, corpus_document  # noqa: E402


def write_once(path: Path, text: str) -> None:
    """Create a file, or accept an identical existing one."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise SystemExit(f"同名文件内容不同，停止：{path}")
        return
    with path.open("x", encoding="utf-8") as file:
        file.write(text)


def preview(dataset: dict[str, object], corpus_file: Path, release_id: str) -> str:
    """Human-readable summary for the import confirmation."""
    rows = dataset["observations"]
    counts = dataset["counts"]
    flags = Counter(flag for row in rows for flag in row["flags"])
    years = Counter(row["year"] for row in rows)
    lines = [
        "# 院校录取分数统计导入清单（2026-11-18）", "",
        f"- 清单SHA-256：`{dataset['datasetSha256']}`",
        f"- 来源：{dataset['sourceLabel']}；状态 `{dataset['reviewStatus']}`",
        f"- 输入：{len(dataset['inputs'])} 个CSV，{counts['inputRows']} 行；合并明显重复 {counts['merged']} 行；"
        f"保留观测 {counts['observations']} 条，覆盖 {counts['schools']} 所院校",
        "- 年份：" + "、".join(f"{year}年 {count} 条" for year, count in sorted(years.items(), reverse=True)),
        f"- 需新增院校（仅当日常库中不存在时插入，层次留空）：{len(dataset['newSchools'])} 所",
        f"- 语料版本：`{corpus_file.name}`，releaseId `{release_id}`", "",
        "## 数据提示（原值保留，仅标记）", "", "| 标记 | 含义 | 条数 |", "| --- | --- | ---: |",
    ]
    lines += [f"| `{flag}` | {FLAG_LABELS[flag]} | {count} |" for flag, count in sorted(flags.items())]
    lines += ["", f"说明：{dataset['notice']}。合并规则及边界见搭建文档“院校录取分数统计导入契约”。", ""]
    return "\n".join(lines)


def main() -> None:
    """Validate inputs and write dataset, preview and corpus release."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, required=True)
    parser.add_argument("--provinces", type=Path, default=ROOT / "config/school-score-provinces-20261118.json")
    parser.add_argument("--base", type=Path, required=True, help="当前发布的语料副本")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/school-scores-20261118")
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "kaoyan-agent/knowledge")
    parser.add_argument("--retrieved-at", default="2026-11-18")
    args = parser.parse_args()
    provinces = json.loads(args.provinces.read_text(encoding="utf-8"))
    dataset = build_dataset(args.csv_dir, provinces)
    base = Corpus(args.base)
    version = "school-scores-" + dataset["datasetSha256"][:16]
    documents = [corpus_document(row, version, args.retrieved_at) for row in dataset["observations"]]
    existing = {record["id"] for record in base.records}
    if existing & {document["id"] for document in documents}:
        raise SystemExit("基础语料已含同编号分数资料，停止")
    records = [*base.records, *documents]
    checksum = hashlib.sha256(canonical(records).encode("utf-8")).hexdigest()[:16]
    corpus_file = args.corpus_dir / f"school-score-corpus-{checksum}.json"
    write_once(corpus_file, json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    release = Corpus(corpus_file)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_once(args.output_dir / "dataset.json", json.dumps(dataset, ensure_ascii=False, indent=2) + "\n")
    write_once(args.output_dir / "preview.md", preview(dataset, corpus_file, release.release_id))
    print(json.dumps({
        "dataset": str(args.output_dir / "dataset.json"), "datasetSha256": dataset["datasetSha256"],
        "corpus": str(corpus_file), "releaseId": release.release_id, "baseRecords": len(base.records),
        "scoreDocuments": len(documents), "chunks": len(release.chunks), **dataset["counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
