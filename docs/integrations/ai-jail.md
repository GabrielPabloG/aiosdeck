# ai-jail Integration

**Status**: Accepted
**Date**: 2026-08-02
**Updated**: 2026-08-30

## Context

ai-jail provides sandboxed execution for AI agents. It isolates processes, masks secrets, restricts filesystem access, and enforces per-project policies. The Security Manager in AiosDeck provides application-level authorization (capabilities, policies, audit). ai-jail provides OS-level isolation. Together they form defense-in-depth.

## Decision

### Invocation

The Runtime Adapter always invokes OpenCode through ai-jail:

```bash
ai-jail opencode
```

If ai-jail is not installed, the adapter logs a warning and refuses to invoke OpenCode:

```python
async def _resolve_runtime_command(self) -> list[str]:
    if self._is_installed("ai-jail"):
        return ["ai-jail", "opencode"]
    logging.warning("ai-jail not found. OpenCode execution is disabled.")
    raise RuntimeError("ai-jail is required")
```

The actual adapter (`runtime/opencode.py`) reflects this: with OpenCode but no ai-jail, the resolved command is `ai-jail opencode (not found)`, a warning is logged, and `execute()` raises `RuntimeError("Runtime requires ai-jail (sandbox is mandatory)")`. There is no unsandboxed degraded mode.

### Sandbox Capabilities (verified, ai-jail 1.13.0)

- **Process isolation**: PID, UTS, IPC, and mount namespaces via bubblewrap on Linux; the hostname inside the sandbox is `ai-sandbox`; the process dies with its parent.
- **Filesystem masking**: Only allowed directories are visible. The project directory is mounted read-write; `$HOME` is replaced by a tmpfs overlaid with select dotfiles; sensitive dotdirs (`.ssh`, `.gnupg`, `.aws`, `.mozilla`, `.thunderbird`, `.sparrow`) are never mounted.
- **Secret masking**: `.ai-jail` itself is masked by default; browser/config caches such as `~/.config/BraveSoftware` and `~/.cache/chromium` are hidden. **Note:** environment variables and in-project `.env`/`secrets.yml` are visible unless explicitly masked.
- **Policy enforcement**: Per-project policies (`.ai-jail` TOML) plus `--mask` / `--deny-path` / `--map` define what is allowed.
- **Resource limits**: `RLIMIT_NPROC = 4096`, `RLIMIT_NOFILE = 65536`, core dumps disabled (`0`). Lockdown mode uses `NPROC = 1024`, `NOFILE = 4096`. Limits pin hard to soft so the sandboxed process cannot raise them.
- **Syscall filtering**: seccomp applies a blocklist of ~40 syscalls (mount, ptrace, unshare, setns, bpf, io_uring, kernel keyring, module loading, clock_settime, etc.) plus arch-specific ones. This is a blocklist: anything not listed is allowed.
- **LSM**: Landlock (Linux 5.13+) enforces VFS-level access control, on by default.

### Verified Sandbox Behavior

The default mode favors usability over maximum lockdown. These are intentionally open by default (ai-jail 1.13.0):

- **Network is not isolated** in normal mode — the sandbox shares the host network stack; outbound TCP/UDP is unrestricted (blocklist approach, not allowlist).
- **Docker socket passthrough auto-enables** when `/var/run/docker.sock` exists. This grants effective root on the host and is a deliberate trust extension.
- **Display passthrough** mounts `XDG_RUNTIME_DIR`, which can expose host IPC sockets.
- **GPU passthrough** (`/dev/dri`, NVIDIA devices) is enabled on Linux.
- **Environment variables are inherited** — tokens/secrets present in the invoking shell's environment are visible inside the sandbox.
- **Only the project directory is persistent** by default. `$HOME`, `/tmp`, parent and sibling directories live in tmpfs and are wiped when ai-jail exits.

Backends: Linux uses bubblewrap (`bwrap`); macOS uses `sandbox-exec`/seatbelt, a **deprecated** Apple interface.

### Limitations & Caveats

These are verified properties of ai-jail 1.13.0, not assumptions:

