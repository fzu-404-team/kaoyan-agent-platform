"""User-approved score statistics: cleaning, merge, flags, corpus and SQL guards."""
import csv
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "kaoyan-agent"))

import school_scores as scores  # noqa: E402
from retrieval import Corpus, Document  # noqa: E402

HEADER = scores.HEADER
PROVINCES = {"version": "t", "basis": "测试", "aliases": {"华北电力大学（保定）": "华北电力大学"},
             "schools": [{"name": "新校大学", "province": "江苏"}]}


def write(directory: Path, name: str, rows: list[list[str]]) -> None:
    with (directory / name).open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADER)
        writer.writerows(rows)


def row(school="新校大学", college="计算机学院", code="081200", major="计算机科学与技术", year="2026",
        exam="11408", line="300", low="301", median="340", avg="341.5", high="390", count="20"):
    return [school, college, code, major, year, exam, line, low, median, avg, high, count]


def build(tmp_path: Path, rows: list[list[str]]) -> dict:
    write(tmp_path, "a.csv", rows)
    return scores.build_dataset(tmp_path, PROVINCES)


def test_blank_copy_is_merged_without_losing_values(tmp_path):
    data = build(tmp_path, [row(avg="", high="", college="计算机学院 计算机"), row()])
    assert data["counts"] == {"inputRows": 2, "observations": 1, "merged": 1, "schools": 1}
    kept = data["observations"][0]
    assert (kept["avgScore"], kept["maxScore"]) == ("341.5", "390")
    assert kept["source"]["mergedFrom"][0]["college"] == "计算机学院 计算机"


def test_rows_with_different_values_or_codes_are_kept_and_flagged(tmp_path):
    data = build(tmp_path, [row(), row(avg="342"), row(code="083900", major="网络空间安全")])
    assert data["counts"]["observations"] == 3
    flags = [set(item["flags"]) for item in data["observations"]]
    assert all("POSSIBLE_SAME_POOL" in value for value in flags)
    assert sum("SAME_SCORES_DIFFERENT_CODES" in value for value in flags) == 2


def test_contradictions_are_flagged_not_changed(tmp_path):
    data = build(tmp_path, [row(high="330", line="305", avg="400")])
    item = data["observations"][0]
    assert set(item["flags"]) == {"MAX_BELOW_MEDIAN", "LINE_ABOVE_MIN", "AVG_OUT_OF_RANGE"}
    assert (item["maxScore"], item["retestLine"], item["avgScore"]) == ("330", "305", "400")


def test_school_names_normalized(tmp_path):
    data = build(tmp_path, [row(school="华北电力大学(保定)"), row(school="新校大学 27改考", count="3")])
    assert {item["school"] for item in data["observations"]} == {"华北电力大学", "新校大学"}
    assert {item["rawSchool"] for item in data["observations"]} == {"华北电力大学(保定)", "新校大学 27改考"}


@pytest.mark.parametrize("bad", [row(code="81200"), row(exam="11409"), row(low=""), row(median="501"),
                                 row(count="x"), row(major="", code=""), row(low="300.123")])
def test_invalid_rows_are_rejected(tmp_path, bad):
    with pytest.raises(scores.ScoreDataError):
        build(tmp_path, [bad])


def test_header_must_match(tmp_path):
    (tmp_path / "a.csv").write_text("学校,学院\n甲,乙\n", encoding="utf-8")
    with pytest.raises(scores.ScoreDataError):
        scores.build_dataset(tmp_path, PROVINCES)


def test_dataset_checksum_detects_edits(tmp_path):
    data = build(tmp_path, [row()])
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert scores.load_dataset(path)["datasetSha256"] == data["datasetSha256"]
    data["observations"][0]["minScore"] = "200"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(scores.ScoreDataError):
        scores.load_dataset(path)


def test_documents_are_searchable_but_not_citable_or_candidates(tmp_path):
    data = build(tmp_path, [row(), row(school="华北电力大学", major="软件工程", code="083500", count="9")])
    base = json.loads((ROOT / "kaoyan-agent/knowledge/corpus.json").read_text(encoding="utf-8"))
    docs = [scores.corpus_document(item, "school-scores-test", "2026-11-18") for item in data["observations"]]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps([*base, *docs], ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(path)
    score_chunks = [chunk for chunk in corpus.chunks if chunk.reviewStatus == "user_approved"]
    assert len(score_chunks) == 2 and all(chunk.domain == "school" for chunk in score_chunks)
    hits = corpus.bm25("新校大学计算机科学与技术复试线", "school")
    assert hits and hits[0].metadata["school"] == "新校大学"
    assert not [hit for hit in corpus.bm25("新校大学计算机", "knowledge") if hit.reviewStatus == "user_approved"]
    assert "非学校官网原文" in score_chunks[0].content
    with pytest.raises(ValueError):
        score_chunks[0].reference()
    from unittest.mock import AsyncMock
    from config import Settings
    from retrieval import Retriever
    from workflows import Workflows
    settings = Settings(_env_file=None, AGENT_INTERNAL_KEY="k" * 32, RAG_DATA=path)
    engine = Workflows(settings, corpus, Retriever(settings, corpus), AsyncMock())
    assert engine.programs and all(doc.reviewStatus != "user_approved" for _, doc in engine.programs)


def test_user_approved_requires_empty_url_and_kind():
    base = {"id": "x", "domain": "school", "title": "t", "url": "", "locator": "a.csv 第2行", "version": "v",
            "retrievedAt": "2026-11-18", "license": "l", "content": "c", "reviewStatus": "user_approved",
            "metadata": {"kind": "score_statistics"}}
    Document.model_validate(base)
    for change in ({"url": "https://example.com/a"}, {"metadata": {}}, {"domain": "knowledge"}):
        with pytest.raises(ValueError):
            Document.model_validate({**base, **change})


def load_importer():
    spec = importlib.util.spec_from_file_location("score_import", ROOT / "scripts/import-school-score-stats.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sql_literals_never_inline_source_text(tmp_path):
    importer = load_importer()
    data = build(tmp_path, [row(college="x'); DROP TABLE school; --")])
    rows = importer.expected_rows(data)
    projected = next(iter(rows.values()))
    rendered = importer.literal("college", projected["college"])
    assert "DROP" not in rendered and rendered.startswith("CONVERT(0x")
    assert importer.literal("min_score", "301") == "301"
    assert importer.literal("major_name", "") == "''"
    with pytest.raises(RuntimeError):
        importer.literal("min_score", "1;DROP")
