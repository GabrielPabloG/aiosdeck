"""Integration tests — research and retrieved layers with traceability."""

import aios.knowledge  # noqa: F401  (load before selector to avoid circular import)

from unittest.mock import MagicMock

from aios.agents import Task
from aios.context.assembler import ContextAssembler
from aios.context.layers import LayerType
from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.knowledge.models import KnowledgeResult
from aios.retrieval.retrievers import ScoredResult


def _make_context(research: dict | None = None) -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(name="demo", root="/tmp/demo", language="python")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git.branch = "main"
    ctx.git.status = "clean"
    ctx.research = research
    return ctx


def _make_scored(  # noqa: PLR0913, PLR0917
    content: str,
    source_type: str,
    source_id: str = "s1",
    source_path: str = "docs/a.md",
    score: float = 0.8,
    position: int = 0,
    token_estimate: int = 10,
) -> ScoredResult:
    result = KnowledgeResult(
        source_id=source_id,
        source_type=source_type,
        source_path=source_path,
        content=content,
        position=position,
        token_estimate=token_estimate,
    )
    return ScoredResult(result=result, score=score)


class TestResearchLayer:
    def test_research_summary_short_becomes_layer(self):
        context = _make_context(research={"summary_short": "Research says use SQLite."})
        result = ContextAssembler().assemble(
            Task(description="Pick a DB"), context, agent="developer"
        )
        research = next(
            (layer for layer in result.layers if layer.type is LayerType.RESEARCH), None
        )
        assert research is not None
        assert research.content == "Research says use SQLite."
        assert research.source == "packet.research"

    def test_research_missing_produces_no_layer(self):
        context = _make_context(research=None)
        result = ContextAssembler().assemble(
            Task(description="Pick a DB"), context, agent="developer"
        )
        assert not any(layer.type is LayerType.RESEARCH for layer in result.layers)

    def test_research_without_summary_short(self):
        context = _make_context(research={"notes": "no short summary"})
        result = ContextAssembler().assemble(Task(description="x"), context, agent="developer")
        assert not any(layer.type is LayerType.RESEARCH for layer in result.layers)


class TestRetrievedLayer:
    def test_retrieved_chunks_become_layers_with_trace(self):
        knowledge = MagicMock()
        selection = MagicMock()
        selection.chunks = [
            _make_scored("Doc A", "documentation", source_id="doc-a", score=0.91, position=2),
            _make_scored("Code B", "code", source_id="code-b", score=0.77, position=5),
        ]
        knowledge.retrieve.return_value = selection

        context = _make_context()
        result = ContextAssembler(knowledge=knowledge).assemble(
            Task(description="Refactor module"), context, agent="developer"
        )
        retrieved = [layer for layer in result.layers if layer.type is LayerType.RETRIEVED]
        assert len(retrieved) == 2
        assert retrieved[0].source == "selector"
        assert retrieved[0].trace == {
            "source_id": "doc-a",
            "source_path": "docs/a.md",
            "score": 0.91,
            "position": 2,
        }

    def test_skill_source_types_excluded(self):
        knowledge = MagicMock()
        selection = MagicMock()
        selection.chunks = [
            _make_scored("Skill content", "skill", source_id="skill-1"),
            _make_scored("DNA content", "project_dna", source_id="dna-1"),
            _make_scored("Doc content", "documentation", source_id="doc-1"),
        ]
        knowledge.retrieve.return_value = selection

        context = _make_context()
        result = ContextAssembler(knowledge=knowledge).assemble(
            Task(description="x"), context, agent="developer"
        )
        retrieved = [layer for layer in result.layers if layer.type is LayerType.RETRIEVED]
        assert len(retrieved) == 1
        assert retrieved[0].trace["source_id"] == "doc-1"

    def test_no_knowledge_no_retrieved(self):
        context = _make_context()
        result = ContextAssembler(knowledge=None).assemble(
            Task(description="x"), context, agent="developer"
        )
        assert not any(layer.type is LayerType.RETRIEVED for layer in result.layers)

    def test_retrieve_called_with_task_description(self):
        knowledge = MagicMock()
        selection = MagicMock()
        selection.chunks = []
        knowledge.retrieve.return_value = selection

        context = _make_context()
        ContextAssembler(knowledge=knowledge).assemble(
            Task(description="Implement auth"), context, agent="developer"
        )
        knowledge.retrieve.assert_called_once()
        call_kwargs = knowledge.retrieve.call_args.kwargs
        assert call_kwargs["agent"] == "developer"
        assert call_kwargs["limit"] == 20
        assert call_kwargs["use_vector"] is False

    def test_retrieve_failure_is_safe(self):
        knowledge = MagicMock()
        knowledge.retrieve.side_effect = RuntimeError("retrieval exploded")

        context = _make_context()
        result = ContextAssembler(knowledge=knowledge).assemble(
            Task(description="x"), context, agent="developer"
        )
        assert not any(layer.type is LayerType.RETRIEVED for layer in result.layers)


class TestFullIntegration:
    def test_all_four_layers_assembled(self):
        knowledge = MagicMock()
        selection = MagicMock()
        selection.chunks = [_make_scored("Doc content", "documentation", source_id="doc-1")]
        knowledge.retrieve.return_value = selection

        context = _make_context(research={"summary_short": "Research summary."})
        result = ContextAssembler(knowledge=knowledge).assemble(
            Task(description="Task description"), context, agent="developer"
        )
        types = {layer.type for layer in result.layers}
        assert LayerType.TASK in types
        assert LayerType.PROJECT in types
        assert LayerType.RESEARCH in types
        assert LayerType.RETRIEVED in types

    def test_traceability_consistency(self):
        knowledge = MagicMock()
        selection = MagicMock()
        selection.chunks = [_make_scored("Doc content", "documentation", source_id="doc-9")]
        knowledge.retrieve.return_value = selection

        context = _make_context(research={"summary_short": "Research."})
        result = ContextAssembler(knowledge=knowledge).assemble(
            Task(description="x"), context, agent="developer"
        )
        data = result.to_dict()
        retrieved = [layer for layer in data["layers"] if layer["type"] == "retrieved"]
        assert retrieved[0]["trace"]["source_id"] == "doc-9"
        assert retrieved[0]["source"] == "selector"
