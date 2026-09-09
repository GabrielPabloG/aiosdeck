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
        assert m.turns == []
        assert m.repeated_tool_calls == 0
        assert m.exit_reason == "stop"


class TestTurnTracking:
    def test_single_text_turn(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"ok"}}\n'
            '{"type":"step_finish","timestamp":1002,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":6,"output":17,"reasoning":0,'
            '"cache":{"read":0,"write":0}},"cost":0.001}}'
        )
        text, metrics = _parse_jsonl(output)
        assert len(metrics.turns) == 1
        assert metrics.turns[0].kind == "text"
        assert metrics.turns[0].tool_name is None
        assert metrics.turns[0].index == 0

    def test_tool_turn(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"bash","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"result",'
            '"time":{"start":1001,"end":1012}}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert len(metrics.turns) == 1
        assert metrics.turns[0].kind == "tool"
        assert metrics.turns[0].tool_name == "bash"

    def test_multiple_turns_sequence(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"glob","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"files",'
            '"time":{"start":1001,"end":1050}}}}\n'
            '{"type":"step_finish","timestamp":1060,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0001}}\n'
            '{"type":"step_start","timestamp":1100,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1101,'
            '"part":{"type":"tool","tool":"bash","callID":"c2",'
            '"state":{"status":"completed","input":{},"output":"result",'
            '"time":{"start":1101,"end":1112}}}}\n'
            '{"type":"step_finish","timestamp":1120,'
            '"part":{"id":"p4","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0002}}\n'
            '{"type":"step_start","timestamp":1200,'
            '"part":{"id":"p5","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1201,'
            '"part":{"id":"p6","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"done"}}\n'
            '{"type":"step_finish","timestamp":1210,'
            '"part":{"id":"p7","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0003}}'
        )
        text, metrics = _parse_jsonl(output)
        assert len(metrics.turns) == 3
        assert [t.kind for t in metrics.turns] == ["tool", "tool", "text"]
        assert [t.tool_name for t in metrics.turns] == ["glob", "bash", None]
        assert metrics.llm_turns == 3

    def test_turn_tokens(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"content"}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":100,"output":20,"reasoning":0,'
            '"cache":{"read":0,"write":0}},"cost":0.001}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.turns[0].tokens_in == 100
        assert metrics.turns[0].tokens_out == 20
        assert metrics.turns[0].cost == 0.001


class TestRepeatedToolCalls:
    def test_repeated_same_tool_same_input(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"content1"}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}\n'
            '{"type":"step_start","timestamp":1100,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1101,'
            '"part":{"type":"tool","tool":"read","callID":"c2",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"content2"}}}\n'
            '{"type":"step_finish","timestamp":1120,'
            '"part":{"id":"p4","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.repeated_tool_calls == 1

    def test_different_tool_not_repeated(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"content"}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}\n'
            '{"type":"step_start","timestamp":1100,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1101,'
            '"part":{"type":"tool","tool":"bash","callID":"c2",'
            '"state":{"status":"completed","input":{"command":"ls"},'
            '"output":"files"}}}\n'
            '{"type":"step_finish","timestamp":1120,'
            '"part":{"id":"p4","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.repeated_tool_calls == 0

    def test_same_tool_different_input_not_repeated(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"content1"}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}\n'
            '{"type":"step_start","timestamp":1100,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1101,'
            '"part":{"type":"tool","tool":"read","callID":"c2",'
            '"state":{"status":"completed","input":{"file":"b.py"},'
            '"output":"content2"}}}\n'
            '{"type":"step_finish","timestamp":1120,'
            '"part":{"id":"p4","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.repeated_tool_calls == 0

    def test_multiple_consecutive_repeated_calls(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"c1"}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}\n'
            '{"type":"step_start","timestamp":1100,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1101,'
            '"part":{"type":"tool","tool":"read","callID":"c2",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"c2"}}}\n'
            '{"type":"step_finish","timestamp":1120,'
            '"part":{"id":"p4","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}\n'
            '{"type":"step_start","timestamp":1200,'
            '"part":{"id":"p5","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1201,'
            '"part":{"type":"tool","tool":"read","callID":"c3",'
            '"state":{"status":"completed","input":{"file":"a.py"},'
            '"output":"c3"}}}\n'
            '{"type":"step_finish","timestamp":1220,'
            '"part":{"id":"p6","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.repeated_tool_calls == 2


