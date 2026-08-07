"""Tests for SecurityEngine — policy file loading."""

from aios.security import SecurityEngine


def test_security_engine_loads_capabilities_policy(tmp_path):
    (tmp_path / "aios" / "policies").mkdir(parents=True)
    (tmp_path / "aios" / "policies" / "agent_capabilities.yaml").write_text(
        "reviewer:\n  filesystem:\n    - read\n",
        encoding="utf-8",
    )

    engine = SecurityEngine(project_path=tmp_path)
    engine.initialize()

    # _policies_loaded has no public inspection API yet; this is the only
    # observable state of the loading step.
    assert engine._policies_loaded is True


def test_security_engine_without_policies(tmp_path):
    engine = SecurityEngine(project_path=tmp_path)
    engine.initialize()

    assert engine._policies_loaded is False
