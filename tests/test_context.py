from aios.context.collectors.javascript import JavaScriptDetector
from aios.context.collectors.python import PythonDetector
from aios.context.collectors.shell import ShellDetector


def test_python_detector(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    result = PythonDetector.detect(tmp_path)
    assert result is not None
    project, tools = result
    assert project.language == "python"


def test_python_detector_no_match(tmp_path):
    result = PythonDetector.detect(tmp_path)
    assert result is None


def test_python_detector_subdir_py_only(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app.py").write_text("print('hello')")
    result = PythonDetector.detect(tmp_path)
    assert result is not None
    project, _ = result
    assert project.language == "python"


def test_python_detector_skips_venv(tmp_path):
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "app.py").write_text("print('hello')")
    result = PythonDetector.detect(tmp_path)
    assert result is None


def test_python_detector_subdir_with_requirements(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n")
    (tmp_path / "backend" / "main.py").write_text("from fastapi import FastAPI")
    result = PythonDetector.detect(tmp_path)
    assert result is not None
    project, tools = result
    assert project.language == "python"


def test_javascript_detector(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name":"test","devDependencies":{"eslint":"^9","prettier":"^3","vitest":"^1"}}'
    )
    result = JavaScriptDetector.detect(tmp_path)
    assert result is not None
    project, tools = result
    assert project.language == "javascript"
    assert tools.linter == "eslint"
    assert tools.formatter == "prettier"
    assert tools.test_runner == "vitest"


def test_javascript_typescript_detection(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"test"}')
    (tmp_path / "tsconfig.json").write_text("{}")
    result = JavaScriptDetector.detect(tmp_path)
    assert result is not None
    project, _ = result
    assert project.language == "typescript"


def test_shell_detector(tmp_path):
    (tmp_path / "script.sh").write_text("#!/bin/bash\necho hello\n")
    result = ShellDetector.detect(tmp_path)
    assert result is not None
    project, tools = result
    assert project.language == "shell"
    assert tools.linter == "shellcheck"
    assert tools.formatter == "shfmt"
    assert tools.test_runner == "bats"


def test_shell_detector_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tbats tests/\n")
    result = ShellDetector.detect(tmp_path)
    assert result is not None
    project, _ = result
    assert project.language == "shell"


# ---------------------------------------------------------------------------
# Cycle 1 contract test — ContextPacket.to_dict
# ---------------------------------------------------------------------------


def test_context_packet_to_dict_has_all_keys():
    from aios.context.packet import (
        ContextPacket,
        DockerInfo,
        GitInfo,
        ProjectInfo,
        RuntimeInfo,
        StructureInfo,
        ToolsInfo,
    )

    ctx = ContextPacket(
        project=ProjectInfo(name="test", root="/tmp", language="python"),
        tools=ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest"),
        git=GitInfo(
            branch="main",
            status="clean",
            remote="origin",
            last_commit="abc",
            last_commit_message="init",
        ),
        docker=DockerInfo(installed=True, running=False, compose_files=["docker-compose.yml"]),
        runtime=RuntimeInfo(opencode=True, ai_jail=False),
        structure=StructureInfo(
            has_readme=True, has_license=True, has_tests_dir=True, has_docs_dir=False
        ),
        skills=["project-dna"],
        research={"key": "val"},
    )
    data = ctx.to_dict()

    assert set(data.keys()) == {
        "project",
        "tools",
        "git",
        "docker",
        "runtime",
        "structure",
        "skills",
        "memory",
        "research",
        "timestamp",
    }
    assert data["project"]["name"] == "test"
    assert data["project"]["root"] == "/tmp"
    assert data["project"]["language"] == "python"
    assert data["tools"]["linter"] == "ruff"
    assert data["tools"]["formatter"] == "ruff"
    assert data["tools"]["test_runner"] == "pytest"
    assert data["tools"]["dependency_manager"] == ""
    assert data["git"]["branch"] == "main"
    assert data["git"]["status"] == "clean"
    assert data["git"]["remote"] == "origin"
    assert data["git"]["last_commit"] == "abc"
    assert data["git"]["last_commit_message"] == "init"
    assert data["docker"]["installed"] is True
    assert data["docker"]["running"] is False
    assert data["docker"]["compose_files"] == ["docker-compose.yml"]
    assert data["runtime"]["opencode"] is True
    assert data["runtime"]["ai_jail"] is False
    assert data["structure"]["has_readme"] is True
    assert data["structure"]["has_license"] is True
    assert data["structure"]["has_tests_dir"] is True
    assert data["structure"]["has_docs_dir"] is False
    assert data["skills"] == ["project-dna"]
    assert data["research"] == {"key": "val"}
    assert "timestamp" in data
