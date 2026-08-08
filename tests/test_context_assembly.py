"""Tests for layer assembly — precedence ordering, dedupe, budgets, audit."""

import aios.knowledge  # noqa: F401  (load before selector to avoid circular import)

from aios.context.assembly import (
    DEFAULT_LAYER_CAPS,
    ContextAssemblyResult,
    assemble_layers,
    dedupe_layers,
    order_layers,
    truncate_layers,
)
from aios.context.layers import Layer, LayerType


def _layer(layer_type: LayerType, content: str, tokens: int = 0, source: str = "") -> Layer:
    return Layer(type=layer_type, content=content, tokens=tokens, source=source)


class TestOrderLayers:
    def test_orders_by_precedence_desc(self):
        layers = [
            _layer(LayerType.PROJECT, "p"),
            _layer(LayerType.TASK, "t"),
            _layer(LayerType.RETRIEVED, "r"),
        ]
        ordered = order_layers(layers)
        assert [layer.type for layer in ordered] == [
            LayerType.TASK,
            LayerType.PROJECT,
            LayerType.RETRIEVED,
        ]

    def test_stable_for_equal_precedence(self):
        a = _layer(LayerType.RETRIEVED, "a")
        b = _layer(LayerType.RETRIEVED, "b")
        assert order_layers([a, b]) == [a, b]
        assert order_layers([b, a]) == [b, a]


class TestDedupeLayers:
    def test_duplicate_content_drops_lower_precedence(self):
        task = _layer(LayerType.TASK, "  shared content  ")
        project = _layer(LayerType.PROJECT, "shared content")
        kept, dropped = dedupe_layers(order_layers([project, task]))
        assert dropped == 1
        assert len(kept) == 1
        assert kept[0] is task

    def test_distinct_content_no_drops(self):
        layers = [
            _layer(LayerType.TASK, "one"),
            _layer(LayerType.PROJECT, "two"),
            _layer(LayerType.RESEARCH, "three"),
        ]
        kept, dropped = dedupe_layers(order_layers(layers))
        assert dropped == 0
        assert len(kept) == 3

    def test_normalized_content_ignores_whitespace(self):
        a = _layer(LayerType.PROJECT, "hello\nworld")
        b = _layer(LayerType.RESEARCH, "hello world")
        kept, dropped = dedupe_layers(order_layers([b, a]))
        assert dropped == 1
        assert kept[0] is a


class TestTruncateLayers:
    def test_guardrail_never_dropped_or_truncated(self):
        task = _layer(LayerType.TASK, "do it", tokens=10, source="task")
        project = _layer(LayerType.PROJECT, "proj", tokens=5)
        result, truncated, _ = truncate_layers([task, project], budget_total=3)
        assert task in result
        assert task.tokens == 10
        assert truncated is True

    def test_layer_above_cap_truncated(self):
        research = _layer(LayerType.RESEARCH, " ".join(["word"] * 2000), tokens=2000)
        result, truncated, audit = truncate_layers([research], budget_total=10_000)
        assert truncated is True
        assert result[0].tokens <= DEFAULT_LAYER_CAPS[LayerType.RESEARCH]
        assert any(entry["action"] == "truncated" for entry in audit)

    def test_total_over_budget_truncates_lowest_priority_first(self):
        task = _layer(LayerType.TASK, "t", tokens=5, source="task")
        user = _layer(LayerType.USER, " ".join(["u"] * 40), tokens=40)
        retrieved = _layer(LayerType.RETRIEVED, " ".join(["r"] * 40), tokens=40)
        result, truncated, _ = truncate_layers([task, retrieved, user], budget_total=80)
        assert truncated is True
        by_type = {layer.type: layer for layer in result}
        assert by_type[LayerType.TASK].tokens == 5
        assert by_type[LayerType.USER].tokens == 40
        assert by_type[LayerType.RETRIEVED].tokens < 40

    def test_cap_zero_means_no_cap(self):
        project = _layer(LayerType.PROJECT, " ".join(["p"] * 50), tokens=50)
        result, truncated, _ = truncate_layers([project], budget_total=10_000)
        assert truncated is False
        assert result[0].tokens == 50


class TestAssembleLayers:
    def test_full_pipeline_ordered_and_audited(self):
        layers = [
            _layer(LayerType.PROJECT, "project context", tokens=5, source="packet"),
            _layer(LayerType.TASK, "task desc", tokens=3, source="task"),
            _layer(LayerType.RESEARCH, "research summary", tokens=4, source="packet.research"),
        ]
        result = assemble_layers(layers, budget_total=100)
        assert [layer.type for layer in result.layers] == [
            LayerType.TASK,
            LayerType.PROJECT,
            LayerType.RESEARCH,
        ]
        assert result.total_tokens == 12
        assert result.budget_tokens == 100
        assert result.truncated is False
        assert result.dropped_duplicates == 0
        assert any(entry["action"] == "added" for entry in result.audit)

    def test_duplicate_tracked_in_audit(self):
        task = _layer(LayerType.TASK, "dup content", tokens=3, source="task")
        project = _layer(LayerType.PROJECT, "dup content", tokens=3, source="packet")
        result = assemble_layers([project, task], budget_total=100)
        assert result.dropped_duplicates == 1
        assert len(result.layers) == 1
        assert any(entry["action"] == "dropped_duplicate" for entry in result.audit)

    def test_empty_layers_empty_result(self):
        result = assemble_layers([], budget_total=100)
        assert result.layers == []
        assert result.total_tokens == 0
        assert result.truncated is False

    def test_to_dict_roundtrip(self):
        result = assemble_layers(
            [_layer(LayerType.TASK, "t", tokens=3, source="task")], budget_total=50
        )
        data = result.to_dict()
        assert data["total_tokens"] == 3
        assert data["budget_tokens"] == 50
        assert data["truncated"] is False
        assert data["layers"][0]["type"] == "task"
        assert isinstance(data["audit"], list)


class TestContextAssemblyResult:
    def test_is_empty(self):
        assert ContextAssemblyResult().is_empty
        assert not ContextAssemblyResult(layers=[_layer(LayerType.TASK, "t")]).is_empty

    def test_default_budget_layers_caps(self):
        assert DEFAULT_LAYER_CAPS[LayerType.TASK] == 0
        assert DEFAULT_LAYER_CAPS[LayerType.RETRIEVED] == 0
        assert DEFAULT_LAYER_CAPS[LayerType.RESEARCH] == 1500
