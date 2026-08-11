# Security Manager

**Status**: Accepted (Headless hardening in v0.6.1)
**Date**: 2026-08-04

## Context

AiosDeck agents execute code, access files, make network requests, and interact with version control. Without security boundaries, a misconfigured agent or a prompt injection attack could compromise the entire development environment.

The principle is: **security is architecture, not a feature**. Security is not a module added later. It is embedded in the kernel, the runtime, the agent model, and the event bus — in every component.

The Security Manager enforces zero-trust from day one. Every agent is untrusted until explicitly authorized. Every action is audited. Every boundary is enforced.

## Decision

### Architecture

```
                  Event Bus
                     │
                     ▼
              Security Manager
                     │
    ┌────────────────┼────────────────┐
    │                │                │
    ▼                ▼                ▼
Policy Engine   Capability       Secret
                Manager          Manager
    │                │                │
    ▼                ▼                ▼
Prompt          Approval         Audit
Firewall        Gates            Logger
```

### Sub-Components

#### Policy Engine

Evaluates whether an agent is authorized to perform an action. Policies are YAML files:

> **Note:** The complete policy schema below describes the intended policy
> file format. The runtime enforcement model (v0.9.8) is implemented in code:
> `IntentPolicy` (explicit action vocabulary) + coarse agent capabilities +
> a deterministic expansion table + the `effective_permissions` resolver.
> See **Intent vs Capability vs Enforcement** below.

```yaml
# aios/policies/agent_capabilities.yaml
agents:
  planner:
    capabilities: [filesystem_read]
    max_tokens: 8192

  coder:
    capabilities: [filesystem_read, filesystem_write, shell]
    max_tokens: 16384
    allowed_paths:
      - "."
      - "docs/"
      - "tests/"
    denied_paths:
      - "~/.ssh"
      - "~/.aws"
      - "/etc"

  reviewer:
    capabilities: [filesystem_read]
    max_tokens: 8192

  researcher:
    capabilities: [filesystem_read, internet]
    max_tokens: 16384

  git:
    capabilities: [filesystem_read, git]
    allowed_commands:
      - "git add"
      - "git commit"
      - "git push"
      - "git tag"

  tester:
    capabilities: [filesystem_read, shell]
    allowed_paths:
      - "."
      - "tests/"
```

Policy files are loaded from `aios/policies/` in the project directory. The Policy Engine evaluates agent requests against the applicable policy.

#### Capability Manager

Grants and revokes capabilities at runtime. Capabilities are fine-grained:

| Capability | Allows |
|-----------|--------|
| `filesystem_read` | Read files within allowed paths |
| `filesystem_write` | Create and modify files within allowed paths |
| `shell` | Execute shell commands |
| `internet` | Make network requests |
| `git` | Execute git commands |
| `docker` | Execute docker commands |

The Capability Manager evaluates each agent action:

```python
class CapabilityManager:
    async def authorize(self, agent: str, capability: str, resource: str = None) -> bool:
        policy = await self.policy_engine.get_policy(agent)
        if capability not in policy.capabilities:
            await self.audit.denied(agent, capability, resource)
            return False
        if resource and not self._is_allowed_path(policy, resource):
            await self.audit.denied(agent, capability, resource, "path_not_allowed")
            return False
        await self.audit.granted(agent, capability, resource)
        return True
```

#### Secret Manager

Manages secrets without exposing them to agents or prompts:

```python
class SecretManager:
    async def inject_secrets(self, runtime_context: dict) -> dict:
        # Inject secrets into runtime environment, not into prompts
        # Secrets are masked in logs and audit trails
        return {
            **runtime_context,
            "env": {
                "OPENAI_API_KEY": self._load("OPENAI_API_KEY"),
                "GITHUB_TOKEN": self._load("GITHUB_TOKEN"),
            },
        }
```

Secrets are loaded from environment variables or a secure vault. They are never included in prompts, never logged, and never stored in the Memory Engine.

#### Prompt Firewall

Sanitizes prompts before they reach the language model:

```python
class PromptFirewall:
    async def sanitize(self, prompt: str, agent: str) -> str:
        prompt = self._remove_secrets(prompt)  # Strip detected secrets
        prompt = self._block_injection(prompt)  # Detect prompt injection patterns
        prompt = self._enforce_length(prompt, agent)  # Truncate to policy max_tokens
        prompt = self._block_dangerous(prompt)  # Block known dangerous instructions
        prompt = self._inject_context(prompt, agent)  # Add mandatory safety context
        return prompt
```

