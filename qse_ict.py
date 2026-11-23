"""QSE v150 QC 129 - JALUR ICT TERPISAH (liquidity sweep + MSS/CISD + FVG), candle 4J.
Riset riset/upgrade/run_v245_banyak.py, run_v247_ict.py (hasil_v247_ict.txt), 138 koin, biaya 0.15%, aturan keluar QC 127:
  LONG : dalam 6 candle terakhir ada candle yang menembus low 20 candle sebelumnya lalu TUTUP kembali di atasnya (sweep SSL),
         lalu candle terakhir TUTUP menembus high 5 candle sebelum sweep (MSS/CISD, pertama kali), dan di kaki naik itu ada FVG
         (low candle > high 2 candle sebelumnya). SHORT kebalikannya.
  Syarat BTC 1J searah (harga BTC 1J di sisi EMA 50 yang sama dengan arah). SL di ujung sweep +- 0.1 ATR (SL struktur),
  jarak SL 0.3 sampai 3 ATR. Entry tutup candle MSS. Keluar: TP 20% (LONG +1R lalu SL entry, SHORT +0.5R lalu SL -0.25R,
  entry di +1R), sisa trailing 3 ATR, batas 60 candle. Satu sinyal per koin tiap 6 candle.
Hasil sendiri (pilih latih, bukti 3 periode): latih Jul22-Des24 2191 trade PF 1.21 (+118R), uji Jan25-Okt26 1999 trade PF 1.20
(+103R), 12 bulan 967 trade PF 1.29 (+69R), 6 bulan 508 trade PF 1.67 (+72R).
JALUR TERPISAH: digabung ke 12 slot siaran saldo turun (merebut slot sinyal yang lebih kuat), jadi kartu ini memakai modal terpisah
(lot setengah dari siaran) dan tidak ikut Gurita, skor, combo, atau batas slot jalur lain. Saklar QSE_ICT=0 mematikan."""
import fcntl
import json
import os
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import bybit_fetch as B
import telegram_notify as TG
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "ict.json")
H4 = 4 * 3600 * 1000
TRAIL_ATR, MAKS_BAR, JEDA_BAR, TOP_KOIN, MAKS_BARU = 3.0, 60, 6, 150, 6
BIAYA = 0.0015
BT = ("uji 138 koin, biaya ikut: latih 2022-2024 PF 1.21, uji 2025-Okt 2026 PF 1.20, 12 bulan PF 1.29, 6 bulan PF 1.67 "
      "(sekitar 2 sinyal per hari)")


def hidup():
    return os.environ.get("QSE_ICT", "1") != "0"


