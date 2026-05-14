#!/bin/bash
#
# Leap Shell Configuration Helper
# Called by: make install, make update
#
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# `--update` used to gate the overwrite prompt; now the overwrite is always
# silent, so we just consume the flag for backward compatibility with the
# Makefile's `.detect-shell-update` target.
if [ "$1" = "--update" ]; then
    shift
fi
REPO_PATH="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"

# Step 1 — Detect shell and set file names.
SHELL_NAME=$(basename "$SHELL")
if [ "$SHELL_NAME" = "zsh" ]; then
    RC_FILE="$HOME/.zshrc"
    LEAP_RC="$HOME/.leap.zshrc"
elif [ "$SHELL_NAME" = "bash" ]; then
    RC_FILE="$HOME/.bashrc"
    LEAP_RC="$HOME/.leap.bashrc"
else
    echo -e "${YELLOW}⚠ Unknown shell: $SHELL_NAME — please source ~/.leap.zshrc manually${NC}"
    exit 0
fi

# Step 2 — Remove legacy LEAP_*_FLAGS exports (stored in .storage/cli_flags.json now).
if [ -f "$RC_FILE" ]; then
    sed -i.bak '/^export LEAP_[A-Z_]*_FLAGS="/d' "$RC_FILE"
    sed -i.bak '/^# Default flags per CLI/d' "$RC_FILE"
    sed -i.bak '/^# Extra flags can also be passed inline/d' "$RC_FILE"
    # Remove legacy leap-cleanup comment (auto-cleanup runs on every leap invocation)
    sed -i.bak '/^#        leap-cleanup$/d' "$RC_FILE"
    rm -f "$RC_FILE.bak"
fi

# Step 3 — Migrate legacy START/END block (or pre-marker heuristic).
migrated=false
if grep -q "Leap Configuration START" "$RC_FILE" 2>/dev/null; then
    sed -i.bak '/Leap Configuration START/,/Leap Configuration END/d' "$RC_FILE"
    rm -f "$RC_FILE.bak"
    migrated=true
elif grep -q "# Leap" "$RC_FILE" 2>/dev/null; then
    # Legacy pre-marker block — fall back to the old heuristic.
    sed -i.bak '/# Leap/,/^alias claudel=/d' "$RC_FILE"
    rm -f "$RC_FILE.bak"
    migrated=true
fi

# Collapse trailing blank lines left behind by the strip.
if [ "$migrated" = true ] && [ -s "$RC_FILE" ]; then
    awk 'NF {for (i=0;i<bl;i++) print ""; bl=0; print; next} {bl++}' \
        "$RC_FILE" > "$RC_FILE.trim" && mv "$RC_FILE.trim" "$RC_FILE"
fi

# Step 4 — Get Poetry venv path (try stored path first, then poetry command).
VENV_PATH_FILE="$REPO_PATH/.storage/venv-path"
if [ -f "$VENV_PATH_FILE" ]; then
    POETRY_VENV=$(cat "$VENV_PATH_FILE")
else
    POETRY_VENV=$(cd "$REPO_PATH" && poetry env info --path 2>/dev/null || echo "")
fi

# Step 5 — Write ~/.leap.zshrc (or ~/.leap.bashrc) atomically.
LEAP_RC_DIR=$(dirname "$LEAP_RC")
TMP_RC=$(mktemp "${LEAP_RC}.XXXXXX")

cat > "$TMP_RC" <<'BLOCK'
# Leap shell configuration — managed by 'make install'. Do not edit directly.
BLOCK

echo "export LEAP_PROJECT_DIR=\"$REPO_PATH\"" >> "$TMP_RC"

cat >> "$TMP_RC" <<'BLOCK'

leap() {
    "$LEAP_PROJECT_DIR/src/scripts/leap-select.sh" "$@"
}
BLOCK

if [ "$SHELL_NAME" = "zsh" ]; then
    cat >> "$TMP_RC" <<'BLOCK'

# Tab-complete `leap` flags
if [ -f "$LEAP_PROJECT_DIR/src/scripts/_leap" ]; then
    fpath=("$LEAP_PROJECT_DIR/src/scripts" $fpath)
    if (( $+functions[compdef] )); then
        autoload -Uz _leap && compdef _leap leap
    else
        autoload -Uz compinit && compinit -u
    fi
fi
BLOCK
fi

mv "$TMP_RC" "$LEAP_RC"

# Step 6 — Add source line to main rc (idempotent).
LEAP_RC_BASENAME=$(basename "$LEAP_RC")
SOURCE_LINE="[ -f \"\$HOME/$LEAP_RC_BASENAME\" ] && source \"\$HOME/$LEAP_RC_BASENAME\""
if ! grep -qF "$LEAP_RC_BASENAME" "$RC_FILE" 2>/dev/null; then
    echo "" >> "$RC_FILE"
    echo "$SOURCE_LINE" >> "$RC_FILE"
fi

# Step 7 — Report.
if [ "$migrated" = true ]; then
    echo -e "${GREEN}ℹ Migrated Leap config → $LEAP_RC${NC}"
fi
echo -e "${GREEN}✓ Leap shell config written to $LEAP_RC${NC}"
echo "  Using Poetry venv: $POETRY_VENV"
