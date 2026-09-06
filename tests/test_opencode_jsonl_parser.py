"""Tests for OpenCode JSONL parser — _parse_jsonl()."""

import pytest

from aios.runtime.opencode import AgentMetrics, _parse_jsonl


class TestParseJsonlBasic:
    def test_simple_text_response(self):
        output = (
            '{"type":"step_start","timestamp":1788724669546,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1788724669662,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"test ok",'
            '"time":{"start":1788724669640,"end":1788724669658}}}\n'
            '{"type":"step_finish","timestamp":1788724669738,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"total":7584,"input":6,"output":17,"reasoning":0,'
            '"cache":{"write":7561,"read":0}},"cost":0.00152109}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "test ok"
        assert metrics.llm_turns == 1
        assert metrics.tool_calls == 0
        assert metrics.tool_names == []
        assert metrics.total_cost == 0.00152109
        assert metrics.tokens["input"] == 6
        assert metrics.tokens["output"] == 17
        assert metrics.tokens["cache_read"] == 0
        assert metrics.tokens["cache_write"] == 7561

    def test_empty_output(self):
        text, metrics = _parse_jsonl("")
        assert text == ""
        assert metrics.tool_calls == 0
        assert metrics.llm_turns == 0
        assert metrics.total_cost == 0.0

    def test_only_log_lines(self):
        output = (
            "timestamp=2026-09-06T19:57:45.482Z level=INFO message=init\n"
            "timestamp=2026-09-06T19:57:45.583Z level=INFO message=done\n"
        )
        text, metrics = _parse_jsonl(output)
        assert text == ""
        assert metrics.tool_calls == 0
        assert metrics.llm_turns == 0


class TestParseJsonlTools:
    def test_multiple_tool_calls(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"glob","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"files",'
            '"time":{"start":1001,"end":1050}}}}\n'
            '{"type":"tool_use","timestamp":1060,'
            '"part":{"type":"tool","tool":"bash","callID":"c2",'
            '"state":{"status":"completed","input":{},"output":"result",'
            '"time":{"start":1060,"end":1071}}}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"total":8000,"input":10,"output":50,"reasoning":0,'
            '"cache":{"read":7900,"write":40}},"cost":0.0003}}\n'
            '{"type":"step_start","timestamp":1200,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1300,'
            '"part":{"id":"p4","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"done",'
            '"time":{"start":1250,"end":1300}}}\n'
            '{"type":"step_finish","timestamp":1350,'
            '"part":{"id":"p5","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"total":8500,"input":10,"output":100,"reasoning":0,'
            '"cache":{"read":8400,"write":50}},"cost":0.0004}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "done"
        assert metrics.llm_turns == 2
        assert metrics.tool_calls == 2
        assert "glob" in metrics.tool_names
        assert "bash" in metrics.tool_names
        assert len(metrics.tool_durations_ms) == 2
        assert metrics.tool_durations_ms[0] == 49.0  # glob: 1050-1001
        assert metrics.tool_durations_ms[1] == 11.0  # bash: 1071-1060
        assert metrics.total_cost == 0.0007

    def test_tool_without_timing(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"content"}}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.tool_calls == 1
        assert metrics.tool_names == ["read"]
        assert metrics.tool_durations_ms == [0.0]

    def test_tool_counting(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"a",'
            '"time":{"start":1001,"end":1010}}}}\n'
            '{"type":"tool_use","timestamp":1020,'
            '"part":{"type":"tool","tool":"read","callID":"c2",'
            '"state":{"status":"completed","input":{},"output":"b",'
            '"time":{"start":1020,"end":1030}}}}\n'
            '{"type":"tool_use","timestamp":1040,'
            '"part":{"type":"tool","tool":"grep","callID":"c3",'
            '"state":{"status":"completed","input":{},"output":"c",'
            '"time":{"start":1040,"end":1045}}}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.tool_calls == 3
        assert metrics.tool_names[0] == "read"  # most frequent
        assert metrics.tool_names[1] == "grep"
        assert len(metrics.tool_durations_ms) == 2
        assert metrics.tool_durations_ms[0] == 19.0  # read: 10+9


class TestParseJsonlEdgeCases:
    def test_unknown_event_types_ignored(self):
        output = (
            '{"type":"unknown_event","timestamp":1000,"part":{}}\n'
            '{"type":"step_start","timestamp":1001,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1002,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"ok"}}\n'
            '{"type":"step_finish","timestamp":1003,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "ok"
        assert metrics.llm_turns == 1

    def test_malformed_json_lines_ignored(self):
        output = (
            "not json at all\n"
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            "{broken json\n"
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"ok"}}\n'
            '{"type":"step_finish","timestamp":1002,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "ok"
        assert metrics.llm_turns == 1

    def test_incomplete_jsonl(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"partial"}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "partial"
        assert metrics.llm_turns == 1
        assert metrics.tool_calls == 0
        assert metrics.total_cost == 0.0

    def test_multiple_step_finish_accumulates_cost(self):
        output = (
            '{"type":"step_finish","timestamp":1000,'
            '"part":{"id":"p1","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0001}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p2","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0002}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.total_cost == pytest.approx(0.0003)

    def test_step_finish_tokens_overwrite(self):
        """Last step_finish tokens win (matches real OpenCode behaviour)."""
        output = (
            '{"type":"step_finish","timestamp":1000,'
            '"part":{"id":"p1","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":10,"output":20,"reasoning":0,'
            '"cache":{"read":0,"write":0}},"cost":0.001}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p2","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":5,"output":100,"reasoning":5,'
            '"cache":{"read":500,"write":10}},"cost":0.002}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.tokens["input"] == 5
        assert metrics.tokens["output"] == 100
        assert metrics.tokens["reasoning"] == 5
        assert metrics.tokens["cache_read"] == 500
        assert metrics.tokens["cache_write"] == 10


class TestAgentMetrics:
    def test_defaults(self):
        m = AgentMetrics()
        assert m.tool_calls == 0
        assert m.tool_names == []
        assert m.tool_durations_ms == []
        assert m.llm_turns == 0
        assert m.total_cost == 0.0
        assert m.tokens == {}