The Firewall runs before every agent interaction. It is the last line of defense between an agent and the model.

#### Audit Logger

Records every security-relevant action:

```
[2026-08-02 14:20:01] agent=coder action=start_session status=allowed
[2026-08-02 14:20:05] agent=coder action=filesystem_write path=src/auth.py status=allowed
[2026-08-02 14:20:12] agent=coder action=shell command="ruff check ." status=allowed
[2026-08-02 14:20:15] agent=coder action=git status=denied reason="coder lacks git capability"
[2026-08-02 14:20:20] agent=coder action=filesystem_write path=~/.ssh/config status=denied reason="path_not_allowed"
```

The audit log is append-only and stored locally.

#### Approval Gates

Requires human confirmation for destructive operations:

```python
class ApprovalGate:
    DESTRUCTIVE_COMMANDS = [
        "git push",
        "git push --force",
        "docker rm",
        "docker system prune",
        "rm -rf",
        "DROP TABLE",
        "DELETE FROM",
    ]

    async def check(self, agent: str, action: str, resource: str) -> ApprovalResult:
        if self._is_destructive(action):
            await self.bus.publish("security.approval_requested", {...})
            response = await self._prompt_user(agent, action, resource)
            if response == "approve":
                await self.bus.publish("security.approval_granted", {...})
                return ApprovalResult.APPROVED
            else:
                await self.bus.publish("security.approval_denied", {...})
                return ApprovalResult.DENIED
        return ApprovalResult.NOT_REQUIRED
```

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `agent.started` | Consumed | Initialize agent security context |
| `agent.completed` | Consumed | Revoke agent capabilities |
| `security.violation` | Emitted | Capability check failed |
| `security.approval_requested` | Emitted | Destructive action needs confirmation |
| `security.approval_granted` | Emitted | User approved action |
| `security.approval_denied` | Emitted | User denied action |
| `session.start` | Consumed | Initialize security subsystems |
| `session.shutdown` | Consumed | Finalize audit log |

### v0.1 Scope vs Full Implementation

In v0.1, the Security Manager is a **skeleton**: it loads policy files, logs all events, and prepares the infrastructure. Full enforcement is implemented incrementally.

| Component | v0.1 (Foundation) | v0.6 (Full) |
|-----------|-------------------|-------------|
| Policy Engine | Load YAML policies | Evaluate and enforce |
| Capability Manager | Define capability model | Enforce at agent runtime |
| Secret Manager | Define secret model | Inject secrets into runtime env |
| Prompt Firewall | No-op (pass through) | Sanitize all prompts |
| Audit Logger | Log all events | Query and alert on anomalies |
| Approval Gates | No-op (allow all) | Intercept destructive actions |

## Consequences

### Positive

- **Defense in depth**: Multiple layers (policies, capabilities, firewall, ai-jail) protect the system.
- **Auditability**: Every security decision is logged with timestamp and context.
- **Configurable**: Policies are YAML files, not hard-coded rules.
- **Progressive enforcement**: v0.1 establishes the infrastructure. Enforcement tightens over time.

### Negative

- **Performance**: Every prompt passes through the Firewall. Every action passes through the Capability Manager. Adds latency.
- **Complexity**: Five sub-components with interdependent logic.
- **Configuration burden**: Policies must be written and maintained. Default policies cover common cases, but advanced use requires policy editing.

### Neutral

- Security is defense-in-depth. The Security Manager enforces application-level policies. ai-jail enforces OS-level sandboxing. OpenCode tool permissions (v0.6.1) add a runtime-level guard. No single layer replaces another.
- Approval Gates require a user interface. CLI prompts are the v0.6 implementation. Future versions may support non-interactive modes with pre-approved actions.

### Headless Tool Permission Hardening (v0.6.1)

When AiosDeck runs headless (no interactive terminal), any OpenCode tool that requires human input (e.g., `question`) causes a silent timeout. The `OPENCODE_PERMISSION` environment variable is injected before every `subprocess.run()` call to enforce tool-level controls directly at the runtime boundary:

```json
{
  "question": "deny"
}
```

The permission model is binary (`allow`/`deny`). No `ask` — there is no user to ask.

Permissions are derived from each agent's `required_capabilities`:
- **PlannerAgent** (`filesystem_read` only): `edit: deny`, `bash: deny`
- **DeveloperAgent** (`filesystem_write`, `shell`): full access except `question: deny`

This is enforced in `runtime/opencode.py` via `_build_permissions(capabilities)` and injected through the subprocess environment. Permissions are cached by capabilities set.

