"""QC 86 ALARM GAWAT: pesan yang dikirim, dihapus, lalu dikirim ulang tiap menit sampai dijawab OKE.

Kapan berbunyi (riset/upgrade/run_v191_gawat.py, hasil_v191_gawat.txt, siaran QC 85, Jul 2022 sampai Okt 2026):
  BTC bergerak 2% atau lebih dalam 60 menit MELAWAN posisi yang sedang untung, dan SL posisi itu belum di entry.
  Aksi yang terbukti: geser SL ke entry. Dari 56 aturan keluar yang diuji (4 pemicu lebar pasar dan BTC x ambang x 4 aksi x 2 ambang
  untung), hanya ini yang tidak menurunkan total R di latih, uji, 12 bulan, dan 6 bulan sekaligus (+1R, tidak mengurangi profit).
  TP penuh saat gawat menurunkan profit 4.3 tahun 4% sampai 46%: BTC 2% tutup penuh +2776R lawan dasar +3014R, koin serentak turun
  1% tutup penuh +1615R. Tutup separuh juga turun (+2896R). Jadi alarm menyuruh SL ke entry, bukan TP.
  BTC bergerak 2% dalam 1 jam terjadi 21 sampai 57 jam per tahun, jadi alarm ini jarang.
  POSISI RUGI (run_v191b_rugi.py): saat BTC bergerak 2% dalam 1 jam melawan posisi yang sudah rugi lebih dari 0.5R, TUTUP PENUH lolos di
  latih, uji, 12 bulan, 6 bulan (+6R, dasar +3014R -> +3020R). Rugi kecil (0 sampai -0.5R) lebih baik dibiarkan: tutup penuh di sana
  menurunkan profit (-29R), tutup separuh juga (-18R). Pemicu koin serentak untuk posisi rugi menurunkan profit di semua varian.

Cara kerja: tiap menit robot mencatat harga BTC. Kalau pemicu terpenuhi untuk posisi anggota mana pun, alarm aktif. Tiap 60 detik pesan
lama dihapus dan pesan baru dikirim (notifikasi bunyi lagi) sampai semua pemilik posisi menekan OKE, atau seseorang menekan
OKE SEMUA (mewakili anggota lain), atau 45 menit lewat. Ketik "oke" di grup juga diterima.
Saklar: QSE_GAWAT=0 mati, QSE_GAWAT_BTC (persen, bawaan 2), QSE_GAWAT_ULANG (detik, bawaan 60), QSE_GAWAT_MAKS (menit, bawaan 45)."""
import html
import json
import os
import time

STATE_DIR = os.environ.get("QSE_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"))
PATH = os.path.join(STATE_DIR, "gawat.json")
AMBANG = float(os.environ.get("QSE_GAWAT_BTC", "2"))
ULANG = float(os.environ.get("QSE_GAWAT_ULANG", "60"))
MAKS_MENIT = float(os.environ.get("QSE_GAWAT_MAKS", "45"))
RUGI_TUTUP = float(os.environ.get("QSE_GAWAT_RUGI", "-0.5"))          # R, posisi rugi lebih dari ini ditutup penuh
JEDA_ARAH = 4 * 3600          # alarm arah yang sama tidak diulang dalam 4 jam
_BTC = []          # (waktu, harga) 90 menit terakhir


def hidup():
    return os.environ.get("QSE_GAWAT", "1") != "0"


def _baca():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PATH + ".tmp", PATH)


def gerak_btc(px, now=None):
    """Catat harga BTC, return gerak persen dalam 60 menit terakhir (None kalau catatan belum 55 menit)."""
    now = now or time.time()
    if px and px > 0:
        _BTC.append((now, float(px)))
    while _BTC and now - _BTC[0][0] > 90 * 60:
        _BTC.pop(0)
    lama = [p for t, p in _BTC if now - t >= 55 * 60]
    if not lama or not _BTC:
        return None
    ref = [p for t, p in _BTC if now - t <= 65 * 60]
    return (_BTC[-1][1] / ref[0] - 1) * 100 if ref else None


