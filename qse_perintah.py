"""QSE v150 - semua perintah Telegram. Dipakai qse_listener.py (balasan detik) dan main.py (cadangan)."""
import fcntl
import json
import os
import re
import time
import qse_fixprofit as FX
import qse_saya as SY
import qse_alarm as AL
import telegram_notify as TG
from config import STATE_DIR

LOCK_BOT = os.path.join(STATE_DIR, ".lock")

def mulai_scan():
    """Jalankan scan sekarang di proses terpisah supaya listener tetap bisa membalas perintah lain."""
    import subprocess
    import sys
    tanda = os.path.join(STATE_DIR, ".scan_terakhir")
    try:
        if time.time() - os.path.getmtime(tanda) < 600:
            sisa = int(600 - (time.time() - os.path.getmtime(tanda))) // 60 + 1
            return f"Scan terakhir belum 10 menit. Coba lagi sekitar {sisa} menit lagi, atau cek /sinyal4j dan /sinyal1j."
    except OSError:
        pass
    open(tanda, "w").close()
    folder = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, "main.py", "--scan"], cwd=folder, env=os.environ.copy(),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return ("Scan dimulai. Robot menilai ulang koin rapor A/B di TF 4J dan TF 1J dengan harga terkini. "
            "Hasilnya terkirim dalam 1 sampai 3 menit.")