- **Persistence**: only the current project directory persists. Parent/sibling directories, `$HOME`, and `/tmp` are tmpfs and are wiped on exit. The README warns: *"The agent cannot tell from inside the sandbox; the filesystem looks writable."* Work written outside the project (e.g. a sibling scaffold, `~/.cache`, or `/tmp`) disappears unless copied back into the project or exposed with `--rw-map`.
- **Agent opacity**: a process inside the sandbox cannot reliably distinguish a tmpfs-backed path (which looks empty) from an actually empty directory — the filesystem looks writable either way.
- **Network**: shared host stack in normal mode; only lockdown (`--lockdown` / `--no-lockdown`) unshares the network namespace. Inside lockdown, outbound ports are controlled via Landlock V4 (Linux ≥ 6.5) and default to none; note Landlock V4 covers **TCP only** — UDP/ICMP are unrestricted when allow-ports are configured.
- **Seccomp is a blocklist**: anything not explicitly denied is allowed (arbitrary compilers, interpreters, network tools). This is not an allowlist; ai-jail does not enumerate every permissible tool.
- **Secrets**: env vars and in-project secret files (`.env`, `credentials.json`, `secrets.yml`) are visible by default and must be hidden via `--mask` / `--deny-path`.
- **AppArmor**: Ubuntu 24.04+/Debian 13+ deny unprivileged user-namespace creation, which bwrap requires; this surfaces as `bwrap: setting up uid map: Permission denied` and needs a sysctl change or a local bwrap AppArmor profile.
- **Overlay maps** (`--overlay-map`): bwrap-only, backed by unprivileged OverlayFS (kernel ≥ 5.11); on macOS they degrade to read-only with a warning; disabled under `--lockdown` and browser mode.
- **Cross-platform parity** is approximate: Linux and macOS primitives are not equivalent, and some flags have no effect on macOS (`--no-gpu`, `--no-display`, `--allow-tcp-port`, `--systemd-user`, `--tailscale`).
- **Out of scope for the sandbox**: kernel escapes are out of scope (all backends depend on host kernel correctness); this is a process sandbox, not hardware isolation — a VM runs a separate kernel and is stronger; timing/cache side channels and scheduler interference still exist; `sandbox-exec` on macOS is deprecated and Apple could remove it.

### Policy Alignment

AiosDeck policies (capabilities) and ai-jail policies (filesystem masks, resource limits, mount maps) are complementary:

| Layer | Responsibility |
|-------|---------------|
| AiosDeck Security Manager | Agent-level: can this agent write files? Which tools/capabilities? |
| ai-jail | OS-level: which directories can this process see, and in what mode (rw/ro/overlay/deny)? What resource limits apply? Is the network shared or isolated? |

They do not fully overlap. AiosDeck decides **what** an agent can do; ai-jail decides **where**, **how much**, and — via masks/maps/deny-paths — the granularity of filesystem exposure.

### Configuration

```yaml
# .aios/project.yaml
sandbox: ai-jail

# ~/.config/aiosdeck/config.yaml
runtime:
  command: "ai-jail opencode"
```

### Health Check

The adapter detects ai-jail via `shutil.which("ai-jail")` and reports it with the `has_sandbox` property. The deep diagnostic runs `ai-jail opencode models <provider>` from inside the sandbox to verify the provider endpoint and model:

```python
class AiJailAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("ai-jail")

    async def health_check(self) -> bool:
        result = await self._run("ai-jail --version")
        return result.returncode == 0
```

### Missing Sandbox

Without ai-jail, runtime execution is unavailable. The Security Manager remains an application-level control, but it does not replace OS-level isolation. `execute()` raises when ai-jail is absent and the adapter is initialized.

### Agent Awareness (Roadmap)

The sandbox is currently **transparent to agents**: AiosDeck does not tell the agent it is sandboxed, what persists, or which paths are masked. This is intentional for now. A future, backend-agnostic capability — **Execution-Environment Awareness** — will expose the relevant execution environment (persistence, network, filesystem mounts, tool restrictions) to agents generically, without hardcoding ai-jail. See [ADR-0002](../decisions/ADR-0002-ai-jail-as-sandbox.md) and the tracking epic.

## Consequences

- **Defense in depth**: AiosDeck + ai-jail = application + OS security layers.
- **Transparent to agents (currently)**: Agents are unaware of ai-jail. The Runtime Adapter handles it. Work towards agent awareness is planned under Execution-Environment Awareness.
- **Fail closed**: System does not execute runtime processes without ai-jail.
- **Persistence caveat**: only the project directory persists; temporary and out-of-project writes are lost on exit.

## Implementation Notes

- [x] Runtime Adapter must detect ai-jail: `which ai-jail`
- [x] Runtime command resolution: ai-jail present → `ai-jail opencode`, absent → execution disabled
- [x] Deep doctor diagnostic: verify ai-jail and the provider from inside the sandbox
- [x] Warning log: "ai-jail not found. OpenCode execution is disabled."
- [x] Policy file location: ai-jail reads policies from its own config directory
- [x] Test: ai-jail installed → command is `ai-jail opencode`
- [x] Test: ai-jail not installed → warning logged, direct OpenCode is rejected
- [x] Test: ai-jail healthy → health check returns True
- [ ] Execution-Environment Awareness: expose sandbox behavior to agents generically (see epic)