def _posisi_terancam(arah_gerak, harga):
    """Posisi untung yang melawan gerak BTC dan SL-nya belum di entry. Return {uid: (nama, [baris])}."""
    import qse_saya as SY
    p = SY._peng()
    out = {}
    for uid in SY.daftar_pengguna():
        try:
            for it in SY._baca(SY._path_uid(uid))["open"].values():
                if it.get("status") not in ("TERISI", "TP1"):
                    continue
                if (it["arah"] == "LONG") == (arah_gerak > 0):
                    continue          # searah gerak BTC, aman
                px = harga.get(it["sym"])
                fl = SY.floating(it, px) if px else None
                if not fl:
                    continue
                L = it["arah"] == "LONG"
                t_ = it.get("tick") or 0.0001
                kd = it["sym"].replace("USDT", "")
                if fl["r"] <= RUGI_TUTUP:          # rugi lebih dari 0.5R: tutup penuh (uji lolos 4 periode)
                    baris = (f"{'🟢' if L else '🔴'} <b>{it['sym']} {it['arah']}</b> RUGI {fl['r']:+.2f}R, BTC melawan"
                             f"\n   ➡️ TUTUP PENUH sekarang di Market (/tutup {kd}). Uji: menunggu SL di sini lebih rugi")
                elif fl["r"] > 0 and (it["sl"] - it["entry"]) * (1 if L else -1) < 0:
                    baris = (f"{'🟢' if L else '🔴'} <b>{it['sym']} {it['arah']}</b> untung {fl['r']:+.2f}R, SL masih {SY.fp(it['sl'], t_)}"
                             f"\n   ➡️ Geser SL ke entry <b>{SY.fp(it['entry'], t_)}</b> sekarang (/sl {kd} {SY.fp(it['entry'], t_)})")
                else:
                    continue          # untung dengan SL sudah di entry, atau rugi kecil: biarkan aturan jalur bekerja
                nm = p["nama"].get(uid) or it.get("oleh") or ("Pemilik" if uid == str(p.get("pemilik") or "") else uid)
                out.setdefault(uid or "pemilik", (nm, []))[1].append(baris)
        except Exception as ex:
            print("[WARN] gawat posisi", uid, ex)
    return out


def teks(d, now=None):
    now = now or time.time()
    arah = "TURUN" if d["gerak"] < 0 else "NAIK"
    rows = [f"🚨🚨 <b>QSE v150 | GAWAT: BTC {arah} {d['gerak']:+.2f}% DALAM 1 JAM</b> 🚨🚨",
            f"Ke-{d.get('ke', 1)} · mulai {time.strftime('%H:%M', time.gmtime(d['mulai'] + 7 * 3600))} WIB · berhenti kalau semua jawab OKE",
            ""]
    for uid, (nm, bs) in d["siapa"].items():
        sudah = uid in d.get("oke", {})
        rows.append(f"👤 <b>{html.escape(nm)}</b>" + (f"  ✅ OKE ({html.escape(d['oke'][uid])})" if sudah else "  ⏳ belum OKE"))
        rows += bs
    rows += ["",
             "Uji 2022-2026 saat BTC bergerak 2% dalam 1 jam melawan posisi: yang untung cukup SL ke entry (TP penuh malah menurunkan "
             "profit, +2776R lawan +3014R). Yang rugi lebih dari 0.5R tutup penuh. Rugi kecil dibiarkan, SL dan aturan jalur yang menutup.",
             "Tekan OKE kalau SL sudah digeser. OKE SEMUA = kamu mewakili anggota lain."]
    return "\n".join(rows)


def _kirim(d, now=None):
    import qse_menu as QM
    mk = {"inline_keyboard": [[{"text": "✅ OKE (saya)", "callback_data": "g:oke"}, {"text": "✅ OKE SEMUA (wakili)", "callback_data": "g:semua"}]]}
    if d.get("mid"):
        QM._api("deleteMessage", message_id=d["mid"])
    js = QM._api("sendMessage", text=teks(d), parse_mode="HTML", reply_markup=mk) or {}
    d["mid"] = (js.get("result") or {}).get("message_id")
    d["kirim_t"] = now or time.time()
    d["ke"] = d.get("ke", 1) + 1


