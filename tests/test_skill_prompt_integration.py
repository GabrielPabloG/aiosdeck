"""Tests for PromptBuilder skill integration — smart section + golden path fallback."""

from aios.agents import Task
from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.knowledge.models import KnowledgeResult
from aios.prompts import PromptBuilder
from aios.retrieval.retrievers import ScoredResult
from aios.skills.discovery import ScoredSkill
from aios.skills.metadata import SkillMetadata
from aios.skills.retrieval import SkillContext


def _make_context():
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _make_skill_context(
    name: str, score: float = 0.82, content: str = "Chunk content"
) -> SkillContext:
    skill = SkillMetadata(
        name=name,
        description=f"Skill {name} for testing",
        triggers=["react"],
        scope=["javascript"],
        priority=8,
    ).validate()
    scored = ScoredSkill(
        skill=skill,
        score=score,
        trigger_matches=["react"],
        scope_matches=["javascript"],
        priority_score=0.8,
    )
    result = KnowledgeResult()
    result.content = content
    result.source_type = "skill"
    result.source_path = f".opencode/skills/{name}/SKILL.md"
    result.token_estimate = len(content.split())
    sr = ScoredResult(result=result, score=score)

    prompt = f"## Relevant Skills\n- **{name}** (score={score:.2f}) [triggers: react] [scope: javascript]\n  Skill {name} for testing\n\n{content}"
    return SkillContext(
        skill=scored,
        chunks=[sr],
        prompt_section=prompt,
        tokens_used=len(content.split()),
        relevance_score=score,
    )


class TestSmartSkillsSection:
    def test_smart_section_renders_skill_name_and_score(self):
        builder = PromptBuilder()
        ctx = _make_context()
        skill_ctx = _make_skill_context("react-ui", 0.85, "Use React hooks.")
        prompt = builder.build(Task(description="Build dashboard"), ctx, skill_contexts=[skill_ctx])
        assert "## Relevant Skills" in prompt
        assert "react-ui" in prompt
        assert "0.85" in prompt
        assert "Use React hooks" in prompt

    def test_audit_trail_present(self):
        builder = PromptBuilder()
        ctx = _make_context()
        skill_ctx = _make_skill_context("test-skill", 0.72, "Content.")
        prompt = builder.build(Task(description="Test"), ctx, skill_contexts=[skill_ctx])
        assert "[Audit]" in prompt

    def test_multiple_skills_in_section(self):
        builder = PromptBuilder()
        ctx = _make_context()
        s1 = _make_skill_context("first", 0.82, "First content.")
        s2 = _make_skill_context("second", 0.61, "Second content.")
        prompt = builder.build(Task(description="Test"), ctx, skill_contexts=[s1, s2])
        assert "first" in prompt
        assert "second" in prompt

    def test_trigger_and_scope_info_in_section(self):
        builder = PromptBuilder()
        ctx = _make_context()
        skill_ctx = _make_skill_context("my-skill", 0.82, "Content.")
        prompt = builder.build(Task(description="Test"), ctx, skill_contexts=[skill_ctx])
        assert "[triggers:" in prompt
        assert "[scope:" in prompt


class TestGoldenPathFallback:
    def test_skill_contexts_none_uses_old_section(self):
        builder = PromptBuilder()
        ctx = _make_context()
        prompt = builder.build(Task(description="Test"), ctx, skill_contexts=None)
        assert "## Skills Loaded" in prompt
        assert "project-dna" in prompt
        assert "coding-style" in prompt
        assert "## Relevant Skills" not in prompt
        assert "[Audit]" not in prompt

    def test_skill_contexts_empty_uses_old_section(self):
        builder = PromptBuilder()
        ctx = _make_context()
        prompt = builder.build(Task(description="Test"), ctx, skill_contexts=[])
        assert "## Skills Loaded" in prompt
        assert "## Relevant Skills" not in prompt

    def test_skills_empty_in_context_no_section(self):
        builder = PromptBuilder()
        ctx = ContextPacket()
        ctx.project = ProjectInfo(language="python", root="/tmp/test", name="test")
        ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
        ctx.skills = []
        prompt = builder.build(Task(description="Test"), ctx)
        assert "## Skills Loaded" not in prompt
        assert "## Relevant Skills" not in prompt

    def test_existing_prompt_tests_still_pass(self):
        builder = PromptBuilder()
        ctx = _make_context()
        ctx.git.branch = "main"
        ctx.git.status = "clean"
        prompt = builder.build(Task(description="Write a test"), ctx)
        assert "## Task" in prompt
        assert "## Project Context" in prompt
        assert "## Git Status" in prompt
        assert "## Skills Loaded" in prompt
        assert "project-dna" in prompt


class TestBackwardCompatSignature:
    def test_build_without_skill_contexts_works(self):
        builder = PromptBuilder()
        ctx = _make_context()
        prompt = builder.build(Task(description="Test"), ctx)
        assert "## Task" in prompt
