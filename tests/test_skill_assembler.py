"""Tests for SkillAssembler — the explicit fallback boundary."""

from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.skills.assembler import SkillAssembler
from aios.skills.discovery import ScoredSkill
from aios.skills.metadata import SkillMetadata
from aios.skills.retrieval import SkillContext


def _make_context():
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root="/tmp/test", name="test")
    ctx.tools = ToolsInfo()
    return ctx


def _make_skill(name: str, triggers: list[str] | None = None) -> SkillMetadata:
    return SkillMetadata(name=name, description=f"Skill {name}", triggers=triggers or []).validate()


def _make_scored(name: str, score: float = 0.8) -> ScoredSkill:
    return ScoredSkill(
        skill=_make_skill(name),
        score=score,
        trigger_matches=[],
        scope_matches=[],
        priority_score=0.0,
    )


class FailingDiscovery:
    def __init__(self, should_fail: bool = True) -> None:
        self.should_fail = should_fail

    def discover(self, intent, context=None):
        if self.should_fail:
            raise RuntimeError("discovery failed")
        return []


class EmptyDiscovery:
    def discover(self, intent, context=None):
        return []


class SuccessDiscovery:
    def discover(self, intent, context=None):
        return [_make_scored("test-skill", 0.8)]


class FailingRetrieval:
    def __init__(self, should_fail: bool = True) -> None:
        self.should_fail = should_fail

    def retrieve(self, scored, intent, *, agent, max_chunks_per_skill=2):
        if self.should_fail:
            raise RuntimeError("retrieval failed")
        return []


class EmptyRetrieval:
    def retrieve(self, scored, intent, *, agent, max_chunks_per_skill=2):
        return []


class SuccessRetrieval:
    def retrieve(self, scored, intent, *, agent, max_chunks_per_skill=2):
        ctx = SkillContext(
            skill=scored[0],
            chunks=[],
            prompt_section="## Skills\ntest",
            tokens_used=10,
            relevance_score=0.8,
        )
        return [ctx]


class TestAssemblerFallbackBoundary:
    def test_discovery_raises_returns_empty(self):
        assembler = SkillAssembler(
            discovery=FailingDiscovery(should_fail=True),
            retrieval=SuccessRetrieval(),
        )
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert result == []

    def test_discovery_returns_empty_returns_empty(self):
        assembler = SkillAssembler(
            discovery=EmptyDiscovery(),
            retrieval=SuccessRetrieval(),
        )
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert result == []

    def test_retrieval_raises_returns_empty(self):
        assembler = SkillAssembler(
            discovery=SuccessDiscovery(),
            retrieval=FailingRetrieval(should_fail=True),
        )
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert result == []

    def test_retrieval_returns_empty_returns_empty(self):
        assembler = SkillAssembler(
            discovery=SuccessDiscovery(),
            retrieval=EmptyRetrieval(),
        )
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert result == []

    def test_full_success_returns_contexts(self):
        assembler = SkillAssembler(
            discovery=SuccessDiscovery(),
            retrieval=SuccessRetrieval(),
        )
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert len(result) == 1
        assert result[0].skill.skill.name == "test-skill"
        assert result[0].relevance_score == 0.8
        assert result[0].prompt_section == "## Skills\ntest"


class TestAssemblerWithOptionalComponents:
    def test_assembler_without_retrieval_returns_empty(self):
        assembler = SkillAssembler(
            discovery=SuccessDiscovery(),
            retrieval=None,
        )
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert result == []

    def test_assembler_default_fields(self):
        assembler = SkillAssembler()
        result = assembler.assemble("test", _make_context(), agent="planner")
        assert result == []
