"""QSE v148 - pendengar Telegram. Jalan terus di VPS: balas perintah dalam hitungan detik dan
pantau trade kamu (/entry) tiap menit. Pasang sekali dengan: bash pasang_listener.sh"""
import fcntl
import json
import os
import sys
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


def _tugas_berkala():
    """Tiap 15 menit: peringatan dini posisi, BTC berbalik, scan momentum 15/30 menit.
    Tiap jam menit ke-2: jalankan main.py (cadangan jadwal GitHub yang sering telat). Ganda dicegah oleh main.py."""
    import subprocess
    now = time.time()
    st = _st()
    if now - st.get("t15", 0) >= 900:
        _st({"t15": now})
        try:
            pesan = SY.peringatan_dini()
            if pesan:
                TG.send(["⚠️ <b>QSE v148 | PERINGATAN</b>\n\n" + "\n\n".join(pesan)])
        except Exception as ex:
            print("[WARN] dini", ex)
        try:
            import qse_momentum as MO
            with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
                lama = json.load(f)
            bias = {r["symbol"]: (r.get("pasar") or {}).get("arah") for r in lama
                    if r.get("tf", "240") == "240" and r["rapor"] in ("A", "B")}
            pos = {it["sym"]: it["arah"] for it in SY.lihat()["open"].values() if it["status"] in ("TERISI", "TP1")}
            pesan = MO.scan(list(dict.fromkeys(list(pos) + list(bias))), bias, pos)
            if pesan:
                TG.send(["⚡ <b>QSE v148 | MOMENTUM 15/30 MENIT</b>\n\n" + "\n\n".join(pesan)])
        except Exception as ex:
            print("[WARN] momentum", ex)
    jam = int(now // 3600)
    if time.gmtime(now).tm_min >= 2 and st.get("jam_main") != jam:
        _st({"jam_main": jam})
        try:
            subprocess.Popen([sys.executable, "main.py"], cwd=os.path.dirname(os.path.abspath(__file__)),
                             env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except Exception as ex:
            print("[WARN] jadwal main", ex)


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
                fb = SY.sentuh_fib()
                if fb:
                    TG.send(["📐 <b>QSE v148 | SENTUH FIB 0.618</b> (Golden Zone Hunter)\n\n" + "\n\n".join(fb)])
            except Exception as ex:
                print("[WARN] fib", ex)
            try:
                kena = AL.cek()
                if kena:
                    TG.send(["🔔 <b>QSE v148 | ALARM HARGA</b>\n\n" + "\n\n".join(kena)])
            except Exception as ex:
                print("[WARN] alarm", ex)
        _tugas_berkala()
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
