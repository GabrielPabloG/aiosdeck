# Reviewer Agent

**Status**: Draft
**Date**: 2026-08-02
**Introduced**: v0.5

## Context

Code generation without review is dangerous. The Reviewer agent critiques agent output — checking for correctness, security, performance, style, and architectural alignment. It does not write code. It only reads, analyzes, and reports.

The Reviewer is the first agent that introduces a feedback loop: `write → review → fix → review`. This loop is the foundation of the Quality Pipeline (v0.6).

## Decision

### In → Process → Out

```
In:  Task (type: "review", payload: {files: ["src/auth/provider.py"], context: "OAuth2 implementation review"})
     Context Packet (language, framework, conventions, architecture)
     Skills: ["project-dna", "coding-style"]

Process:
  1. Load project DNA (conventions, patterns, architecture)
  2. Read changed files
  3. Analyze against checklist:
     - Security: secrets, injection, unsafe operations
     - Performance: N+1 queries, memory leaks, blocking operations
     - Architecture: module boundaries, dependency direction
     - Style: naming, organization, conventions
     - Correctness: logic errors, edge cases, error handling
  4. Produce structured review with findings and severity

Out: AgentResult with review report
```

### Output Format

```python
{
    "files_reviewed": ["src/auth/provider.py"],
    "findings": [
        {
            "severity": "error",
            "category": "security",
            "file": "src/auth/provider.py",
            "line": 42,
            "message": "Client secret hardcoded in source code",
            "suggestion": "Use environment variable or Secret Manager",
        },
        {
            "severity": "warning",
            "category": "style",
            "file": "src/auth/provider.py",
            "line": 15,
            "message": "Function name 'getUserData' does not follow snake_case convention",
            "suggestion": "Rename to 'get_user_data'",
        },
        {
            "severity": "info",
            "category": "architecture",
            "message": "Auth module depends on database module directly. Consider dependency injection.",
            "suggestion": "Inject database session, do not import database module in auth module",
        },
    ],
    "summary": "1 error, 1 warning, 1 info found in 1 file",
    "verdict": "changes_requested",  # approved, changes_requested, commented
}
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: review) | Consumed | Receive a review task |
| `agent.completed` | Emitted | Review complete |
| `task.created` (type: code) | Emitted | If changes requested, create fix task |

### Required Capabilities

- `filesystem_read` — to read code for review

### Cannot

- Write code
- Execute Git commands
- Access the internet
- Run shell commands
- Modify files

### Required Skills

- `project-dna` — must understand project conventions and architecture
- `coding-style` — must evaluate code against project style rules

### Future (v0.8+)

- Historical pattern detection: "this pattern caused bugs in the past" (Memory Engine)
- Automated fix suggestions: Review produces a fix task with precise instructions
- Cross-review: Reviewer critiques the Planner's task decomposition

## Consequences

### Positive

- **Quality feedback loop**: Every code change is reviewed before acceptance.
- **Security enforcement**: Hardcoded secrets, injection vectors caught at review time.
- **Style consistency**: Codebase maintains consistent conventions automatically.
- **Audit trail**: Review reports are stored in Memory Engine for trend analysis.

### Negative

- **Latency**: Review adds a full agent cycle after coding.
- **False positives**: Reviewer may flag patterns that are intentional trade-offs.
- **Context limitations**: Reviewer analyzes individual files, not the full system impact.

### Neutral

- Review is advisory. The human developer can override any finding.
- The Reviewer is introduced at v0.5, before the Quality Pipeline. It lays the foundation.

## Implementation Notes

- [ ] Implement `agents/reviewer.py` — ReviewerAgent class
- [ ] Review checklist must be configurable (add/remove categories)
- [ ] Severity levels: error (must fix), warning (should fix), info (consider)
- [ ] Verdict: approved, changes_requested, commented
- [ ] If changes requested → emit `task.created` (type: code) with fix instructions
- [ ] Reviewer must never write files, only read
- [ ] Test: code with hardcoded secret → error finding
- [ ] Test: code with wrong naming convention → warning finding
- [ ] Test: clean code → approved verdict, no fix task created
