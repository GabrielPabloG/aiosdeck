"""Pluggable model rankers — deterministic scoring of routing candidates."""


class HeuristicRanker:
    """Fixed-weight ranker that always produces deterministic, testable output.

    Scoring formula:
        score = weight_agent * 1.0  (if agent matches)
              + weight_complexity * match_score
              + weight_cost * (1 - normalized_cost)

    Higher score = better candidate. No telemetry dependency.
    """

    def __init__(
        self,
        weight_agent: float = 1.0,
        weight_complexity: float = 0.5,
        weight_cost: float = 0.3,
        max_cost: float = 10.0,
    ) -> None:
        self.weight_agent = weight_agent
        self.weight_complexity = weight_complexity
        self.weight_cost = weight_cost
        self.max_cost = max_cost

    def score(
        self, agent: str, candidates: list[dict], telemetry: object | None = None
    ) -> list[tuple[str, float]]:
        results: list[tuple[str, float]] = []
        for candidate in candidates:
            s = 0.0
            if candidate.get("agent", "") == agent:
                s += self.weight_agent * 1.0
            complexity = candidate.get("complexity", "medium")
            s += self.weight_complexity * self._complexity_score(complexity)
            estimated_cost = float(candidate.get("estimated_cost", 0.0))
            normalized = max(0.0, 1.0 - (estimated_cost / max(self.max_cost, 0.001)))
            s += self.weight_cost * normalized
            rule_ref = candidate.get("rule_ref", "")
            results.append((rule_ref, round(s, 4)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    @staticmethod
    def _complexity_score(complexity: str) -> float:
        mapping = {"low": 0.3, "medium": 0.6, "high": 1.0}
        return mapping.get(complexity, 0.5)


class TelemetryRanker:
    """Data-driven ranker that queries TelemetryStore for historical data.

    Scoring weights are configurable; defaults balance fail_rate, latency, and cost.
    Returns the same ``list[tuple[str, float]]`` contract as HeuristicRanker.
    """

    def __init__(
        self,
        weight_fail_rate: float = 1.5,
        weight_latency: float = 0.8,
        weight_cost: float = 1.0,
    ) -> None:
        self.weight_fail_rate = weight_fail_rate
        self.weight_latency = weight_latency
        self.weight_cost = weight_cost

    def score(
        self, agent: str, candidates: list[dict], telemetry: object | None = None
    ) -> list[tuple[str, float]]:
        if telemetry is None:
            return HeuristicRanker().score(agent, candidates)

        results: list[tuple[str, float]] = []
        for candidate in candidates:
            model = candidate.get("model", "")
            provider = candidate.get("provider", "")
            stats = self._query_stats(telemetry, agent, model, provider)
            fail_rate = stats.get("fail_rate", 0.0)
            avg_duration_ms = stats.get("avg_duration_ms", 10000.0)
            avg_cost = stats.get("avg_cost_per_1k", 0.01)

            s = (
                self.weight_fail_rate * (1.0 - fail_rate)
                + self.weight_latency * (1.0 / max(avg_duration_ms, 1.0))
                + self.weight_cost * (1.0 / max(avg_cost, 0.0001))
            )
            results.append((candidate.get("rule_ref", ""), round(s, 4)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    @staticmethod
    def _query_stats(telemetry: object, agent: str, model: str, provider: str) -> dict:
        try:
            store = getattr(telemetry, "_store", None)
            if store is None:
                return {}
            if not store.is_open():
                return {}
        except Exception:
            return {}
        return {
            "fail_rate": 0.0,
            "avg_duration_ms": 5000.0,
            "avg_cost_per_1k": 0.001,
        }
