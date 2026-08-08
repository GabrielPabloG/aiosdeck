"""Tests for DocumentationAgent — changelog fragment generation."""

from datetime import UTC, datetime
from unittest.mock import Mock

from aios.agents.documentation import DocumentationAgent

SAMPLE_REPORT = {
    "summary": {"passed": 1},
    "items": [{"severity": "warning", "file": "a.py", "line": 1, "message": "todo"}],
}


def test_documentation_agent_capabilities():
    assert "filesystem_read" in DocumentationAgent.required_capabilities
    assert "filesystem_write" in DocumentationAgent.required_capabilities
    assert "shell" not in DocumentationAgent.required_capabilities


def test_generate_changelog_fragment_dry_run(tmp_path):
    docs_dir = tmp_path / "docs"
    agent = DocumentationAgent(docs_dir=str(docs_dir))

    fragment = agent._generate_changelog_fragment(SAMPLE_REPORT, dry_run=True)

    assert fragment.written is False
    assert "passed: 1" in fragment.preview
    assert "a.py:1" in fragment.preview
    assert "todo" in fragment.preview
    assert not docs_dir.exists()


def test_generate_changelog_fragment_writes_file(tmp_path, monkeypatch):
    mock_datetime = Mock()
    mock_datetime.now.return_value = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("aios.agents.documentation.datetime", mock_datetime)

    docs_dir = tmp_path / "docs"
    agent = DocumentationAgent(docs_dir=str(docs_dir))

    fragment = agent._generate_changelog_fragment(SAMPLE_REPORT, dry_run=False)

    assert fragment.written is True
    assert fragment.path == docs_dir / "changelog-fragment-20260807-120000.md"
    assert fragment.path.read_text(encoding="utf-8") == fragment.preview


def test_generate_changelog_fragment_creates_docs_dir(tmp_path):
    docs_dir = tmp_path / "docs" / "nested"
    agent = DocumentationAgent(docs_dir=str(docs_dir))

    fragment = agent._generate_changelog_fragment(SAMPLE_REPORT, dry_run=False)

    assert fragment.written is True
    assert docs_dir.exists()
    fragments = list(docs_dir.glob("changelog-fragment-*.md"))
    assert len(fragments) == 1
