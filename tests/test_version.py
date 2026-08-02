import subprocess

from aios import __version__


def test_version_is_string():
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_cli_version():
    result = subprocess.run(["aios", "--version"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert __version__ in result.stdout
