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


# ──────────────────────────────────────────────────────────
# TelemetryRanker — post-1.0 (fast-follow)
#
# Data-driven ranker that queries TelemetryStore for historical
# fail_rate, latency, and cost data.  The contract is defined here
# so the Routing domain knows a model ranker may carry telemetry
# awareness, but the implementation lives post-1.0.
# ──────────────────────────────────────────────────────────
