"""Static shell completion scripts emitted by ``aios completion``.

These are thin shell glue that delegate to the ``aios __complete`` hook, so
all completion intelligence lives in Python (see ``aios.cli.completion``).
They live here — a module with zero imports — so both the CLI command and
any future installers can use them without circular-import risk.
"""

from __future__ import annotations

BASH_COMPLETION = r"""# AiosDeck bash completion
# Install: source <(aios completion --bash)
# Alternatively, keep this file and source it directly.

_aios_completion() {
    local cur prev words cword
    _init_completion || return

    local tokens=()
    local i
    for ((i = 1; i < cword; i++)); do
        tokens+=("${words[i]}")
    done

    mapfile -t COMPREPLY < <(aios __complete "${cur}" "${tokens[@]}" 2>/dev/null)
    return 0
}

complete -F _aios_completion aios aiosdeck ad
"""

ZSH_COMPLETION = r"""#compdef aios aiosdeck ad

# AiosDeck zsh completion
# Install: source <(aios completion --zsh)
# Alternatively, keep this file and source it directly.

_aios_completion() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    local tokens=("${words[@]:2:$((CURRENT - 2))}")
    local cur="${words[CURRENT]}"

    local IFS=$'\n'
    local completions=($(aios __complete "${cur}" "${tokens[@]}" 2>/dev/null))
    _describe 'command' completions
}

compdef _aios_completion aios aiosdeck ad
"""
