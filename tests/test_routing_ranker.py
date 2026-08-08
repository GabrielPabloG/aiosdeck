"""Tests for pluggable model rankers."""

from aios.routing.ranker import HeuristicRanker, TelemetryRanker


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


class TestTelemetryRanker:
    def test_falls_back_to_heuristic_without_telemetry(self):
        ranker = TelemetryRanker()
        candidates = [
            {"rule_ref": "0", "agent": "planner", "complexity": "high", "estimated_cost": 0.0},
            {"rule_ref": "1", "agent": "developer", "complexity": "medium", "estimated_cost": 0.0},
        ]
        results = ranker.score("planner", candidates)
        assert results[0][0] == "0"

    def test_with_mock_telemetry(self):
        class FakeStore:
            def is_open(self):
                return True

        class FakeTelemetry:
            _store = FakeStore()

        ranker = TelemetryRanker()
        candidates = [
            {"rule_ref": "0", "agent": "planner", "model": "gpt-4o", "provider": "openai"}
        ]
        results = ranker.score("planner", candidates, telemetry=FakeTelemetry())
        assert len(results) == 1
        assert isinstance(results[0][1], float)

    def test_telemetry_without_store(self):
        class FakeTelemetry:
            pass

        ranker = TelemetryRanker()
        candidates = [{"rule_ref": "0", "agent": "planner"}]
        results = ranker.score("planner", candidates, telemetry=FakeTelemetry())
        assert len(results) == 1
