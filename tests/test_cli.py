import subprocess


def test_help():
    result = subprocess.run(["aios", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_no_args_shows_help():
    result = subprocess.run(["aios"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_invalid_command():
    result = subprocess.run(["aios", "nonexistent"], capture_output=True, text=True, check=False)
    assert result.returncode != 0


def test_start_runs():
    result = subprocess.run(
        ["aios", "start", "--project", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output
    assert "Healthy" in output
