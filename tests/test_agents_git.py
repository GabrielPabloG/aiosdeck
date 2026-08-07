"""Tests for GitAgent — local git operations and push approval guard."""

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

    result = _git(repo).stage()

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

    agent.stage()
    result = agent.commit("Initial commit")

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

    agent.stage()
    agent.commit("Initial commit")
    result = agent.create_tag("v0.1.0")

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

    agent.stage()
    agent.commit("Initial commit")
    result = agent.create_branch("feature/add-health-endpoint-1")

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
    result = GitAgent(repository=tmp_path).push(approved=False)

    assert result.executed is False
    assert result.command == ["git", "push"]
    assert result.returncode == 0
