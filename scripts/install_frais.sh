#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${FRAIS_HOME:-$HOME/.frais}"
BIN_DIR="$INSTALL_DIR/bin"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --------------- prerequisites ---------------
if ! command -v uv &>/dev/null; then
    echo "frais: uv is not installed." >&2
    echo "Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
    echo "frais: pyproject.toml not found at $REPO_DIR." >&2
    echo "Run this script from the frais repository (scripts/install_frais.sh)." >&2
    exit 1
fi

# --------------- build ---------------
echo "frais: building binary (this may take a minute)..." >&2
uv run --extra build --frozen --directory "$REPO_DIR" python "$REPO_DIR/scripts/build_binary.py"

# --------------- install ---------------
echo "" >&2
echo "frais: installing to $BIN_DIR/..." >&2
rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"
cp -R "$REPO_DIR/dist/frais/" "$BIN_DIR/"
chmod +x "$BIN_DIR/frais"

echo "frais: installed — $BIN_DIR/frais" >&2

# --------------- warm dyld cache ---------------
echo "frais: warming cache..." >&2
"$BIN_DIR/frais" doctor >/dev/null 2>&1 || true
echo "frais: ready." >&2
