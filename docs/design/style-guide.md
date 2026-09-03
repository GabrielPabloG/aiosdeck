# AiosDeck Visual Style Guide — "Control Room"

**Status**: Proposed (epic D1 artifact)
**Tokens**: [tokens.json](tokens.json) is the single source of truth. This
document explains *how* to use them; it never redefines values.

## 1. Identity

AiosDeck's interface is a **submarine control room**: an instrument panel for
an intelligence system that works below the surface. The user is the officer
on watch — they set missions, read instruments, and approve maneuvers. The
screens should feel like precision instruments, never like a chat window.

Mood: deep water, sonar, pressure gauges, quiet amber warnings. Density is
fine; noise is not. **Less friction. More intelligence.**

## 2. Color

| Role | Token | Use |
|---|---|---|
| Canvas | `base.abyss` / `background` | full screen background |
| Panels | `base.deep` + `border.default` | every framed region |
| Raised | `base.surf` | selected rows, active tabs |
| Muted fill | `base.foam` | meters, inactive sonar rings |
| Secondary text | `base.ice` | labels, units, timestamps |
| Primary text | `foreground` | values, titles |
| Running / focus / sonar | `accent.info` | active agent, focus ring, sweep |
| Completed / healthy | `accent.success` | done, passing gates, OK status |
| Blocked / degraded | `accent.warning` | BLOCKED, capability missing, budget pressure |
| Failed / timeout / cancelled | `accent.danger` | FAILED, TIMEOUT, user cancellation |

Rules:

- Color is **semantic first, decorative never**. If a pixel is cyan,
  something is running or focused. If it is amber, a human decision is
  near.
- Statuses are never communicated by color alone — always pair with a
  glyph/state word (`● RUNNING`, `✗ TIMEOUT`), so `MONO` mode and color-blind
  users stay informed.
- One accent per region maximum. A screen where everything glows says nothing.

## 3. Typography

- **Mono** (`JetBrains Mono` → `Fira Code` → `monospace`) for all data:
  metrics, IDs, durations, logs, code, status lines.
- **Sans** (`Inter` → `system-ui`) for prose only: mission descriptions,
  help text, empty states.
- Sizes: display 24 (screen titles), title 16 (panel headers), body 13,
  meta 11 (timestamps, units, key hints).
- Uppercase with letter-spacing for panel headers and status words; never
  for sentences.

## 4. Elements

- **Lines**: 1px hairlines (`border.default`); focus rings 2px
  (`border.focused`). No drop shadows — depth comes from the ocean palette
  itself.
- **Corners**: radius 2px. Instruments are nearly square.
- **Grids**: 8px unit. Panels align to it; whitespace is structure.
- **Circular indicators**: gauges, agent pods, sonar rings. Circles mean
  *live instrument*; rectangles mean *recorded data*.
- **Sonar motifs**: use sparingly — sweep lines, faint concentric rings
  (`base.foam` at low opacity) as background texture on Sonar and Mission
  Control only.
- **Depth**: the vertical axis is always *depth* (shallower at top, abyss at
  bottom). Never invert it; `DEPTH 042m` reads like a dive gauge.

## 5. Iconography & glyphs

SVG icons, 1px stroke, geometric, no fills at small sizes. Standard glyphs
for states:

| Glyph | Meaning |
|---|---|
| `◉` | AiosDeck / kernel identity |
| `●` | agent or task live (color = state) |
| `▸` | running |
| `✓` | completed |
| `✗` | failed / timeout |
| `○` | pending |
| `⊘` | blocked (capability missing) |
| `⚠` | warning / approval required |
| `≋` | sonar / scan |
| `↯` | cancellation signal |

## 6. Layout vocabulary

| Screen | Pattern |
|---|---|
| Mission Control | mission header + depth gauge (top), task strip, system rail (right), sonar mini (bottom-left) |
| Sonar View | circular scan left, detection/token-reduction panel right |
| Control Room | agent pod grid, event ticker at the bottom |
| Mission Log | single chronological column, timestamps left gutter — **never an infinite chat** |
| Deep Dive | dense tables: event stream, telemetry, context assembly |

## 7. Motion

Terminal-first: spinners are phase-scoped (already shipped), progress bars
for workflow stages. On web, transitions ≤ 150ms, sonar sweep is the only
ambient animation. Motion communicates state change, never decoration.

## 8. Anti-patterns (rejected)

- Chat bubbles as primary UI.
- Gradients, glows, or glassmorphism.
- More than one focus color.
- Red used for anything other than failure/cancellation.
- Diagrams that show unimplemented behavior without a "TARGET CONTRACT"
  annotation (see `penpot/04-fluxo-cancelamento.svg`).

## 9. Artifact map

| File | Artifact |
|---|---|
| `penpot/01-arquitetura.svg` | High-level architecture (blocks, events, core vs adapters) |
| `penpot/02-sequencia-missao.svg` | Sequence of a typical mission |
| `penpot/03-camadas-profundidade.svg` | Context depth layers |
| `penpot/04-fluxo-cancelamento.svg` | Cancellation flow — **target contract, not current behavior** |
| `penpot/10..14-ws-*.svg` | TUI wireframes (Mission Control, Sonar, Control Room, Mission Log, Deep Dive) |
| `penpot/20-web-mission-control.svg` | Web wireframe |
