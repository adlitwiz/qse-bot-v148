"""QSE v170 MESIN TEMPUR NEWS: WHIP-FADE (QC 65, 10 Nov 2026, riset/upgrade/run_v170_news.py, hasil_v170_news.txt, hasil_v170_news2.txt).
Tidak memakai kalender berita. Detektor lonjakan ekstrem candle 15 menit: rentang >= 6 x ATR dan volume >= 3 x rata volume
(keduanya dari 96 candle = 24 jam sebelum lonjakan). Jalan terus, termasuk saat jeda berita menahan sinyal teknikal lain.
Aturan (sama dengan uji): candle lonjakan menyapu ke bawah lalu tutup kembali, sumbu bawah >= 60% rentang. Candle 15 menit berikutnya
tutup di atas tutup candle lonjakan tanpa menyentuh SL (konfirmasi). LONG di harga tutup candle konfirmasi, SL di ujung sumbu - 0.1 ATR,
TP PENUH 2R, paling lama 32 candle (8 jam). Maksimal 3 koin per kejadian pasar, dipilih dari lonjakan volume terbesar.
Uji 40 koin likuid, data 15 menit, biaya 0.11%:
  semua koin : latih 2023-2024 n 214 rata +0.233R PF 2.50, uji 2025-2026 n 130 WR 67% rata +0.452R PF 3.95.
  maks 3 koin per kejadian (yang dipasang): 2023 +0.192R, 2024 +0.027R, 2025 +0.117R, 2026 +0.272R, uji n 64.
Catatan jujur: untung menumpuk di beberapa hari sapuan besar (tanpa 5 hari terbaik tiap tahun hasilnya sekitar impas sampai minus), sampel
uji kecil, selip harga saat berita belum dihitung. Karena itu KELAS RINGAN dan dicatat terpisah.
BREAKOUT CONTINUATION (ikut arah lonjakan) TIDAK dipasang: dari 864 kombinasi hanya 20 lolos latih, calon terbaik (SHORT) rata per kejadian
pasar negatif di 2023 dan 2026, untungnya hanya dari 5 hari jatuh serentak, bulan positif 8 dari 24. SHORT sapuan atas juga tidak lolos.
QC 68: detektor ini diberi nama indikator DLI (indikator waktu, sapuan likuiditas). Uji gabungan dengan QIE (run_v170_qie.py): kejadian DLI
dengan QIE mendukung 2025 -0.072R, 2026 +0.145R. QIE tidak mendukung 2025 +0.190R, 2026 +0.637R. QIE tidak memperbaiki DLI, jadi DLI
berjalan tanpa syarat QIE. Matikan: QSE_WHIP=0."""
import json
import os
import time

import numpy as np

from config import STATE_DIR

F = os.path.join(STATE_DIR, "whip.json")
K_MIN, V_MIN, W_MIN, TP_R, MAKS_CANDLE, MAKS_KOIN, N_KOIN = 6.0, 3.0, 0.6, 2.0, 32, 3, 40
M15 = 900
BIAYA = 0.0011


def _baca():
    try:
        with open(F) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": [], "kirim": {}}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(F + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(F + ".tmp", F)


def deteksi(o, h, l, c, v):
    """Candle terakhir = konfirmasi, candle sebelumnya = lonjakan. Semua candle sudah tutup. Return dict setup atau None. Sama dengan uji."""
    n = len(c)
    if n < 99:
        return None
    i, j = n - 2, n - 1
    pc = c[i - 96:i]          # tutup candle sebelum tiap candle jendela
    tr = np.maximum(h[i - 95:i] - l[i - 95:i], np.maximum(np.abs(h[i - 95:i] - pc[:-1]), np.abs(l[i - 95:i] - pc[:-1])))
    tr0 = max(h[i - 96] - l[i - 96], abs(h[i - 96] - c[i - 97]), abs(l[i - 96] - c[i - 97]))
    a = float((tr.sum() + tr0) / 96)
    va = float(v[i - 96:i].mean())
    rng = h[i] - l[i]
    if a <= 0 or va <= 0 or rng <= 0:
        return None
    K, V = rng / a, v[i] / va
    w = (min(o[i], c[i]) - l[i]) / rng
    if K < K_MIN or V < V_MIN or w < W_MIN:
        return None
    sl = l[i] - 0.1 * a
    if c[j] <= c[i] or l[j] <= sl:
        return None
    e = float(c[j]); risk = e - sl
    if risk < 0.3 * a or risk > 0.08 * e:
        return None
    return dict(arah="LONG", entry=e, sl=float(sl), tp=float(e + TP_R * risk), atr=a, K=round(float(K), 1), V=round(float(V), 1), sumbu=round(float(w), 2))


def rapor():
    r = [x["R"] for x in _baca()["closed"] if x.get("R") is not None]
    return dict(n=len(r), wr=(sum(1 for x in r if x > 0) / len(r) * 100) if r else 0.0, tot=sum(r))


