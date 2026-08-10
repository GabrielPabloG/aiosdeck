"""Tests for learning CLI commands."""

import json
import tempfile
from pathlib import Path

import pytest

from aios.learning.cli import (
    cmd_learning_approve,
    cmd_learning_candidates,
    cmd_learning_export,
    cmd_learning_ingest,
    cmd_learning_reject,
    cmd_learning,
)
from aios.learning.engine import LearningEngine


def _factory(engine: LearningEngine):
    def build(path: Path):
        class FakeKernel:
            def start(self) -> None:
                pass

            def shutdown(self) -> None:
                pass

            def get_engine(self, name: str):
                if name == "learning":
                    return engine
                return None

        return FakeKernel()

    return build


@pytest.fixture
def engine_and_factory():
    tmp = tempfile.mkdtemp()
    db_path = str(Path(tmp) / "test_cli.db")
    engine = LearningEngine(
        project_path=Path("/tmp/test-cli"),
        db_path=db_path,
    )
    engine.initialize()
    factory = _factory(engine)
    yield engine, factory
    engine.shutdown()


class TestLearningCandidates:
    def test_empty(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        cmd_learning_candidates([], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert "No candidates found" in captured.out

    def test_with_candidates(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        store.insert_candidate(
            LearningCandidate(
                content="Use type hints",
                suggested_type="convention",
                confidence=0.9,
                risk_level="low",
                dedupe_hash="cli-h1",
            )
        )
        cmd_learning_candidates([], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert "type hints" in captured.out
        assert "convention" in captured.out

    def test_json_output(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        store.insert_candidate(
            LearningCandidate(
                content="test candidate",
                suggested_type="pattern",
                confidence=0.8,
                risk_level="low",
                dedupe_hash="cli-h2",
            )
        )
        cmd_learning_candidates(["--json"], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) >= 1
        assert "advisor" in data[0]

    def test_state_filter(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        store.insert_candidate(
            LearningCandidate(
                content="approved candidate",
                dedupe_hash="cli-h3",
                state="approved",
            )
        )
        store.insert_candidate(
            LearningCandidate(
                content="draft candidate",
                dedupe_hash="cli-h4",
                state="draft",
            )
        )
        cmd_learning_candidates(["--state", "approved"], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert "approved candidate" in captured.out
        assert "draft candidate" not in captured.out


class TestLearningApprove:
    def test_approve_valid(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        cid = store.insert_candidate(
            LearningCandidate(
                content="test approve",
                dedupe_hash="cli-a1",
                confidence=0.9,
                risk_level="low",
            )
        )
        cmd_learning_approve([str(cid)], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert f"Candidate {cid} approved" in captured.out

        candidate = engine.get_candidate(cid)
        assert candidate.state == "approved"

    def test_approve_nonexistent(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        with pytest.raises(SystemExit) as exc:
            cmd_learning_approve(["9999"], Path("/tmp/test-cli"), factory)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_approve_already_approved(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        cid = store.insert_candidate(
            LearningCandidate(
                content="test double approve",
                dedupe_hash="cli-a2",
                state="approved",
            )
        )
        with pytest.raises(SystemExit) as exc:
            cmd_learning_approve([str(cid)], Path("/tmp/test-cli"), factory)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestLearningReject:
    def test_reject_valid(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        cid = store.insert_candidate(
            LearningCandidate(
                content="test reject",
                dedupe_hash="cli-r1",
                confidence=0.9,
                risk_level="low",
            )
        )
        cmd_learning_reject([str(cid), "--reason", "not relevant"], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert f"Candidate {cid} rejected" in captured.out

        candidate = engine.get_candidate(cid)
        assert candidate.state == "rejected"

    def test_reject_missing_reason(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        cid = store.insert_candidate(LearningCandidate(content="test", dedupe_hash="cli-r2"))
        with pytest.raises(SystemExit) as exc:
            cmd_learning_reject([str(cid)], Path("/tmp/test-cli"), factory)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err or "reason is required" in captured.err.lower()


class TestLearningIngest:
    def test_ingest_without_approval(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        cid = store.insert_candidate(
            LearningCandidate(
                content="test ingest block",
                dedupe_hash="cli-i1",
                state="draft",
            )
        )
        with pytest.raises(SystemExit) as exc:
            cmd_learning_ingest([str(cid)], Path("/tmp/test-cli"), factory)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestLearningExport:
    def test_export_creates_file(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        store = engine.get_store()
        assert store is not None
        from aios.learning.models import LearningCandidate

        store.insert_candidate(
            LearningCandidate(
                content="exported convention",
                suggested_type="convention",
                confidence=0.9,
                risk_level="low",
                dedupe_hash="cli-e1",
                state="approved",
            )
        )
        store.insert_candidate(
            LearningCandidate(
                content="exported pattern",
                suggested_type="pattern",
                confidence=0.85,
                risk_level="low",
                dedupe_hash="cli-e2",
                state="ingested",
            )
        )
        store.insert_candidate(
            LearningCandidate(
                content="should not appear",
                suggested_type="mistake",
                dedupe_hash="cli-e3",
                state="draft",
            )
        )

        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "export.md")
            cmd_learning_export(["--out", out], Path("/tmp/test-cli"), factory)
            captured = capsys.readouterr()
            assert "Exported 2 candidates" in captured.out

            result = Path(out).read_text()
            assert "exported convention" in result
            assert "exported pattern" in result
            assert "should not appear" not in result

    def test_export_empty(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        cmd_learning_export([], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert "No approved" in captured.out


class TestLearningDispatch:
    def test_no_subcommand_shows_usage(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        cmd_learning([], Path("/tmp/test-cli"), factory)
        captured = capsys.readouterr()
        assert "Usage" in captured.out or "Subcommands" in captured.out

    def test_unknown_subcommand(self, capsys, engine_and_factory) -> None:
        engine, factory = engine_and_factory
        with pytest.raises(SystemExit) as exc:
            cmd_learning(["nonexistent"], Path("/tmp/test-cli"), factory)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Unknown" in captured.err
