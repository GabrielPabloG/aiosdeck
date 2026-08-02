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