def _ubah(fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(FILE) as f:
                d = json.load(f)
        except Exception:
            d = {"open": {}, "closed": [], "akhir": {}}
        hasil = fn(d)
        d["closed"] = d["closed"][-500:]
        with open(FILE + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(FILE + ".tmp", FILE)
        return hasil


def lihat():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": [], "akhir": {}}


def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    a = np.full(len(c), np.nan); x = tr[0]
    for i, v in enumerate(tr):
        x = v if i == 0 else x + (v - x) / n          # sama ewm(alpha=1/14) di riset
        a[i + 1] = x
    return a


def deteksi(o, h, l, c):
    """Pola di candle tutup terakhir. Return (arah, sl, atr, jarak_sl_ok) atau None. Sama persis dengan riset v247
    (pola yang jarak SL-nya di luar 0.3-3 ATR tetap memulai jeda 6 candle, seperti riset)."""
    i = len(c) - 1
    if i < 40:
        return None
    a = _atr(h, l, c)
    if not a[i] > 0:
        return None
    for d in (1, -1):
        for j in range(i - 6, i):
            if j < 21:
                continue
            ref = l[j - 20:j].min() if d > 0 else h[j - 20:j].max()
            if not ((l[j] < ref and c[j] > ref) if d > 0 else (h[j] > ref and c[j] < ref)):
                continue
            sw = h[j - 5:j].max() if d > 0 else l[j - 5:j].min()
            if not ((c[i] > sw and c[i - 1] <= sw) if d > 0 else (c[i] < sw and c[i - 1] >= sw)):
                continue
            if not any((l[q] > h[q - 2]) if d > 0 else (h[q] < l[q - 2]) for q in range(j + 2, i + 1)):
                continue
            sl = (l[j] - 0.1 * a[i]) if d > 0 else (h[j] + 0.1 * a[i])
            risk = (c[i] - sl) * d
            return ("LONG" if d > 0 else "SHORT"), float(sl), float(a[i]), bool(0.3 * a[i] <= risk <= 3 * a[i])
    return None


def btc_searah(arah, df1=None):
    """BTC 1J: harga di sisi EMA 50 yang sama dengan arah (riset SUP1)."""
    try:
        df1 = df1 if df1 is not None else B._raw("BTCUSDT", "60", 200)
        c = df1["close"].values.astype(float)
        now = int(time.time() * 1000)
        if len(df1) and int(df1.index[-1]) + 3600000 > now:
            c = c[:-1]          # candle 1J berjalan dibuang
        e = c[0]; k = 2 / 51
        for v in c[1:]:
            e = e + k * (v - e)
        return (c[-1] > e) == (arah == "LONG")
    except Exception as ex:
        print("[WARN] ict btc", ex)
        return None


def _k4(sym, bars=200):
    try:
        import qse_strat as ST
        return ST.k4_kuat(sym, bars, tag="ict", tunggu=False)
    except Exception as ex:
        print(f"[WARN] ict {sym}: {ex}")
        return None


def _kelola(it, df):
    """Trailing 3 ATR dan batas 60 candle di buku jalur (jejak aturan orang ikut di it['v9'])."""
    import qse_strat as ST
    L = it["arah"] == "LONG"; e, risk = it["entry"], it["risk"]
    a = _atr(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float))
    for k, ts in enumerate(df.index):
        if ts <= it["last"]:
            continue
        hi, lo, cl = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        ST.v150_langkah(it, hi, lo, cl)
        if (lo <= it["sl"]) if L else (hi >= it["sl"]):
            ST.v150_tutup(it, it["sl"])
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk
        it["bar"] += 1
        it["best"] = max(it["best"], hi) if L else min(it["best"], lo)
        if not np.isnan(a[k]):
            ns = it["best"] - TRAIL_ATR * a[k] if L else it["best"] + TRAIL_ATR * a[k]
            it["sl"] = max(it["sl"], ns) if L else min(it["sl"], ns)
        it["last"] = int(ts); it["close"] = cl
        if it["bar"] >= MAKS_BAR:
            ST.v150_tutup(it, cl)
            return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk
    return "BUKA", None


def kartu(it, no):
    import qse_saya as SY
    import qse_strat as ST
    L = it["arah"] == "LONG"; t = it["tick"]; px, sl, risk = it["entry"], it["sl"], it["risk"]
    pc = risk / px * 100
    return "\n".join([
        SY.GARIS,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  ICT 4J (sweep + MSS + FVG)",
        "🟪 <b>JALUR TERPISAH</b>: pakai modal terpisah atau lot setengah dari sinyal biasa. Tidak dihitung di Gurita dan 12 slot",
        SY.GARIS,
        SY.blok_salin(px, sl, order="MARKET", tick=t, catatan_tp="tanpa, pakai SL berjalan", sym=it["sym"], arah=it["arah"], sebagian=True),
        *ST.rencana_tp(px, sl, it["arah"], t, tp=None, jarak=TRAIL_ATR * it["atr"]),
        "💡 <b>Kenapa</b>",
        f"• Likuiditas {'di bawah low' if L else 'di atas high'} 20 candle sudah disapu (stop orang lain diambil), lalu harga tutup kembali",
        f"• Struktur pecah {'ke atas' if L else 'ke bawah'} (MSS/CISD) dengan FVG di kaki ekspansi: dorongan nyata",
        f"• BTC 1J searah. SL di ujung sapuan ({pc:.1f}% dari entry): kalau ditembus lagi, alasan entry batal",
        f"• Bukti: {BT}",
        "🛠 <b>Cara</b>",
        f"1. Masuk MARKET sekarang, SL {TG.fp(sl, t)}. TP sebagian 20% di baris 💰",
        f"2. Sisa posisi tanpa TP. Tiap candle 4J geser SL ke puncak {'-' if L else '+'} 3 ATR (tidak pernah mundur). Batas 10 hari",
        f"3. Catat dengan /entry {it['sym'].replace('USDT', '')} supaya robot memantau TP 20%, SL napas, dan PETA SL",
    ])


def jalankan(baru_ok=True, now=None):
    """Dipanggil listener tiap candle 4J tutup. Return list kartu sinyal baru."""
    if not hidup():
        return []
    now = now or time.time()
    d = lihat()
    hasil = {}
    for key, it in d["open"].items():
        df = _k4(it["sym"], 200)
        if df is None or not len(df):
            continue
        it = dict(it)
        st, R = _kelola(it, df)
        hasil[key] = (it, st, R)

    def simpan(dd):
        for key, (it, st, R) in hasil.items():
            if key not in dd["open"]:
                continue
            if st in ("SL", "WAKTU"):
                dd["open"].pop(key); dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=now))
            else:
                dd["open"][key] = it
    _ubah(simpan)
    if not baru_ok:
        return []
    try:
        tk = B.get_tickers()
        tick = B.get_symbols()
    except Exception as ex:
        print("[WARN] ict tickers", ex)
        return []
    d = lihat()
    buka = {it["sym"] for it in d["open"].values()}
    koin = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s != "BTCUSDT" and (s in tick or not tick)][:TOP_KOIN]
    koin = [s for s in koin if s not in buka]

    def cek(sym):
        df = _k4(sym, 200)
        if df is None or len(df) < 60:
            return sym, None, None
        x = deteksi(*(df[k].values.astype(float) for k in ("open", "high", "low", "close")))
        return sym, x, df
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, koin))
    btc = {}
    out = []
    baru = []
    jeda = {}
    for sym, x, df in semua:
        if not x or len(baru) >= MAKS_BARU:
            continue
        arah, sl, a, ok_sl = x
        last = int(df.index[-1])
        if last - int(d["akhir"].get(sym, 0)) < JEDA_BAR * H4:
            continue
        jeda[sym] = last          # riset: pola apa pun memulai jeda 6 candle
        if not ok_sl:
            continue
        if arah not in btc:
            btc[arah] = btc_searah(arah)
        if btc[arah] is not True:
            continue
        px = float(df["close"].iloc[-1])
        if (tk[sym].get("last") or px) and abs((tk[sym].get("last") or px) - px) > 0.5 * abs(px - sl):
            print(f"[ICT] {sym} dilewati: harga sudah lari dari harga sinyal")
            continue
        it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=abs(px - sl), atr=a, best=px, bar=0, t=now, last=last,
                  close=px, tick=tick.get(sym, 0.0001), trail_atr=TRAIL_ATR)
        baru.append(it)
        out.append(kartu(it, len(baru)))

    def tambah(dd):
        for it in baru:
            dd["open"][f"{it['sym']}#{int(it['t'])}"] = it
        dd["akhir"].update(jeda)
    if baru or jeda:
        _ubah(tambah)
    return out


def teks():
    d = lihat()
    cl = d.get("closed", [])
    r = np.array([x.get("R", 0) for x in cl]) if cl else np.zeros(0)
    g = r[r > 0].sum(); l_ = -r[r < 0].sum()
    rows = ["🟪 <b>QSE v150 | JALUR ICT 4J</b> (sweep + MSS + FVG, jalur terpisah)", BT,
            f"Live: {len(cl)} selesai, WR {(r > 0).mean() * 100 if len(r) else 0:.0f}%, total {r.sum():+.2f}R, PF {g / l_ if l_ > 0 else 0:.2f}. "
            f"Jalan {len(d['open'])}."]
    for it in list(d["open"].values())[:10]:
        rows.append(f"• {it['sym']} {it['arah']} entry {TG.fp(it['entry'], it['tick'])}, SL sekarang {TG.fp(it['sl'], it['tick'])}")
    return "\n".join(rows)
