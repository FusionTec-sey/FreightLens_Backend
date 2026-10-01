from datetime import datetime, timezone
from types import SimpleNamespace

from Model.containermgmt.Report.ReportRenderJob import ReportRenderJob
from reporting.worker import ReportRenderWorker


class _Query:
    def __init__(self, job):
        self.job = job

    def filter(self, *criteria):
        return self

    def order_by(self, *criteria):
        return self

    def with_for_update(self, **kwargs):
        assert kwargs == {"skip_locked": True}
        return self

    def first(self):
        return self.job


class _Db:
    def __init__(self, job):
        self.job = job
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        assert model is ReportRenderJob
        return _Query(self.job)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, job):
        assert job is self.job


def test_claim_sets_worker_lease_and_attempt_atomically():
    job = SimpleNamespace(
        status="PENDING",
        worker_id=None,
        started_at=None,
        heartbeat_at=None,
        lease_expires_at=None,
        retry_at=None,
        attempt_count=0,
        error_message="old error",
    )
    db = _Db(job)

    claimed = ReportRenderWorker(worker_id="worker-test", lease_seconds=90).claim_next(db)

    assert claimed is job
    assert job.status == "RENDERING"
    assert job.worker_id == "worker-test"
    assert job.attempt_count == 1
    assert job.error_message is None
    assert job.lease_expires_at > datetime.now(timezone.utc)
    assert db.committed


def test_empty_claim_releases_transaction():
    db = _Db(None)

    assert ReportRenderWorker(worker_id="worker-test").claim_next(db) is None
    assert db.rolled_back


def test_render_job_model_contains_retry_and_snapshot_contract():
    columns = ReportRenderJob.__table__.c
    assert {"data_snapshot", "output_sha256", "attempt_count", "max_attempts"}.issubset(columns.keys())
    assert {"worker_id", "lease_expires_at", "retry_at"}.issubset(columns.keys())
