.PHONY: test lint format

test:
	@echo "Running tests..."
	bats tests/

lint:
	shellcheck *.sh

format:
	shfmt -w *.sh
