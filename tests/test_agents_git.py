"""Tests for GitAgent — local git operations and push approval guard."""

import os
import subprocess

from aios.agents.git import GitAgent


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    return repo


def _git(repo) -> GitAgent:
    return GitAgent(repository=repo)


def test_git_agent_capabilities():
    assert GitAgent.required_capabilities == ["git"]


def test_stage(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")

    result = _git(repo)._stage()

    assert result.executed is True
    assert result.returncode == 0
    diff = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "hello" in diff.stdout


def test_commit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    agent = _git(repo)

    agent._stage()
    result = agent._commit("Initial commit")

    assert result.executed is True
    assert result.returncode == 0
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Initial commit" in log.stdout


def test_create_tag(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    agent = _git(repo)

    agent._stage()
    agent._commit("Initial commit")
    result = agent._create_tag("v0.1.0")

    assert result.executed is True
    assert result.returncode == 0
    tags = subprocess.run(
        ["git", "tag"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "v0.1.0" in tags.stdout


def test_create_branch(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    agent = _git(repo)

    agent._stage()
    agent._commit("Initial commit")
    result = agent._create_branch("feature/add-health-endpoint-1")

    assert result.executed is True
    assert result.returncode == 0
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert branch.stdout.strip() == "feature/add-health-endpoint-1"


def test_push_requires_approval(tmp_path):
    result = GitAgent(repository=tmp_path)._push(approved=False)

    assert result.executed is False
    assert result.command == ["git", "push"]
    assert result.returncode == 0


def _init_with_commit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo)._stage()
    _git(repo)._commit("init")
    return repo


def test_changed_files_tracked_modification(tmp_path):
    repo = _init_with_commit(tmp_path)
    (repo / "src" / "base.py").write_text("x = 2\n", encoding="utf-8")

    assert _git(repo)._changed_files() == ["src/base.py"]


def test_changed_files_untracked_with_spaces(tmp_path):
    repo = _init_with_commit(tmp_path)
    (repo / "src" / "new file.py").write_text("y = 1\n", encoding="utf-8")

    assert _git(repo)._changed_files() == ["src/new file.py"]


def test_changed_files_rename_reports_new_path(tmp_path):
    repo = _init_with_commit(tmp_path)
    os.rename(repo / "src" / "base.py", repo / "src" / "renamed.py")
    _git(repo)._stage()

    assert _git(repo)._changed_files() == ["src/renamed.py"]


def test_changed_files_excludes_deletion(tmp_path):
    repo = _init_with_commit(tmp_path)
    for p in (repo / "src").glob("*.py"):
        p.unlink()

    assert _git(repo)._changed_files() == []


def test_changed_files_clean_tree(tmp_path):
    repo = _init_with_commit(tmp_path)

    assert _git(repo)._changed_files() == []
