import subprocess


def test_help():
    result = subprocess.run(["aios", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_help_command():
    result = subprocess.run(["aios", "help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_no_args_shows_dashboard():
    result = subprocess.run(["aios"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output


def test_invalid_command():
    result = subprocess.run(["aios", "nonexistent"], capture_output=True, text=True, check=False)
    assert result.returncode != 0


def test_start_alias():
    result = subprocess.run(
        ["aios", "start", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output


def test_status_alias():
    result = subprocess.run(
        ["aios", "status", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output


def test_doctor():
    result = subprocess.run(
        ["aios", "doctor", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_memory_list(tmp_path):
    result = subprocess.run(
        ["aios", "memory", "list"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0


def test_memory_add_convention(tmp_path):
    result = subprocess.run(
        ["aios", "memory", "add", "convention", "Use snake_case"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Convention saved" in result.stdout or "convention saved" in result.stdout.lower()


def test_memory_add_unknown_type(tmp_path):
    result = subprocess.run(
        ["aios", "memory", "add", "invalid", "something"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Unknown type" in result.stdout


def test_memory_forget(tmp_path):
    subprocess.run(
        ["aios", "memory", "add", "convention", "ToDelete"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    result = subprocess.run(
        ["aios", "memory", "forget", "convention", "ToDelete"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0


def test_memory_search(tmp_path):
    subprocess.run(
        ["aios", "memory", "add", "convention", "UseSnakeCase"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    result = subprocess.run(
        ["aios", "memory", "search", "Snake"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0


def test_completion_top_level():
    result = subprocess.run(
        ["aios", "__complete", ""],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "doctor" in result.stdout
    assert "memory" in result.stdout
    assert "help" in result.stdout


def test_completion_memory_subcommands():
    result = subprocess.run(
        ["aios", "__complete", "", "memory"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "add" in result.stdout
    assert "forget" in result.stdout
    assert "list" in result.stdout
    assert "search" in result.stdout


def test_completion_memory_add_types():
    result = subprocess.run(
        ["aios", "__complete", "", "memory", "add"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "convention" in result.stdout
    assert "decision" in result.stdout


def test_completion_partial():
    result = subprocess.run(
        ["aios", "__complete", "m", ""],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "memory" in result.stdout
