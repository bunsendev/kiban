"""Keep immutable application files separate from operator data."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def input(self) -> Path:
        return self.root / "Input"

    @property
    def results(self) -> Path:
        return self.root / "Results"

    @property
    def state(self) -> Path:
        return self.root / "State"

    @property
    def logs(self) -> Path:
        return self.root / "Logs"

    @property
    def analysis(self) -> Path:
        return self.root / "Analysis"

    @property
    def prepared(self) -> Path:
        return self.root / "Prepared"

    @property
    def decisions(self) -> Path:
        return self.root / "Decisions"

    @property
    def formal_inventory(self) -> Path:
        return self.root / "FormalInventory"

    @property
    def formal_forecast(self) -> Path:
        return self.root / "FormalForecast"

    def ensure(self) -> None:
        for path in (
            self.input,
            self.results,
            self.state,
            self.logs,
            self.analysis,
            self.prepared,
            self.decisions,
            self.formal_inventory,
            self.formal_forecast,
        ):
            path.mkdir(parents=True, exist_ok=True)
        probe = self.state / ".write-test"
        probe.write_bytes(b"ok")
        probe.unlink()