def kartu(s, x):
    import qse_saya as SY
    t = SY.tick_of(None, x["entry"])
    try:
        import qse_modal as MD
        lot = MD.baris_lot(x["entry"], x["sl"], kelas="RINGAN")
    except Exception:
        lot = ""
    st = rapor()
    return (f"⚡ <b>DLI · WHIP-FADE NEWS: {s} LONG MARKET</b>\n"
            f"🌩 Lonjakan 15 menit: rentang {x['K']}x ATR, volume {x['V']}x rata-rata, sumbu bawah {x['sumbu'] * 100:.0f}%. Sapuan ke bawah ditolak, "
            f"candle berikutnya sudah tutup naik (konfirmasi)\n"
            f"🏅 Uji 2025-2026 (maks 3 koin per kejadian): +0.18R per trade dari 64 trade, 2024 hanya impas. Untung menumpuk di hari sapuan besar"
            + (f"  ·  live {st['n']} trade WR {st['wr']:.0f}% {st['tot']:+.1f}R" if st["n"] else "") + "\n"
            + SY.blok_salin(x["entry"], x["sl"], x["tp"], x["tp"], "MARKET", t, sym=s, arah="LONG")
            + f"\n📲 TP PENUH di +{TP_R:g}R, tutup semua di sana. SL di bawah ujung sumbu. Paling lama {MAKS_CANDLE * 15 // 60} jam. "
            f"Spread bisa lebar saat berita: kalau harga sudah lari lebih dari 0.3R dari entry, lewati. 🟨 KELAS RINGAN."
            + ("\n" + lot if lot else ""))


def _lilin(sym, bars):
    import bybit_fetch as B
    df = B._raw(sym, "15", bars)
    now = int(time.time() * 1000)
    return df[df.index + M15 * 1000 <= now]


def _kelola(d):
    out = []
    for k, it in list(d["open"].items()):
        try:
            df = _lilin(it["sym"], 60)
        except Exception as ex:
            print("[WARN] whip kelola", it["sym"], ex)
            continue
        df = df[df.index > it["t_ms"]]
        R, why = None, ""
        risk = it["entry"] - it["sl"]
        for n_, (ts, row) in enumerate(df.iterrows(), 1):
            if row["low"] <= it["sl"]:
                R, why = -1.0, "SL kena"
                break
            if row["high"] >= it["tp"]:
                R, why = TP_R, f"TP {TP_R:g}R kena"
                break
            if ts >= it["t_ms"] + MAKS_CANDLE * M15 * 1000:
                R, why = (row["close"] - it["entry"]) / risk, f"{MAKS_CANDLE * 15 // 60} jam, tutup market"
                break
        if R is None:
            continue
        R -= BIAYA * it["entry"] / risk
        d["open"].pop(k)
        d["closed"] = (d["closed"] + [dict(it, R=round(R, 3), why=why, selesai=time.time())])[-300:]
        out.append(f"{'✅' if R > 0 else '🛑'} ⚡ <b>WHIP-FADE {it['sym']} LONG</b> selesai: {why}, {R:+.2f}R.")
    return out


def _koin():
    import bybit_fetch as B
    tk = B.get_tickers()
    try:
        from config import bukan_saham
    except Exception:
        bukan_saham = lambda s: True
    ok = [s for s in tk if s.endswith("USDT") and bukan_saham(s) and tk[s]["spread"] < 0.2]
    return sorted(ok, key=lambda s: -tk[s]["turnover"])[:N_KOIN]


def jalankan(simbol=None):
    """Dipanggil tiap menit. Kerja sekali sesudah candle 15 menit tutup (detik 20-240). Return list pesan."""
    if os.environ.get("QSE_WHIP", "1") == "0":
        return []
    now = time.time()
    c15 = int(now // M15 * M15)
    d = _baca()
    out = []
    try:
        out += _kelola(d)
    except Exception as ex:
        print("[WARN] whip kelola", ex)
    if d.get("c15") == c15 or not (20 <= now - c15 <= 240):
        _tulis(d)
        return out
    d["c15"] = c15
    try:
        simbol = simbol if simbol is not None else _koin()
    except Exception as ex:
        print("[WARN] whip koin", ex)
        simbol = []
    calon = []

    def _cek(s):
        try:
            df = _lilin(s, 110)
            if len(df) < 99 or int(df.index[-1]) != (c15 - M15) * 1000:
                return None
            x = deteksi(*(df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume")))
            return (s, x, int(df.index[-1])) if x else None
        except Exception as ex:
            print("[WARN] whip", s, ex)
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex_:
        calon = [r for r in ex_.map(_cek, [s for s in simbol if not any(it["sym"] == s for it in d["open"].values())]) if r]
    calon.sort(key=lambda r: -r[1]["V"])
    for s, x, t_ms in calon[:MAKS_KOIN]:
        d["open"][f"{s}|{t_ms}"] = dict(sym=s, t_ms=t_ms, t=now, **x)
        out.append(kartu(s, x))
    if len(calon) > MAKS_KOIN:
        out.append("⚡ Whip-Fade: " + ", ".join(r[0] for r in calon[MAKS_KOIN:]) + f" juga memenuhi syarat, dilewati (maks {MAKS_KOIN} koin per kejadian).")
    _tulis(d)
    return out


def teks():
    d = _baca(); st = rapor()
    rows = ["⚡ <b>DLI · WHIP-FADE NEWS</b> (lonjakan 15 menit 6x ATR + volume 3x, sapuan bawah ditolak, LONG, TP 2R, kelas ringan)",
            f"Live: {st['n']} trade selesai, WR {st['wr']:.0f}%, total {st['tot']:+.2f}R. Posisi jalan {len(d['open'])}."]
    for it in d["open"].values():
        rows.append(f"• {it['sym']} LONG entry {it['entry']:.6g} SL {it['sl']:.6g} TP {it['tp']:.6g}")
    return "\n".join(rows)
