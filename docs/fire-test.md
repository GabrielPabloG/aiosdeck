# Fire Test Manual — CLI thin + Kernel.run()

Guia prático para testar o PR 3 **"CLI usa Workflow"** num projeto descartável,
sem depender da suíte de testes. Testa o fluxo real ponta a ponta: a CLI só
dispara `Kernel.run()` e renderiza o resultado.

## Pré-requisitos

- Python 3.12+ com o pacote instalado (`pip install -e .` no repo)
- **OpenCode** e **ai-jail** instalados (a `aios doctor` confirma)
- Shell no Linux

## Passo 0 — Instalar a branch

```bash
cd <seu-repo-aiosdeck>
git checkout feature/pr3-cli-thin
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Passo 1 — Criar um projeto de teste descartável

```bash
mkdir -p /tmp/firetest && cd /tmp/firetest
git init -q
git config user.email "you@test.com" && git config user.name "You"
touch README.md && git add . && git commit -qm "init"
aios init
```

`aios init` cria `.aios/project.yaml` e ajusta o `.gitignore`.

## Passo 2 — Sanidade: dashboard e doctor

```bash
aios doctor
```

Confira a seção **Workflow Pipeline**: planner/scheduler/developer/reviewer
marcados com ✓ e tester/documentation/git como `(optional)`. Se algum opcional
não estiver instalado, ele aparece com `—` e a linha "Optional not installed".

## Passo 3 — `aios plan` (só planeja)

```bash
aios plan "add a /health endpoint"
```

Esperado: a CLI mostra o spinner "Planning..." e imprime o JSON do plano.
Nenhuma execução acontece. Se falhar, a mensagem amigável sai em
`Error: ...` (sem traceback).

## Passo 4 — `aios plan --run` (fluxo completo)

```bash
aios plan "add a /health endpoint" --run
```

Esperado, nesta ordem:
1. Dashboard + "Running workflow..."
2. `Plano de Execução (N tarefas):` com o checklist
3. `[✓] <subtask>` a cada tarefa concluída
4. `N/N tasks completed`
5. `git branch` atual é `feature/add-health-endpoint-1` e há um commit `feat: ...`

Confira o kanban persistido:

```bash
sqlite3 .aios/memory.db "SELECT title, column_name, blocked FROM kanban_cards"
```

Tudo em `Done`, `blocked=0`.

## Passo 5 — Degradação graciosa (opcionais ausentes)

Crie um projeto **sem** git e sem `tests/`:

```bash
mkdir -p /tmp/firetest-nogit && cd /tmp/firetest-nogit
aios init
aios plan "add a /health endpoint" --run
```

Esperado: o pipeline **continua mesmo sem** tester/documentation/git. O resultado
mostra as etapas como `skipped` e termina com sucesso (mesmo sem branch/commit).
Em vez de quebrar, as etapas opcionais são puladas.

## Passo 6 — Caminho de erro

```bash
aios plan ""                  # sem intent → Usage + exit 1
aios plan "tarefa impossível xyz" --run
```

No segundo caso, se o planner/developer falhar, a CLI imprime
`Error: <mensagem>` e sai com código ≠ 0. Nenhum traceback Python escapa.

## Verificação da arquitetura (o que o PR 3 muda)

- `aios plan` **não** chama `planner.execute`, `developer.execute` nem
  `kernel.get_engine(...)` — tudo passa por `kernel.run(...)`.
- Se você remover a variável `AIOS_USE_WORKFLOW_ENGINE`, nada muda: o caminho
  legado foi removido.
- `grep -rn "get_engine(\"planner\")" src/aios/cli/` não deve retornar nada.

## Limpeza

```bash
rm -rf /tmp/firetest /tmp/firetest-nogit
```
