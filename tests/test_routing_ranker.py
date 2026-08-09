"""Tests for pluggable model rankers."""

from aios.routing.ranker import HeuristicRanker


class TestHeuristicRanker:
    def test_scores_by_agent_match(self):
        ranker = HeuristicRanker()
        candidates = [
            {"rule_ref": "0", "agent": "planner", "complexity": "medium", "estimated_cost": 0.0},
            {"rule_ref": "1", "agent": "developer", "complexity": "medium", "estimated_cost": 0.0},
        ]
        results = ranker.score("planner", candidates)
        assert results[0][0] == "0"
        assert results[0][1] > results[1][1]

    def test_scores_by_complexity(self):
        ranker = HeuristicRanker()
        candidates = [
            {"rule_ref": "0", "agent": "planner", "complexity": "low", "estimated_cost": 0.0},
            {"rule_ref": "1", "agent": "planner", "complexity": "high", "estimated_cost": 0.0},
        ]
        results = ranker.score("planner", candidates)
        assert results[0][0] == "1"
        assert results[0][1] > results[1][1]

    def test_scores_by_cost(self):
        ranker = HeuristicRanker()
        candidates = [
            {"rule_ref": "0", "agent": "planner", "complexity": "medium", "estimated_cost": 5.0},
            {"rule_ref": "1", "agent": "planner", "complexity": "medium", "estimated_cost": 0.0},
        ]
        results = ranker.score("planner", candidates)
        assert results[0][0] == "1"
        assert results[0][1] > results[1][1]

    def test_empty_candidates(self):
        ranker = HeuristicRanker()
        assert ranker.score("planner", []) == []

    def test_default_complexity_score(self):
        ranker = HeuristicRanker()
        score = round(
            ranker.weight_agent * 1.0 + ranker.weight_complexity * 0.5 + ranker.weight_cost * 1.0, 4
        )
        results = ranker.score(
            "planner", [{"rule_ref": "", "agent": "planner", "complexity": "unknown"}]
        )
        assert results[0][1] == score


# TelemetryRanker tests removed (post-1.0 fast-follow).
# HeuristicRanker remains the only stable, deterministic ranker for v1.0.
