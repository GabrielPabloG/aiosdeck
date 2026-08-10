# Git Agent

**Status**: Implemented
**Review date**: 2026-08-09
**Date**: 2026-08-02
**Introduced**: v0.7

## Context

Version control operations — commit, push, tag, branch — are destructive by nature. A bad commit message is recoverable. A force-push to main is not. The Git agent is the **only agent** with Git permissions. No other agent can stage, commit, push, or tag.

This constraint is enforced by the Security Manager. The Developer writes code. The Reviewer approves it. The Tester verifies it. Only then does the Git agent commit and push — and even then, push requires human approval.

## Decision

### In → Process → Out

```
In:  Task (type: "git", payload: {
       action: "commit",
       files: ["src/auth/provider.py", "tests/test_auth.py"],
       message: "feat: add OAuth2 provider integration",
       workflow_context: "feature/add-oauth2-login"
     })
     Context Packet (branch, remote, git status)
     Skills: []

Process:
  1. Stage specified files (git add)
  2. Create commit with conventional message (git commit)
  3. Optionally push (git push, requires approval gate)
  4. Report commit hash and status

Out: AgentResult with git operation results
```

### Allowed Commands

| Command | Requires Approval | Description |
|---------|:---:|-------------|
| `git add` | No | Stage files for commit |
| `git commit` | No | Create a commit |
| `git push` | **Yes** | Push to remote |
| `git push --force` | **Yes** | Force push (rare) |
| `git tag` | **Yes** | Create a tag |
| `git branch` | No | Create a branch |
| `git checkout` | No | Switch branches |
| `git status` | No | Check repository status |
| `git log` | No | View commit history |

### Output Format

```python
{
    "action": "commit",
    "status": "success",
    "commit_hash": "abc1234def5678",
    "branch": "feature/add-oauth2-login",
    "files_changed": 2,
    "message": "feat: add OAuth2 provider integration",
    "pushed": False,  # Push requires separate action
}
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: git) | Consumed | Receive a git task |
| `agent.completed` | Emitted | Git operation complete |
| `security.approval_requested` | Emitted | Destructive action (push, force-push, tag) |

### Required Capabilities

- `filesystem_read` — to read repository status
- `shell` — to execute git commands
- `git` — special capability for git operations

### Cannot

- Write application code
- Access the internet
- Run non-git shell commands

### Required Skills

- (none required — git operations are mechanical)

### Commit Convention

Git agent enforces Conventional Commits:

```
feat: add OAuth2 provider integration
fix: resolve token refresh race condition
docs: document OAuth2 setup process
test: add integration tests for auth flow
refactor: extract token validation logic
chore: update dependencies
```

### Future (v0.9+)

- Automatic changelog generation from commit history
- Semantic versioning based on commit types
- Pre-commit hook integration (run quality gates before commit)
- PR creation and management (GitHub integration)

## Consequences

### Positive

- **Safety**: Only one agent has Git access. Push requires human approval.
- **Convention enforcement**: All commits follow Conventional Commits format.
- **Auditability**: Every git action is logged with agent and timestamp.
- **Isolation**: Git access is a capability, not a default. Agents without it cannot touch version control.

### Negative

- **Approval friction**: Push requires human interaction. Slows down automated workflows.
- **Limited scope**: Git agent handles basic operations. Complex rebase/cherry-pick workflows are manual.
- **Single point of git access**: If the Git agent is unavailable, no commits can be created.

### Neutral

- Git agent is introduced at v0.7, after the Quality Pipeline. Only approved code is committed.
- Push approval can be automated for specific branches (e.g., feature branches) in future configurations.

## Implementation Notes

- [ ] Implement `agents/git.py` — GitAgent class
- [ ] Allowed commands whitelist: only commands in the table above
- [ ] Push, force-push, tag → emit `security.approval_requested` before execution
- [ ] Commit message must follow Conventional Commits format
- [ ] File staging: only stage files that exist and were changed by the Developer
- [ ] Git agent must verify repository is not in detached HEAD state before committing
- [ ] Test: commit → files staged, commit created, hash returned
- [ ] Test: push → approval requested → approved → push executes
- [ ] Test: push → approval denied → push not executed
- [ ] Test: force-push → approval required (higher severity)
