"""QSE v150 - Rencana Sniper S/R: angka order LIMIT harian di support (LONG) atau resistance (SHORT) 4J.
Level sama dengan qse_btcmap.snr (pivot 3 candle, 150 candle 4J terakhir). Entry antre di level, SL di luar level,
TP1 tutup 50% lalu SL ke entry, TP2 sisa. Order berlaku 24 jam. Parameter dari riset/upgrade/run_v158_sr.py
(dipilih di 2023-2024, dinilai di 2025-2026, hasil di hasil_v158_sr.txt). Lot kecil karena ini rencana pasang, bukan sinyal jalur."""
import json
import os
import time
import numpy as np
from config import STATE_DIR

PATH = os.path.join(STATE_DIR, "rencana.json")
# off = jarak entry dari level (ATR 4J), sk = SL di luar level, t1/t2 = TP dari entry, mx = batas tahan (candle 4J), dist = jarak maks level dari harga
PARAM = dict(off=0.0, sk=1.0, t1=0.5, t2=0.8, mx=6, dist=2.0, fil="semua", lot=0.25)
UJI = ("Uji 183 koin, latih 2023-2024, uji 2025-2026: koin umum -0.08R per trade (WR 62%). Spesialis 🥇 PSG/ACM/BAR +0.12R, "
       "WR 75%. Perak 🥈 CITY/NEXO/PORTO/LAZIO uji +0.045R, WR 71% (dipilih memakai data uji). Rincian hasil_v158_spesialis.txt.")
CACHE_DETIK = 1800
KOIN_MAKS = 183            # jumlah koin yang dipindai (sama dengan riset)
KOIN_MIN_TURNOVER = 3e6
SPESIALIS_MIN = 0.3        # nilai bawaan lalat minimal supaya koin+arah masuk daftar spesialis


def _lapar_nyala():
    try:
        import qse_lalat as LT
        return bool(LT.state().get("mode_lapar", False))
    except Exception:
        return False


def daftar_spesialis():
    """Daftar spesialis bertingkat dari lalat_bawaan.json (tier 1 PSG/ACM/BAR, tier 2 cadangan). sym -> dict."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lalat_bawaan.json")) as f:
            return json.load(f).get("spesialis", {})
    except Exception:
        return {}


def _wr(sym, k):
    d = daftar_spesialis().get(sym) or {}
    return f"{d.get(k, 0) * 100:.0f}%"


def _ex(sym):
    d = daftar_spesialis().get(sym) or {}
    return f"{d.get('ex_uji', 0):+.3f}R"


def spesialis(minv=SPESIALIS_MIN):
    """Koin+arah dengan nilai latih 2023-2024 >= minv (lalat_bawaan.json). Contoh PSGUSDT LONG. Return dict sym -> arah."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lalat_bawaan.json")) as f:
            tok = json.load(f).get("token", {})
    except Exception:
        return {}
    out = {}
    for k, v in tok.items():
        if k.startswith("spesialis:") and v >= minv:
            _, s, a = k.split(":")
            out[s] = a
    return out


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


def _btc_naik():
    try:
        import qse_strat as ST
        return ST.btc_naik()
    except Exception:
        return None


def fitur(d4, a):
    """Fitur candle 4J terakhir untuk mata lalat (Optic Lobe): RSI 14, volume relatif, kemiringan EMA 50, badan candle, ATR persen."""
    c = d4["close"].values.astype(float); o = d4["open"].values.astype(float); v = d4["volume"].values.astype(float) if "volume" in d4 else None
    dc = np.diff(c[-40:])
    up = dc.clip(min=0); dn = (-dc).clip(min=0)
    au, ad = up[:14].mean(), dn[:14].mean()
    for x, y in zip(up[14:], dn[14:]):
        au = (au * 13 + x) / 14; ad = (ad * 13 + y) / 14
    rsi = 100 - 100 / (1 + au / ad) if ad > 0 else 100.0
    vr = float(v[-1] / max(v[-21:-1].mean(), 1e-12)) if v is not None and len(v) > 21 else 1.0
    e50 = __import__("qse_btcmap")._ema(c, 50)
    return dict(rsi=float(rsi), vr=vr, slope=float(np.sign(e50[-1] - e50[-4])), body=float((c[-1] - o[-1]) / a) if a else 0.0,
                atrp=float(a / c[-1] * 100))


