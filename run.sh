#!/usr/bin/env bash
# Jalankan QSE Bot di VPS: dipanggil GitHub self-hosted runner atau crontab.
set -euo pipefail
cd "$(dirname "$0")"
STATE="${QSE_STATE_DIR:-$HOME/qse_state}"
export QSE_STATE_DIR="$STATE"
mkdir -p "$STATE"
VENV="$STATE/venv"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
H=$(sha1sum requirements.txt | cut -c1-40)
if [ "$(cat "$STATE/.req" 2>/dev/null || true)" != "$H" ]; then
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r requirements.txt
  echo "$H" > "$STATE/.req"
fi
"$VENV/bin/python" -c "import numba" 2>/dev/null || "$VENV/bin/pip" install -q numba
exec flock -w 600 "$STATE/.lock" "$VENV/bin/python" main.py "$@"