def mulai_laporan4j():
    """Paksa laporan 4 jam sekarang (laporan susulan) di proses terpisah."""
    import fcntl
    import subprocess
    import sys
    try:
        with open(os.path.join(STATE_DIR, ".main.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return "Laporan 4 jam sedang dibuat. Hasilnya otomatis terkirim begitu selesai."
    tanda = os.path.join(STATE_DIR, ".laporan_terakhir")
    try:
        if time.time() - os.path.getmtime(tanda) < 900:
            return "Laporan 4 jam baru saja diminta. Tunggu hasilnya dulu, paling lama 20 menit."
    except OSError:
        pass
    open(tanda, "w").close()
    folder = os.path.dirname(os.path.abspath(__file__))
    log = open(os.path.join(STATE_DIR, "main.log"), "a")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} /laporan4j =====\n")
    log.flush()
    subprocess.Popen([sys.executable, "-u", "main.py", "semua"], cwd=folder, env=os.environ.copy(),
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    return ("Laporan 4 jam susulan dimulai. Robot memindai semua koin dengan harga sekarang. "
            "Hasilnya terkirim dalam 10 sampai 20 menit dan otomatis disematkan.")


# v172 QC 70: perintah yang isinya milik pengirim (posisi, modal, catatan). Balasannya bernama dan tombolnya terkunci ke pengirim.
PRIBADI = {"/entry", "/status", "/milikku", "/punyaku", "/tutup", "/tp", "/sl", "/batal", "/tpall", "/tpsemua", "/slall", "/slsemua", "/ubah",
           "/modify", "/modif", "/edit", "/modal", "/pindah", "/kelola", "/be", "/hapus", "/catat"}
BANTUAN = ("❓ <b>QSE v150 | INFO</b>\n\n"
           "Robot jalan otomatis: scan tiap 4 jam dan per jam, pantau posisi tiap menit, berita, peta BTC pagi 07:05 WIB, "
           "dan aturan jaga modal: TP 20% di +0.5R lalu SL ke entry, jam ke-12, batas 30 jam, jeda 24 jam setelah 3 rugi beruntun. "
           "EMA Cross SHORT: tanpa TP sebagian, SL ke entry di +0.4R lalu SL berjalan. McGinley: sisa posisi trailing 3 ATR. "
           "Robot hanya memberi sinyal koin Futures Bybit. "
           "Semua fitur ada di tombol bawah. Balasan dan tombol pribadi (posisi, status, modal, entry) hanya bisa ditekan pemiliknya, "
           "namanya tertulis di judul pesan.\n\n"
           "📊 <b>Status</b>: hasil hari ini, slot, dan tombol per posisi kamu\n"
           "📡 <b>Sinyal 4J</b>: sinyal valid sekarang plus rencana Sniper S/R, tiap kartu punya tombol 📋 Salin Setup\n"
           "₿ <b>Cek BTC</b>: arah BTC, level, dan peta pasar\n"
           "💼 <b>Modal</b>: isi modal, leverage, entry per koin, risiko persen\n"
           "📝 <b>Entry</b>: catat posisi, cukup tempel blok yang disalin\n"
           "🎯 <b>Kelola Posisi</b>: TP 50%, SL ke entry, tutup, per posisi kamu\n"
           "🔔 <b>Alarm</b>: harga sentuh atau candle tutup\n"
           "🧩 <b>Jalur Sinyal</b>: Sektor, Ichimoku, Order Block, EMA/RSI/SMC, Lab, Rencana Sniper\n"
           "🔎 <b>Cek Koin</b>: analisa lengkap koin apa pun\n"
           "📰 <b>Berita</b>: kabar terbaru dan yang viral 6 jam dalam satu pesan\n"
           "📈 <b>Laporan</b>: mingguan, evaluasi, uji mundur, laporan 4J\n"
           "🪰 <b>Lalat Abdul</b>: lapar, dopamin, serotonin, GABA, pola disukai dan dibenci, pilihan trade harian lalat\n"
           "😴 <b>Mode Tidur</b>: posisi dijaga otomatis saat kamu tidur\n\n"
           "Perintah ketik lama tetap jalan untuk yang sudah hafal.")
BANTUAN_SEMUA = BANTUAN


def _sym(a):
    return a if a.endswith("USDT") else a + "USDT"


def _bot_bebas():
    lk = open(LOCK_BOT, "a")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lk
    except OSError:
        lk.close()
        return None


def _batal_sinyal(sym, dari_main):
    """Hapus sinyal robot koin ini dari catatan. Return teks keterangan."""
    if dari_main:
        led = FX.load()
        n = FX.batal_manual(led, sym)
        FX.save(led)
        return n, False
    lk = _bot_bebas()
    try:
        led = FX.load()
        ada = sum(1 for v in led["open"].values() if v["sym"] == sym)
        if not ada:
            return 0, False
        if lk:
            FX.batal_manual(led, sym)
            FX.save(led)
            return ada, False
        FX.antrian_tambah(sym)
        return ada, True
    finally:
        if lk:
            lk.close()


def balas(cmd, args, dari_main=False):
    if cmd == "/entry":
        return SY.entry(args)
    if cmd in ("/cek", "/cekdetail"):
        if not args:
            return "Format: /cek SOL atau /cek SOL long 185.4"
        sym = _sym(args[0])
        arah = next((("LONG" if a in ("LONG", "BUY") else "SHORT") for a in args[1:]
                     if a in ("LONG", "SHORT", "BUY", "SELL")), None)
        harga = next((SY._angka(a) for a in args[1:] if SY._angka(a) is not None), None)
        if cmd == "/cekdetail":
            return SY.konsultasi(sym, arah, harga)
        return SY.cek_jalur(sym, arah, harga)
    if cmd in ("/tutup", "/tp", "/sl") and args and args[0] in ("ALL", "SEMUA", "ALLUSDT", "SEMUAUSDT"):
        return SY.tutup_semua({"/tp": "ambil profit", "/sl": "cut loss"}.get(cmd, "TUTUP"))
    if cmd in ("/tpall", "/tpsemua"):
        return SY.tutup_semua("ambil profit")
    if cmd in ("/slall", "/slsemua"):
        return SY.tutup_semua("cut loss")
    if cmd == "/tutup":
        return SY.tutup(args) + _sisa_posisi()
    if cmd == "/mode":
        import qse_strat as ST
        if args:
            m = ST.set_mode(args[0])
            if not m:
                return "Pilihan: /mode semua, /mode profit, atau /mode raja"
        m = ST.mode_sinyal()
        return (f"Mode sinyal sekarang: <b>{m.upper()}</b> (skor label minimal {ST.MODE_MIN[m]})\n\n"
                "• /mode semua: semua sinyal jalur terbukti. Uji 2021-2026 PF 1.24 dan 1.28, sekitar 15 sinyal per hari sebelum batas posisi\n"
                "• /mode profit: skor label 5 ke atas. PF 1.65 dan 1.77, WR 44-45%, sekitar 2 sinyal per hari, drawdown 4 kali lebih kecil\n"
                "• /mode raja: skor label 8 ke atas. PF 2.25 dan 2.22, WR 48%, sekitar 1 sinyal per 2-3 hari\n\n"
                "Tidak ada mode yang pasti untung. Mode profit tetap kena SL sekitar 55% trade, untungnya dari trade menang yang lebih besar.")
    if cmd == "/pindah":
        return SY.pindah(args)
    if cmd == "/tp":
        return SY.tutup(args, "ambil profit") + _sisa_posisi()
    if cmd == "/sl":
        return SY.tutup(args, "cut loss") + _sisa_posisi()
    if cmd == "/tespin":
        ids = TG.send(["📌 <b>QSE v150 | TES PIN</b>\nKalau pesan ini tersemat, izin pin bot sudah benar."]) or []
        if not ids:
            return "Pesan tes gagal terkirim."
        err = TG.pin(ids[0])
        return ("✅ Pin berhasil. Sinyal 4 jam berikutnya akan otomatis disematkan dan pin lama dilepas."
                if not err else f"❌ Pin gagal. Kata Telegram: {TG.e(str(err))}\nBuka info grup, Administrator, pilih bot, "
                f"lalu aktifkan izin Sematkan pesan (Pin messages).")
    if cmd == "/kalibrasi":
        return SY.kalibrasi_teks(args[0]) if args else "Format: /kalibrasi ETHFI"
    if cmd == "/serok":
        return SY.serok(args)
    if cmd == "/hapus":
        return SY.hapus(args)
    if cmd in ("/ubah", "/modify", "/modif", "/edit"):
        return SY.ubah_level(args)
    if cmd in ("/alert", "/alarm"):
        return AL.perintah(args)
    if cmd in ("/tunggu", "/close"):
        return AL.tunggu(args)
    if cmd in ("/sinyal4j", "/sinyal4", "/sinyal", "/scan"):
        # v150 urutan: 1 sinyal jalur live yang masih valid, 2 sinyal terkuat (combo raja/fix/emas, NILAI 9-10) dan yang ditahan otak,
        # 3 Sniper S/R koin medali
        isi = SY.sinyal_jalur()
        try:
            import qse_kompas as KP          # 9 Nov 2026: kompas yang sama dengan Cek BTC, di bawah judul
            kp = KP.kompas()
            if kp:
                j1, _, sisa = isi.partition("\n")
                isi = j1 + "\n" + KP.blok(kp, singkat=True) + "\n" + sisa
        except Exception as ex:
            print("[WARN] sinyal4j kompas", ex)
        try:
            import qse_ditahan as DT
            import qse_cuaca as CU
            now = time.time()
            kuat, tahan = [], []
            for k, nama, it in DT._sumber():
                if now - it.get("t", 0) > 12 * 3600:
                    continue
                prio, nm_p = DT.prioritas_live(k, it)
                cu = CU.NAMA[CU.jenis(k)].split(" ", 1)[1]
                kl_ = DT.kelas(k, it, prio)[0]
                baris = (f"• {it['sym']} {it['arah']} · {nama} · {cu}" + (f" · {nm_p}" if nm_p else "")
                         + f" · {'🟦 UTAMA' if kl_ == 'UTAMA' else '🟨 RINGAN'} · entry {it['entry']:.6g} SL {it['sl']:.6g}")
                if prio:
                    kuat.append(baris)
                elif it.get("otak_saring"):
                    tahan.append(baris)
            if kuat:
                isi += ("\n\n🔥 <b>SINYAL TERKUAT 12 JAM TERAKHIR</b> (combo raja, fix, emas, EMA Cross SHORT, BTC.D TURUN SHORT, "
                        "NILAI 9-10, dikirim tanpa ditahan)\n" + "\n".join(kuat[:10]))
            if tahan:
                isi += "\n\n🧠 <b>EKS-TAHANAN OTAK, tetap dikirim 🟨 KELAS RINGAN</b>\n" + "\n".join(tahan[:10])
        except Exception as ex:
            print("[WARN] sinyal4j kuat", ex)
        try:
            import qse_gzh2 as GZ2
            isi += "\n\n" + GZ2.teks()
        except Exception as ex:
            print("[WARN] sinyal4j gzh2", ex)
        try:
            import qse_whip as WP
            isi += "\n\n" + WP.teks()
        except Exception as ex:
            print("[WARN] sinyal4j whip", ex)
        try:
            import qse_rencana as RC
            sp, _ = RC.blok_spesialis()          # koin medali di bagian ketiga
            isi += "\n\n" + sp
        except Exception as ex:
            print("[WARN] sinyal4j rencana", ex)
        try:
            import qse_lalat as LT
            pl = LT.pilihan_teks()
            if pl:
                isi += "\n\n" + pl
        except Exception as ex:
            print("[WARN] sinyal4j lalat", ex)
        return isi
    if cmd in ("/sinyal1j", "/sinyal1"):
        return ("Saran 1J dimatikan. Uji 111 koin data 1 jam 2020-2026: 9 jalur terbukti versi 1J PF 1.00 sampai 1.11, "
                "tidak ada yang untung setelah biaya. Pakai /sinyal4j.")
    if cmd in ("/laporan4j", "/laporan", "/susul"):
        return mulai_laporan4j()
    if cmd in ("/jalur", "/rekapjalur"):
        import qse_catat as CT
        return CT.teks()
    if cmd in ("/mingguan", "/pekan"):
        import qse_mingguan as MG
        return MG.teks()
    if cmd in ("/arah", "/tren"):
        import qse_arah as AR
        return AR.teks(args)
    if cmd in ("/strategi", "/strat", "/ema", "/rsi", "/mcginley", "/mcg", "/snr", "/msb", "/smc"):
        import qse_strat as ST
        return ST.teks()
    if cmd in ("/ob", "/orderblock"):
        import qse_ob as OB
        return OB.teks()
    if cmd in ("/lab", "/papan"):
        import qse_lab as LB
        return LB.status_teks()
    if cmd in ("/pelengkap", "/sektor"):
        import qse_sektor as SKT
        return SKT.teks()
    if cmd in ("/ichimoku", "/ichi"):
        import qse_ichimoku as IC
        return IC.teks()
    if cmd in ("/jagoan", "/koinjagoan"):
        import qse_jagoan as JG
        return JG.teks()
    if cmd in ("/altseason", "/alt"):
        import qse_altseason as AS
        return AS.teks() or "Data altcoin gagal diambil, coba lagi nanti."
    if cmd in ("/ujimomentum", "/ujimom"):
        return ("Momentum 15/30 menit dimatikan. Uji 40 koin paling likuid data 15 menit 2021-2026: aturan robot PF 0.58 (15 menit) "
                "dan 0.67 (30 menit). Variasi terbaik PF 1.06, tetap tidak lolos.")
        import qse_momentum as MO
        try:
            with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
                lama = json.load(f)
        except Exception:
            return "Belum ada hasil scan 4 jam. Coba lagi setelah laporan 4 jam keluar."
        sym = [r["symbol"] for r in lama if r.get("tf", "240") == "240" and r["rapor"] in ("A", "B")]
        if args:
            sym = [a.upper() if a.upper().endswith("USDT") else a.upper() + "USDT" for a in args]
        return MO.uji(sym) if sym else "Belum ada koin rapor A/B untuk diuji."
    if cmd in ("/kabar", "/info", "/viral", "/trending", "/hits", "/hot", "/berita", "/news"):
        # v150: berita dan kabar jadi satu. Kabar terbaru lalu yang viral 6 jam (atau jam yang diketik)
        import qse_news as NW
        try:
            jam = int(args[0]) if args else 6
        except ValueError:
            jam = 6
        bag = []
        for f in (lambda: NW.kabar(), lambda: NW.viral(max(1, min(72, jam)))):
            try:
                x = f()
                if x:
                    bag.append(x)
            except Exception as ex:
                bag.append(f"Sebagian berita gagal diambil: {TG.e(str(ex)[:120])}")
        return "\n\n".join(bag) or "Belum ada berita baru."
    if cmd in ("/beritauji", "/ujiberita"):
        import qse_news as NW
        return NW.tes()
    if cmd in ("/rencana", "/sniper"):
        import qse_rencana as RC
        return RC.teks(args[0] if args else "utama")
    if cmd in ("/gurita", "/octopus"):
        import qse_gurita as GR
        try:
            import qse_overmind as OM
            om = OM.ringkas() + "\n\n"
        except Exception:
            om = ""
        return om + GR.teks()
    if cmd in ("/lalat", "/otak"):
        import qse_lalat as LT
        return LT.perintah(args)
    if cmd == "/modal":
        import qse_modal as MD
        return MD.perintah(args)
    if cmd in ("/slok", "/slsudah"):
        return SY.slok(args)
    if cmd == "/evaluasi":
        return SY.evaluasi()
    if cmd == "/uji":
        import qse_uji as QU
        return QU.ringkas()
    if cmd == "/batal":
        if not args:
            return "Format: /batal AUSDT"
        rows = []
        for a in args:
            sym = _sym(a)
            n_sig, antri = _batal_sinyal(sym, dari_main)
            n_saya, jalan = SY.batal(sym)
            bag = []
            if n_sig:
                bag.append(f"{n_sig} saran robot dihapus dari daftar pantau" + (" (tercatat permanen setelah scan selesai)" if antri else ""))
            if n_saya:
                bag.append(f"{n_saya} order kamu yang belum terisi dibatalkan")
            if jalan:
                bag.append(f"{jalan} posisi kamu masih jalan, pakai /tutup {a} HARGA untuk keluar")
            rows.append(f"➡️ {sym}: " + ("; ".join(bag) if bag else "tidak ada order terbuka"))
        return "\n".join(rows)
    if cmd in ("/tidur", "/sl_terbaru", "/slterbaru"):
        teks, _ = SY.kartu_sl(tidur=cmd == "/tidur")
        return teks or ("😴 <b>QSE v150 | SIAP TIDUR</b>\nTidak ada posisi jalan. Tidak ada yang perlu diatur. Sinyal jam 23:00 dan "
                        "03:00 WIB masih bisa kamu ikuti pagi di laporan 07:05, selama harga masih dekat entry robot.")
    if cmd == "/status":
        try:
            with open(os.path.join(STATE_DIR, "state.json")) as f:
                s4 = json.load(f).get("scan4")
        except Exception:
            s4 = None
        akhir = time.strftime("%d/%m %H:%M", time.gmtime(s4 / 1000 + 7 * 3600)) if s4 else "-"
        return ("📊 <b>QSE v150 | STATUS</b>" + (f"  ·  👤 {SY.nama_pengguna(SY.uid_aktif())}" if SY.uid_aktif() else "")
                + "\n" + f"Scan 4 jam terakhir: candle tutup {akhir} WIB\n\n" + SY.status_saya()
                + ("" if SY._peng().get("pemilik") else "\n\nℹ️ Ketik /milikku supaya catatan trade lama jadi milik kamu. "
                   "Trade orang lain di grup tercatat terpisah."))
    if cmd in ("/bantuan", "/help", "/start"):
        try:
            import qse_overmind as OM
            om = OM.ringkas() + "\n\n"
        except Exception:
            om = ""
        return om + (BANTUAN_SEMUA if args and args[0] in ("SEMUA", "ALL", "LENGKAP") else BANTUAN)
    return ""


JUDUL = {"/status": "STATUS", "/sinyal4j": "SINYAL 4J", "/cek": "CEK KOIN", "/berita": "BERITA", "/kabar": "BERITA",
         "/viral": "BERITA", "/modal": "MODAL", "/lalat": "LALAT ABDUL", "/gurita": "OTAK GURITA", "/rencana": "RENCANA SNIPER", "/bantuan": "INFO"}


def _sisa_posisi():
    """Daftar posisi aktif sesudah tutup, supaya layar status langsung terbarui (bug ARC 9 Nov)."""
    try:
        import qse_saya as SY
        op = list(SY.lihat()["open"].values())
        if not op:
            return "\n\n📭 Posisi aktif kamu sekarang: kosong."
        return "\n\n📋 Posisi aktif kamu sekarang: " + ", ".join(f"{v['sym'].replace('USDT', '')} {v['arah']}" for v in op[:10])
    except Exception:
        return ""


def proses(cmds, dari_main=False):
    """Jalankan daftar (perintah, argumen), kirim balasan ke Telegram. Return jumlah dibalas."""
    n = 0
    for item in cmds:
        cmd, args = item[0], item[1]
        uid, nama = (item[2], item[3]) if len(item) >= 4 else (None, "")
        args = [x for x in (re.sub(r"[^A-Z0-9.,:/%]", "", a.upper()) for a in args) if x]
        try:
            if uid is not None:
                SY.pakai(uid, nama)       # catatan trade milik pengirim perintah
            if cmd in ("/milikku", "/punyaku"):
                isi = SY.milikku(uid, nama) if uid is not None else "Kirim dari grup supaya pengirimnya dikenali."
            else:
                isi = balas(cmd, args, dari_main)
        except Exception as ex:
            isi = f"Perintah gagal: {TG.e(str(ex)[:200])}"
        finally:
            SY.pakai(None)
        if isi:
            ikon = {"/entry": "📝", "/cek": "🧐", "/cekdetail": "🧐", "/tutup": "✋", "/tp": "💰", "/sl": "🛑", "/ubah": "✏️", "/modify": "✏️", "/modif": "✏️", "/edit": "✏️", "/hapus": "🗑️", "/serok": "➕", "/kalibrasi": "🧪", "/tespin": "📌", "/batal": "❌", "/alert": "🔔", "/alarm": "🔔", "/tunggu": "⏳", "/close": "⏳", "/evaluasi": "📚",
                    "/uji": "🧪", "/mingguan": "📅", "/pekan": "📅", "/modal": "💼", "/scan": "🔎", "/laporan4j": "📊", "/laporan": "📊", "/susul": "📊", "/berita": "📰", "/kabar": "📰", "/viral": "🔥", "/trending": "🔥", "/hits": "🔥", "/hot": "🔥", "/info": "📰", "/ujimomentum": "⚡", "/jalur": "📒", "/rekapjalur": "📒", "/altseason": "🌈", "/jagoan": "👑", "/koinjagoan": "👑", "/ichimoku": "📈", "/pelengkap": "🧩", "/lab": "🧪", "/papan": "🧪", "/menu": "🤖", "/sektor": "🧩", "/ob": "⭐", "/strategi": "📈", "/strat": "📈", "/ema": "📈", "/rsi": "📈", "/orderblock": "⭐", "/smc": "⭐", "/arah": "🧭", "/tren": "🧭", "/ichi": "📈", "/alt": "🌈", "/ujimom": "⚡", "/news": "📰", "/sinyal4j": "📡", "/sinyal4": "📡",
                    "/sinyal": "📡", "/sinyal1j": "📡", "/sinyal1": "📡",
                    "/bantuan": "❓", "/milikku": "👤", "/pindah": "🔀", "/mode": "🎚️", "/tpall": "💰", "/tpsemua": "💰", "/slall": "🛑", "/slsemua": "🛑", "/punyaku": "👤", "/help": "❓", "/start": "❓"}
            isi = isi if "QSE v150 |" in isi.split("\n")[0] else f"{ikon.get(cmd, '🤖')} <b>QSE v150 | {JUDUL.get(cmd, cmd.upper()[1:])}</b>\n\n{isi}"
            pribadi = uid is not None and cmd in PRIBADI
            if pribadi:          # v172 QC 70: balasan pribadi diberi nama pemilik di baris judul, tombolnya hanya untuk pemilik
                _b = isi.split("\n", 1)
                isi = _b[0] + f"  ·  👤 {TG.e(str(nama or uid))}" + ("\n" + _b[1] if len(_b) > 1 else "")
            try:
                import qse_menu as QM
                mk = QM.tombol_untuk(cmd, args, isi, uid, nama)
            except Exception as ex:
                print("[WARN] tombol", ex)
                mk = None
            ids = TG.send(isi.split("\n\n"), markup=mk)
            if pribadi:
                try:
                    QM.catat_pemilik(ids, uid, nama)
                except Exception as ex:
                    print("[WARN] pemilik", ex)
            n += 1
    return n
