#!/usr/bin/env bash
set -euo pipefail
# Run from a reviewed local checkout. Does not use sudo or mutate system packages.
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HOME/.local/share/tsbench"
BIN="$HOME/.local/bin/tsbench"
mkdir -p "$ROOT" "$HOME/.local/bin"
chmod 700 "$ROOT"
if [[ -e "$BIN" || -L "$BIN" ]]; then
  echo "Refusing to overwrite existing $BIN" >&2
  exit 1
fi
python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/python" -m pip install --no-deps "$HERE"
ln -s "$ROOT/venv/bin/tsbench" "$BIN"
"$BIN" setup --config "$HERE/benchmark.yaml"
echo "Installed $BIN. Run: tsbench doctor"
