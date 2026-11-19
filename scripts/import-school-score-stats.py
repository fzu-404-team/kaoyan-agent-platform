#!/usr/bin/env python3
"""Preview, rehearse or apply the user-approved score-statistics import.

Default is a read-only preview of kaoyan_dev. --rehearse makes a private full
backup, restores it into a random isolated database and runs failure, rollback,
apply, read-back, repeat and manual-revision checks there. --apply requires the
reviewed dataset SHA-256 and repeats the rehearsal before one guarded
transaction. V16 DDL is additive and commits separately. Never starts services.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sys
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
from school_scores import canonical, load_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLE = "school_score_statistic"
MIGRATION = ROOT / "kaoyan-B/src/main/resources/db/V16__school_score_statistic.sql"
PRIVATE = ROOT / ".cache/school-scores-20261118/operations"
LOCK_NAME = "kaoyan_school_scores_v1"
COLUMNS = ("college", "major_code", "major_name", "stat_year", "exam_combo", "retest_line", "min_score",
           "median_score", "avg_score", "max_score", "admitted_count", "review_status", "flags_json",
           "source_json", "row_key")
DECIMALS = {"retest_line", "min_score", "median_score", "avg_score", "max_score"}
SCORE = re.compile(r"^\d{1,3}(?:\.\d{1,2})?$")


def helpers() -> ModuleType:
    """Load the existing local-MySQL and backup helpers without running their CLI."""
    spec = importlib.util.spec_from_file_location("score_import_helpers", ROOT / "scripts/import-real-data.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载数据库维护工具")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = helpers()
sql = helper.sql
require = helper.require


def literal(column: str, value: object) -> str:
    """Safe SQL literal: validated decimals inline, everything else hex-encoded."""
    if column in DECIMALS:
        if value is None:
            return "NULL"
        require(isinstance(value, str) and SCORE.fullmatch(value) is not None, "分数格式不符")
        return value
    if column.endswith("_json"):
        return "CAST(" + sql(canonical(value)) + " AS JSON)"
    if value == "":
        # The shared helper would emit an empty hex literal, which MySQL rejects.
        return "''"
    return sql(value)


def expected_rows(dataset: dict[str, object]) -> dict[str, dict[str, object]]:
    """Project each observation to the V16 columns, keyed by row_key."""
    rows = {}
    for item in dataset["observations"]:
        rows[item["rowKey"]] = {
            "school": item["school"], "college": item["college"], "major_code": item["majorCode"],
            "major_name": item["major"], "stat_year": item["year"], "exam_combo": item["examCombo"],
            "retest_line": item["retestLine"], "min_score": item["minScore"], "median_score": item["medianScore"],
            "avg_score": item["avgScore"], "max_score": item["maxScore"], "admitted_count": item["admittedCount"],
            "review_status": item["reviewStatus"], "flags_json": item["flags"], "source_json": item["source"],
            "row_key": item["rowKey"],
        }
    require(len(rows) == len(dataset["observations"]), "观测编号重复")
    return rows


def comparable(row: dict[str, object]) -> dict[str, object]:
    """Normalize decimals and JSON so saved and expected rows compare exactly."""
    result = {}
    for column in COLUMNS:
        value = row[column]
        if column in DECIMALS:
            value = None if value is None else Decimal(str(value))
        elif column.endswith("_json"):
            value = canonical(json.loads(value) if isinstance(value, str) else value)
        elif column == "review_status" and value == "verified":
            value = "USER_APPROVED"
        result[column] = value
    return result


def inspect(db: object, dataset: dict[str, object]) -> dict[str, object]:
    """Plan inserts and reject manual edits or ambiguous school names before mutation."""
    require(db.name == "kaoyan_dev" or db.name.startswith("kaoyan_realdata_verify_"), "目标库不符")
    require(db.query("SELECT DISTINCT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE();") == "InnoDB",
            "存在非事务表，停止导入")
    schools = db.records("school")
    names: dict[str, list[int]] = {}
    for school in schools:
        names.setdefault(school["name"], []).append(school["id"])
    wanted = expected_rows(dataset)
    mapped = {entry["name"] for entry in dataset["newSchools"]}
    needed = {row["school"] for row in wanted.values()}
    require(needed <= set(names) | mapped, "存在既不在院校库也无省份映射的院校："
            + "、".join(sorted(needed - set(names) - mapped)))
    require(all(len(names.get(name, [])) <= 1 for name in needed | mapped), "院校库中存在同名院校，无法唯一关联")
    to_insert_schools = sorted(name for name in mapped if name not in names)
    unused = sorted(mapped - needed)
    require(not unused, "省份映射含数据中未出现的院校：" + "、".join(unused))
    saved = db.records(TABLE) if TABLE in db.tables() else []
    school_by_id = {school["id"]: school["name"] for school in schools}
    present = 0
    for record in saved:
        expected = wanted.get(record["row_key"])
        if expected is None:
            continue
        require(comparable(record) == comparable(expected) and school_by_id.get(record["school_id"]) == expected["school"],
                "已有分数统计与清单不同，禁止覆盖人工或其他批次修改")
        present += 1
    return {"database": db.name, "datasetSha256": dataset["datasetSha256"], "requiresV16": TABLE not in db.tables(),
            "schoolsExisting": len(schools), "schoolsToInsert": len(to_insert_schools),
            "schoolsLinkedExisting": len(needed & set(names)), "statisticsToInsert": len(wanted) - present,
            "statisticsAlreadyPresent": present, "otherBatchRows": len(saved) - present}


def ensure_schema(db: object) -> None:
    """Apply V16 only when absent and check its exact column set."""
    if TABLE not in db.tables():
        db.query(MIGRATION.read_text(encoding="utf-8"))
    require(set(db.columns(TABLE)) == {"id", "school_id", *COLUMNS, "imported_at"}, "V16表结构不符")


def statement(db: object, dataset: dict[str, object], before: dict[str, list[str]],
              rollback: bool = False, failure: bool = False) -> str:
    """Generate one locked, guarded transaction; all source text is hex-encoded."""
    lines = ["SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION';",
             "CREATE TEMPORARY TABLE score_guard(v INT NOT NULL CHECK(v=1));",
             f"INSERT INTO score_guard VALUES(IF(GET_LOCK('{LOCK_NAME}',10)=1,1,0));",
             "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;", "START TRANSACTION;"]
    for table in ("school", TABLE):
        keys = db.keys(table)
        expression = db.fingerprint_expression(table)
        lines.append(f"SELECT {','.join(keys)} FROM `{table}` ORDER BY {','.join(keys)} FOR UPDATE;")
        lines.append(f"INSERT INTO score_guard SELECT IF(COUNT(*)={len(before[table])},1,0) FROM `{table}`;")
        for fingerprint in before[table]:
            identity, checksum = fingerprint.split("\t")
            where = " AND ".join(f"`{key}`={sql(value)}" for key, value in zip(keys, json.loads(identity)))
            lines.append(f"INSERT INTO score_guard SELECT IF(COUNT(*)=1,1,0) FROM `{table}` WHERE {where} AND {expression}={sql(checksum)};")
    for entry in dataset["newSchools"]:
        lines.append("INSERT INTO school(name,province,level) SELECT " + sql(entry["name"]) + "," + sql(entry["province"])
                     + ",NULL WHERE NOT EXISTS(SELECT 1 FROM school WHERE name=" + sql(entry["name"]) + ");")
    rows = expected_rows(dataset)
    for row in rows.values():
        # The scalar subquery fails on duplicate names instead of guessing.
        values = ["(SELECT id FROM school WHERE name=" + sql(row["school"]) + ")"]
        values += [literal(column, row[column]) for column in COLUMNS]
        lines.append(f"INSERT INTO `{TABLE}`(school_id," + ",".join(COLUMNS) + ") SELECT " + ",".join(values)
                     + f" WHERE NOT EXISTS(SELECT 1 FROM `{TABLE}` WHERE row_key=" + sql(row["row_key"]) + ");")
    for row in rows.values():
        matches = [f"`{column}` <=> " + literal(column, row[column]) for column in COLUMNS if column != "review_status"]
        matches.append("review_status IN ('USER_APPROVED', 'verified')")
        matches.append("school_id=(SELECT id FROM school WHERE name=" + sql(row["school"]) + ")")
        lines.append(f"INSERT INTO score_guard SELECT IF(COUNT(*)=1,1,0) FROM `{TABLE}` WHERE " + " AND ".join(matches) + ";")
    for entry in dataset["newSchools"]:
        lines.append("INSERT INTO score_guard SELECT IF(COUNT(*)=1,1,0) FROM school WHERE name=" + sql(entry["name"]) + ";")
    if failure:
        lines.append("INSERT INTO score_guard VALUES(0);")
    lines += ["ROLLBACK;" if rollback else "COMMIT;", f"SELECT RELEASE_LOCK('{LOCK_NAME}');"]
    return "\n".join(lines) + "\n"


def verify(db: object, dataset: dict[str, object], before: dict[str, list[str]],
           original_schools: list[dict[str, object]]) -> dict[str, object]:
    """Read every target row back and hash all unrelated tables."""
    after = db.snapshot()
    for table, fingerprints in before.items():
        if table not in ("school", TABLE):
            require(after[table] == fingerprints, "非目标表摘要发生变化：" + table)
    plan = inspect(db, dataset)
    require(plan["statisticsToInsert"] == 0 and plan["schoolsToInsert"] == 0, "导入回读不完整")
    saved = {row["id"]: row for row in db.records("school")}
    require(all(saved.get(row["id"]) == row for row in original_schools), "原有院校记录被修改")
    added = [row for key, row in saved.items() if key not in {r["id"] for r in original_schools}]
    provinces = {entry["name"]: entry["province"] for entry in dataset["newSchools"]}
    require(all(provinces.get(row["name"]) == row["province"] and row["level"] is None for row in added),
            "新增院校字段不符")
    return {"statisticsReadBack": len(dataset["observations"]), "schoolsAdded": len(added),
            "originalSchoolsUnchanged": True, "nonTargetTableHashesUnchanged": True}


def rehearse(db: object, dataset: dict[str, object], output: Path) -> tuple[dict[str, object], dict]:
    """Backup, restore into an isolated database and exercise every guard there."""
    before = db.snapshot()
    backup = db.backup(output)
    require(before == db.snapshot(), "备份期间数据变化，停止")
    name = "kaoyan_realdata_verify_" + secrets.token_hex(6)
    db.query(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4;", server=True)
    clone = helper.Database(name)
    clone.query(backup.read_text(), timeout=180)
    require(clone.snapshot() == before, "完整备份恢复摘要不一致")
    ensure_schema(clone)
    baseline = clone.snapshot()
    original_schools = clone.records("school")
    inspect(clone, dataset)
    try:
        clone.query(statement(clone, dataset, baseline, failure=True), timeout=180)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("失败注入未触发")
    require(clone.snapshot() == baseline, "失败事务未回滚")
    clone.query(statement(clone, dataset, baseline, rollback=True), timeout=180)
    require(clone.snapshot() == baseline, "显式回滚改变数据")
    clone.query(statement(clone, dataset, baseline), timeout=180)
    validation = verify(clone, dataset, baseline, original_schools)
    once = clone.snapshot()
    clone.query(statement(clone, dataset, once), timeout=180)
    require(clone.snapshot() == once, "重复执行并非幂等")
    first = clone.records(TABLE)[0]
    clone.query(f"UPDATE `{TABLE}` SET median_score=median_score+1 WHERE id={int(first['id'])};")
    try:
        inspect(clone, dataset)
    except RuntimeError as error:
        require("禁止覆盖" in str(error), "人工修订拒绝原因不符")
    else:
        raise RuntimeError("人工修订未被保护")
    clone.query(f"UPDATE `{TABLE}` SET median_score=median_score-1 WHERE id={int(first['id'])};")
    require(clone.snapshot() == once, "隔离人工修订夹具未恢复")
    report = {"restoreDatabase": name, "backup": str(backup), "backupRestoredTables": len(before),
              "failureRollbackVerified": True, "explicitRollbackVerified": True, "repeatUnchanged": True,
              "manualRevisionProtected": True, "validation": validation,
              "migrationSha256": hashlib.sha256(MIGRATION.read_bytes()).hexdigest()}
    return report, before


def run(dataset: dict[str, object], apply: bool) -> dict[str, object]:
    """Rehearse in isolation and optionally apply the same guarded transaction."""
    db = helper.Database()
    preview = inspect(db, dataset)
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    with (PRIVATE / "operation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = PRIVATE / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output.mkdir(mode=0o700)
        report, before = rehearse(db, dataset, output)
        report.update(applied=False, preview=preview)
        if apply:
            require(db.snapshot() == before, "预演期间日常数据变化，停止写入")
            inspect(db, dataset)
            ensure_schema(db)
            baseline = db.snapshot()
            original_schools = db.records("school")
            db.query(statement(db, dataset, baseline), timeout=180)
            report["validation"] = verify(db, dataset, baseline, original_schools)
            report["applied"] = True
        helper.dump(output / "report.json", report)
        report["reportPath"] = str(output / "report.json")
        return report


def main() -> None:
    """Expose explicit preview, rehearsal and checksum-bound apply modes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "outputs/school-scores-20261118/dataset.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rehearse", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    if args.apply and args.expected_sha != dataset["datasetSha256"]:
        parser.error("--apply必须提供已审阅清单的完整--expected-sha")
    result = run(dataset, args.apply) if args.rehearse or args.apply else inspect(helper.Database(), dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
