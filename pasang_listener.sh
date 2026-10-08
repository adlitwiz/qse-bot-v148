#!/usr/bin/env bash
# Pasang pendengar perintah Telegram sebagai layanan di VPS (jalan terus, hidup lagi otomatis saat VPS restart).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="${QSE_STATE_DIR:-$HOME/qse_state}"
if [ ! -f "$STATE/.env" ]; then
  echo "Buat dulu file $STATE/.env berisi dua baris:"
  echo "TELEGRAM_BOT_TOKEN=token_bot_kamu"
  echo "TELEGRAM_CHAT_ID=id_grup_kamu"
  exit 1
fi
[ -x "$STATE/venv/bin/python" ] || { echo "Jalankan bot sekali dulu (bash run.sh) supaya venv terbentuk."; exit 1; }
sudo tee /etc/systemd/system/qse-listener.service > /dev/null << UNIT
[Unit]
Description=QSE v148 pendengar perintah Telegram
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DIR
Environment=QSE_STATE_DIR=$STATE
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=$STATE/.env
ExecStart=$STATE/venv/bin/python $DIR/qse_listener.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now qse-listener
sleep 2
systemctl --no-pager status qse-listener | head -5
