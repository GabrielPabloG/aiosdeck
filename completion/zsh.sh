#compdef aios aiosdeck ad

# AiosDeck zsh completion
# Source this file: source completion/zsh.sh

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
