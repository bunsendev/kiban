"""日次buildの確認画面向け読み取り処理。"""

from .contracts import DailyBuildJob, DailyValue
from .records import daily_value_from_row, job_from_row

DAILY_STATES = frozenset(
    {"OBSERVED", "CONFIRMED_ZERO", "MISSING", "NOT_HANDLED", "CLOSED", "PARTIAL_OR_INVALID"}
)


class ReadinessStoreMixin:
    """SQLite/PostgreSQLで共用する日次buildの検索・集計。"""

    def list_jobs(self) -> list[DailyBuildJob]:
        with self._connect() as db:
            return [
                job_from_row(row)
                for row in db.execute(
                    "SELECT * FROM daily_build_jobs ORDER BY created_at DESC,build_id"
                )
            ]

    def readiness_summary(self, build_id: str) -> dict:
        with self._connect() as db:
            completeness = {
                row["status"]: int(row["count"])
                for row in db.execute(
                    "SELECT status,COUNT(*) AS count FROM daily_file_completeness "
                    "WHERE build_id=? GROUP BY status ORDER BY status",
                    (build_id,),
                )
            }
            states = {
                row["state"]: int(row["count"])
                for row in db.execute(
                    "SELECT state,COUNT(*) AS count FROM daily_values "
                    "WHERE build_id=? GROUP BY state ORDER BY state",
                    (build_id,),
                )
            }
            issues = [
                {"state": row["state"], "issue": row["issue"], "count": int(row["count"])}
                for row in db.execute(
                    "SELECT state,issue,COUNT(*) AS count FROM daily_values "
                    "WHERE build_id=? AND issue IS NOT NULL "
                    "GROUP BY state,issue ORDER BY count DESC,state,issue",
                    (build_id,),
                )
            ]
        return {
            "build_id": build_id,
            "completeness_counts": completeness,
            "state_counts": states,
            "issue_counts": issues,
            "value_count": sum(states.values()),
        }

    def list_values_page(
        self,
        build_id: str,
        *,
        state: str | None = None,
        canonical_product_id: str | None = None,
        center_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[int, list[DailyValue]]:
        if state is not None and state not in DAILY_STATES:
            raise ValueError("daily stateが不正です")
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("page範囲が不正です")
        conditions = ["build_id=?"]
        params: list[object] = [build_id]
        for column, value in (
            ("state", state),
            ("canonical_product_id", canonical_product_id),
            ("center_id", center_id),
        ):
            if value:
                conditions.append(f"{column}=?")
                params.append(value)
        where = " AND ".join(conditions)
        with self._connect() as db:
            total = int(
                db.execute(
                    f"SELECT COUNT(*) AS count FROM daily_values WHERE {where}", params
                ).fetchone()["count"]
            )
            rows = db.execute(
                f"SELECT * FROM daily_values WHERE {where} "
                "ORDER BY ds,canonical_product_id,center_id,unique_id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
            return total, [daily_value_from_row(row) for row in rows]