def hitung(sym, px=None, p=None, semua_jarak=False):
    """Rencana LONG dan SHORT satu koin dari candle 4J yang sudah tutup. Return list dict.
    semua_jarak=True (koin spesialis): level jauh tetap dihitung, ditandai jauh=True (lalat tidak memakainya)."""
    import bybit_fetch as B
    import qse_btcmap as BM
    p = p or PARAM
    ms = int(time.time() * 1000)
    d4 = B._raw(sym, "240", 220)
    d4 = d4[d4.index + 14400000 <= ms]
    if len(d4) < 160:
        return []
    h, l, c = (d4[x].values.astype(float) for x in ("high", "low", "close"))
    a = float(BM._atr(h, l, c)[-1])
    sup, res = BM.snr(h, l, c)
    px = px or float(c[-1])
    e200 = float(BM._ema(c, 200)[-1]) if hasattr(BM, "_ema") else None
    fit = fitur(d4, a)
    out = []
    for L, lv in ((True, sup), (False, res)):
        if not lv or a <= 0:
            continue
        dist = abs(px - lv) / a
        if dist > p["dist"] and not semua_jarak:
            continue
        e = lv + p["off"] * a if L else lv - p["off"] * a
        if (L and e >= px) or ((not L) and e <= px):
            continue
        sl = lv - p["sk"] * a if L else lv + p["sk"] * a
        d_ = 1 if L else -1
        lv, e, sl, a, dist, px = (float(x) for x in (lv, e, sl, a, dist, px))
        out.append(dict(sym=sym, arah="LONG" if L else "SHORT", level=lv, entry=e, sl=sl, tp1=e + d_ * p["t1"] * a,
                        tp2=e + d_ * p["t2"] * a, atr=a, dist=dist, distp=abs(px - lv) / px * 100, px=px, tren=bool((e200 is None) or ((px > e200) == L)),
                        jauh=bool(dist > p["dist"]), **fit))
    return out


