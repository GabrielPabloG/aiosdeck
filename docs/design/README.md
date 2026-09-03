# AiosDeck Design — "Control Room"

Sistema de design e artefatos visuais do AiosDeck. Identidade: **centro de
controle de submarino** — profundidade (contexto), sonar (escaneamento),
missões (unidades de trabalho), salas de controle (monitoramento).

**Status**: proposed (epic D1). Os diagramas descrevem o sistema **real**
(v1.1.0) com duas exceções explicitamente anotadas como *target contract*
(01 marca E1.5 no Kernel; 04 é inteiramente um contrato não implementado).

## Arquivos

| Arquivo | O que é | Como ler |
|---|---|---|
| [style-guide.md](style-guide.md) | Regras visuais: cor semântica, tipografia, elementos, ícones, anti-patterns | Antes de criar qualquer UI ou diagrama novo |
| [tokens.json](tokens.json) | Fonte única de design tokens (espelho canônico de `src/aios/ui/theme.py`; D2 inverte a dependência) | Programa: importe tokens; Humano: consulte nomes |
| `penpot/01-arquitetura.svg` | Blocos de alto nível: Kernel, Event Bus, spokes, execução, ai-jail, core⇄adaptadores | Setas tracejadas ciano = eventos; sólidas = chamadas; vermelho = fronteira de segurança |
| `penpot/02-sequencia-missao.svg` | Missão típica `ad plan`: contexto → plano → execução → gates → relatório | Numereado 1–10; nota inferior: tudo emite eventos |
| `penpot/03-camadas-profundidade.svg` | Camadas L1–L5 (Surface→Abyss) e o mergulho/retorno do agente | Eixo vertical = profundidade, sempre; à direita o budget de tokens |
| `penpot/04-fluxo-cancelamento.svg` | **CONTRATO DESEJADO (E1.5)** — Ctrl+C → cancel cooperativo → kill children → flush → exit 130 | Banner âmbar indica: NÃO é comportamento atual; ver ADR-0007 |
| `penpot/10-ws-mission-control.svg` | Wireframe TUI: tela principal (missão, task strip, sonar mini, rail de sistema) | A tela que `aios` deveria abrir |
| `penpot/11-ws-sonar.svg` | Wireframe TUI: varredura de escopo, detecções, economia de contexto | Mostra o princípio relevance/token com números |
| `penpot/12-ws-control-room.svg` | Wireframe TUI: pods de agentes + ticker do Event Bus | QA/Browser aparece BLOCKED — é o incidente ADR-0007 domado |
| `penpot/13-ws-mission-log.svg` | Wireframe TUI: cronologia da missão (não-chat) | O log do Flappy Bird como caso de uso |
| `penpot/14-ws-deep-dive.svg` | Wireframe TUI: eventos, telemetria e assembly de contexto por task | Responde "por que t9 demorou 600s" com dados |
| `penpot/20-web-mission-control.svg` | Wireframe web: sidebar, cartões de missão, graph, aprovação, telemetria | Base da epic D4 (M7) |

## Uso no Penpot

Todos os SVGs são auto-contidos (sem fontes externas, sem raster) e
importam direto no Penpot (`Upload` → arrastar → *keep as SVG*). Recomenda-se
um projeto Penpot com páginas espelhando esta estrutura:
`Arquitetura`, `Missão`, `Cancelamento`, `TUI`, `Web`, `Guia de Estilo`.

Ao importar, converta cores para **styles** do Penpot usando os nomes de
`tokens.json` (ex.: `color/base/deep`) — é isso que mantém TUI, SVG e web
futuros na mesma verdade.

## Suposições documentadas

1. Telas TUI modeladas em 800×600 (proporção terminal comum); web em 1040×680.
2. `DEPTH 042m` é metáfora de profundidade de contexto, não métrica real.
3. Estados de task nos wireframes já assumem o vocabulário de E1.8
   (`TIMEOUT/BLOCKED/CANCELLED`) — como *target*, coerente com 04.
4. Números de tokens/custos são ilustrativos, extraídos do incidente real
   (ADR-0007) arredondados.
5. QA/Browser como agente/pod próprio pressupõe E4.4/E5.4 — exibido
   BLOCKED para reforçar que capability inexistente nunca virou timeout.

## Regra de manutenção

- Diagrama que descreve comportamento futuro **deve** levar banner
  *TARGET CONTRACT* âmbar (ver §8 do style guide).
- Mudança em `theme.py` exige sincronizar `tokens.json` (e vice-versa a
  partir de D2, com teste de arquitetura garantindo os dois lados).
- Este diretório não contém lógica; a lógica visual mora no código que
  consumir os tokens.
