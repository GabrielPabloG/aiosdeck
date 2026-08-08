"""Policy resolution tests — severity × environment matrix.

Covers the canonical decision rules:
- critical/high always block
- medium blocks in release, warns in dev
- low always warns
- no findings passes
- no policy → fail-safe default
- unknown environment → fail-safe block
- explicit overrides are auditable and must match gate + environment
"""

import json

import pytest

from aios.quality.contracts import Severity
from aios.quality.policy import (
    DEFAULT_POLICY,
    DecisionResult,
    GateDecision,
    GateOverride,
    resolve_decision,
)


class TestSeverityEnvironmentMatrix:
    @pytest.mark.parametrize(
        ("severities", "environment", "expected"),
        [
            ([Severity.CRITICAL], "dev", GateDecision.BLOCK),
            ([Severity.HIGH], "dev", GateDecision.BLOCK),
            ([Severity.MEDIUM], "dev", GateDecision.WARN),
            ([Severity.LOW], "dev", GateDecision.WARN),
            ([], "dev", GateDecision.PASS),
            ([Severity.CRITICAL], "release", GateDecision.BLOCK),
            ([Severity.HIGH], "release", GateDecision.BLOCK),
            ([Severity.MEDIUM], "release", GateDecision.BLOCK),
            ([Severity.LOW], "release", GateDecision.WARN),
            ([], "release", GateDecision.PASS),
        ],
    )
    def test_matrix(self, severities, environment, expected):
        result = resolve_decision(severities, environment=environment)
        assert result.decision is expected

    def test_accepts_raw_string_severities(self):
        result = resolve_decision(["high"], environment="dev")
        assert result.decision is GateDecision.BLOCK

    def test_mixed_severities_block_when_any_blocking(self):
        result = resolve_decision([Severity.LOW, Severity.HIGH], environment="dev")
        assert result.decision is GateDecision.BLOCK
        assert result.findings["low"] == 1
        assert result.findings["high"] == 1

    def test_findings_counts_all_severities(self):
        result = resolve_decision(
            [Severity.MEDIUM, Severity.MEDIUM, Severity.LOW], environment="dev"
        )
        assert result.findings == {"low": 1, "medium": 2, "high": 0, "critical": 0}


class TestFailSafe:
    def test_no_policy_uses_default_and_blocks_high(self):
        result = resolve_decision([Severity.HIGH], environment="dev", policy=None)
        assert result.decision is GateDecision.BLOCK

    def test_unknown_environment_blocks_on_findings(self):
        result = resolve_decision([Severity.LOW], environment="staging")
        assert result.decision is GateDecision.BLOCK
        assert "fail-safe" in result.reason

    def test_unknown_environment_without_findings_passes(self):
        result = resolve_decision([], environment="staging")
        assert result.decision is GateDecision.PASS

    def test_custom_policy_raises_block_threshold(self):
        policy = {"dev": ["critical"]}
        result = resolve_decision([Severity.HIGH], environment="dev", policy=policy)
        assert result.decision is GateDecision.WARN

    def test_custom_policy_can_loosen_default(self):
        policy = {"release": ["critical"]}
        result = resolve_decision([Severity.MEDIUM], environment="release", policy=policy)
        assert result.decision is GateDecision.WARN

    def test_default_policy_shape(self):
        assert DEFAULT_POLICY["dev"] == ["critical", "high"]
        assert DEFAULT_POLICY["release"] == ["critical", "high", "medium"]


class TestOverride:
    def test_matching_override_lifts_block(self):
        overrides = [
            GateOverride(gate="code_gate", environment="dev", reason="manual inspection passed")
        ]
        result = resolve_decision(
            [Severity.HIGH], gate="code_gate", environment="dev", overrides=overrides
        )
        assert result.blocks() is False
        assert result.overridden is True
        assert result.override_reason == "manual inspection passed"

    def test_override_must_match_gate_and_environment(self):
        overrides = [GateOverride(gate="security_gate", environment="dev", reason="nope")]
        result = resolve_decision(
            [Severity.HIGH], gate="code_gate", environment="dev", overrides=overrides
        )
        assert result.blocks() is True
        assert result.overridden is False

    def test_override_accepts_config_dicts(self):
        overrides = [{"gate": "code_gate", "environment": "dev", "reason": "accepted"}]
        result = resolve_decision(
            [Severity.HIGH], gate="code_gate", environment="dev", overrides=overrides
        )
        assert result.overridden is True
        assert result.override_reason == "accepted"

    def test_override_does_not_touch_warn(self):
        overrides = [GateOverride(gate="code_gate", environment="dev", reason="whatever")]
        result = resolve_decision(
            [Severity.MEDIUM], gate="code_gate", environment="dev", overrides=overrides
        )
        assert result.decision is GateDecision.WARN
        assert result.overridden is False


class TestDecisionResult:
    def test_blocks_property(self):
        blocked = DecisionResult(decision=GateDecision.BLOCK, gate="g", environment="dev")
        overridden = DecisionResult(
            decision=GateDecision.BLOCK, gate="g", environment="dev", overridden=True
        )
        assert blocked.blocks() is True
        assert overridden.blocks() is False

    def test_to_dict_is_json_serializable(self):
        result = resolve_decision([Severity.HIGH], gate="code_gate", environment="dev")
        data = result.to_dict()
        assert json.loads(json.dumps(data)) == data
        assert data["decision"] == "block"
        assert data["findings"]["high"] == 1
        assert data["overridden"] is False
