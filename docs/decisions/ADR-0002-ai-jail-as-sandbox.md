# ADR-0002 — ai-jail as Security Sandbox

**Status**: Implemented
**Level**: Architecture
**Review date**: 2026-08-30
**Date**: 2026-08-02
**Updated**: 2026-08-30

## Context

AiosDeck agents execute code, access files, run shell commands, and interact with models. Without a sandbox, a misconfigured agent or a prompt injection attack could compromise the developer's machine.

We evaluated four approaches:

| Option | Description |
|--------|-------------|
| **No sandbox** | Rely on the Security Manager's capability checks alone |
| **ai-jail** | Lightweight sandbox: process isolation, filesystem masks, secret masking, per-project policies |
| **Docker containers** | Full container isolation for every agent run |
| **Custom sandbox** | Build our own process isolation and filesystem restriction layer |

## Decision

**Use ai-jail as the security sandbox.** The Runtime Adapter always invokes OpenCode through ai-jail (`ai-jail opencode`). If ai-jail is not installed, the system degrades gracefully with a warning — but the intended path always includes sandbox isolation.

ai-jail provides OS-level security: process isolation, controlled filesystem mounts, secret masking, and resource limits. The AiosDeck Security Manager provides application-level security: capability checks, policy enforcement, prompt sanitization, and audit logging. Together they form **defense in depth**.

## Consequences

### Positive

- **Defense in depth**: Application-level (AiosDeck Security Manager) + OS-level (ai-jail) security. Neither layer trusts the other.
- **Proven isolation model**: Process isolation and filesystem masking are well-understood security primitives.
- **Alignment**: ai-jail was designed for exactly this use case — sandboxing AI agent tool execution.
- **Gradual adoption**: System works without ai-jail (with warning). Teams can install ai-jail when ready for production security.

### Negative

- **Dependency**: ai-jail is an external project. Breaking changes or abandonment would require a new sandbox or degradation to direct execution.
- **Startup overhead**: Each agent invocation adds process startup latency through the sandbox.
- **Configuration complexity**: ai-jail policies and AiosDeck policies must be kept consistent. Two policy files per project.
- **Only the project directory persists**: `$HOME`, `/tmp`, and sibling/parent directories are tmpfs and are wiped on exit. Out-of-project work is silently lost unless copied back or exposed via `--rw-map` (verified: `docs/integrations/ai-jail.md`).
- **Network is not isolated in normal mode**: the sandbox shares the host network stack. Only `--lockdown` unshares the network namespace. In lockdown, Landlock V4 covers TCP only, and UDP/ICMP remain unrestricted when ports are allow-listed.
- **Seccomp is a blocklist, not an allowlist**: anything not explicitly denied (arbitrary compilers, runtimes, network tools) is permitted.
- **Secrets are visible by default**: environment variables are inherited, and in-project secret files (`.env`, `credentials.json`, `secrets.yml`) are readable unless masked or denied.
- **Default open-trust surfaces**: Docker socket passthrough auto-enables (effective root on the host), and display/GPU passthrough are on by default.
- **AppArmor friction**: Ubuntu 24.04+/Debian 13+ deny unprivileged user namespaces, surfacing as `bwrap: setting up uid map: Permission denied` until a sysctl or bwrap profile is configured.
- **Backends are not equivalent**: macOS uses the deprecated `sandbox-exec`/seatbelt; cross-platform policy parity is approximate, and some flags are no-ops on macOS.
- **Sandbox scope is bounded**: this is a process sandbox, not hardware isolation; kernel escapes and side channels are out of scope.

### Neutral

- ai-jail is an implementation of the zero-trust principle. If it is replaced, the principle remains — only the tool changes.
- The Runtime Adapter abstracts the sandbox invocation. No other component knows ai-jail is the sandbox.

## Evolution: Execution-Environment Awareness

This ADR is the architectural home for an evolving, **backend-agnostic** capability: giving agents awareness of their execution environment (persistence, network, filesystem mounts, process/tool restrictions). It deliberately does **not** hardcode ai-jail — agents should not be told "you are in ai-jail"; instead AiosDeck exposes a structured, generic notion of the execution environment so future runtimes/sandboxes can plug in the same way.

- **Not a new ADR**: the decision space (sandboxed execution, agent awareness of limits) belongs to this ADR. New capabilities are tracked as issues under the "Execution-Environment Awareness" epic, which references this ADR and `docs/integrations/ai-jail.md`.
- **Guiding constraints**: backend-agnostic (no ai-jail knowledge outside the environment detector); awareness off by default initially; only relevant restrictions/capabilities are injected (avoid context pollution); prompt/output token impact is accounted for.
- Verified ai-jail facts that motivate this: only the project persists; the agent cannot tell a tmpfs-backed path from an empty one; network is shared in normal mode; secrets are visible unless masked. These are documented in `docs/integrations/ai-jail.md`.

Referenced by the "Execution-Environment Awareness" epic.
