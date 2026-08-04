# TAPEDECK — native macOS app build targets.
# Run from this directory (native/).

PROJECT := Tapedeck.xcodeproj
SCHEME  := Tapedeck
BUILD   := build
APP     := $(BUILD)/Build/Products/Release/TAPEDECK.app
DEST    := $(HOME)/Applications/TAPEDECK.app
# Location-independent: derived from this Makefile's own path, not the working
# directory make was invoked from (`cd .. && pwd` would resolve to the repo's
# PARENT if someone ran `make -f native/Makefile` from the repo root, baking
# the wrong TDRepoRoot into the bundle).
MAKEFILE_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
REPO_ROOT := $(shell cd "$(MAKEFILE_DIR)/.." && pwd)
VENV_PY := $(REPO_ROOT)/.venv/bin/python3

.PHONY: all icon project build install venv check clean

all: build

icon:
	@./icon/generate.sh

project:
	@xcodegen generate

build: project check
	@echo "→ baking TDRepoRoot = $(REPO_ROOT)"
	@xcodebuild -project $(PROJECT) -scheme $(SCHEME) -configuration Release \
		-derivedDataPath $(BUILD) build CODE_SIGNING_ALLOWED=NO \
		TD_REPO_ROOT="$(REPO_ROOT)" | tail -5

install: build
	@if [ -e "$(DEST)" ]; then \
		echo "→ removing existing $(DEST)"; \
		rm -rf "$(DEST)"; \
	fi
	@mkdir -p "$(HOME)/Applications"
	@echo "→ installing $(APP) → $(DEST)"
	@cp -R "$(APP)" "$(DEST)"
	@# Ad-hoc sign so macOS keeps the app's identity stable across rebuilds and
	@# stops re-prompting for local network access.
	@codesign --force --sign - "$(DEST)" 2>/dev/null || true
	@echo "→ TDRepoRoot in the installed bundle:"
	@defaults read "$(DEST)/Contents/Info.plist" TDRepoRoot
	@echo "✅  installed. Click the dock icon to launch (may need to drag it onto the dock first)."

# The app refuses to boot without this, and says so with this exact command.
venv:
	@cd "$(REPO_ROOT)" && python3 -m venv .venv && \
		.venv/bin/pip install --quiet --upgrade pip && \
		.venv/bin/pip install --quiet -r requirements.txt
	@echo "✅  .venv ready at $(REPO_ROOT)/.venv"

# Fail the build rather than shipping a bundle that cannot start its server.
check:
	@test -x "$(VENV_PY)" || { \
		echo "✗ no interpreter at $(VENV_PY) — run: make venv"; exit 1; }
	@cd "$(REPO_ROOT)" && "$(VENV_PY)" -c "import tapedeck.server" 2>/dev/null || { \
		echo "✗ $(VENV_PY) cannot import tapedeck.server"; exit 1; }
	@echo "✓ backend importable"

clean:
	@rm -rf $(BUILD)
	@echo "✅  build/ removed."