### Intent vs Capability vs Enforcement (v0.9.8)

**Status**: Implemented (v0.9.8)

Security is layered: an **intent** is what a run asks for, **capabilities**
are what an agent may do, and **enforcement** is where the two intersect and
are translated into runtime rules. All three live in `aios/security`:

| Layer | What | Where |
|-------|------|-------|
| Intent | Explicit granular action vocabulary of a run (`actions`, explicit `deny`) | `security/contracts.py` (`IntentPolicy`) |
| Capability | Coarse, per-agent grants (unchanged, 7 agents, YAML/compliance intact) | `agents/contracts.py` (`AgentCapabilities`) |
| Expansion | Additive, deterministic map of coarse capability → granular actions | `security/actions.py` (`CAPABILITY_ACTIONS`, `expand`) |
| Resolution | `effective = (intent.actions - intent.deny) ∩ expand(capabilities)` | `security/resolver.py` (`effective_permissions`, `decide`) |
| Enforcement | Run-gate at the executor boundary; opt-in per run | `agents/executor.py` |
| Runtime | Least-privilege `OPENCODE_PERMISSION` derived from effective permissions | `runtime/opencode.py` |
| Audit | `security.*` events → `telemetry_security` table (queryable allow/deny) | `agents/executor.py`, `telemetry/` |

Frozen semantics:

- **deny = absence (intersection).** An action must survive the intent
  (present in `actions`, absent from `deny`) AND be granted by the agent's
  coarse capability. Any absence in either layer denies.
- **Explicit deny wins.** `intent.deny` removes actions even when they are in
  `intent.actions` and granted by the capability.
- **Fail-safe.** An action not mapped in `CAPABILITY_ACTIONS` is never granted;
  an empty effective set is a structured `PERMISSION_DENIED` — never a silent
  fallback.
- **An intent can never elevate capabilities.** `develop` under a
  `filesystem_read`-only agent resolves to exactly `{filesystem.read}`.
- **Destructive actions are never implicit.** `filesystem.delete`, `git.push`,
  `git.tag`, `network.access`, and `release.publish` only enter through an
  explicit intent override. `release` has no default intent.
- **Safe defaults (pinned by tests).** `plan` → `{filesystem.read, ask_user}`,
  `review`/`research` → `{filesystem.read}`, `develop` →
  `{filesystem.read, filesystem.write, shell.execute, git.branch, git.commit}`,
  `test` → `{filesystem.read, shell.execute}`. The workflow runtime intent is
  the `develop` defaults plus `ask_user` (the planner's reasoning loop).
- **Opt-in.** No intent on a run means byte-identical behavior and no
  `security.*` events.

Runtime mapping (least privilege): `question` always denied; `read`/`glob`/
`grep` require `filesystem.read`; `edit` requires `filesystem.write`; `bash`
requires `shell.execute` and, when granted, carries an explicit deny set
(`git push`, `git tag`, `rm -rf`, `curl`, `wget`) plus an allowlist of run
commands (`git branch`, `git commit`, `grep`, `ruff`, `python`, `pytest`) —
opencode's last-match-wins rule keeps the denies in effect under `--auto`.
The `GitAgent` is deterministic via subprocess and never passes through
opencode; its `push`/`tag` are prevented at the intent level, which never
grants them.

The audit trail is a query, not a raw log: `aios policy show` renders the
policy, `aios security stats` renders the allow/deny trail from
`telemetry_security`.

## Implementation Notes

- [x] Implement `security/intent_validator.py` — `validate_intent` zero-trust allow/deny decision
- [x] Implement `security/resolver.py` — `effective_permissions`, `decide` policy resolution
- [x] Implement `security/capabilities.py` — `CapabilityEnforcer`, capability validation
- [x] Implement `security/actions.py` — capability expansion to granular actions
- [x] Implement `security/contracts.py` — IntentPolicy, EffectivePermissions, SecurityDecision
- [x] Capabilities policy (`aios/policies/agent_capabilities.yaml`) must ship with the project
- [x] Capability check must run before every agent action
- [x] Audit log must be append-only; directory created if missing
- [ ] Secrets must be masked in logs: `OPENAI_API_KEY=***` — post-1.0
- [x] Test: coder with no git capability → git action denied
- [x] Test: coder writes to allowed path → action allowed
- [x] Test: coder writes to denied path (~/.ssh) → action denied
- [ ] Test: prompt contains a secret → sanitized version has secret removed — post-1.0
- [x] Test: destructive action triggers approval request
