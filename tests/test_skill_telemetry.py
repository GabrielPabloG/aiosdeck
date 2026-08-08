"""Tests for skill telemetry — recording and querying lifecycle signals."""

from aios.knowledge.models import KnowledgeResult
from aios.retrieval.retrievers import ScoredResult
from aios.skills.discovery import ScoredSkill
from aios.skills.metadata import SkillMetadata
from aios.skills.retrieval import SkillContext
from aios.skills.telemetry import SkillUsageRecorder
from aios.telemetry.engine import TelemetryEngine


def _make_skill(name: str, score: float = 0.8) -> SkillMetadata:
    return SkillMetadata(
        name=name, description=f"Skill {name}", triggers=["test"], priority=5
    ).validate()


def _make_scored(name: str, score: float = 0.8) -> ScoredSkill:
    return ScoredSkill(
        skill=_make_skill(name, score),
        score=score,
        trigger_matches=["test"],
        scope_matches=[],
        priority_score=0.5,
    )


def _make_context(scored: ScoredSkill, tokens: int = 100) -> SkillContext:
    r = KnowledgeResult()
    r.content = "content"
    r.source_type = "skill"
    r.source_path = f".opencode/skills/{scored.skill.name}/SKILL.md"
    r.token_estimate = tokens
    sr = ScoredResult(result=r, score=0.8)
    return SkillContext(
        skill=scored,
        chunks=[sr],
        prompt_section="## Skills\ntest",
        tokens_used=tokens,
        relevance_score=scored.score,
    )


class TestSkillUsageRecorder:
    def test_recorder_is_noop_without_telemetry(self):
        recorder = SkillUsageRecorder(telemetry=None)
        scorer = _make_scored("test-skill")
        recorder.record_pipeline([], [scorer], intent="test", agent="planner")
        # should not raise

    def test_record_pipeline_single_skill(self, tmp_path):
        db = tmp_path / "test.db"
        engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
        engine.initialize()

        recorder = SkillUsageRecorder(
            telemetry=engine,
            execution_id="exec-001",
            correlation_id="corr-001",
        )

        scored = _make_scored("test-skill", 0.85)
        contexts = [_make_context(scored, tokens=120)]
        recorder.record_pipeline(contexts, [scored], intent="build a dashboard", agent="planner")

        stats = engine.query_skill_stats(skill="test-skill")
        assert len(stats) == 1
        assert stats[0]["total_records"] == 1
        assert stats[0]["total_considered"] == 1
        assert stats[0]["total_selected"] == 1
        assert stats[0]["total_used"] == 1
        assert stats[0]["total_tokens"] == 120
        assert stats[0]["avg_relevance"] is not None

        engine.shutdown()

    def test_multiple_skills_some_not_used(self, tmp_path):
        db = tmp_path / "test.db"
        engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
        engine.initialize()

        recorder = SkillUsageRecorder(telemetry=engine)

        s1 = _make_scored("skill-a", 0.9)
        s2 = _make_scored("skill-b", 0.6)
        considered = [s1, s2]
        used = [_make_context(s1, 50)]

        recorder.record_pipeline(used, considered, intent="test", agent="planner")

        stats = engine.query_skill_stats()
        assert len(stats) == 2

        a_stat = next(s for s in stats if s["skill_name"] == "skill-a")
        assert a_stat["total_considered"] == 1
        assert a_stat["total_selected"] == 1
        assert a_stat["total_used"] == 1
        assert a_stat["total_tokens"] == 50

        b_stat = next(s for s in stats if s["skill_name"] == "skill-b")
        assert b_stat["total_considered"] == 1
        assert b_stat["total_selected"] == 1
        assert b_stat["total_used"] == 0

        engine.shutdown()

    def test_stats_empty_without_data(self, tmp_path):
        db = tmp_path / "test.db"
        engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
        engine.initialize()

        stats = engine.query_skill_stats()
        assert stats == []

        engine.shutdown()

    def test_recorder_works_without_execution_id(self, tmp_path):
        db = tmp_path / "test.db"
        engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
        engine.initialize()

        recorder = SkillUsageRecorder(telemetry=engine)
        scored = _make_scored("s", 0.7)
        recorder.record_pipeline([_make_context(scored, 30)], [scored], intent="x", agent="planner")

        stats = engine.query_skill_stats(skill="s")
        assert stats[0]["total_used"] == 1
        assert stats[0]["total_tokens"] == 30

        engine.shutdown()

    def test_empty_considered_no_records(self, tmp_path):
        db = tmp_path / "test.db"
        engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
        engine.initialize()

        recorder = SkillUsageRecorder(telemetry=engine)
        recorder.record_pipeline([], [], intent="test", agent="planner")

        stats = engine.query_skill_stats()
        assert stats == []

        engine.shutdown()
