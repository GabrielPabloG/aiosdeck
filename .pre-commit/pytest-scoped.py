#!/usr/bin/env python3
"""
Pre-commit hook que roda pytest APENAS nos testes que cobrem os arquivos modificados.
Baseado no diff do git e na convenção de nomenclatura de testes.
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Set


def get_staged_python_files() -> List[Path]:
    """Retorna os arquivos Python staged (prestes a serem commitados)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    files = [Path(f) for f in result.stdout.splitlines() if f.endswith(".py")]
    # Filtra apenas src/ e tests/
    return [f for f in files if f.parts[0] in ("src", "tests")]


def get_related_tests(src_file: Path) -> List[Path]:
    """
    Mapeia um arquivo fonte (src/aios/x.py) para seu teste correspondente.
    Exemplo: src/aios/telemetry/writer.py → tests/telemetry/test_writer.py
    """
    if src_file.parts[0] == "tests":
        # Se já é um arquivo de teste, retorna ele mesmo
        return [src_file]

    # Converte: src/aios/telemetry/writer.py → tests/telemetry/test_writer.py
    relative_path = src_file.relative_to("src")
    test_file = Path("tests") / relative_path.parent / f"test_{relative_path.stem}.py"
    if test_file.exists():
        return [test_file]

    # Se não encontrar, busca qualquer test_*.py no mesmo diretório
    test_dir = Path("tests") / relative_path.parent
    if test_dir.exists():
        tests = list(test_dir.glob("test_*.py"))
        return tests if tests else []

    return []


def main():
    staged = get_staged_python_files()
    if not staged:
        print("ℹ️ Nenhum arquivo Python staged. Pulando pytest.")
        return 0

    # Determina quais testes rodar
    tests_to_run: Set[Path] = set()
    for file in staged:
        if file.parts[0] == "src":
            tests_to_run.update(get_related_tests(file))
        elif file.parts[0] == "tests":
            tests_to_run.add(file)

    if not tests_to_run:
        print("⚠️ Nenhum teste correspondente encontrado. Pulando pytest.")
        return 0

    # Monta comando pytest
    test_args = [str(t) for t in sorted(tests_to_run)]
    cmd = ["pytest", "-v"] + test_args
    print(f"🧪 Rodando pytest em: {' '.join(test_args)}")

    result = subprocess.run(cmd, capture_output=False)  # Deixa saída ao vivo
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())