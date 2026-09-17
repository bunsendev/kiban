"""保存済み実験から適合試験jobを登録するアプリケーションサービス。"""

from .contracts import ConformanceJobStore


class ConformanceJobNotFound(KeyError):
    pass


class ConformanceJobService:
    def __init__(self, catalog, jobs: ConformanceJobStore) -> None:
        self.catalog = catalog
        self.jobs = jobs

    def enqueue(self, experiment_id: str, requested_by: str):
        experiment = self.catalog.get_experiment(experiment_id)
        if experiment is None:
            raise ConformanceJobNotFound(experiment_id)
        definition = experiment.definition
        return self.jobs.enqueue(
            experiment_id,
            definition["provider_id"],
            definition["model_name"],
            requested_by,
        )

    def get(self, job_id: str):
        value = self.jobs.get_job(job_id)
        if value is None:
            raise ConformanceJobNotFound(job_id)
        return value

    def list(self, experiment_id: str | None = None):
        if experiment_id is not None and self.catalog.get_experiment(experiment_id) is None:
            raise ConformanceJobNotFound(experiment_id)
        return self.jobs.list_jobs(experiment_id)
