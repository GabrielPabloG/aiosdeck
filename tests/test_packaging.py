"""Packaging invariant: the config loader's YAML support must be guaranteed.

``ConfigLoader`` reads ``.aios/project.yaml`` and the user config through
PyYAML. When PyYAML was only an incidental dev-venv package, installed
distributions (e.g. pipx) silently skipped every YAML source and the whole
stack degraded to dataclass defaults. ``[project].dependencies`` must
declare PyYAML so every install environment loads the manifest.
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


def test_pyproject_declares_pyyaml_dependency():
    data = tomllib.loads(PYPROJECT.read_text())
    dependencies = data["project"].get("dependencies", [])
    declared = [dep for dep in dependencies if dep.lower().startswith("pyyaml")]
    assert declared, f"PyYAML must be a [project] dependency, got: {dependencies}"
