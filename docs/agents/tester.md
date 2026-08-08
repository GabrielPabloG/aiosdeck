# Tester Agent

**Status**: Proposed
**Date**: 2026-08-02
**Introduced**: v0.6

## Context

The Tester agent runs the project's test suite and reports results. It is part of the Quality Pipeline (v0.6) but exists as a standalone agent so it can be invoked independently — both as a pipeline gate and as a manual `aios /test` workflow.

The Tester does not write tests. It only executes existing tests. Test generation is the Coder's responsibility (when the Planner creates a test task).

## Decision

### In → Process → Out

```
In:  Task (type: "test", payload: {files: ["tests/test_auth.py"], command: "pytest"})
     Context Packet (language, test runner, test configuration)
     Skills: []

Process:
  1. Load project test configuration from Context Packet
  2. Execute test command (pytest, vitest, cargo test, bats, ...)
  3. Parse test output: pass/fail, failures, coverage
  4. Report structured results

Out: AgentResult with test report
```

### Output Format

```python
{
    "command": "pytest tests/test_auth.py -v",
    "exit_code": 1,
    "status": "failed",  # passed, failed, error
    "total": 12,
    "passed": 11,
    "failed": 1,
    "errors": 0,
    "skipped": 0,
    "duration_ms": 4500,
    "coverage": None,  # Future: coverage percentage
    "failures": [
        {
            "test": "test_oauth2_token_refresh",
            "file": "tests/test_auth.py",
            "line": 87,
            "message": "AssertionError: Expected 200, got 401",
            "traceback": "...",
        },
    ],
}
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: test) | Consumed | Receive a test task |
| `agent.completed` | Emitted | Test run complete (even if tests failed) |
| `task.created` (type: code) | Emitted | If tests failed, create fix task |

### Required Capabilities

- `filesystem_read` — to read test files and configuration
- `filesystem_write` — to store test results (optional)
- `shell` — to execute test commands

### Cannot

- Write application code
- Execute Git commands
- Access the internet
- Modify test files

### Required Skills

- (none required — test execution does not need domain knowledge)

### Future (v0.8+)

- Coverage reporting with thresholds
- Test selection: only run tests affected by changed files
- Flaky test detection via Memory Engine (test that fails inconsistently)
- Parallel test execution for large suites

## Consequences

### Positive

- **Automated verification**: Every code change is tested without manual effort.
- **Structured output**: Test results are machine-readable. The Quality Pipeline consumes them.
- **Tool detection**: Test runner is auto-detected. No configuration.

### Negative

- **Execution time**: Large test suites take minutes.
- **Environment dependency**: Tests may require database, services, or configurations.
- **False negatives**: Environment issues (missing Docker) → test runner error, not test failure.

### Neutral

- The Tester reports failures. It does not fix them. That is the Coder's job.
- Test execution is synchronous within the Quality Pipeline. Parallel test execution is future work.

## Implementation Notes

- [ ] Implement `agents/tester.py` — TesterAgent class
- [ ] Test runner auto-detection: use Context Packet to determine correct command
- [ ] Test output parsing: support pytest, vitest, jest, cargo test, bats, go test
- [ ] If tests fail → emit `task.created` (type: code) with failure details
- [ ] Test command must run within ai-jail sandbox
- [ ] Timeout: tests running longer than configurable limit are terminated
- [ ] Test: clean suite → passed status
- [ ] Test: failing test → failed status, fix task created
- [ ] Test: missing test runner → error, agent reports gracefully
