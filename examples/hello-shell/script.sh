#!/usr/bin/env bash
# Hello Shell — a simple example project for testing AiosDeck detection

set -euo pipefail

greet() {
    local name="${1:-World}"
    echo "Hello, ${name}!"
}

main() {
    greet
}

main "$@"
