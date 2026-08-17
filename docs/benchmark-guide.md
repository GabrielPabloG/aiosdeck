# Guia de Benchmark no AiosDeck

Este guia explica como utilizar o sistema de benchmark do AiosDeck para coletar dados de desempenho, validar relatórios e comparar versões.

---

## 1. Como Usar o Benchmark (`aios benchmark`)

O comando `aios benchmark` permite medir tempos de resposta (wall clock e CPU), uso de pico de memória (`peak_memory_kb`) e comportamento de comandos e fases do AiosDeck sem dependências externas.

### Alvos Principais (Targets)

- **`aios benchmark phases`**: Perfila as fases do ciclo de vida do kernel.
- **`aios benchmark all`**: Mede toda a superfície da CLI (`dashboard`, `doctor`, `skills`, `memory`, `plan`, `backlog`).
- **`aios benchmark <comando>`**: Mede um comando específico (`dashboard`, `doctor`, `skills`, `memory`, `plan`, `backlog`).
- **`aios benchmark startup`**: Mede o tempo de inicialização (pode usar `--process` para medir via subprocesso real).

### Opções Úteis

- `--warmup N`: Execuções de aquecimento antes de iniciar a medição (padrão: `1`).
- `--repeat N`: Número de repetições medidas por alvo (padrão: `5`).
- `--json`: Retorna a saída em formato JSON puro no terminal.
- `--output <path>`: Salva o relatório JSON gerado em um arquivo de baseline.
- `--skip-agents`: Pula alvos que exigem runtime de agente (útil para ambientes sem LLM configurado).
- `--bare-task`: Executa sondas restritas (focado em latência pura do modelo sem permissões de ferramentas).
- `--profile`: Registra detalhamentos de `kernel.timings` (Schema v1.1).

### Exemplos de Uso

```bash
# Executar benchmark das fases do ciclo de vida e salvar como baseline
aios benchmark phases --output .benchmarks/baseline.json

# Executar benchmark de todos os comandos CLI salvando em JSON
aios benchmark all --json --output .benchmarks/commands.json

# Medir inicialização via processo real
aios benchmark startup --process
```

---

## 2. Obtendo Dados Importantes e Versões

Todo relatório gerado pelo AiosDeck (seja em JSON ou texto) inclui metadados cruciais para auditoria, rastreamento de versão e diagnóstico de desempenho:

- **Versão do AiosDeck**: `aiosdeck_version` (ex: `"0.1.0"`)
- **Commit do Git**: `git_commit` (hash curto do HEAD no momento da execução)
- **Informações do Sistema**: `system_info` (sistema operacional, plataforma, máquina, processador, versão do Python)
- **Informações de Runtime/LLM**: `runtime_info` (provedor, modelo e host configurados, ex: `provider: google`, `model: gemini-2.5-flash-lite`)
- **Métricas por Execução (`runs`)**:
  - `wall_time_ms`: Tempo de relógio (milissegundos)
  - `cpu_user_ms`: Tempo de CPU no modo usuário
  - `cpu_system_ms`: Tempo de CPU no modo kernel
  - `peak_memory_kb`: Pico de memória RSS em quilobytes

### Validação de Relatórios

Para verificar se um relatório gerado cumpre rigorosamente o schema do AiosDeck:

```bash
aios benchmark validate .benchmarks/baseline.json
```

### Comparação e Detecção de Regressões

Para comparar o desempenho atual com uma baseline anterior:

```bash
# Executa um run ao vivo das fases e compara com a baseline salva
aios benchmark compare .benchmarks/baseline.json

# Compara dois arquivos de relatório diretamente
aios benchmark compare baseline.json current.json --threshold 10
```
