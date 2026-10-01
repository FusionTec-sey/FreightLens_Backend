from collections.abc import Iterable

from reporting.catalog.definitions import DatasetDef
from reporting.policy import AccessPolicy


class ReportingCatalog:
    def __init__(self) -> None:
        self._datasets: dict[str, DatasetDef] = {}

    def register(self, dataset: DatasetDef) -> DatasetDef:
        if dataset.key in self._datasets:
            raise ValueError(f"Dataset '{dataset.key}' is already registered")
        self._datasets[dataset.key] = dataset
        return dataset

    def get(self, key: str) -> DatasetDef:
        try:
            return self._datasets[key]
        except KeyError as exc:
            raise KeyError(f"Unknown reporting dataset '{key}'") from exc

    def visible_to(self, policy: AccessPolicy) -> Iterable[DatasetDef]:
        return tuple(
            dataset
            for dataset in self._datasets.values()
            if dataset.module in policy.module_names and policy.has(dataset.permission)
        )
