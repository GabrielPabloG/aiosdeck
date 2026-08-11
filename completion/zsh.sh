#compdef aios aiosdeck ad

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
