"""Background adapter for the existing intake and daily workflow."""

import logging
import threading
import uuid

from fastapi import HTTPException

from .field_store import now

LOG = logging.getLogger("portable.field")


class FieldWorkflow:
    def __init__(self, app, store, intake, daily):
        self.app, self.store, self.intake, self.daily = app, store, intake, daily

    def start(self, action, operation, analysis_id=None, filename=""):
        with self.app.state.lock:
            if self.app.state.closing or self.app.state.active:
                raise HTTPException(409, "別の処理を実行中です。しばらくしてから確認してください")
            self.app.state.active += 1
        job = {
            "id": str(uuid.uuid4()),
            "action": action,
            "status": "RUNNING",
            "analysis_id": analysis_id,
            "filename": filename[:200],
            "created_at": now(),
            "message": "ファイルを分析しています"
            if action == "UPLOAD"
            else "在庫確認・予測を実行しています",
        }
        try:
            self.store.put_job(job)
            thread = threading.Thread(
                target=self._execute, args=(dict(job), operation), daemon=True
            )
            thread.start()
        except Exception:
            with self.app.state.lock:
                self.app.state.active -= 1
            raise
        return job

    def _execute(self, job, operation):
        try:
            value = operation()
            job.update(
                status="SUCCEEDED", analysis_id=value["analysis_id"], message="処理が完了しました"
            )
        except ValueError as exc:
            job.update(status="FAILED", message=str(exc))
        except Exception:
            LOG.exception("field_job_failed job=%s", job["id"])
            job.update(
                status="FAILED",
                message="処理を完了できませんでした。保存済みの分析を開いて再確認してください（FIELD-001）",
            )
        finally:
            try:
                self.store.put_job(job | {"finished_at": now()})
            finally:
                with self.app.state.lock:
                    self.app.state.active -= 1