def daftar(tk=None, maks=5, segar=False, semua=False):
    """Rencana terbaik hari ini, urut dari level terdekat. Cache 30 menit supaya angka sama dan hemat API."""
    import bybit_fetch as B
    st = _baca()
    if not segar and st.get("t", 0) > time.time() - CACHE_DETIK and st.get("rows") is not None:
        return (st.get("semua") or st["rows"])[:maks] if semua else st["rows"][:maks]
    tk = tk or B.get_tickers()
    sp = spesialis(0.0001)          # semua koin+arah yang disukai bekal lalat
    dft = daftar_spesialis()
    sp.update({s: d["arah"] for s, d in dft.items()})
    utama = {s for s, d in dft.items() if d["tier"] == 1}
    cadangan = {s for s, d in dft.items() if d["tier"] == 2}
    calon = [s for s in sp if s in tk and tk[s]["spread"] < 0.3]
    if _lapar_nyala():          # koin umum hanya dipindai untuk lalat mode lapar (Sniper koin umum dihapus dari tampilan)
        calon += sorted((s for s in tk if s.endswith("USDT") and s not in sp and tk[s]["turnover"] >= KOIN_MIN_TURNOVER and tk[s]["spread"] < 0.2),
                        key=lambda s: -tk[s]["turnover"])[:KOIN_MAKS]
    bn = _btc_naik()
    rows = []
    try:
        from config import bukan_saham
        calon = [s for s in calon if bukan_saham(s)]          # saham/indeks tidak ikut
    except Exception:
        pass
    from concurrent.futures import ThreadPoolExecutor

    def _h(s):
        try:
            return s, hitung(s, tk[s]["last"], semua_jarak=s in dft)
        except Exception as ex:
            print("[WARN] rencana", s, ex)
            return s, []
    with ThreadPoolExecutor(8) as ex_:
        hasil = list(ex_.map(_h, calon))
    for s, hs in hasil:
        try:
            for r in hs:
                if s in sp and r["arah"] != sp[s]:
                    continue
                r["spesialis"] = s in utama
                r["cadangan"] = s in cadangan
                r["calon"] = s in sp and s not in dft
                if PARAM["fil"] in ("btc", "btc+tren") and bn is not None and bn != (r["arah"] == "LONG"):
                    continue
                if PARAM["fil"] in ("tren", "btc+tren") and not r["tren"]:
                    continue
                r["chg24"] = tk[s]["chg24"]
                rows.append(r)
        except Exception as ex:
            print("[WARN] rencana", s, ex)
    rows.sort(key=lambda r: (not r.get("spesialis"), not r.get("cadangan"), r.get("jauh", False), not r.get("calon"), r["dist"]))
    satu, sudah = [], set()
    for r in rows:
        if r["sym"] in sudah:
            continue
        sudah.add(r["sym"]); satu.append(r)
    _tulis(dict(t=time.time(), rows=satu, semua=rows))
    return rows[:maks] if semua else satu[:maks]


def kartu(r, ringkas=False):
    import qse_saya as SY
    t = SY.tick_of(None, r["entry"])
    blok = SY.blok_salin(r["entry"], r["sl"], r["tp1"], r["tp2"], "LIMIT", t, sym=r["sym"], arah=r["arah"])
    jenis = "support" if r["arah"] == "LONG" else "resistance"
    kepala = (f"{'🟢' if r['arah'] == 'LONG' else '🔴'} <b>{r['sym']} {r['arah']} LIMIT</b> di {jenis} {SY.fp(r['level'], t)}  ·  "
              f"harga {SY.fp(r['px'], t)} ({r['dist']:.1f} ATR dari level)"
              + ("\n🏅 Koin spesialis: uji 2025-2026 +0.12R per trade, WR 75%"
                 + (f". Level masih {r['dist']:.1f} ATR, order jarang terisi hari ini" if r.get("jauh") else "") if r.get("spesialis") else
                 f"\n🥈 Koin perak (latih WR {_wr(r['sym'], 'wr_latih')}): uji 2025-2026 WR {_wr(r['sym'], 'wr_uji')}, "
                 f"{_ex(r['sym'])} per trade" if r.get("cadangan") else
                 "\n🥈 Calon spesialis: uji 2025-2026 sekitar impas, dipantau lalat" if r.get("calon") else
                 "\n⚠️ Koin umum: uji 2025-2026 -0.08R per trade. Angka cadangan, lot paling kecil"))
    if ringkas:
        return kepala + "\n" + blok
    try:
        import qse_modal as MD
        lot = MD.baris_lot(r["entry"], r["sl"], kelas="UTAMA" if (r.get("spesialis") or r.get("cadangan")) else "RINGAN")
    except Exception:
        lot = ""
    return (kepala + "\n" + blok + f"\n📲 Pasang <b>Limit</b> di entry, isi SL. TP1 tutup 50% lalu SL kunci +0.2R. Order berlaku 24 jam, "
            f"posisi terisi tutup paling lambat {PARAM['mx'] * 4} jam." + ("\n" + lot if lot else ""))


def bagi(rows):
    """Pisah rencana: medali (spesialis tier 1 dan cadangan tier 2, tampil langsung) dan umum (calon + koin umum, di balik tombol)."""
    med = [r for r in rows if r.get("spesialis") or r.get("cadangan")]
    return med, [r for r in rows if not (r.get("spesialis") or r.get("cadangan"))]


