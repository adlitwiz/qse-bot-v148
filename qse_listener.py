"""QSE v148 - pendengar Telegram. Jalan terus di VPS: balas perintah dalam hitungan detik dan
pantau trade kamu (/entry) tiap menit. Pasang sekali dengan: bash pasang_listener.sh"""
import fcntl
import json
import os
import sys
import time
import threading
import requests

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

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
            import qse_makro as MK
            bb = MK.berita_baru()
            if bb:
                TG.send(["📰 <b>QSE v148 | BERITA PENTING</b>\nDisaring kata kunci berdampak besar. Bukan sinyal, cek kondisi pasar.\n\n"
                         + "\n\n".join(f"🗞️ <b>{TG.e(b['judul'])}</b>\n↳ {b['sumber']} | {', '.join(b['kategori'])}"
                                         + (f"\n↳ {TG.e(b['link'])}" if b["link"] else "") for b in bb)])
        except Exception as ex:
            print("[WARN] berita", ex)
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


HB = {"perintah": time.time(), "kerja": time.time()}
BATAS_PERINTAH = 180      # loop perintah macet lebih dari 3 menit -> restart paksa
BATAS_KERJA = 1500        # tugas berkala macet lebih dari 25 menit -> restart paksa


def _tugas_menit():
    try:
        pesan = SY.pantau()
        if pesan:
            TG.send(["👤 <b>QSE v148 | TRADE KAMU</b>\n\n" + "\n".join(pesan)])
    except Exception as ex:
        print("[WARN] pantau", ex)
    try:
        fb = SY.sentuh_fib()
        if fb:
            TG.send(["📐 <b>QSE v148 | GOLDEN ZONE HUNTER</b>\nCuma setup yang lolos penilaian semua aspek yang aku kirim.\n\n" + "\n\n".join(fb)])
    except Exception as ex:
        print("[WARN] fib", ex)
    try:
        kena = AL.cek()
        if kena:
            TG.send(["🔔 <b>QSE v148 | ALARM HARGA</b>\n\n" + "\n\n".join(kena)])
    except Exception as ex:
        print("[WARN] alarm", ex)


def _pekerja():
    """Thread terpisah: pantau trade, alarm, berita, momentum. Kalau macet, balasan perintah tetap jalan."""
    terakhir = 0.0
    while True:
        HB["kerja"] = time.time()
        try:
            if time.time() - terakhir >= 60:
                terakhir = time.time()
                _tugas_menit()
            _tugas_berkala()
        except Exception as ex:
            print("[WARN] pekerja", ex)
        HB["kerja"] = time.time()
        time.sleep(5)


def _penjaga():
    """Bila salah satu loop macet, matikan proses. systemd (Restart=always) menghidupkannya lagi dalam 5 detik."""
    while True:
        time.sleep(30)
        a = time.time() - HB["perintah"]
        b = time.time() - HB["kerja"]
        if a > BATAS_PERINTAH or b > BATAS_KERJA:
            print(f"[FATAL] listener macet (perintah {a:.0f}s, kerja {b:.0f}s), restart paksa")
            os._exit(1)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise SystemExit(f"Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di {ENV}")
    os.makedirs(STATE_DIR, exist_ok=True)
    print("QSE listener aktif", flush=True)
    threading.Thread(target=_pekerja, daemon=True).start()
    threading.Thread(target=_penjaga, daemon=True).start()
    while True:
        HB["perintah"] = time.time()
        with open(ALIVE, "w") as f:
            f.write(str(time.time()))
        off = _st().get("tg_offset", 0)
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                             params={"offset": off, "timeout": 25, "allowed_updates": '["message"]'}, timeout=(10, 40))
            js = r.json()
        except Exception as ex:
            print("[WARN] getUpdates", ex)
            time.sleep(5)
            continue
        if not js.get("ok"):
            # 401 = token salah/dicabut, 409 = ada pemanggil getUpdates lain atau webhook aktif
            print("[WARN] getUpdates ditolak Telegram:", r.status_code, js.get("description"))
            time.sleep(10)
            continue
        data = js.get("result", [])
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
            print("perintah:", [c for c, _ in cmds], flush=True)
            try:
                print("dibalas:", QP.proses(cmds), flush=True)
            except Exception as ex:
                print("[WARN] proses perintah", ex)


if __name__ == "__main__":
    main()
