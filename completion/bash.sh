# AiosDeck bash completion
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
