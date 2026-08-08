"""Tests for SkillDiscoveryService — deterministic ranking by intent + context."""

from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.skills.discovery import ScoredSkill, SkillDiscoveryService
from aios.skills.metadata import SkillMetadata
from aios.skills.registry import SkillRegistry


def _make_skill(
    name: str,
    description: str = "Test skill",
    triggers: list[str] | None = None,
    scope: list[str] | None = None,
    priority: int = 0,
) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=description,
        triggers=triggers or [],
        scope=scope or [],
        priority=priority,
    ).validate()


def _make_context(language: str = "python") -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language=language, root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    return ctx


class TestScoredSkill:
    def test_explainable_fields(self):
        skill = _make_skill(
            "test", triggers=["react", "dashboard"], scope=["javascript"], priority=7
        )
        scored = ScoredSkill(
            skill=skill,
            score=0.72,
            trigger_matches=["react", "dashboard"],
            scope_matches=["javascript"],
            priority_score=0.7,
        )
        assert scored.trigger_matches == ["react", "dashboard"]
        assert scored.scope_matches == ["javascript"]
        assert scored.priority_score == 0.7
        assert 0.0 <= scored.score <= 1.0


class TestDiscoveryRanking:
    def make_service(self, skills: list[SkillMetadata], **kwargs) -> SkillDiscoveryService:
        registry = SkillRegistry("/tmp")
        registry._skills = {s.name: s for s in skills}
        return SkillDiscoveryService(registry, **kwargs)

    def test_discover_with_trigger_matches(self):
        skills = [
            _make_skill("react-ui", triggers=["react", "frontend"], priority=5),
            _make_skill("python-backend", triggers=["python", "api"], priority=5),
            _make_skill("docker-deploy", triggers=["docker", "deploy"], priority=5),
        ]
        service = self.make_service(skills)
        context = _make_context("javascript")
        result = service.discover("build a react dashboard", context)

        assert len(result) > 0
        top = result[0]
        assert top.skill.name == "react-ui"
        assert "react" in top.trigger_matches
        assert top.score > 0.0

    def test_discover_scores_explainable(self):
        skills = [_make_skill("react-skill", triggers=["react", "component", "state"], priority=9)]
        service = self.make_service(skills, min_score=0.0)
        result = service.discover("build react components with state management", _make_context())
        assert len(result) == 1
        assert len(result[0].trigger_matches) > 0
        assert result[0].priority_score > 0
        assert result[0].score > 0

    def test_discover_respects_top_k(self):
        skills = [_make_skill(f"skill-{i}", triggers=["test"], priority=i) for i in range(10)]
        service = self.make_service(skills, top_k=3, min_score=0.0)
        result = service.discover("test", _make_context())
        assert len(result) == 3

    def test_discover_filters_by_min_score(self):
        skills = [
            _make_skill("high-relevance", triggers=["react", "frontend", "component"], priority=8),
            _make_skill("low-relevance", triggers=["backup"], priority=0),
        ]
        service = self.make_service(skills, min_score=0.3, top_k=5)
        result = service.discover("build a react dashboard", _make_context())
        assert len(result) == 1
        assert result[0].skill.name == "high-relevance"

    def test_discover_no_matches_returns_empty(self):
        skills = [_make_skill("only-python", triggers=["python"], priority=5)]
        service = self.make_service(skills)
        result = service.discover("deploy docker containers", _make_context())
        assert result == []

    def test_discover_empty_skills_returns_empty(self):
        service = self.make_service([])
        result = service.discover("anything", _make_context())
        assert result == []

    def test_discover_empty_intent(self):
        skills = [_make_skill("any", triggers=["test"])]
        service = self.make_service(skills, min_score=0.0)
        result = service.discover("", _make_context())
        assert result == []  # no trigger matches in empty intent

    def test_discover_sorted_by_score(self):
        skills = [
            _make_skill("low", triggers=["python"], priority=1),
            _make_skill("high", triggers=["python", "backend", "api"], priority=8),
            _make_skill("mid", triggers=["python", "backend"], priority=4),
        ]
        service = self.make_service(skills, min_score=0.0, top_k=5)
        result = service.discover("build a python backend api", _make_context())
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_discover_deterministic(self):
        skills = [
            _make_skill("a", triggers=["x"], priority=5),
            _make_skill("b", triggers=["x"], priority=5),
        ]
        service = self.make_service(skills, min_score=0.0, top_k=5)
        r1 = service.discover("x", _make_context())
        r2 = service.discover("x", _make_context())
        assert [s.skill.name for s in r1] == [s.skill.name for s in r2]


class TestDiscoveryScoreComponents:
    def make_service(self, skills: list[SkillMetadata], **kwargs) -> SkillDiscoveryService:
        registry = SkillRegistry("/tmp")
        registry._skills = {s.name: s for s in skills}
        return SkillDiscoveryService(registry, **kwargs)

    def test_trigger_score_full_match(self):
        skill = _make_skill("test", triggers=["react", "dashboard", "component"])
        service = self.make_service([skill], min_score=0.0, top_k=1)
        result = service.discover("build a react dashboard component", _make_context())
        assert len(result) == 1
        score = result[0]
        assert "react" in score.trigger_matches
        assert "dashboard" in score.trigger_matches
        assert "component" in score.trigger_matches
        assert len(score.trigger_matches) == 3

    def test_trigger_score_partial_match(self):
        skill = _make_skill("test", triggers=["react", "dashboard", "component", "state"])
        service = self.make_service([skill], min_score=0.0, top_k=1)
        result = service.discover("react component", _make_context())
        assert len(result) == 1
        assert len(result[0].trigger_matches) == 2  # react + component

    def test_scope_match(self):
        skill = _make_skill("test", triggers=["build"], scope=["python", "architecture"])
        service = self.make_service([skill], min_score=0.0, top_k=1)
        ctx = _make_context("python")
        ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
        result = service.discover("build something", ctx)
        assert len(result) == 1
        assert "python" in result[0].scope_matches

    def test_scope_no_match(self):
        skill = _make_skill("test", triggers=["build"], scope=["javascript"])
        service = self.make_service([skill], min_score=0.0, top_k=1)
        result = service.discover("build something", _make_context("python"))
        assert len(result) == 1
        assert result[0].scope_matches == []

    def test_no_scope_is_neutral(self):
        skill = _make_skill("test", triggers=["build"], scope=[])
        service = self.make_service([skill], min_score=0.0, top_k=1)
        result = service.discover("build something", _make_context("python"))
        assert len(result) == 1
        assert result[0].scope_matches == []
        assert result[0].score >= 0.5  # trigger full match + priority neutral

    def test_priority_score_range(self):
        for p in (0, 5, 10, 20):
            skill = _make_skill(f"p{p}", triggers=["test"], priority=p)
            service = self.make_service([skill], min_score=0.0, top_k=1)
            result = service.discover("test", _make_context())
            assert len(result) == 1
            assert 0.0 <= result[0].priority_score <= 1.0

    def test_scope_matches_context_tools(self):
        skill = _make_skill("test", triggers=["build"], scope=["ruff", "pytest"])
        service = self.make_service([skill], min_score=0.0, top_k=1)
        ctx = _make_context("python")
        ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
        result = service.discover("build something", ctx)
        assert len(result) == 1
        assert len(result[0].scope_matches) == 2
        assert "ruff" in result[0].scope_matches
        assert "pytest" in result[0].scope_matches