def cek(tickers=None, now=None):
    """Dipanggil tiap menit. Mencatat BTC dan menyalakan alarm kalau pemicu terpenuhi."""
    if not hidup():
        return None
    now = now or time.time()
    if tickers is None:
        import bybit_fetch as B
        tickers = B.get_tickers()
    btc = (tickers.get("BTCUSDT") or {}).get("last")
    g = gerak_btc(btc, now)
    d = _baca()
    if d.get("aktif") or g is None or abs(g) < AMBANG:
        return None
    arah = 1 if g > 0 else -1
    if now - float(d.get(f"akhir_{arah}", 0)) < JEDA_ARAH:
        return None
    harga = {s: v.get("last") for s, v in tickers.items() if v.get("last")}
    siapa = _posisi_terancam(arah, harga)
    if not siapa:
        return None
    d = {"aktif": True, "mulai": now, "gerak": round(g, 2), "siapa": siapa, "oke": {}, "ke": 1, f"akhir_{arah}": now,
         **{k: v for k, v in d.items() if k.startswith("akhir_") and k != f"akhir_{arah}"}}
    _kirim(d, now)
    _tulis(d)
    print(f"[GAWAT] BTC {g:+.2f}% 1 jam, {len(siapa)} pemilik posisi terancam", flush=True)
    return d


def ulang(now=None):
    """Dipanggil tiap 5 detik: hapus lalu kirim ulang pesan alarm tiap ULANG detik selama belum semua OKE."""
    d = _baca()
    if not d.get("aktif"):
        return
    now = now or time.time()
    if now - d["mulai"] > MAKS_MENIT * 60:
        selesai(d, f"⏹️ Alarm gawat berhenti sendiri setelah {MAKS_MENIT:.0f} menit.")
        return
    if now - float(d.get("kirim_t", 0)) >= ULANG:
        _kirim(d, now)
        _tulis(d)


def selesai(d, catatan):
    import qse_menu as QM
    if d.get("mid"):
        QM._api("deleteMessage", message_id=d["mid"])
    d["aktif"] = False
    d["mid"] = None
    _tulis(d)
    ok_ = ", ".join(f"{d['siapa'][u][0]} oleh {n}" for u, n in d.get("oke", {}).items() if u in d.get("siapa", {}))
    QM._api("sendMessage", text=f"✅ <b>Alarm gawat selesai.</b> {html.escape(catatan)}" + (f"\nOKE: {html.escape(ok_)}" if ok_ else ""),
            parse_mode="HTML")


def oke(uid, nama, semua=False):
    """Tombol OKE / OKE SEMUA atau ketik 'oke'. Return True kalau ada alarm aktif yang dijawab."""
    d = _baca()
    if not d.get("aktif"):
        return False
    import qse_saya as SY
    uid = str(uid or "")
    kunci = uid
    p = SY._peng()
    if uid and uid == str(p.get("pemilik") or "") and uid not in d["siapa"] and "" in d["siapa"]:
        kunci = ""
    if semua:
        for u in d["siapa"]:
            d["oke"].setdefault(u, nama or "anggota")
    elif kunci in d["siapa"]:
        d["oke"][kunci] = nama or "sendiri"
    else:
        d["oke"]["_" + uid] = nama          # bukan pemilik posisi: dicatat, alarm tetap jalan
    if all(u in d["oke"] for u in d["siapa"]):
        selesai(d, "Semua pemilik posisi sudah OKE.")
    else:
        _tulis(d)
        _kirim(d)
        _tulis(d)
    return True


def dari_update(cq, pesan, uid, nama):
    """Dipanggil listener sebelum menu. Return True kalau update ini milik alarm gawat (tidak diteruskan ke menu)."""
    if cq is not None:
        data = cq.get("data") or ""
        if not data.startswith("g:"):
            return False
        try:
            import qse_menu as QM
            QM._api("answerCallbackQuery", callback_query_id=cq.get("id"), chat_id=None,
                    text="Tercatat OKE" if data == "g:oke" else "Tercatat OKE untuk semua anggota")
        except Exception:
            pass
        if not oke(uid, nama, semua=data == "g:semua"):
            return True
        return True
    t = (pesan or "").strip().lower().strip("!. ")
    if t in ("oke", "ok", "oke semua", "ok semua", "oke all", "ok all"):
        return oke(uid, nama, semua="semua" in t or "all" in t)
    return False
