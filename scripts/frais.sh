#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${FRAIS_HOME:-$HOME/.frais}"

if [ ! -f "$INSTALL_DIR/bin/frais" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    mkdir -p "$INSTALL_DIR"

    if [ -d "$SCRIPT_DIR/frais" ]; then
        cp -R "$SCRIPT_DIR/frais" "$INSTALL_DIR/bin/"
        chmod +x "$INSTALL_DIR/bin/frais"
    elif [ -f "$SCRIPT_DIR/frais.zip" ]; then
        unzip -qo "$SCRIPT_DIR/frais.zip" -d "$INSTALL_DIR/bin/"
        chmod +x "$INSTALL_DIR/bin/frais"
    else
        echo "frais: could not find frais bundle or frais.zip" >&2
        exit 1
    fi
    echo "frais installed to $INSTALL_DIR/bin/"
fi

exec "$INSTALL_DIR/bin/frais" "$@"