class TestExitReason:
    def test_exit_reason_stop(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"ok"}}\n'
            '{"type":"step_finish","timestamp":1002,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        _, metrics = _parse_jsonl(output)
        assert metrics.exit_reason == "stop"

    def test_exit_reason_tool_calls_not_used(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"bash","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"r"}}}\n'
            '{"type":"step_finish","timestamp":1020,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}\n'
            '{"type":"step_start","timestamp":1100,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1101,'
            '"part":{"id":"p4","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"done"}}\n'
            '{"type":"step_finish","timestamp":1110,'
            '"part":{"id":"p5","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        _, metrics = _parse_jsonl(output)
        assert metrics.exit_reason == "stop"

    def test_exit_reason_unknown(self):
        output = (
            '{"type":"step_finish","timestamp":1000,'
            '"part":{"id":"p1","reason":"","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        _, metrics = _parse_jsonl(output)
        assert metrics.exit_reason == "stop"  # default when no non-tool-calls reason


class TestGate2Coverage:
    """Gate 2: tests targeting specific branches in _parse_jsonl for mutation survival."""

    def test_reasoning_turn(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"reasoning","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"reasoning","text":"thinking..."}}\n'
            '{"type":"step_finish","timestamp":1003,'
            '"part":{"id":"p4","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert len(metrics.turns) == 1
        assert metrics.turns[0].kind == "reasoning"

    def test_tool_pending_not_counted(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"read","callID":"c1",'
            '"state":{"status":"pending","input":{},"output":""}}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p2","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.tool_calls == 0
        assert metrics.tool_names == []

    def test_text_before_step_start(self):
        output = (
            '{"type":"text","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"orphan"}}\n'
            '{"type":"step_start","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1002,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"ok"}}\n'
            '{"type":"step_finish","timestamp":1003,'
            '"part":{"id":"p4","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "orphan\nok"
        assert metrics.llm_turns == 1

    def test_multiple_text_in_one_turn(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"hello"}}\n'
            '{"type":"text","timestamp":1002,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":" world"}}\n'
            '{"type":"step_finish","timestamp":1003,'
            '"part":{"id":"p4","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "hello\n world"
        assert len(metrics.turns) == 1

    def test_tool_duration_no_turns(self):
        output = (
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"bash","callID":"c1",'
            '"state":{"status":"completed","input":{},"output":"r",'
            '"time":{"start":1001,"end":1020}}}}\n'
            '{"type":"step_finish","timestamp":1100,'
            '"part":{"id":"p1","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.0}}'
        )
        text, metrics = _parse_jsonl(output)
        assert metrics.tool_calls == 1
        assert metrics.tool_names == ["bash"]
        assert metrics.tool_durations_ms == [19.0]
        assert metrics.llm_turns == 0

    def test_step_finish_empty_tokens(self):
        output = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"ok"}}\n'
            '{"type":"step_finish","timestamp":1002,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{},"cost":0.005}}'
        )
        text, metrics = _parse_jsonl(output)
        assert text == "ok"
        assert metrics.total_cost == 0.005
        assert metrics.tokens == {}

    def test_realistic_multiturn_session(self):
        output = (
            # Turn 1: glob
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":1001,'
            '"part":{"type":"tool","tool":"glob","callID":"c1",'
            '"state":{"status":"completed","input":{"pattern":"*.py"},'
            '"output":"files",'
            '"time":{"start":1001,"end":1050}}}}\n'
            '{"type":"step_finish","timestamp":1060,'
            '"part":{"id":"p2","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":10,"output":20,"reasoning":0,'
            '"cache":{"read":0,"write":0}},"cost":0.001}}\n'
            # Turn 2: bash (repeated)
            '{"type":"step_start","timestamp":2000,'
            '"part":{"id":"p3","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"tool_use","timestamp":2001,'
            '"part":{"type":"tool","tool":"bash","callID":"c2",'
            '"state":{"status":"completed","input":{"command":"ls"},'
            '"output":"result1",'
            '"time":{"start":2001,"end":2010}}}}\n'
            '{"type":"tool_use","timestamp":2020,'
            '"part":{"type":"tool","tool":"bash","callID":"c3",'
            '"state":{"status":"completed","input":{"command":"ls"},'
            '"output":"result2",'
            '"time":{"start":2020,"end":2030}}}}\n'
            '{"type":"step_finish","timestamp":2040,'
            '"part":{"id":"p4","reason":"tool-calls","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":30,"output":40,"reasoning":0,'
            '"cache":{"read":100,"write":10}},"cost":0.002}}\n'
            # Turn 3: text final
            '{"type":"step_start","timestamp":3000,'
            '"part":{"id":"p5","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":3001,'
            '"part":{"id":"p6","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"done"}}\n'
            '{"type":"step_finish","timestamp":3010,'
            '"part":{"id":"p7","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":50,"output":100,"reasoning":0,'
            '"cache":{"read":200,"write":20}},"cost":0.003}}'
        )
        text, metrics = _parse_jsonl(output)
        # 3 turns
        assert len(metrics.turns) == 3
        assert metrics.llm_turns == 3
        # 3 tool calls (1 glob + 2 bash)
        assert metrics.tool_calls == 3
        assert metrics.tool_names[0] == "bash"  # most frequent
        # 1 repeated call (bash with same input)
        assert metrics.repeated_tool_calls == 1
        # text
        assert text == "done"
        # cost accumulated
        assert metrics.total_cost == pytest.approx(0.006)
        # tokens from last step_finish
        assert metrics.tokens["input"] == 50
        assert metrics.tokens["output"] == 100
        # exit reason
        assert metrics.exit_reason == "stop"
