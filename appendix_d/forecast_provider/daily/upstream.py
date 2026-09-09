"""日次buildが参照する採用済み上流版を検証・読出しする。"""

import json

from .contracts import DailyBuildJob


def source_inputs(store, job: DailyBuildJob) -> list[dict]:
    validate_job_inputs(store, job)
    results = []
    with store._connect() as db:
        for normalization_id in job.definition["normalization_ids"]:
            metadata = db.execute(
                "SELECT n.status,n.source_file_id,s.logical_path,s.created_at AS source_created_at,"
                "m.definition_json "
                "FROM normalization_jobs n JOIN source_files s "
                "ON s.source_file_id=n.source_file_id JOIN column_mappings m "
                "ON m.mapping_id=n.mapping_id WHERE n.normalization_id=?",
                (normalization_id,),
            ).fetchone()
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT center_id,shipment_date,raw_jan,quantity,available_at,status,error "
                    "FROM shipment_rows WHERE normalization_id=? "
                    "ORDER BY row_number",
                    (normalization_id,),
                )
            ]
            results.append(
                {
                    "normalization_id": normalization_id,
                    "source_file_id": metadata["source_file_id"],
                    "logical_path": metadata["logical_path"],
                    "status": metadata["status"],
                    "source_created_at": metadata["source_created_at"],
                    "mapping": json.loads(metadata["definition_json"]),
                    "rows": rows,
                }
            )
    return results


def validate_job_inputs(store, job: DailyBuildJob) -> None:
    schedule = store.get_schedule(job.definition["schedule_id"])
    if schedule is None:
        raise ValueError("予定ファイル定義が見つかりません")
    if (
        schedule.definition["valid_from"] > job.definition["train_start"]
        or schedule.definition["valid_to"] < job.definition["test_end"]
    ):
        raise ValueError("予定ファイル定義がdataset期間全体を覆っていません")
    planned = {item["logical_path"] for item in schedule.definition["files"]}
    schedule_centers = {item["center_id"] for item in schedule.definition["files"]}
    selected_centers = {item["center_id"] for item in job.definition["selected_series"]}
    if not selected_centers <= schedule_centers:
        raise ValueError("選定centerが予定ファイル定義にありません")
    seen_paths = set()
    with store._connect() as db:
        for normalization_id in job.definition["normalization_ids"]:
            row = db.execute(
                "SELECT n.status,n.source_file_id,s.status AS source_status,s.logical_path,"
                "m.definition_json FROM normalization_jobs n JOIN source_files s "
                "ON s.source_file_id=n.source_file_id JOIN column_mappings m "
                "ON m.mapping_id=n.mapping_id WHERE n.normalization_id=?",
                (normalization_id,),
            ).fetchone()
            if row is None or row["status"] != "SUCCEEDED":
                raise ValueError("成功済みnormalizationだけを指定できます")
            latest = db.execute(
                "SELECT source_file_id FROM source_file_selections WHERE logical_path=? "
                "ORDER BY decided_at DESC,selection_id DESC LIMIT 1",
                (row["logical_path"],),
            ).fetchone()
            current = (
                row["source_status"] == "ACCEPTED"
                if latest is None
                else latest[0] == row["source_file_id"]
            )
            if not current:
                raise ValueError("現在採用中ではない原本のnormalizationです")
            if row["logical_path"] not in planned:
                raise ValueError("normalizationのlogical pathが予定にありません")
            if row["logical_path"] in seen_paths:
                raise ValueError("同じlogical pathのnormalizationは1件だけ指定します")
            seen_paths.add(row["logical_path"])
            mapping = json.loads(row["definition_json"])
            if mapping["availability_mode"] != job.definition["availability_mode"]:
                raise ValueError("availability modeが上流mappingと一致しません")
        mappings = db.execute(
            "SELECT COUNT(*) FROM jan_mappings WHERE mapping_version=?",
            (job.definition["mapping_version"],),
        ).fetchone()[0]
        if mappings == 0:
            raise ValueError("JAN mapping versionが見つかりません")
        closure_version = job.definition["closure_version"]
        if closure_version is not None:
            closures = db.execute(
                "SELECT COUNT(*) FROM closed_days WHERE closure_version=?",
                (closure_version,),
            ).fetchone()[0]
            if closures == 0:
                raise ValueError("closure versionが見つかりません")
        periods = {
            (row[0], row[1])
            for row in db.execute(
                "SELECT canonical_product_id,center_id FROM handling_periods "
                "WHERE period_version=?",
                (job.definition["period_version"],),
            )
        }
    selected = {
        (item["canonical_product_id"], item["center_id"])
        for item in job.definition["selected_series"]
    }
    if not selected <= periods:
        raise ValueError("選定系列の取扱期間が指定versionにありません")
