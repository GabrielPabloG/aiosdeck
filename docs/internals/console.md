# Ocean Console

**Status**: Accepted
**Date**: 2026-08-09

## Context

`aios ocean` opens the *Ocean Console* — the terminal dashboard for AiosDeck.
It renders a dark, marine-themed overview of engine health, workflow,
telemetry, routing and configuration entirely through semantic design tokens,
so the same output survives truecolor, xterm-256 and monochrome terminals
without code changes.

## Theme — tokens, never raw ANSI

Every color on screen is a **semantic token** resolved through
`ColorResolver`; widgets never emit hex or ANSI codes directly.

- **`Theme`** — a declarative palette (plain 6-digit hex strings) with three
  token groups: `base` (surface shades), `accents` (semantic states:
  `info`/`success`/`warning`/`danger`) and `borders` (chrome). `ocean_theme`
  ships the dark, deep-water palette (`#0b1420` background, `#38bdf8` info).
- **`ColorResolver`** — turns a `Theme` + `ColorMode` into concrete output.
  Callers pass `fg`/`bg` *token names*, not colors.
- **`ColorMode`** — `COLOR` (truecolor 24-bit), `MODE_256` (xterm-256) and
  `MONO` (strips color, keeps plain-text markers so emphasis survives).
  `AUTO` is a preference, never used directly for rendering.
- **`detect_color_mode`** — resolves the effective mode from the environment:
  `NO_COLOR` / `CLICOLOR=0` are universal kill switches; `AIOS_UI_COLORMODE`
  / `AIOS_UI_COLOR` set it explicitly; `FORCE_COLOR` forces 1/2/3; otherwise
  the terminal is probed via `COLORTERM`, `TERM` and TTY detection, falling
  back to monochrome.

```python
resolver = ColorResolver(ocean_theme, detect_color_mode())
ctx = RenderContext(resolver=resolver)
```

## Components

Each component consumes tokens through the resolver:

- **Panel** (`render_panel`) — bordered frame with optional title/body.
- **ProgressBar** (`render_progress`) — labeled fill bar.
- **StatusPill** (`render_status_pill`) — bracketed/filled status chip.
- **MetricCard** (`render_metric_card`) — `label: value` card.
- **SectionHeader** (`render_section_header`) — title + rule.
- **TableLite** (`render_table`) — aligned header/rows grid.

**`RenderContext`** carries `width`, `height`, compact state and the
resolver. Layout adapts via `compact`: when the terminal is under 80 columns
**or** under 24 rows the widgets collapse to condensed single-line output.

## Pages

`render_page(name, data, ctx)` dispatches to a builder keyed by page name;
`datasources.py` produces the structured data (returning safe empty defaults
when an engine or store is absent).

| Page | Data source |
|------|-------------|
| `overview` | `overview_data` — status, workflow health, usage today, runtime/sandbox |
| `workflows` | `workflows_data` — pipeline agent availability |
| `agents` | `agents_data` — executions by agent |
| `skills` | `skills_data` — invocation statistics |
| `knowledge` | `knowledge_data` — retrieval stats |
| `usage` | `usage_data` — totals, per agent/model, costs |
| `quality` | `quality_data` — quality gate records |
| `settings` | `settings_data` — persisted `ui:` configuration |

## Command

```
aios ocean [--page NAME] [--once] [--json] [--refresh N] [--save]
```

- **Interactive** (when `stdin`/`stdout` are a TTY): keys `1..8` switch
  pages, `tab` / `Shift+tab` cycle forward/backward, `r` refreshes the
  current view, `q` quits; `--refresh N` enables periodic re-pulls.
- **Static fallback** (non-TTY): renders the selected page once to stdout
  and exits.
- `--once` prints the page and exits; `--json` emits the raw page data;
  `--save` persists the current `ui:` section to
  `~/.config/aiosdeck/config.yaml` (never written without the flag).

## ASCII screenshots

Overview (80 columns):

```
System Overview
────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Project: aiosdeck                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────┐
│ Engines: 3/3 ready                                                           │
└──────────────────────────────────────────────────────────────────────────────┘
 Runtime Down
 No Sandbox
```

Usage (80 columns):

```
Usage
────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Calls: 42                                                                    │
└──────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────┐
│ Prompt_tokens: 1234                                                          │
└──────────────────────────────────────────────────────────────────────────────┘
Per Agent
────────────────────────────────────────────────────────────────────────────────
Agent     Calls
───────────────
research  10
review    5
Per Model
────────────────────────────────────────────────────────────────────────────────
Model   Calls
─────────────
llama3  12
Costs
────────────────────────────────────────────────────────────────────────────────
Agent     Model          Cost
────────────────────────────────
research  ollama/llama3  $0.0012
```