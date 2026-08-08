"""Tests for knowledge CLI commands."""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from aios.core import Kernel
from aios.knowledge.cli import (
    cmd_knowledge_index,
    cmd_knowledge_search,
    cmd_knowledge_sources,
)
from aios.knowledge.engine import KnowledgeEngine


class TestKnowledgeCLIIndex:
    def test_index_command(self, tmp_path, capsys):
        engine = KnowledgeEngine(project_path=tmp_path)
        engine.initialize()

        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(engine)

        cmd_knowledge_index([], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        assert "Indexing Knowledge" in captured.out

        engine.shutdown()

    def test_index_unavailable_engine(self, tmp_path, capsys):
        kernel = Kernel(project_path=str(tmp_path))
        with patch.object(kernel, "start", lambda: None):
            cmd_knowledge_index([], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        assert "Knowledge engine not available" in captured.out


class TestKnowledgeCLISearch:
    def test_search_command_json_output(self, tmp_path, capsys):
        engine = KnowledgeEngine(project_path=tmp_path)
        engine.initialize()
        engine.index()

        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(engine)

        cmd_knowledge_search(["architecture", "--json"], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)

        engine.shutdown()

    def test_search_no_query(self, tmp_path, capsys):
        kernel = Kernel(project_path=str(tmp_path))
        with (
            patch.object(kernel, "start", lambda: None),
            patch("sys.exit", side_effect=SystemExit(1)),
            contextlib.suppress(SystemExit),
        ):
            cmd_knowledge_search([], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        assert "Usage:" in captured.out or "Usage:" in captured.err

    def test_search_unavailable_engine(self, tmp_path, capsys):
        kernel = Kernel(project_path=str(tmp_path))
        with patch.object(kernel, "start", lambda: None):
            cmd_knowledge_search(["test"], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        assert "Knowledge engine not available" in captured.out


class TestKnowledgeCLISources:
    def test_sources_command(self, tmp_path, capsys):
        engine = KnowledgeEngine(project_path=tmp_path)
        engine.initialize()
        engine.index()

        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(engine)

        cmd_knowledge_sources([], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        assert "Knowledge Sources" in captured.out or "No knowledge sources" in captured.out

        engine.shutdown()

    def test_sources_json_output(self, tmp_path, capsys):
        engine = KnowledgeEngine(project_path=tmp_path)
        engine.initialize()

        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(engine)

        cmd_knowledge_sources(["--json"], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)

        engine.shutdown()

    def test_sources_unavailable_engine(self, tmp_path, capsys):
        kernel = Kernel(project_path=str(tmp_path))
        with patch.object(kernel, "start", lambda: None):
            cmd_knowledge_sources([], Path(tmp_path), lambda p: kernel)
        captured = capsys.readouterr()
        assert "Knowledge engine not available" in captured.out


def test_knowledge_cli_help(tmp_path):
    result = subprocess.run(
        ["aios", "knowledge"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode != 0 or "knowledge" in (result.stdout + result.stderr).lower()


def test_knowledge_sources_no_index(tmp_path):
    result = subprocess.run(
        ["aios", "knowledge", "sources"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "Run 'aios knowledge index'" in output or "No knowledge sources" in output
