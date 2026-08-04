"""Tests for aios init — project initialization command."""

import subprocess

from aios.cli.commands import COMMANDS, Command


def test_init_is_registered_in_commands():
    assert "init" in COMMANDS, "COMMANDS missing: init"
    cmd = COMMANDS["init"]
    assert isinstance(cmd, Command)
    assert cmd.execute is not None
    assert cmd.hidden is False
    assert cmd.aliases == []


def test_init_creates_aios_directory(tmp_path):
    result = subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert (tmp_path / ".aios").is_dir()


def test_init_creates_project_yaml(tmp_path):
    result = subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    yaml_path = tmp_path / ".aios" / "project.yaml"
    assert yaml_path.exists()
    content = yaml_path.read_text()
    assert "name:" in content
    assert "runtime:" in content
    assert "skills:" in content


def test_init_creates_gitignore_when_missing(tmp_path):
    result = subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert ".aios/memory.db" in content


def test_init_appends_to_existing_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n.env\n")
    result = subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    content = (tmp_path / ".gitignore").read_text()
    lines = content.splitlines()
    assert "*.log" in lines
    assert ".env" in lines
    assert ".aios/memory.db" in lines


def test_init_is_idempotent_no_duplicate_rules(tmp_path):
    subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    content = (tmp_path / ".gitignore").read_text()
    count = content.count(".aios/memory.db")
    assert count == 1


def test_init_shows_success_message(tmp_path):
    result = subprocess.run(
        ["aios", "init"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    output = result.stdout + result.stderr
    assert "initialized" in output.lower() or "created" in output.lower()
