"""End-to-end proof: the jailed build agent writes files (opt-in manual gate).

Runs the real ``ai-jail opencode`` stack against a disposable directory.
Skipped unless both binaries exist AND ``AIOS_E2E_RUNTIME`` is enabled, so
the regular suite stays fast, deterministic and CI-safe.
"""

import os
import pathlib
import shutil

import pytest

from aios.runtime.opencode import OpenCodeAdapter

requires_runtime = pytest.mark.skipif(
    not shutil.which("opencode")
    or not shutil.which("ai-jail")
    or os.environ.get("AIOS_E2E_RUNTIME", "").lower() not in {"1", "true", "yes"},
    reason="requires opencode + ai-jail on PATH and AIOS_E2E_RUNTIME=1",
)


@requires_runtime
def test_build_agent_creates_file_in_disposable_dir(monkeypatch):
    """Write-capable execution must produce a real file inside the jail.

    ai-jail only allows writes inside this repository, so the disposable
    directory is created under the repo root (and removed afterwards). The
    probe uses a relative target path from within it.
    """
    original_cwd = os.getcwd()
    probe_dir = os.path.join(original_cwd, f".e2e-opencode-probe-{os.getpid()}")
    os.mkdir(probe_dir)
    try:
        monkeypatch.chdir(probe_dir)
        adapter = OpenCodeAdapter()
        adapter.initialize()

        output = adapter.execute(
            "Create a file named aios_e2e_probe.txt containing exactly one line: OK",
            skills=[],
            capabilities=["filesystem_read", "filesystem_write", "shell"],
        )

        target = os.path.join(probe_dir, "aios_e2e_probe.txt")
        assert os.path.exists(target), f"file was not created; agent replied: {output[:200]}"
        assert "OK" in pathlib.Path(target).read_text(encoding="utf-8")
    finally:
        monkeypatch.chdir(original_cwd)
        shutil.rmtree(probe_dir, ignore_errors=True)
