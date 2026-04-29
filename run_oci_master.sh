#!/usr/bin/env sh
set -eu

BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="/usr/local/python3/bin/python3.14"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "❌ 未找到 Python 解释器: $PYTHON_BIN" >&2
  exit 1
fi

cd "$BASE_DIR"
exec "$PYTHON_BIN" "$BASE_DIR/OCI_Master.py" "$@"
