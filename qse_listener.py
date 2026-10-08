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
    _jaga_main(now)
    jam = int(now // 3600)
    if time.gmtime(now).tm_min >= 2 and st.get("jam_main") != jam:
        _st({"jam_main": jam})
        _jalankan_main(now)


MAIN = {"p": None, "t": 0.0, "lapor": 0.0}
LOG_MAIN = os.path.join(STATE_DIR, "main.log")


def _main_terkunci():
    """True bila .main.lock dipegang proses lain (main.py masih jalan atau nyangkut)."""
    import fcntl
    try:
        with open(os.path.join(STATE_DIR, ".main.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def _bunuh_main(alasan):
    import signal
    import subprocess
    p = MAIN["p"]
    try:
        if p is not None and p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", "main.py$"], check=False)
    MAIN["p"] = None
    print("[WARN] main.py dihentikan:", alasan)
    TG.send([f"🛠️ <b>QSE v148 | PERBAIKAN OTOMATIS</b>\n{TG.e(alasan)}. Proses lama aku hentikan, jadwal jalan lagi."])


def _ekor_log(n=600):
    try:
        with open(LOG_MAIN, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _jaga_main(now):
    """Cek hasil main.py yang dijalankan listener. Gagal di awal (misal file tidak cocok) langsung dilaporkan."""
    p = MAIN["p"]
    if p is None:
        return
    rc = p.poll()
    if rc is None:
        if now - MAIN["t"] > 55 * 60:
            _bunuh_main("main.py nyangkut lebih dari 55 menit")
        return
    MAIN["p"] = None
    if rc != 0 and now - MAIN["lapor"] > 3 * 3600:
        MAIN["lapor"] = now
        TG.send([f"⚠️ <b>QSE v148 | JADWAL GAGAL</b>\nmain.py berhenti dengan kode {rc}. Potongan log:\n"
                 f"<code>{TG.e(_ekor_log())}</code>"])


def _jalankan_main(now):
    import subprocess
    st = _st()
    if (MAIN["p"] is not None and MAIN["p"].poll() is None) or _main_terkunci():
        if now - st.get("main_mulai", 0) > 55 * 60:
            _bunuh_main("main.py sebelumnya nyangkut dan mengunci jadwal")
        else:
            return
    try:
        if os.path.exists(LOG_MAIN) and os.path.getsize(LOG_MAIN) > 2_000_000:
            os.replace(LOG_MAIN, LOG_MAIN + ".1")
        log = open(LOG_MAIN, "a")
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} mulai main.py =====\n")
        log.flush()
        MAIN["p"] = subprocess.Popen([sys.executable, "-u", "main.py"],
                                     cwd=os.path.dirname(os.path.abspath(__file__)), env=os.environ.copy(),
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        MAIN["t"] = now
        log.close()
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
