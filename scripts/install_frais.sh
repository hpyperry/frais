#!/usr/bin/env bash
set -euo pipefail

# install_frais.sh — build and install frais from source or download prebuilt binary.
# Usage:
#   # Install from source (requires Rust toolchain):
#   bash scripts/install_frais.sh
#
#   # Download prebuilt binary (from GitHub Releases):
#   curl -fsSL https://raw.githubusercontent.com/hpy/frais/main/scripts/install_frais.sh | bash -s -- --from-release

INSTALL_DIR="${FRAIS_HOME:-$HOME/.frais}"
BIN_DIR="$INSTALL_DIR/bin"
VERSION="${FRAIS_VERSION:-0.1.0}"
REPO="hpy/frais"

# --------------- parse args ---------------
FROM_RELEASE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-release) FROM_RELEASE=true; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# --------------- prerequisites ---------------
if [ "$(uname -s)" != "Darwin" ]; then
    echo "frais: macOS is required." >&2
    exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
    arm64) RELEASE_ARCH="aarch64" ;;
    x86_64) RELEASE_ARCH="x86_64" ;;
    *) echo "frais: unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# --------------- install ---------------
mkdir -p "$BIN_DIR"

if $FROM_RELEASE; then
    # Download prebuilt binary from GitHub Releases
    TARBALL="frais-${VERSION}-${RELEASE_ARCH}-apple-darwin.tar.gz"
    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/v${VERSION}/${TARBALL}"

    echo "frais: downloading $DOWNLOAD_URL..." >&2
    TMPDIR="$(mktemp -d)"
    trap 'rm -rf "$TMPDIR"' EXIT

    if command -v curl &>/dev/null; then
        curl -fsSL "$DOWNLOAD_URL" -o "$TMPDIR/$TARBALL"
    elif command -v wget &>/dev/null; then
        wget -q "$DOWNLOAD_URL" -O "$TMPDIR/$TARBALL"
    else
        echo "frais: curl or wget is required." >&2
        exit 1
    fi

    echo "frais: extracting..." >&2
    tar xzf "$TMPDIR/$TARBALL" -C "$TMPDIR"
    cp "$TMPDIR/frais" "$BIN_DIR/frais"
    chmod +x "$BIN_DIR/frais"
else
    # Build from source
    if ! command -v cargo &>/dev/null; then
        echo "frais: Rust toolchain is required. Install it: https://rustup.rs" >&2
        exit 1
    fi

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

    if [ ! -f "$REPO_DIR/Cargo.toml" ]; then
        echo "frais: Cargo.toml not found at $REPO_DIR." >&2
        echo "Run this script from the frais repository (scripts/install_frais.sh)." >&2
        exit 1
    fi

    echo "frais: building release binary (this may take a minute)..." >&2
    cargo build --release --manifest-path "$REPO_DIR/Cargo.toml"

    echo "frais: installing to $BIN_DIR/..." >&2
    cp "$REPO_DIR/target/release/frais" "$BIN_DIR/frais"
    chmod +x "$BIN_DIR/frais"
fi

# --------------- warm dyld cache ---------------
echo "frais: warming cache..." >&2
"$BIN_DIR/frais" doctor >/dev/null 2>&1 || true

# --------------- PATH instructions ---------------
echo "" >&2
echo "frais: installed — $BIN_DIR/frais" >&2
echo "" >&2

# Check if frais bin dir is in PATH
if ! echo "${PATH:-}" | tr ':' '\n' | grep -qxF "$BIN_DIR"; then
    SHELL_NAME="$(basename "${SHELL:-bash}")"
    RC_FILE=""
    case "$SHELL_NAME" in
        zsh) RC_FILE="$HOME/.zshrc" ;;
        bash) RC_FILE="$HOME/.bashrc" ;;
        *) RC_FILE="$HOME/.profile" ;;
    esac
    echo "Add frais to your PATH:" >&2
    echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> $RC_FILE" >&2
    echo "  source $RC_FILE" >&2
fi

echo "frais: ready." >&2