def blok_spesialis(maks=6):
    """Kartu medali paling atas Sinyal 4J: semua tier 1, lalu tier 2 yang levelnya dekat. Return (teks, jumlah yang disembunyikan)."""
    med, um = bagi(daftar(maks=60))
    t1 = [r for r in med if r.get("spesialis")]
    t2 = [r for r in med if r.get("cadangan") and not r.get("jauh")]
    tampil = (t1 + t2)[:maks]
    sembunyi = len(um) + len(med) - len(tampil)
    dft = daftar_spesialis()
    n1 = ", ".join(s.replace("USDT", "") for s, d in dft.items() if d["tier"] == 1)
    n2 = ", ".join(s.replace("USDT", "") for s, d in dft.items() if d["tier"] == 2)
    kep = (f"🏅 <b>SNIPER KOIN SPESIALIS</b>\n🥇 {n1}: uji 2025-2026 WR 75%, +0.12R per trade\n"
           f"🥈 Perak {n2}: uji 2025-2026 WR 71%, +0.045R per trade (dipilih memakai data uji)\n"
           f"Order Limit antre di level 4J, 🟦 KELAS UTAMA, berlaku 24 jam.")
    if not tampil:
        return kep + "\nData koin spesialis belum terbaca, dicoba lagi 30 menit.", sembunyi
    return kep + "\n\n" + "\n\n".join(kartu(r) for r in tampil), sembunyi


def teks(mode="utama", maks=6):
    """Sniper S/R koin medali. Sniper koin umum dihapus 5 Nov 2026 (uji 2025-2026 -0.08R per trade, QC 53)."""
    isi, _ = blok_spesialis()
    kep = "🎯 <b>QSE v150 | RENCANA SNIPER S/R</b>\nTekan 📋 Salin Setup lalu pasang Limit di Bybit."
    if UJI:
        kep += "\n🧪 " + UJI
    return kep + "\n\n" + isi


def baris_pantauan(tk=None, maks=3):
    """Untuk laporan sesi: pengganti 'dekat support/resistance, tunggu sinyal'. Angka siap pasang."""
    try:
        rows, _ = bagi(daftar(tk, maks=60))
        rows = rows[:maks]
    except Exception as ex:
        print("[WARN] rencana pantauan", ex)
        return []
    return ["• 🎯 Sniper " + kartu(r, ringkas=True) for r in rows]


def antrean_teks(n=2, tk=None):
    """QC 54: 2 rencana Limit koin medali yang levelnya paling dekat dengan harga (dipakai saat 8 jam tanpa sinyal).
    Aturan sama dengan Sniper medali yang diuji (S/R 4J, SL 1 ATR, TP1 0.5 ATR 50% lalu SL kunci +0.2R, TP2 0.8 ATR, 24 jam):
    medali + NEXO uji 2025-2026 WR 73%, +0.085R per posisi."""
    med, _ = bagi(daftar(tk=tk, maks=60, semua=True))
    med = sorted(med, key=lambda r: r["dist"])
    pilih, sudah = [], set()
    for r in med:
        if r["sym"] in sudah:
            continue
        sudah.add(r["sym"]); pilih.append(r)
        if len(pilih) >= n:
            break
    if not pilih:
        return ""
    rows = ["📌 <b>ANTREAN LIMIT ABDUL</b> (8 jam tanpa sinyal baru, robot tidak memaksa entry, ini antrean di level terdekat)",
            "Koin medali, 🟦 KELAS UTAMA. Uji 2025-2026 aturan ini WR 73%, +0.085R per posisi."]
    for r in pilih:
        jarak = abs(r["px"] - r["entry"]) / r["px"] * 100
        rows.append(f"\n⏳ Jarak harga ke entry {jarak:.2f}%\n" + kartu(r))
    return "\n".join(rows)
