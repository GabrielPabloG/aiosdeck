"""Tests for context layer contracts — LayerType, Layer, LayeredContext."""

from aios.context.layers import (
    GUARDRAIL_LAYERS,
    LAYER_PRECEDENCE,
    Layer,
    LayerType,
    LayeredContext,
    empty_layers,
)


class TestLayerType:
    def test_enum_members(self):
        members = {lt.value for lt in LayerType}
        assert members == {"global", "user", "project", "task", "research", "retrieved"}

    def test_precedence_ordering(self):
        assert LAYER_PRECEDENCE[LayerType.TASK] == 5
        assert LAYER_PRECEDENCE[LayerType.USER] == 4
        assert LAYER_PRECEDENCE[LayerType.PROJECT] == 3
        assert LAYER_PRECEDENCE[LayerType.GLOBAL] == 2
        assert LAYER_PRECEDENCE[LayerType.RESEARCH] == 1
        assert LAYER_PRECEDENCE[LayerType.RETRIEVED] == 0
        assert len(LAYER_PRECEDENCE) == 6

    def test_guardrail_layers_contains_task(self):
        assert LayerType.TASK in GUARDRAIL_LAYERS


class TestLayer:
    def test_defaults(self):
        layer = Layer(type=LayerType.PROJECT, content="content")
        assert layer.source == ""
        assert layer.guardrail is False
        assert layer.tokens == 0
        assert layer.trace is None
        assert layer.priority == 0
        assert layer.is_guardrail is False

    def test_explicit_guardrail_flag(self):
        layer = Layer(type=LayerType.GLOBAL, content="x", guardrail=True)
        assert layer.is_guardrail is True

    def test_guardrail_by_type(self):
        layer = Layer(type=LayerType.TASK, content="x")
        assert layer.is_guardrail is True

    def test_tokens_set_at_construction(self):
        layer = Layer(type=LayerType.RESEARCH, content="abc", tokens=3)
        assert layer.tokens == 3


class TestLayeredContext:
    def test_empty_by_default(self):
        ctx = LayeredContext()
        assert ctx.is_empty
        assert ctx.layers == []
        assert ctx.total_tokens() == 0

    def test_add_layer(self):
        ctx = LayeredContext()
        layer = Layer(type=LayerType.TASK, content="do it")
        ctx.add(layer)
        assert not ctx.is_empty
        assert len(ctx.layers) == 1
        assert ctx.layers[0] is layer

    def test_total_tokens_sums(self):
        ctx = LayeredContext()
        ctx.add(Layer(type=LayerType.TASK, content="a", tokens=10))
        ctx.add(Layer(type=LayerType.PROJECT, content="b", tokens=5))
        assert ctx.total_tokens() == 15

    def test_by_type_returns_matching(self):
        ctx = LayeredContext()
        ctx.add(Layer(type=LayerType.TASK, content="a"))
        ctx.add(Layer(type=LayerType.RESEARCH, content="b"))
        ctx.add(Layer(type=LayerType.RESEARCH, content="c"))
        assert len(ctx.by_type(LayerType.RESEARCH)) == 2
        assert len(ctx.by_type(LayerType.TASK)) == 1
        assert ctx.by_type(LayerType.GLOBAL) == []

    def test_to_dict_roundtrip(self):
        ctx = LayeredContext()
        ctx.add(
            Layer(
                type=LayerType.RETRIEVED,
                content="doc content",
                source="selector",
                tokens=4,
                trace={"source_id": "s1", "source_path": "docs/a.md", "score": 0.9, "position": 0},
            )
        )
        data = ctx.to_dict()
        assert data["total_tokens"] == 4
        assert len(data["layers"]) == 1
        layer_data = data["layers"][0]
        assert layer_data["type"] == "retrieved"
        assert layer_data["content"] == "doc content"
        assert layer_data["source"] == "selector"
        assert layer_data["trace"]["source_id"] == "s1"


class TestEmptyLayersFactory:
    def test_returns_empty_layered_context(self):
        ctx = empty_layers()
        assert isinstance(ctx, LayeredContext)
        assert ctx.is_empty
