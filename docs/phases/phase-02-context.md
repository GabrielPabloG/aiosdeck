# Phase 02 — Context Engine

**Status**: Accepted
**Date**: 2026-08-02
**Target Version**: v0.1

## Context

The Context Engine is the sensory organ of AiosDeck. It detects everything about a project that an agent needs to produce high-quality output — language, framework, tools, conventions, dependencies, structure. This information is assembled before any agent prompt and injected automatically.

The principle is: **detect, do not ask**. If the project has a `pyproject.toml`, the Context Engine knows it is Python and knows which linter, formatter, and test runner are configured. No user prompt. No configuration wizard.

## Decision

### Architecture

```
Context Engine
   │
   ├── Detectors (per-language, per-tool)
   │     ├── PythonDetector
   │     ├── JavaScriptDetector
   │     ├── RustDetector
   │     ├── ShellDetector
   │     ├── GoDetector
   │     └── ... (extensible)
   │
   ├── Project Manifest Loader
   │     └── Reads .aios/project.yaml if present
   │
   ├── Context Assembler
   │     └── Merges detected + manifest + session context
   │
   └── Output: Context Packet (dict)
```

### Detection Pipeline

The Context Engine runs detectors in priority order. The first detector that returns a positive match wins. Each detector inspects specific files to determine language and tooling.

```
1. Check .aios/project.yaml → if present, load override values
2. Run detectors in order:
   a. PythonDetector    (checks pyproject.toml, setup.py, requirements.txt)
   b. JavaScriptDetector (checks package.json, tsconfig.json)
   c. RustDetector      (checks Cargo.toml)
   d. ShellDetector     (checks for .sh files, Makefile, shellcheck config)
   e. GoDetector        (checks go.mod)
3. If no detector matches → generic context (Git, filesystem structure only)
```

### Context Packet Format

The output of the Context Engine is a standardized dictionary:

```python
{
    "project": {
        "name": "my-project",          # from .aios/project.yaml or directory name
        "root": "/path/to/project",
        "language": "python",          # detected
    },
    "tools": {
        "dependency_manager": "uv",    # detected: uv, pip, poetry, npm, cargo
        "linter": "ruff",             # detected: ruff, eslint, clippy, shellcheck
        "formatter": "black",         # detected: black, prettier, cargo fmt, shfmt
        "test_runner": "pytest",      # detected: pytest, vitest, jest, bats, cargo test
    },
    "git": {
        "branch": "main",
        "status": "clean",            # clean, dirty, untracked
        "remote": "origin",
        "last_commit": "abc1234",
        "last_commit_message": "feat: add user authentication",
    },
    "docker": {
        "present": true,              # docker-compose.yml or Dockerfile found
        "running": false,
        "compose_files": ["docker-compose.yml"],
    },
    "opencode": {
        "installed": true,
        "skills": ["project-dna", "coding-style", "bash-style"],
        "config_present": true,
    },
    "ai_jail": {
        "installed": true,
        "policies": ["default.yaml"],
    },
    "structure": {
        "has_readme": true,
        "has_license": true,
        "has_tests_dir": true,
        "has_docs_dir": true,
    },
    "timestamp": "2026-08-02T14:00:00Z",
}
```

### Language-Specific Detectors

Each detector inspects a small set of signature files:

| Detector | Signature Files | Extracts |
|----------|----------------|----------|
| PythonDetector | `pyproject.toml`, `setup.py`, `requirements.txt` | language, dep manager, linter, formatter, test runner |
| JavaScriptDetector | `package.json`, `tsconfig.json` | language, runtime, dep manager, linter, formatter, test runner |
| RustDetector | `Cargo.toml` | language, dep manager, linter, formatter, test runner |
| ShellDetector | `*.sh` files, `Makefile`, `.shellcheckrc` | language, linter, formatter, test runner |
| GoDetector | `go.mod` | language, dep manager, test runner |

MVP (v0.1) ships with PythonDetector, JavaScriptDetector, and ShellDetector. Other detectors are added incrementally.

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `context.detected` | Emitted | Context packet ready. Published after detection completes. |
| `context.error` | Emitted | Detection failed for a specific detector. Non-fatal. |
| `session.start` | Consumed | Triggers detection pipeline on session start. |
| `memory.loaded` | Consumed | After memory is restored, enriches context with prior knowledge. |

### Configuration Override

The `.aios/project.yaml` manifest can override detected values:

```yaml
# .aios/project.yaml
name: projdesk
language: bash          # Override detection
runtime: opencode

quality:
  lint: shellcheck      # Force specific tool
  format: shfmt
  tests: bats

skills:
  - project-dna
  - bash-style
  - semantic-command-tree

workflows:
  - feature
  - fix
  - review
```

Manifest values take precedence over detected values. If the manifest specifies `language: bash`, detectors are skipped for language detection (but still run for tools).

## Consequences

### Positive

- **Zero configuration**: v0.1 works out of the box with no configuration files.
- **Extensible**: Adding a new language requires only a new detector module.
- **Standardized output**: All agents receive the same context format, regardless of project type.
- **Override capability**: Project manifest allows manual control when detection is wrong.

### Negative

- **Detection is fragile**: A project with both `pyproject.toml` and `package.json` creates ambiguity.
- **Missing tools**: If a project lacks a configured linter, the `tools.linter` field is null. Agents must handle null values.
- **Startup latency**: Running all detectors adds time before the first interaction.

### Neutral

- Context is re-detected every session. Memory Engine (v0.3) adds persistence for patterns and conventions that survive across sessions.
- Detectors are Python classes, not configuration files. They are the source of truth for "what tools does this project use?"

## Implementation Notes

- [ ] Implement `context/engine.py` — orchestrates detectors, assembles context packet
- [ ] Implement `context/collectors/python.py` — detects Python project characteristics
- [ ] Implement `context/collectors/javascript.py` — detects JS/TS project characteristics
- [ ] Implement `context/collectors/shell.py` — detects Shell project characteristics
- [ ] Implement `.aios/project.yaml` loader — reads and validates manifest
- [ ] Context packet must be serializable to JSON for logging/debugging
- [ ] Each detector must return `None` (no match) or a partial context dict (match)
- [ ] Detectors must not throw exceptions. Errors are caught and logged at the engine level.
- [ ] Test: project with no config files → generic context still returns (Git, structure)
- [ ] Test: project with pyproject.toml → PythonDetector matches → correct tools inferred
- [ ] Test: project with .aios/project.yaml → manifest values override detected values
