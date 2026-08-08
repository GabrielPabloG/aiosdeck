"""Tests for SkillRetrievalService — per-skill chunk selection with budget."""

from aios.knowledge.engine import KnowledgeEngine
from aios.retrieval.selector import ContextBudget
from aios.skills.discovery import ScoredSkill
from aios.skills.metadata import SkillMetadata
from aios.skills.retrieval import SkillContext, SkillRetrievalService

_SKILL_SOURCE_RE = ".opencode/skills/"


def _make_skill(name: str, triggers: list[str] | None = None) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"Skill {name}",
        triggers=triggers or [],
        priority=0,
    ).validate()


def _make_scored(skill: SkillMetadata, score: float = 0.8) -> ScoredSkill:
    return ScoredSkill(
        skill=skill,
        score=score,
        trigger_matches=[],
        scope_matches=[],
        priority_score=0.0,
    )


def _write_skill_text(name: str, body: str) -> str:
    return f"---\nname: {name}\ndescription: Test\n---\n\n# {name}\n\n{body}"


class TestSkillContext:
    def test_fields(self):
        ctx = SkillContext(
            skill=_make_scored(_make_skill("test"), 0.75),
            chunks=[],
            prompt_section="## Skills\ncontent",
            tokens_used=100,
            relevance_score=0.75,
        )
        assert ctx.skill.score == 0.75
        assert ctx.skill.skill.name == "test"
        assert ctx.prompt_section == "## Skills\ncontent"
        assert ctx.tokens_used == 100


class TestSkillRetrievalService:
    def _make_engine(self, tmp_path):
        db = tmp_path / "test.db"
        engine = KnowledgeEngine(project_path=tmp_path, db_path=str(db))
        engine.initialize()
        return engine

    def _index_skill(self, engine: KnowledgeEngine, tmp_path, name: str, content: str):
        skill_dir = tmp_path / ".opencode" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_write_skill_text(name, content))
        engine.index()

    def test_retrieve_groups_by_skill(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(
            engine, tmp_path, "react-skill", "React components use hooks for state management."
        )
        self._index_skill(
            engine, tmp_path, "python-skill", "Python conventions: use snake_case and type hints."
        )

        budget = ContextBudget()
        svc = SkillRetrievalService(engine, budget)
        scored = [
            _make_scored(_make_skill("react-skill"), 0.8),
            _make_scored(_make_skill("python-skill"), 0.6),
        ]

        result = svc.retrieve(scored, "components and state", agent="planner")
        assert len(result) > 0
        for ctx in result:
            assert ctx.skill.skill.name.startswith(("react-skill", "python-skill"))

    def test_respects_max_chunks_per_skill(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(
            engine,
            tmp_path,
            "big-skill",
            "# Intro\nIntro content.\n\n# Section A\nAAA.\n\n# Section B\nBBB.\n\n# Section C\nCCC.",
        )

        budget = ContextBudget()
        svc = SkillRetrievalService(engine, budget)
        scored = [_make_scored(_make_skill("big-skill"), 0.9)]

        result = svc.retrieve(scored, "intro", agent="planner", max_chunks_per_skill=1)
        assert len(result) == 1
        assert len(result[0].chunks) <= 1

    def test_empty_store_returns_empty(self, tmp_path):
        engine = self._make_engine(tmp_path)
        svc = SkillRetrievalService(engine, ContextBudget())
        scored = [_make_scored(_make_skill("nope"), 0.9)]
        result = svc.retrieve(scored, "test", agent="planner")
        assert result == []

    def test_no_scored_skills_returns_empty(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(engine, tmp_path, "any", "Some content")
        svc = SkillRetrievalService(engine, ContextBudget())
        result = svc.retrieve([], "test", agent="planner")
        assert result == []

    def test_budget_limits_total_tokens(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(
            engine,
            tmp_path,
            "big-skill",
            "word " * 5000,
        )
        budget = ContextBudget({"planner": 100})
        svc = SkillRetrievalService(engine, budget)
        scored = [_make_scored(_make_skill("big-skill"), 0.9)]
        result = svc.retrieve(scored, "word", agent="planner", max_chunks_per_skill=1)
        if result:
            assert result[0].tokens_used <= 150  # rough — within budget-ish

    def test_skill_not_indexed_dropped(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(engine, tmp_path, "indexed-skill", "Some content here")
        svc = SkillRetrievalService(engine, ContextBudget())
        scored = [
            _make_scored(_make_skill("indexed-skill"), 0.8),
            _make_scored(_make_skill("missing-skill"), 0.6),
        ]
        result = svc.retrieve(scored, "content", agent="planner")
        names = [c.skill.skill.name for c in result]
        assert "missing-skill" not in names

    def test_token_estimate_in_skill_context(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(engine, tmp_path, "token-skill", "token test content here for counting")
        svc = SkillRetrievalService(engine, ContextBudget())
        scored = [_make_scored(_make_skill("token-skill"), 0.9)]
        result = svc.retrieve(scored, "token test", agent="planner")
        assert len(result) == 1
        assert result[0].tokens_used > 0

    def test_prompt_section_format(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(engine, tmp_path, "fmt-skill", "This is formatted chunk content.")
        svc = SkillRetrievalService(engine, ContextBudget())
        scored = [_make_scored(_make_skill("fmt-skill"), 0.9)]
        result = svc.retrieve(scored, "formatted", agent="planner")
        assert len(result) == 1
        assert result[0].prompt_section.startswith("## Relevant Skills")

    def test_higher_scored_skills_get_priority(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(engine, tmp_path, "high-priority", "Unique high priority content")
        self._index_skill(engine, tmp_path, "low-priority", "Unique low priority content")
        budget = ContextBudget({"planner": 50})
        svc = SkillRetrievalService(engine, budget)
        scored = [
            _make_scored(_make_skill("high-priority"), 0.9),
            _make_scored(_make_skill("low-priority"), 0.3),
        ]
        result = svc.retrieve(scored, "unique", agent="planner", max_chunks_per_skill=1)
        scores = [c.relevance_score for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_relevance_score_matches_skill_score(self, tmp_path):
        engine = self._make_engine(tmp_path)
        self._index_skill(engine, tmp_path, "rel-skill", "Relevant content here")
        svc = SkillRetrievalService(engine, ContextBudget())
        scored = [_make_scored(_make_skill("rel-skill"), 0.77)]
        result = svc.retrieve(scored, "relevant", agent="planner")
        assert len(result) == 1
        assert result[0].relevance_score == 0.77
