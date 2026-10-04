from __future__ import annotations

from collections.abc import Mapping

from pharma_proto.knowledge import RangeStats, UsageEvidence


class FakeKnowledge:
    def __init__(
        self,
        *,
        doses: Mapping[str, list[float]] | None = None,
        ranges: Mapping[str, RangeStats] | None = None,
        functions: Mapping[str, str] | None = None,
        function_ranges: Mapping[str, RangeStats] | None = None,
        usage: Mapping[tuple[str, str], UsageEvidence] | None = None,
    ) -> None:
        self._doses = dict(
            {"rabeprazole": [20.0, 40.0]} if doses is None else doses
        )
        self._ranges = dict({} if ranges is None else ranges)
        self._functions = dict(
            {
                "povidone": "binder",
                "mannitol": "diluent",
            }
            if functions is None
            else functions
        )
        self._function_ranges = dict({} if function_ranges is None else function_ranges)
        self._usage = dict({} if usage is None else usage)

    def api_doses(self, name: str, *, mode: str | None = None) -> list[float]:
        return list(self._doses.get(name, []))

    def pct_range(self, ingredient: str, *, mode: str | None = None) -> RangeStats:
        return self._ranges.get(
            ingredient,
            RangeStats(n=10, lo=2, hi=6, mean=4, p5=2, p95=6, median=4),
        )

    def function(self, ingredient: str) -> str | None:
        return self._functions.get(ingredient)

    def function_pct_range(self, function: str) -> RangeStats:
        return self._function_ranges.get(
            function,
            RangeStats(n=10, p5=1, p95=10, median=4),
        )

    def compatibility_usage(self, api: str, excipient: str) -> UsageEvidence:
        return self._usage.get(
            (api, excipient),
            UsageEvidence(count=2, source_types=("patent",)),
        )

    def health(self) -> Mapping[str, object]:
        return {"status": "ok"}

    def close(self) -> None:
        pass
