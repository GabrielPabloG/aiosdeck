# Fire Test Manual — Researcher v0.9.1

Guia prático para testar a v0.9.1 **"ResearcherAgent de primeira classe"** num
projeto descartável, sem depender da suíte de testes. Testa o fluxo real ponta
a ponta: `aios research` (repo/docs/web), semântica de disponibilidade
(`source_unavailable`/`partial`) e o front-gate opcional no workflow.

## Pré-requisitos

- Python 3.12+ com o pacote instalado (`pip install -e .` no repo)
- **OpenCode** e **ai-jail** instalados (a `aios doctor` confirma) — apenas
  para o Passo 8 (`plan --run`)
- Shell no Linux

## Passo 0 — Instalar a branch

```bash
cd <seu-repo-aiosdeck>
git checkout feature/researcher-first-class
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Passo 1 — Criar um projeto de teste descartável

```bash
mkdir -p /tmp/firetest-research && cd /tmp/firetest-research
git init -q
git config user.email "you@test.com" && git config user.name "You"
touch README.md && git add . && git commit -qm "init"
aios init
```

Crie arquivos que o Researcher vai encontrar:

```bash
mkdir docs
cat > health.py <<'EOF'
def health_check():
    return True
EOF
cat > docs/guide.md <<'EOF'
Auth flow explained in the guide.
EOF
```

## Passo 2 — Sanidade: dashboard e doctor

```bash
aios doctor
```

Confira a seção **Workflow Pipeline**: agora existe `research (optional)`.
Os demais agentes continuam como antes — nenhuma etapa se tornou obrigatória.

## Passo 3 — `aios research` — escopo `repo` (happy path)

```bash
aios research "health check" --scope repo
```

Esperado:

```
status: ok
summary: Collected 1 source(s), 1 finding(s), confidence 0.70.
Findings:
  - [F1] (conf 0.70) def health_check(): ...
Sources:
  - code: health.py (file://health.py)
```

Sem rede, sem chave de API: a coleta é local e determinística.

## Passo 4 — `aios research` — escopo `docs`

```bash
aios research "auth flow" --scope docs
```

Esperado: `status: ok`, com fontes do tipo `doc` apontando para
`file://docs/guide.md`.

## Passo 5 — `aios research` — escopo `web` sem fetcher (disponibilidade explícita)

```bash
aios research "how does fastapi oauth work" --scope web
```

Esperado:

```
status: source_unavailable
summary: Web collection unavailable: configure a fetcher/provider to research external sources.
confidence: 0.00

Recommendations:
  - [low] Configure a web source fetcher before requesting web research
```

Pontos críticos:
- **Sem findings** — não há claims fabricados ("não encontramos informação" ≠
  "não conseguimos acessar a web").
- A recomendação afirma explicitamente que a coleta web está indisponível;
  nunca parece derivada de uma pesquisa real.

## Passo 6 — `aios research` — escopo `mixed` sem fetcher (degradação graciosa)

```bash
aios research "health check" --scope mixed
```

Esperado: `status: partial`, fontes locais presentes (repo/docs), **e** a nota
de web indisponível nas recomendações. O resultado local não é perdido.

## Passo 7 — `aios research` — JSON e auditoria

```bash
aios research "health check" --scope repo --json
aios research "health check" --scope repo --output research-report.json
```

No `--json`, valide o schema:

```bash
python - <<'EOF'
import json
d = json.load(open("research-report.json"))
assert "sources" in d and "findings" in d and "memory_candidates" in d
source_ids = {s["id"] for s in d["sources"]}
for f in d["findings"]:
    assert set(f["evidence_source_ids"]) <= source_ids, "finding sem proveniência!"
print("schema ok — findings rastreáveis a sources")
EOF
```

`memory_candidates` aparecem como **advisory** (`kind`, `content`, `confidence`);
nada é gravado no Memory Engine (confira: `.aios/memory.db` continua sem
convention/pattern novo).

## Passo 8 — Workflow: front-gate opcional

```bash
aios plan "add a /health endpoint" --run
```

Esperado: pipeline roda normalmente — `Plano de Execução`, `[✓] <subtask>`,
`N/N tasks completed`, branch `feature/add-health-endpoint-1` e commit `feat: ...`.

O estágio `research` roda antes do planner **somente porque o Researcher está
injetado** no kernel. Ele é advisory: um resultado de pesquisa alimenta o
contexto do planner/developer via `ContextPacket.research`, mas nunca bloqueia
o pipeline. Como a CLI não renderiza o estágio `research` (apenas planner e
developer aparecem no progresso), a verificação fina está na suíte automatizada:

```bash
pytest tests/test_workflow.py::test_workflow_research_front_gate_feeds_planner -q
pytest tests/test_workflow.py::test_workflow_optional_agents_skipped -q
```

Sem Researcher (agente ausente), o pipeline é idêntico ao v0.9.0 — o front-gate
não cria branch alternativo nem dependência obrigatória.

## Passo 9 — Caminhos de erro

```bash
aios research                    # sem pergunta → Usage + exit 1
aios research "x" --scope nope   # --scope inválido → Error + exit 1
aios research "x" --bogus        # opção desconhecida → Error + exit 1
aios research "" --scope web     # pergunta vazia → Usage + exit 1
```

Nenhum traceback Python escapa.

## Verificação da arquitetura (o que a v0.9.1 muda)

- `ResearchAgent.required_capabilities == ["filesystem_read"]` — **sem**
  `internet`. Rede é capability contextual de um fetcher injetado, não do agente.
- `grep -rn "internet" src/aios/agents/research.py` não deve retornar nada.
- Cada `Finding` cita `evidence_source_ids` existentes (proveniência); a
  validação de schema falha se apontar para fonte inexistente.
- `web` sem fetcher → `source_unavailable` com **zero** findings; `mixed` →
  `partial`.
- `memory_candidates` são advisory; nada persiste no Memory Engine.
- O front-gate é opcional e o workflow linear permanece o mesmo.

## Limpeza

```bash
rm -rf /tmp/firetest-research
```
