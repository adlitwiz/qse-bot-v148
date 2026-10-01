"""QSE v148 - pendengar Telegram. Jalan terus di VPS: balas perintah dalam hitungan detik dan
pantau trade kamu (/entry) tiap menit. Pasang sekali dengan: bash pasang_listener.sh"""
import fcntl
import json
import os
import time
import requests

STATE_DIR = os.environ.get("QSE_STATE_DIR") or os.path.expanduser("~/qse_state")
ENV = os.path.join(STATE_DIR, ".env")
if os.path.exists(ENV):
    for ln in open(ENV):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import qse_perintah as QP           # noqa: E402
import qse_saya as SY               # noqa: E402
import qse_alarm as AL              # noqa: E402
import telegram_notify as TG        # noqa: E402

STATE = os.path.join(STATE_DIR, "state.json")
ALIVE = os.path.join(STATE_DIR, "listener.alive")


def _st(upd=None):
    try:
        with open(STATE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    if upd is not None:
        with open(STATE + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                with open(STATE) as f:
                    st = json.load(f)
            except Exception:
                st = {}
            st.update(upd)
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f)
            os.replace(STATE + ".tmp", STATE)
    return st


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise SystemExit(f"Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di {ENV}")
    os.makedirs(STATE_DIR, exist_ok=True)
    print("QSE listener aktif")
    terakhir = 0.0
    while True:
        with open(ALIVE, "w") as f:
            f.write(str(time.time()))
        if time.time() - terakhir >= 60:
            terakhir = time.time()
            try:
                pesan = SY.pantau()
                if pesan:
                    TG.send(["👤 <b>QSE v148 | TRADE KAMU</b>\n\n" + "\n".join(pesan)])
            except Exception as ex:
                print("[WARN] pantau", ex)
            try:
                kena = AL.cek()
                if kena:
                    TG.send(["🔔 <b>QSE v148 | ALARM HARGA</b>\n\n" + "\n\n".join(kena)])
            except Exception as ex:
                print("[WARN] alarm", ex)
        off = _st().get("tg_offset", 0)
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                             params={"offset": off, "timeout": 25, "allowed_updates": '["message"]'}, timeout=40)
            data = r.json().get("result", [])
        except Exception as ex:
            print("[WARN]", ex)
            time.sleep(5)
            continue
        cmds = []
        for u in data:
            off = max(off, u["update_id"] + 1)
            m = u.get("message") or {}
            txt = (m.get("text") or "").strip()
            if str(m.get("chat", {}).get("id")) != str(chat) or not txt.startswith("/"):
                continue
            parts = txt.split()
            cmds.append((parts[0].split("@")[0].lower(), parts[1:]))
        if data:
            _st({"tg_offset": off})
        if cmds:
            print("perintah:", QP.proses(cmds))


if __name__ == "__main__":
    main()
