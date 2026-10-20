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


# Momentum 15/30 menit dimatikan. Uji 40 koin paling likuid data 15 menit 2021-2026, aturan robot persis:
# 15 menit PF 0.58, 30 menit PF 0.67. Variasi terbaik (30 menit, MARKET, trailing, volume 4x, searah EMA200 4J) PF 1.06.
# Info momentum di posisi kamu juga tidak membantu: geser SL ke entry saat momentum searah, profit turun 45%.
MOMENTUM_AKTIF = False


def _tugas_berkala():
    """Tiap 15 menit: peringatan dini posisi, BTC berbalik, scan momentum 15/30 menit.
    Tiap jam menit ke-2: jalankan main.py (cadangan jadwal GitHub yang sering telat). Ganda dicegah oleh main.py."""
    now = time.time()
    st = _st()
    if now - st.get("tnews", 0) >= 300:          # news tiap 5 menit (dulu 15 menit) supaya tidak terlalu telat
        _st({"tnews": now})
        try:
            import qse_news as NW
            with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
                simbol = {r["symbol"] for r in json.load(f)}
            nb = NW.cek(simbol)
            if nb:
                TG.send(["📰 <b>QSE v148 | NEWS PENTING</b>\n\n" + "\n\n".join(nb)])
        except Exception as ex:
            print("[WARN] news", ex)
    if now - st.get("t15", 0) >= 900:
        _st({"t15": now})
        try:
            import qse_catat as CT
            hasil = CT.cek()
            if hasil:
                TG.send(["📒 <b>QSE v148 | HASIL SARAN JALUR TAMBAHAN</b>\nDicatat otomatis untuk menilai jalur momentum "
                         "dan news. Ketik /jalur untuk rekap.\n\n" + "\n".join(hasil)])
        except Exception as ex:
            print("[WARN] catat", ex)
        try:
            if not MOMENTUM_AKTIF:
                raise StopIteration
            import qse_momentum as MO
            with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
                lama = json.load(f)
            bias = {r["symbol"]: (r.get("pasar") or {}).get("arah") for r in lama
                    if r.get("tf", "240") == "240" and r["rapor"] in ("A", "B")}
            info = {r["symbol"]: dict(rapor=r["rapor"], tick=r.get("tick")) for r in lama if r.get("tf", "240") == "240"}
            pos = {it["sym"]: it["arah"] for it in SY.lihat()["open"].values() if it["status"] in ("TERISI", "TP1")}
            pesan = MO.scan(list(dict.fromkeys(list(pos) + list(bias))), bias, pos, info)
            if pesan:
                TG.send(["⚡ <b>QSE v148 | MOMENTUM 15/30 MENIT</b>\nHanya momentum yang lolos penilaian semua aspek "
                         "yang jadi saran.\n\n" + "\n\n".join(pesan)])
        except StopIteration:
            pass
        except Exception as ex:
            print("[WARN] momentum", ex)
    t4 = int(now // 14400) * 14400
    if now - t4 >= 150 and st.get("ichi4", 0) < t4:
        # jalur Ichimoku tren: kelola trailing SL dan cari sinyal baru sekali tiap candle 4J tutup
        _st({"ichi4": t4})
        try:
            _btc_ema50()
        except Exception as ex:
            print("[WARN] btc ema50", ex)
        # candle 4J baru: lepas semua pin sinyal jalur dari candle sebelumnya, supaya yang disematkan hanya yang penting
        # sekarang (sinyal candle ini, laporan 4 jam terbaru, SL terbaru, peringatan posisi)
        try:
            import qse_strat as ST0
            stp = _st()
            lepas = {}
            for slot in ["pin_gzh", "pin_strat", "pin_ob", "pin_ichi"] + [f"pin_{k}" for k in ST0.STRAT]:
                if stp.get(slot) and stp.get(slot + "_t", 0) < t4:
                    TG.unpin(stp[slot])
                    lepas[slot] = None
            if lepas:
                _st(lepas)
        except Exception as ex:
            print("[WARN] lepas pin lama", ex)
        # semua jalur dikumpulkan dulu, lalu kartu sinyal baru dikirim urut prioritas (label terbukti dulu, lalu PF jalur):
        # yang paling bagus dikirim pertama, jadi berada paling atas di chat
        import qse_strat as ST
        kumpul = []          # (prioritas, slot pin, judul, kartu)
        try:
            import qse_ichimoku as IC
            pesan = IC.jalankan(baru_ok=True)          # telat (VPS sempat mati) tetap boleh asal harga belum lari, dicek di IC
            lain = [m for m in pesan or [] if "BISA DIIKUTI" not in m]
            if lain:
                TG.send(["📈 <b>QSE v148 | ICHIMOKU TREN 4J</b>\n\n" + "\n\n".join(lain)])
            kumpul += [(ST.prioritas_teks("ichimoku", m), "pin_ichi", "ICHIMOKU", m) for m in pesan or [] if "BISA DIIKUTI" in m]
        except Exception as ex:
            print("[WARN] ichimoku", ex)
        try:
            import qse_ob as OB
            pesan = OB.jalankan(baru_ok=True)          # jalur Order Block + Volume, aturan sama dengan backtest 6 tahun
            lain = [m for m in pesan or [] if "BISA DIIKUTI" not in m]
            if lain:
                TG.send(["⭐ <b>QSE v148 | ORDER BLOCK 4J</b>\n\n" + "\n\n".join(lain)])
            kumpul += [(ST.prioritas_teks("orderblock", m), "pin_ob", "ORDER BLOCK + VOLUME (LONG)", m)
                       for m in pesan or [] if "BISA DIIKUTI" in m]
            sl_v = OB.proses_sl()                      # analisa volume SL setelah candle 4J tempat SL kena sudah tutup
            if sl_v:
                TG.send(["📊 <b>QSE v148 | ANALISA VOLUME SL</b>\n\n" + "\n\n".join(sl_v)])
        except Exception as ex:
            print("[WARN] orderblock", ex)
        try:
            for k, pesan in ST.jalankan(baru_ok=True).items():
                nama = ST.STRAT[k]["nama"].upper()
                lain = [m for m in pesan if "BISA DIIKUTI" not in m]
                if lain:
                    TG.send([f"📈 <b>QSE v148 | {nama}</b>\n\n" + "\n\n".join(lain)])
                kumpul += [(ST.prioritas_teks(k, m), f"pin_{k}", nama, m) for m in pesan if "BISA DIIKUTI" in m]
        except Exception as ex:
            print("[WARN] strategi", ex)
        try:
            kumpul.sort(key=lambda z: z[0], reverse=True)
            kirim = []
            for no, (pr, slot, nama, m) in enumerate(kumpul, 1):
                lb = ST.label_nama_teks(m)
                ids = TG.send([f"📌 <b>QSE v148 | DETAIL SINYAL BARU {nama}</b>\n"
                               f"{('⭐ ' + ' + '.join(lb)) if lb else 'tanpa label'}  ·  PF jalur {pr[1]:.2f}  ·  "
                               f"dikirim urut prioritas, urutan lengkap ada di pesan 🎯 SINYAL 4 JAM\n"
                               f"{SY.baris_jadwal(telat_menit=3)}\n{m}"])
                kirim.append((slot, ids))
            terbaik = {}
            for slot, ids in kirim:
                terbaik.setdefault(slot, ids)          # tiap slot menyematkan sinyal terbaik jalur itu
            for slot, ids in reversed(list(terbaik.items())):
                _pin_ichi(ids, slot)                   # disematkan terbalik: prioritas 1 jadi pin paling atas
        except Exception as ex:
            print("[WARN] kirim prioritas", ex)
        try:
            teks, tanda = SY.kartu_sl()
            if teks and [list(x) for x in tanda] != _st().get("sl_tanda"):
                _st({"sl_tanda": [list(x) for x in tanda]})
                _pin_ichi(TG.send([teks]), "pin_sl")
        except Exception as ex:
            print("[WARN] kartu SL", ex)
    hari = int(now // 86400) * 86400
    if now - hari >= 15 * 3600 and st.get("tidur_hari", 0) < hari and now - hari <= 16 * 3600:
        # 22:00 WIB: kartu siap tidur kalau ada posisi jalan
        _st({"tidur_hari": hari})
        try:
            teks, _ = SY.kartu_sl(tidur=True)
            if teks:
                TG.send([teks])
        except Exception as ex:
            print("[WARN] kartu tidur", ex)
    if now - hari >= 300 and st.get("arah_hari", 0) < hari and now - hari <= 6 * 3600:
        # 07:05 WIB, candle harian baru tutup: kirim arah pasar otomatis (BTC, ETH, posisi kamu, berita hari ini)
        _st({"arah_hari": hari})
        try:
            import qse_arah as AR
            TG.send(["🧭 <b>QSE v148 | ARAH PASAR HARIAN</b>\n\n" + AR.harian()])
        except Exception as ex:
            print("[WARN] arah harian", ex)
    _jaga_main(now)
    tutup4 = int(now // 14400) * 14400
    if now - tutup4 >= 120 and st.get("scan4", 0) < tutup4 * 1000 and now - st.get("susul_coba", 0) >= 900:
        # laporan 4 jam terakhir belum pernah jadi (bot mati, update, atau gagal): susulkan sekarang
        _st({"susul_coba": now})
        _jalankan_main(now)
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
    jalan = MAIN["p"] is not None and MAIN["p"].poll() is None
    if jalan or _main_terkunci():
        # main_mulai baru ditulis main.py beberapa detik setelah start, jadi untuk proses milik listener
        # pakai MAIN["t"]. Tanpa ini run yang baru 2 detik jalan ikut dibunuh (laporan nyangkut palsu).
        mulai = max(MAIN["t"] if jalan else 0.0, st.get("main_mulai", 0))
        if now - mulai > 55 * 60:
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


def _btc_ema50():
    """Info saja: kabari saat arah resmi BTC 4J pindah sisi EMA 50 (batas 0.3% dan 2 candle, sekitar 1.5 kali seminggu). Bukan ramalan,
    uji 2021-2026 arah ini tepat sekitar 49% untuk 4 sampai 72 jam ke depan. Tidak menyaring sinyal."""
    import qse_strat as ST
    df = ST._k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return
    c = df["close"].values.astype(float)
    naik = ST.btc_arah_resmi(c, ST._ema(c, 50))
    lama = _st().get("btc50")
    _st({"btc50": naik})
    if lama is None or lama == naik:
        return
    TG.send([f"{'🟢' if naik else '🔴'} <b>QSE v148 | ARAH BTC BERUBAH</b>\n{ST.btc_ema50_teks()}\n"
             f"BTC 4J sudah 2 candle tutup lebih dari {ST.BTC_BAND:g}% {'di atas' if naik else 'di bawah'} EMA 50. "
             f"Batas ini membuang flip palsu: tanpa batas 47% flip balik lagi dalam 12 jam, dengan batas 8%. "
             f"Info saja, sinyal jalur tetap jalan seperti biasa."])


def _pin_ichi(ids, slot="pin_ichi"):
    """Slot pin prioritas sinyal terbukti: pin_ichi untuk Ichimoku, pin_ob untuk Order Block. Pin lama slot yang sama
    dilepas. Pin ini dinaikkan lagi ke paling atas setiap laporan 4 jam disematkan (main._naikkan_pin_ichi), selama 24 jam."""
    if not ids or not ids[0]:
        return
    lama = _st().get(slot)
    if TG.pin(ids[0]) is None:
        if lama and lama != ids[0]:
            TG.unpin(lama)
        _st({slot: ids[0], slot + "_t": time.time()})


def _pin_dini(ids):
    """Slot pin kedua: peringatan dini trade kamu. Pin lama slot ini dilepas, pin laporan 4 jam tidak disentuh."""
    if not ids or not ids[0]:
        return
    lama = _st().get("pin_dini")
    if TG.pin(ids[0]) is None:
        if lama and lama != ids[0]:
            TG.unpin(lama)
        _st({"pin_dini": ids[0]})


_GERAK = []          # snapshot harga tiap menit: (waktu, {simbol: harga}), 40 menit terakhir


def _gerak_serentak():
    """Peringatan cepat dari HARGA, bukan berita: berita kripto biasanya terbit setelah harga bergerak.
    Pemicu (30 menit): BTC bergerak 2% atau lebih, atau 70% dari 40 koin paling likuid bergerak 3% searah.
    Uji data 15 menit 2022-2026: sekitar 6 sampai 9 kali per bulan. Jeda 2 jam antar peringatan. Info saja:
    uji 2021-2026 menutup posisi lebih awal saat pasar bergejolak menurunkan profit, jadi aturan jalur tetap dipakai."""
    import bybit_fetch as B
    now = time.time()
    tk = B.get_tickers()
    top = [s for s, _ in sorted(((s, v["turnover"]) for s, v in tk.items() if s.endswith("USDT") and s != "BTCUSDT"),
                                key=lambda z: -z[1])[:40]]
    snap = {s: tk[s]["last"] for s in top + ["BTCUSDT"] if s in tk and tk[s]["last"] > 0}
    _GERAK.append((now, snap))
    while _GERAK and now - _GERAK[0][0] > 40 * 60:
        _GERAK.pop(0)
    lama = next((sn for t, sn in _GERAK if now - t >= 28 * 60), None)
    if not lama or now - _st().get("gerak_t", 0) < 7200:
        return
    ch = {s: (snap[s] / lama[s] - 1) * 100 for s in snap if lama.get(s)}
    btc = ch.get("BTCUSDT")
    alt = [v for s, v in ch.items() if s != "BTCUSDT"]
    if btc is None or len(alt) < 20:
        return
    naik = sum(1 for v in alt if v >= 3) / len(alt)
    turun = sum(1 for v in alt if v <= -3) / len(alt)
    if not (abs(btc) >= 2 or naik >= 0.7 or turun >= 0.7):
        return
    arah_naik = (btc > 0) if abs(btc) >= 2 else naik >= 0.7
    _st({"gerak_t": now})
    rows = [f"{'🚀' if arah_naik else '💥'} <b>QSE v148 | PASAR BERGERAK SERENTAK {'NAIK' if arah_naik else 'TURUN'}</b>",
            f"30 menit terakhir: BTC {btc:+.1f}%, {round(naik * len(alt))} dari {len(alt)} koin utama naik 3%+, "
            f"{round(turun * len(alt))} turun 3%+.",
            "Biasanya berita baru muncul setelah ini, jadi peringatan ini dari harga langsung."]
    pos = []
    try:
        for it in SY.lihat()["open"].values():
            if it["status"] not in ("TERISI", "TP1"):
                continue
            px = (tk.get(it["sym"]) or {}).get("last")
            fl = SY.floating(it, px) if px else None
            searah = (it["arah"] == "LONG") == arah_naik
            pos.append(f"{'🟢' if searah else '🔴'} {it['sym']} {it['arah']} "
                       + (f"{fl['r']:+.2f}R" if fl else "") + (" (searah gerak)" if searah else " (melawan gerak)"))
    except Exception as ex:
        print("[WARN] gerak posisi", ex)
    if pos:
        rows += ["", "👤 Posisi kamu:"] + pos + [
            "↳ Melawan gerak: SL di Bybit yang membatasi rugi, jangan geser SL menjauh dan jangan tambah posisi.",
            "↳ Searah gerak: biarkan Trailing Stop atau TP jalur bekerja.",
            "Uji 2021-2026: tutup lebih awal saat pasar bergejolak menurunkan profit 18 sampai 78%."]
    rows += ["", "Jangan kejar harga di luar sinyal robot. Sinyal baru hanya dari laporan 4J dan /sinyal4j yang masih valid."]
    TG.send(["\n".join(rows)])


def _tugas_menit():
    try:
        _gerak_serentak()
    except Exception as ex:
        print("[WARN] gerak serentak", ex)
    try:
        pesan = SY.pantau()
        if pesan:
            TG.send(["👤 <b>QSE v148 | TRADE KAMU</b>\n\n" + "\n".join(pesan)])
    except Exception as ex:
        print("[WARN] pantau", ex)
    try:
        sb = SY.siaga_berita()
        if sb:
            TG.send(["📅 <b>QSE v148 | SIAGA BERITA BESAR</b>\n\n" + "\n\n".join(sb)])
    except Exception as ex:
        print("[WARN] siaga berita", ex)
    try:
        pesan = SY.peringatan_dini()
        if pesan:
            _pin_dini(TG.send(["⚠️ <b>QSE v148 | PERINGATAN DINI TRADE KAMU</b>\n\n" + "\n\n".join(pesan)]) or [])
        elif _st().get("pin_dini") and not any(it["status"] in ("TERISI", "TP1") for it in SY.lihat()["open"].values()):
            TG.unpin(_st()["pin_dini"])           # semua posisi sudah tutup: lepas pin peringatan
            _st({"pin_dini": None})
    except Exception as ex:
        print("[WARN] dini", ex)
    try:
        fb = SY.sentuh_fib()
        if fb:
            TG.send(["📐 <b>QSE v148 | GOLDEN ZONE HUNTER (GZH)</b>\nSearah tren dan BTC, keluar dengan SL berjalan.\n\n" + "\n\n".join(fb)])
    except Exception as ex:
        print("[WARN] fib", ex)
    try:
        kena = AL.cek()
        gz = [m for m in kena if "GZH TERKONFIRMASI" in m]
        kena = [m for m in kena if m not in gz]
        if gz:
            ids = TG.send([f"📌 <b>QSE v148 | SINYAL GZH GOLDEN ZONE ({len(gz)})</b>\nJalur terbukti, disematkan.\n\n" + "\n\n".join(gz)])
            _pin_ichi(ids, "pin_gzh")
        if kena:
            TG.send(["🔔 <b>QSE v148 | ALARM</b>\n\n" + "\n\n".join(kena)])
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
