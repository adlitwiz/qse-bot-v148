"""QSE LAB (26 Okt 2026): robot riset otomatis. Tiap hari mencari, menguji, dan menambah teknik baru sendiri.

Alur:
1. RISET HARIAN 02:30 WIB (proses terpisah, prioritas rendah): susun 300 teknik baru dari blok bangunan (22 pemicu,
   11 penyaring, 10 cara keluar, combo 2 pemicu dalam 6 candle). 70% acak, 30% mutasi dari teknik yang hampir lolos.
   Diuji di 30 koin teramai, candle 4J sejak 2021, biaya 0.15% per trade, masuk di open candle berikutnya.
2. SYARAT LOLOS (ketat supaya teknik kebetulan terbuang): 2021-2023 minimal 150 trade PF 1.35, 2024-sekarang minimal
   100 trade PF 1.30, rata-rata minimal +0.10R di dua periode, untung di 2/3 tahun, PF minimal 0.10 di atas masuk acak
   dengan penyaring dan cara keluar yang sama (bukti pemicunya menambah nilai), tetap untung saat SL atau target digeser
   (PF 1.15), untung di dua kelompok koin terpisah (PF 1.10), dan paling banyak 40% trade sama dengan teknik aktif lain.
   Teknik yang mirip jalur robot dilewati. Uji lokal 600 teknik acak: 8% lolos syarat dasar, mayoritas SHORT breakout,
   jadi dipilih paling banyak 2 terbaik per hari.
3. KANDIDAT: sinyal 🧪 LAB lot 0.25x, dicatat otomatis di harga live (uji maju). Maksimal 12 teknik aktif.
4. TERBUKTI LAB: 150 trade maju dalam minimal 90 hari dengan PF 1.15 ke atas, lot 0.5x. DICABUT: 200 trade maju PF di
   bawah 0.90, atau gagal uji ulang tiap Minggu dengan data terbaru (PF di bawah 1.10). Kalau 12 tempat penuh, teknik baru
   yang PF-nya 0.15 lebih tinggi menggantikan kandidat terlemah yang uji majunya belum 50 trade (maksimal 1 per hari).
5. BULANAN (tanggal 1, atau saat belum pernah): uji saran SL (interval 1, 2, 3, 5%) di sinyal robot sendiri 180 hari.
   Saran SL aktif otomatis hanya kalau total R dan PF lebih tinggi dari aturan jalur. Uji pola open interest BTC
   (risiko likuidasi massal) dengan data Bybit, hasilnya dipakai /cek BTC.
Risiko jujur: menguji ratusan teknik per hari pasti menemukan beberapa yang bagus karena kebetulan. Penjaganya syarat
dua periode, uji ketahanan, lot kecil, dan uji maju di harga live sebelum naik status.
Manual: python qse_lab.py riset | sinyal | bulanan | status"""
import hashlib
import html
import json
import os
import random
import sys
import time

import numpy as np
import pandas as pd

from config import STATE_DIR

LAB = os.path.join(STATE_DIR, "lab")
DATA = os.path.join(LAB, "data")
BUKU = os.path.join(LAB, "buku.json")
H4 = 4 * 3600 * 1000
MULAI_MS = int(pd.Timestamp("2021-01-01", tz="UTC").value // 10 ** 6)
BATAS_MS = int(pd.Timestamp("2024-01-01", tz="UTC").value // 10 ** 6)
AWAL_DATA = int(pd.Timestamp("2020-10-01", tz="UTC").value // 10 ** 6)
N_RISET = int(os.environ.get("QSE_LAB_N", "300"))
MAKS_AKTIF = int(os.environ.get("QSE_LAB_MAKS", "12"))
N_KOIN = int(os.environ.get("QSE_LAB_KOIN", "30"))
MAKS_KARTU = 5
BIAYA = 0.0015
LOKAL = os.environ.get("QSE_LAB_LOKAL", "")          # folder csv untuk uji tanpa internet
SYARAT = dict(n_dev=150, n_uji=100, pf_dev=1.35, pf_uji=1.30, exp=0.10, tahun_plus=0.66, tetangga_pf=1.15, separuh_pf=1.10,
              acak=0.10, tumpang=0.40)
MAKS_BARU_HARI = 2
MAKS_SHORT = 8
AKTIF = ("KANDIDAT", "TERBUKTI LAB")
STABLE = ("USDCUSDT", "USDEUSDT", "FDUSDUSDT", "DAIUSDT", "TUSDUSDT", "USD1USDT", "BUSDUSDT")
INTERVAL_SL = (1.0, 2.0, 3.0, 5.0)


def _now():
    return float(os.environ.get("QSE_LAB_SEKARANG") or time.time())


def _log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "[LAB]", *a, flush=True)


# ---------------------------------------------------------------- penyimpanan
def _baca():
    try:
        with open(BUKU) as f:
            d = json.load(f)
    except Exception:
        d = {}
    for k, v in (("teknik", {}), ("open", {}), ("closed", []), ("diuji", []), ("riwayat", []), ("hampir", [])):
        d.setdefault(k, v)
    return d


def _simpan(d):
    os.makedirs(LAB, exist_ok=True)
    d["diuji"] = d["diuji"][-60000:]
    d["closed"] = d["closed"][-3000:]
    d["riwayat"] = d["riwayat"][-120:]
    d["hampir"] = sorted(d["hampir"], key=lambda z: -z["skor"])[:40]
    with open(BUKU + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(BUKU + ".tmp", BUKU)


def _json(nama):
    try:
        with open(os.path.join(LAB, nama)) as f:
            return json.load(f)
    except Exception:
        return None


def _kirim(teks):
    if LOKAL:
        print(teks, flush=True)
        return
    try:
        import telegram_notify as TG
        TG.send([teks])
    except Exception as ex:
        _log("kirim telegram gagal:", ex)


# ---------------------------------------------------------------- data 4J (cache sendiri, terpisah dari bot)
def _universe():
    if LOKAL:
        skor = {}
        for f in os.listdir(LOKAL):
            if not f.endswith("_240.csv") or f[:-8] in STABLE:
                continue
            try:
                d = pd.read_csv(os.path.join(LOKAL, f), usecols=["close", "volume"]).tail(2190)
                skor[f[:-8]] = float((d["close"] * d["volume"]).mean())
            except Exception:
                pass
        top = sorted(skor, key=lambda s: -skor[s])[:N_KOIN]
    else:
        import bybit_fetch as B
        tk = B.get_tickers()
        top = [s for s, _ in sorted(((s, v["turnover"]) for s, v in tk.items() if s.endswith("USDT") and s not in STABLE),
                                    key=lambda z: -z[1])[:N_KOIN]]
    if "BTCUSDT" not in top:
        top = ["BTCUSDT"] + top[:N_KOIN - 1]
    return top


def data4j(sym):
    """DataFrame candle 4J yang sudah tutup sejak Okt 2020, index waktu buka (ms)."""
    if LOKAL:
        df = pd.read_csv(os.path.join(LOKAL, f"{sym}_240.csv"), index_col=0, parse_dates=True)
        df.index = (df.index - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)
        return df[["open", "high", "low", "close", "volume"]].astype(float)
    import bybit_fetch as B
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, f"{sym}.pkl")
    now = int(time.time() * 1000)
    try:
        old = pd.read_pickle(p)
    except Exception:
        old = None
    df = None
    if old is not None and len(old):
        new = B._raw(sym, "240", 1000)
        if len(new) and new.index.min() <= old.index.max() + H4:
            df = pd.concat([old[old.index < new.index.min()], new])
    if df is None:
        df = B._raw(sym, "240", int((now - AWAL_DATA) / H4) + 10)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if len(df):
        df.to_pickle(p + ".tmp")
        os.replace(p + ".tmp", p)
    return df[df.index + H4 <= now][["open", "high", "low", "close", "volume"]].astype(float)


# ---------------------------------------------------------------- indikator
def _ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def _wma(x, n):
    a = np.asarray(x, float)
    out = np.full(len(a), np.nan)
    if len(a) >= n:
        w = np.arange(1, n + 1, dtype=float)
        out[n - 1:] = np.convolve(a, w[::-1], "valid") / w.sum()
    return pd.Series(out, index=x.index)


def _geser(a, k=1, isi=np.nan):
    """Nilai k bar sebelumnya (tanpa melihat masa depan)."""
    a = np.asarray(a, float)
    return np.r_[np.full(k, isi), a[:-k]] if k else a


def fitur(df, btc=None):
    """Semua indikator satu koin. Nilai di bar i hanya memakai data sampai bar i."""
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    F = {"o": o.values, "h": h.values, "l": l.values, "c": c.values, "t": df.index.values.astype(np.int64)}
    for n in (9, 20, 21, 50, 100, 200):
        F[f"ema{n}"] = _ema(c, n).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    F["atr"] = atr.values
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    F["rsi"] = (100 - 100 / (1 + up / dn)).values
    mac = _ema(c, 12) - _ema(c, 26)
    F["macd"], F["macds"] = mac.values, _ema(mac, 9).values
    sma = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    F["bbu"], F["bbl"] = (sma + 2 * sd).values, (sma - 2 * sd).values
    lebar = 4 * sd / sma
    F["squeeze"] = (lebar <= lebar.rolling(100).quantile(0.2)).astype(float).shift(1).fillna(0).values > 0
    F["dc20h"], F["dc20l"] = h.rolling(20).max().shift(1).values, l.rolling(20).min().shift(1).values
    F["dc55h"], F["dc55l"] = h.rolling(55).max().shift(1).values, l.rolling(55).min().shift(1).values
    F["kcu"], F["kcl"] = (_ema(c, 20) + 2 * atr).values, (_ema(c, 20) - 2 * atr).values
    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    k = (100 * (c - lo14) / (hi14 - lo14)).rolling(3).mean()
    F["stk"], F["std"] = k.values, k.rolling(3).mean().values
    F["wr"] = (-100 * (hi14 - c) / (hi14 - lo14)).values
    F["roc"] = (c / c.shift(10) - 1).values
    F["hma"] = _wma(2 * _wma(c, 10) - _wma(c, 21), 4).values
    pdm = h.diff().where((h.diff() > -l.diff()) & (h.diff() > 0), 0.0)
    ndm = (-l.diff()).where((-l.diff() > h.diff()) & (-l.diff() > 0), 0.0)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(alpha=1 / 14, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    F["adx"], F["pdi"], F["ndi"] = dx.ewm(alpha=1 / 14, adjust=False).mean().values, pdi.values, ndi.values
    sa = (((h.rolling(9).max() + l.rolling(9).min()) / 2 + (h.rolling(26).max() + l.rolling(26).min()) / 2) / 2).shift(26)
    sb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    F["awan_atas"], F["awan_bawah"] = np.fmax(sa.values, sb.values), np.fmin(sa.values, sb.values)
    F["vol80"] = (v >= v.rolling(100).quantile(0.8)).values
    F["vol90"] = (v >= v.rolling(100).quantile(0.9)).values
    # supertrend 10,3
    hl = ((h + l) / 2).values
    a10 = tr.ewm(alpha=1 / 10, adjust=False).mean().values
    ub, lb = hl + 3 * a10, hl - 3 * a10
    cv = c.values
    fu, fl, st = ub.copy(), lb.copy(), np.zeros(len(cv))
    for i in range(1, len(cv)):
        fu[i] = min(ub[i], fu[i - 1]) if cv[i - 1] <= fu[i - 1] else ub[i]
        fl[i] = max(lb[i], fl[i - 1]) if cv[i - 1] >= fl[i - 1] else lb[i]
        st[i] = 1 if cv[i] > fu[i - 1] else -1 if cv[i] < fl[i - 1] else st[i - 1]
    F["st"] = st
    # tren harian: close harian lawan EMA50 harian, hari kemarin yang sudah tutup
    t = pd.to_datetime(F["t"], unit="ms", utc=True)
    hc = pd.Series(cv, index=t).resample("1D").last().dropna()
    hdir = np.sign(hc - _ema(hc, 50)).shift(1)
    F["harian"] = hdir.reindex(t.floor("D")).values
    F["btc"] = btc.reindex(df.index).values if btc is not None else np.full(len(cv), np.nan)
    return F


def btc_arah(df_btc):
    """+1 kalau close BTC 4J di atas EMA50, -1 kalau di bawah. Index waktu buka (ms)."""
    c = df_btc["close"]
    return np.sign(c - _ema(c, 50))


# ---------------------------------------------------------------- blok bangunan
def _x(a, b, s):
    """Silang searah s: s=1 a memotong ke atas b, s=-1 ke bawah."""
    a = np.asarray(a, float)
    b = np.asarray(b, float) if np.ndim(b) else np.full(len(a), float(b))
    pa, pb = _geser(a), _geser(b)
    return ((a > b) & (pa <= pb)) if s == 1 else ((a < b) & (pa >= pb))


def _gt(a, b, s):
    a = np.asarray(a, float)
    return (a > b) if s == 1 else (a < b)


def _engulf(F, s):
    o, c = F["o"], F["c"]
    po, pc = _geser(o), _geser(c)
    arah_ok = (c > o) & (pc < po) if s == 1 else (c < o) & (pc > po)
    bungkus = (c > po) & (o <= pc) if s == 1 else (c < po) & (o >= pc)
    return arah_ok & bungkus & (np.abs(c - o) > np.abs(pc - po))


def _inside(F, s):
    h1, l1, h2, l2 = _geser(F["h"]), _geser(F["l"]), _geser(F["h"], 2), _geser(F["l"], 2)
    return (h1 < h2) & (l1 > l2) & ((F["c"] > h1) if s == 1 else (F["c"] < l1))


PEMICU = {
    "ema9_21": ("EMA 9 memotong EMA 21", lambda F, s: _x(F["ema9"], F["ema21"], s)),
    "ema20_50": ("EMA 20 memotong EMA 50", lambda F, s: _x(F["ema20"], F["ema50"], s)),
    "ema50_200": ("EMA 50 memotong EMA 200", lambda F, s: _x(F["ema50"], F["ema200"], s)),
    "harga_ema50": ("harga menembus EMA 50", lambda F, s: _x(F["c"], F["ema50"], s)),
    "harga_ema100": ("harga menembus EMA 100", lambda F, s: _x(F["c"], F["ema100"], s)),
    "rsi50": ("RSI melewati 50", lambda F, s: _x(F["rsi"], 50, s)),
    "rsi_balik": ("RSI keluar dari jenuh 30/70", lambda F, s: _x(F["rsi"], 30 if s == 1 else 70, s)),
    "macd_sinyal": ("MACD memotong garis sinyal", lambda F, s: _x(F["macd"], F["macds"], s)),
    "macd_nol": ("MACD melewati nol", lambda F, s: _x(F["macd"], 0, s)),
    "donchian20": ("tembus Donchian 20", lambda F, s: _x(F["c"], F["dc20h"] if s == 1 else F["dc20l"], s)),
    "donchian55": ("tembus Donchian 55", lambda F, s: _x(F["c"], F["dc55h"] if s == 1 else F["dc55l"], s)),
    "bb_tembus": ("tembus Bollinger Band", lambda F, s: _x(F["c"], F["bbu"] if s == 1 else F["bbl"], s)),
    "bb_balik": ("balik dari luar Bollinger Band", lambda F, s: _x(F["c"], F["bbl"] if s == 1 else F["bbu"], s)),
    "keltner": ("tembus Keltner Channel", lambda F, s: _x(F["c"], F["kcu"] if s == 1 else F["kcl"], s)),
    "supertrend": ("Supertrend berbalik", lambda F, s: _x(F["st"], 0, s)),
    "stoch": ("Stochastic silang dari jenuh",
              lambda F, s: _x(F["stk"], F["std"], s) & ((_geser(F["stk"]) < 20) if s == 1 else (_geser(F["stk"]) > 80))),
    "williams": ("Williams %R keluar dari jenuh", lambda F, s: _x(F["wr"], -80 if s == 1 else -20, s)),
    "roc": ("ROC 10 melewati nol", lambda F, s: _x(F["roc"], 0, s)),
    "hma": ("Hull MA berbalik arah", lambda F, s: _x(F["hma"] - _geser(F["hma"]), 0, s)),
    "engulf": ("candle engulfing", _engulf),
    "inside_tembus": ("tembus inside bar", _inside),
    "candle_kuat": ("candle besar searah bervolume", lambda F, s: (((F["c"] - F["o"]) * s) > 1.2 * F["atr"]) & F["vol90"]),
}

SARING = {
    "tren200": ("searah EMA 200", lambda F, s: _gt(F["c"], F["ema200"], s)),
    "tren50": ("searah EMA 50", lambda F, s: _gt(F["c"], F["ema50"], s)),
    "ema2050": ("EMA 20 searah EMA 50", lambda F, s: _gt(F["ema20"], F["ema50"], s)),
    "adx_tren": ("ADX di atas 20 searah", lambda F, s: (F["adx"] > 20) & _gt(F["pdi"], F["ndi"], s)),
    "adx_sepi": ("ADX di bawah 20", lambda F, s: F["adx"] < 20),
    "vol80": ("volume 20% tertinggi", lambda F, s: F["vol80"]),
    "btc": ("searah BTC 4J (EMA 50)", lambda F, s: F["btc"] == s),
    "rsi_aman": ("RSI belum jenuh", lambda F, s: (F["rsi"] < 70) if s == 1 else (F["rsi"] > 30)),
    "squeeze": ("keluar dari Bollinger menyempit", lambda F, s: F["squeeze"]),
    "awan": ("di luar awan Ichimoku searah", lambda F, s: (F["c"] > F["awan_atas"]) if s == 1 else (F["c"] < F["awan_bawah"])),
    "harian": ("searah tren harian (EMA 50 1D)", lambda F, s: F["harian"] == s),
}

KELUAR = [("trail", 1.5, 3.0), ("trail", 1.5, 4.0), ("trail", 2.0, 3.0), ("trail", 2.0, 4.0),
          ("tp", 1.5, 2.0), ("tp", 1.5, 3.0), ("tp", 1.5, 4.0), ("tp", 2.0, 2.0), ("tp", 2.0, 3.0), ("tp", 2.0, 4.0)]

# jalur robot yang sudah ada: teknik lab yang mirip (pemicu sama, penyaring beda paling banyak 1) dilewati
SUDAH_ADA = [("ema20_50", "S", {"tren200", "btc"}), ("rsi50", "LS", {"vol80", "tren200"})]


def _id(spec):
    return hashlib.md5(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]


def _arah(spec):
    return (1,) if spec["arah"] == "L" else (-1,) if spec["arah"] == "S" else (1, -1)


def _mirip(a, b):
    """Dua teknik dianggap sama kalau pemicunya sama, arahnya beririsan, dan penyaring beda paling banyak 1."""
    return a["p"] == b["p"] and a.get("p2") == b.get("p2") and bool(set(a["arah"]) & set(b["arah"])) \
        and len(set(a["f"]) ^ set(b["f"])) <= 1


def _mirip_jalur(spec):
    return any(_mirip(spec, {"p": p, "p2": None, "arah": a, "f": fs}) for p, a, fs in SUDAH_ADA)


def nama(spec):
    arah = {"L": "LONG", "S": "SHORT", "LS": "LONG dan SHORT"}[spec["arah"]]
    t = PEMICU[spec["p"]][0]
    if spec.get("p2"):
        t += f" setelah {PEMICU[spec['p2']][0]} (combo dalam 6 candle)"
    if spec["f"]:
        t += ", " + ", ".join(SARING[f][0] for f in spec["f"])
    ex = spec["ex"]
    t += f", SL {ex[1]:g} ATR, " + (f"trailing {ex[2]:g} ATR" if ex[0] == "trail" else f"TP {ex[2]:g}R")
    return f"{t} ({arah})"


def acak_spec(rng):
    p = rng.choice(sorted(PEMICU))
    p2 = rng.choice(sorted(x for x in PEMICU if x != p)) if rng.random() < 0.3 else None
    f = sorted(rng.sample(sorted(SARING), rng.choice([0, 1, 1, 2, 2, 2, 3])))
    return {"p": p, "p2": p2, "arah": rng.choice(["L", "S", "LS"]), "f": f, "ex": list(rng.choice(KELUAR))}


def mutasi(spec, rng):
    """Ubah satu bagian teknik yang hampir lolos: penyaring, cara keluar, arah, atau pemicu kedua."""
    s = json.loads(json.dumps(spec))
    m = rng.choice(["f", "f", "ex", "arah", "p2"])
    if m == "f":
        f = set(s["f"])
        if f and (len(f) >= 3 or rng.random() < 0.5):
            f.discard(rng.choice(sorted(f)))
        else:
            f.add(rng.choice(sorted(x for x in SARING if x not in f)))
        s["f"] = sorted(f)
    elif m == "ex":
        s["ex"] = list(rng.choice([e for e in KELUAR if list(e) != s["ex"]]))
    elif m == "arah":
        s["arah"] = rng.choice([a for a in ("L", "S", "LS") if a != s["arah"]])
    else:
        s["p2"] = None if s.get("p2") else rng.choice(sorted(x for x in PEMICU if x != s["p"]))
    return s


# ---------------------------------------------------------------- simulasi
def sinyal_idx(F, spec, s):
    ok = np.asarray(PEMICU[spec["p"]][1](F, s), bool)
    if spec.get("p2"):
        e2 = np.asarray(PEMICU[spec["p2"]][1](F, s), bool)
        win = e2.copy()
        for k in range(1, 7):
            win[k:] |= e2[:-k]
        ok = ok & win
    for f in spec["f"]:
        ok = ok & np.asarray(SARING[f][1](F, s), bool)
    return np.nonzero(ok)[0]


def simulasi(F, spec, mulai_idx=250, idx=None):
    """Trade tanpa tumpang tindih per koin. idx: daftar (bar, arah) kalau mau masuk di bar tertentu (uji pembanding acak).
    Return list (waktu sinyal ms, R bersih biaya, jumlah candle, arah)."""
    o, h, l, c, atr, t = F["o"], F["h"], F["l"], F["c"], F["atr"], F["t"]
    tipe, slk, x = spec["ex"]
    H = 60 if tipe == "trail" else 45
    if idx is None:
        idx = sorted((int(i), s) for s in _arah(spec) for i in sinyal_idx(F, spec, s) if i >= mulai_idx)
    out, akhir, N = [], -1, len(c)
    for i, s in idx:
        if i <= akhir or i + H >= N:
            continue                       # masih ada trade jalan, atau data belum cukup untuk trade ini selesai
        e = o[i + 1]
        risk = slk * atr[i]
        if not (risk > 0 and e > 0) or risk / e < 0.003 or risk / e > 0.10:
            continue
        sl = e - s * risk
        best = e
        tp = e + s * x * risk if tipe == "tp" else None
        end = i + H
        R = None
        j = i + 1
        while j <= end:
            if (l[j] <= sl) if s == 1 else (h[j] >= sl):
                R = (sl - e) * s / risk
                break
            if tp is not None and ((h[j] >= tp) if s == 1 else (l[j] <= tp)):
                R = x
                break
            if tipe == "trail":
                if s == 1:
                    best = max(best, h[j])
                    sl = max(sl, best - x * atr[j])
                else:
                    best = min(best, l[j])
                    sl = min(sl, best + x * atr[j])
            j += 1
        if R is None:
            j = end
            R = (c[end] - e) * s / risk
        out.append((int(t[i]), R - BIAYA * e / risk, j - i, s))
        akhir = j
    return out


def _pf(r):
    r = np.asarray(r, float)
    neg = -r[r < 0].sum()
    return float(r[r > 0].sum() / neg) if neg > 0 else (9.99 if len(r) else 0.0)


def nilai(hasil):
    """hasil: list (t, R, candle, arah) semua koin. Ringkasan 2021-2023 (dev) dan 2024-sekarang (uji)."""
    if not hasil:
        return None
    t = np.array([z[0] for z in hasil])
    r = np.array([z[1] for z in hasil])
    nb = np.array([z[2] for z in hasil])
    mdev, muji = (t >= MULAI_MS) & (t < BATAS_MS), t >= BATAS_MS
    dev, uji = r[mdev], r[muji]
    th = pd.to_datetime(t, unit="ms", utc=True).year
    tahun = [y for y in sorted(set(th)) if y >= 2021 and (th == y).sum() >= 20]
    plus = sum(1 for y in tahun if r[th == y].sum() > 0)
    semua = mdev | muji
    return dict(n_dev=int(len(dev)), n_uji=int(len(uji)), pf_dev=round(_pf(dev), 2), pf_uji=round(_pf(uji), 2),
                exp_dev=round(float(dev.mean()) if len(dev) else 0.0, 3), exp_uji=round(float(uji.mean()) if len(uji) else 0.0, 3),
                wr=round(float((r[semua] > 0).mean() * 100), 0) if semua.any() else 0.0,
                lama=round(float(np.median(nb[semua])) * 4 / 24, 1) if semua.any() else 0.0,
                tahun_plus=round(plus / len(tahun), 2) if tahun else 0.0)


def lolos(m):
    S = SYARAT
    return bool(m) and m["n_dev"] >= S["n_dev"] and m["n_uji"] >= S["n_uji"] and m["pf_dev"] >= S["pf_dev"] \
        and m["pf_uji"] >= S["pf_uji"] and m["exp_dev"] >= S["exp"] and m["exp_uji"] >= S["exp"] and m["tahun_plus"] >= S["tahun_plus"]


def jalankan(FS, spec):
    return {s: simulasi(F, spec) for s, F in FS.items()}


def gabung(per):
    return [z for v in per.values() for z in v]


def saring_idx(F, spec, s, mulai_idx=250):
    """Bar yang lolos semua penyaring teknik (tanpa pemicu)."""
    ok = np.ones(len(F["c"]), bool)
    for f in spec["f"]:
        ok &= np.asarray(SARING[f][1](F, s), bool)
    ok[:mulai_idx] = False
    return np.nonzero(ok)[0]


def pembanding(FS, spec, ulang=3, seed=11):
    """Pembanding acak: masuk di bar acak yang lolos penyaring yang sama, jumlah sinyal sama, cara keluar sama.
    Kalau teknik tidak jauh lebih baik dari ini, pemicunya tidak menambah apa-apa (hanya ikut kondisi pasar)."""
    rng = np.random.default_rng(seed)
    out = []
    for F in FS.values():
        for s in _arah(spec):
            n = len([i for i in sinyal_idx(F, spec, s) if i >= 250])
            pool = saring_idx(F, spec, s)
            if not n or not len(pool):
                continue
            for _ in range(ulang):
                pick = np.sort(rng.choice(pool, size=min(n, len(pool)), replace=False))
                out += simulasi(F, spec, idx=[(int(i), s) for i in pick])
    return nilai(out)


def tetangga(spec):
    """Variasi kecil cara keluar untuk uji ketahanan."""
    tipe, sl, x = spec["ex"]
    return [dict(spec, ex=list(e)) for e in KELUAR if e[0] == tipe and (e[1] != sl) + (e[2] != x) == 1]


def tahan_uji(FS, spec, per):
    """Uji ketahanan: untung di dua kelompok koin terpisah, dan tetap untung saat SL atau target digeser."""
    syms = sorted(per)
    for grup in (syms[::2], syms[1::2]):
        r = [z[1] for s in grup for z in per[s] if z[0] >= MULAI_MS]
        if len(r) < 60 or _pf(r) < SYARAT["separuh_pf"]:
            return False, "gagal di separuh koin"
    nb = tetangga(spec)
    ok = 0
    for s2 in nb:
        m = nilai(gabung(jalankan(FS, s2)))
        if m and m["pf_dev"] >= SYARAT["tetangga_pf"] and m["pf_uji"] >= SYARAT["tetangga_pf"]:
            ok += 1
    if ok < max(1, (len(nb) + 1) // 2):
        return False, "gagal saat SL atau target digeser"
    return True, ""


def tumpang(per_a, per_b):
    """Persen trade teknik A yang juga diambil teknik B (koin dan arah sama, masuk dalam 6 candle). Untuk menjaga keragaman."""
    n = cocok = 0
    for sym, ta in per_a.items():
        tb = per_b.get(sym) or []
        for z in ta:
            n += 1
            cocok += any(w[3] == z[3] and abs(w[0] - z[0]) <= 6 * H4 for w in tb)
    return cocok / n if n else 0.0


def muat_semua(uni=None):
    dfs = {}
    for s in (uni or _universe()):
        try:
            df = data4j(s)
            if len(df) >= 600:
                dfs[s] = df
        except Exception as ex:
            _log(f"data {s} gagal: {ex}")
    btc = btc_arah(dfs["BTCUSDT"]) if "BTCUSDT" in dfs else None
    return {s: fitur(df, btc) for s, df in dfs.items()}


# ---------------------------------------------------------------- riset harian
def riset():
    t0 = time.time()
    try:
        os.nice(10)
    except Exception:
        pass
    FS = muat_semua()
    if len(FS) < 10 or not any(F["t"][-1] >= BATAS_MS for F in FS.values()):
        _log("data kurang, riset batal", len(FS))
        return None
    d = _baca()
    sudah = set(d["diuji"])
    rng = random.Random(int(time.time() * 1000) % 2 ** 31)
    hampir = d["hampir"]
    lulus, baru, coba = [], 0, 0
    while baru < N_RISET and coba < N_RISET * 30:
        coba += 1
        spec = mutasi(rng.choice(hampir)["spec"], rng) if hampir and rng.random() < 0.3 else acak_spec(rng)
        k = _id(spec)
        if k in sudah or _mirip_jalur(spec):
            continue
        sudah.add(k)
        d["diuji"].append(k)
        baru += 1
        per = jalankan(FS, spec)
        m = nilai(gabung(per))
        if not m:
            continue
        if lolos(m):
            lulus.append((spec, m, per))
        elif m["n_dev"] >= SYARAT["n_dev"] and m["n_uji"] >= SYARAT["n_uji"] and min(m["pf_dev"], m["pf_uji"]) >= 1.15:
            hampir.append(dict(spec=spec, skor=min(m["pf_dev"], m["pf_uji"])))
    aktif = {k: v for k, v in d["teknik"].items() if v["status"] in AKTIF}
    per_aktif = {k: jalankan(FS, v["spec"]) for k, v in aktif.items()}
    masuk, n_acak, n_tahan = [], 0, 0
    diganti = []
    skor = lambda m: min(m["pf_dev"], m["pf_uji"])
    for spec, m, per in sorted(lulus, key=lambda z: -skor(z[1])):
        if len(masuk) >= MAKS_BARU_HARI:
            break
        ganti = None
        if len(aktif) >= MAKS_AKTIF:
            lemah = [(skor(v["uji"]), k) for k, v in aktif.items() if v["status"] == "KANDIDAT" and len(v.get("maju", [])) < 50]
            if diganti or not lemah or skor(m) < min(lemah)[0] + 0.15:
                continue
            ganti = min(lemah)[1]
        if any(_mirip(spec, v["spec"]) for kk, v in aktif.items() if kk != ganti):
            continue
        if spec["arah"] == "S" and sum(v["spec"]["arah"] == "S" for kk, v in aktif.items() if kk != ganti) >= MAKS_SHORT:
            continue                          # jaga keragaman: SHORT saja paling banyak 8 teknik, risiko bergerombol saat pasar turun
        b = pembanding(FS, spec)
        if not b or m["pf_dev"] - b["pf_dev"] < SYARAT["acak"] or m["pf_uji"] - b["pf_uji"] < SYARAT["acak"]:
            _log("tidak lebih baik dari masuk acak:", nama(spec))
            continue
        n_acak += 1
        ok, why = tahan_uji(FS, spec, per)
        if not ok:
            hampir.append(dict(spec=spec, skor=min(m["pf_dev"], m["pf_uji"])))
            _log("tidak tahan:", nama(spec), why)
            continue
        n_tahan += 1
        tp = max([tumpang(per, pa) for kk, pa in per_aktif.items() if kk != ganti] or [0.0])
        if tp > SYARAT["tumpang"]:
            _log(f"terlalu mirip teknik aktif ({tp:.0%} trade sama):", nama(spec))
            continue
        if ganti:
            aktif[ganti]["status"], aktif[ganti]["alasan"] = "DIGANTI", "diganti teknik baru yang lebih kuat"
            aktif.pop(ganti)
            per_aktif.pop(ganti, None)
            diganti.append(ganti)
        k = _id(spec)
        v = dict(spec=spec, nama=nama(spec), status="KANDIDAT", uji=m, acak=b, maju=[], t_lolos=int(_now()))
        d["teknik"][k] = v
        aktif[k] = v
        per_aktif[k] = per
        masuk.append(k)
    # uji ulang tiap Minggu dengan data terbaru
    dicabut = []
    if time.gmtime().tm_wday == 6:
        for k, v in list(aktif.items()):
            if k in masuk:
                continue
            m = nilai(gabung(jalankan(FS, v["spec"])))
            if m:
                v["uji"] = m
            if not m or m["pf_uji"] < 1.10 or m["pf_dev"] < 1.10:
                v["status"], v["alasan"] = "DICABUT", "gagal uji ulang mingguan"
                dicabut.append(k)
    dedup = {}
    for z in hampir:
        dedup.setdefault(_id(z["spec"]), z)
    d["hampir"] = list(dedup.values())
    d["riwayat"].append(dict(t=int(time.time()), diuji=baru, lolos=len(lulus), masuk=len(masuk), detik=int(time.time() - t0)))
    _simpan(d)
    rows = ["🧪 <b>QSE v148 | LAB RISET HARIAN</b>",
            f"Hari ini diuji {baru} teknik baru di {len(FS)} koin teramai (candle 4J sejak 2021). Total sudah diuji {len(d['diuji']):,}.",
            f"Lolos syarat 2 periode: {len(lulus)}. Dari yang dicek, lebih baik dari masuk acak {n_acak}, lolos uji ketahanan {n_tahan}. "
            f"Masuk KANDIDAT hari ini: {len(masuk)} (maksimal {MAKS_BARU_HARI} per hari, harus beda dari teknik aktif)."]
    for k in masuk:
        v = d["teknik"][k]
        m, b = v["uji"], v["acak"]
        rows.append(f"🆕 {html.escape(v['nama'])}\n   PF 2021-23 {m['pf_dev']}, 2024-sekarang {m['pf_uji']} (masuk acak {b['pf_dev']} dan "
                    f"{b['pf_uji']}), {m['n_dev'] + m['n_uji']} trade, WR {m['wr']:.0f}%, lama rata {m['lama']:g} hari")
    for k in diganti:
        rows.append(f"🔁 Diganti: {html.escape(d['teknik'][k]['nama'])} (uji majunya belum 50 trade, teknik baru PF lebih tinggi)")
    for k in dicabut:
        rows.append(f"❌ Dicabut: {html.escape(d['teknik'][k]['nama'])} ({d['teknik'][k].get('alasan')})")
    rows.append(status_teks(d, ringkas=time.gmtime().tm_wday != 6))      # daftar lengkap teknik aktif tiap Minggu
    _kirim("\n".join(rows))
    _log(f"riset selesai {int(time.time() - t0)} detik, diuji {baru}, lolos {len(lulus)}, masuk {len(masuk)}")
    return d


def status_teks(d=None, ringkas=False):
    d = d or _baca()
    ak = [v for v in d["teknik"].values() if v["status"] in AKTIF]
    sel = [c["R"] for c in d["closed"]]
    rows = [f"📚 Teknik lab aktif {len(ak)} (kandidat {sum(v['status'] == 'KANDIDAT' for v in ak)}, "
            f"terbukti lab {sum(v['status'] == 'TERBUKTI LAB' for v in ak)}), dicabut "
            f"{sum(v['status'] == 'DICABUT' for v in d['teknik'].values())}. Posisi lab jalan {len(d['open'])}, selesai {len(sel)}"
            + (f" (PF {_pf(sel):.2f}, total {sum(sel):+.1f}R)" if sel else "") + "."]
    if not ringkas:
        for v in ak:
            mj = v.get("maju", [])
            rows.append(f"{'✅' if v['status'] == 'TERBUKTI LAB' else '🧪'} {html.escape(v['nama'])}\n   uji PF {v['uji']['pf_dev']} / "
                        f"{v['uji']['pf_uji']}  ·  maju {len(mj)} trade" + (f", PF {_pf(mj):.2f}" if mj else ""))
    return "\n".join(rows)


# ---------------------------------------------------------------- sinyal live dan uji maju
def _status_maju(v):
    """Uji lokal 52 teknik yang lolos syarat (2024-2026): 40 trade beruntun PF di bawah 0.8 terjadi di 36% waktu walau
    tekniknya bagus, karena trade datang bergerombol saat pasar searah. Jadi status naik atau dicabut pakai jendela panjang:
    150 trade dan 90 hari PF 1.15 (teknik bagus lolos 68%, teknik biasa 39%), dicabut 200 trade PF di bawah 0.90
    (teknik bagus kena 15%, teknik biasa 37%)."""
    mj = v.get("maju", [])
    hari = (_now() - v.get("t_lolos", _now())) / 86400
    if v["status"] == "KANDIDAT" and len(mj) >= 150 and hari >= 90 and _pf(mj) >= 1.15:
        return "TERBUKTI LAB", f"{len(mj)} trade maju dalam {hari:.0f} hari, PF {_pf(mj):.2f}"
    if len(mj) >= 200 and _pf(mj) < 0.90:
        return "DICABUT", f"{len(mj)} trade maju PF {_pf(mj):.2f}"
    return None, ""


def _fmt(x, t):
    try:
        import qse_saya as SY
        return SY.fp(x, t)
    except Exception:
        return f"{x:.6g}"


def _kelola_open(d, FSd, tick):
    """Perbarui posisi lab yang masih jalan dengan candle baru. Return pesan selesai dan perubahan status."""
    pesan = []
    for key in list(d["open"].keys()):
        tr = d["open"][key]
        F = FSd.get(tr["sym"])
        if F is None:
            continue
        t, h, l, c, atr = F["t"], F["h"], F["l"], F["c"], F["atr"]
        s, e, risk = tr["s"], tr["entry"], tr["risk"]
        R, alasan = None, ""
        for j in np.nonzero(t > tr["last"])[0]:
            tr["bar"] += 1
            if (l[j] <= tr["sl"]) if s == 1 else (h[j] >= tr["sl"]):
                R, alasan = (tr["sl"] - e) * s / risk, "SL"
                break
            if tr.get("tp") and ((h[j] >= tr["tp"]) if s == 1 else (l[j] <= tr["tp"])):
                R, alasan = (tr["tp"] - e) * s / risk, "TP"
                break
            if tr["tipe"] == "trail":
                tr["best"] = max(tr["best"], h[j]) if s == 1 else min(tr["best"], l[j])
                tr["sl"] = max(tr["sl"], tr["best"] - tr["x"] * atr[j]) if s == 1 else min(tr["sl"], tr["best"] + tr["x"] * atr[j])
            tr["last"] = int(t[j])
            if tr["bar"] >= tr["H"]:
                R, alasan = (c[j] - e) * s / risk, "WAKTU"
                break
        if R is None:
            continue
        R -= BIAYA * e / risk
        d["open"].pop(key)
        d["closed"].append(dict(tr, R=round(R, 3), alasan=alasan, selesai=int(_now())))
        v = d["teknik"].get(tr["id"])
        if tr.get("kirim"):
            tk = tick.get(tr["sym"]) or 0.0001
            arah = "LONG" if s == 1 else "SHORT"
            pesan.append(f"{'✅' if R > 0 else '🛑'} <b>LAB SELESAI  ·  {tr['sym']} {arah}  ·  {R:+.2f}R</b>\n"
                         + ("Target tersentuh." if alasan == "TP" else f"Kena SL di sekitar {_fmt(tr['sl'], tk)}." if alasan == "SL"
                            else f"Sudah {tr['H']} candle 4J. Tutup sekarang di harga pasar."))
        if v:
            v.setdefault("maju", []).append(round(R, 3))
            st, why = _status_maju(v) if v["status"] in AKTIF else (None, "")
            if st and st != v["status"]:
                v["status"], v["alasan"] = st, why
                pesan.append(f"{'✅ NAIK JADI TERBUKTI LAB (lot 0.5x)' if st == 'TERBUKTI LAB' else '❌ DICABUT'}: "
                             f"{html.escape(v['nama'])} ({why})")
    return pesan


def _posisi_robot():
    """Koin yang sedang dipegang jalur robot terbukti, supaya kartu lab tidak dobel."""
    out = set()
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            out |= {v["sym"] for v in ST.lihat(k).get("open", {}).values()}
    except Exception:
        pass
    for mod in ("qse_ichimoku", "qse_ob"):
        try:
            m = __import__(mod)
            out |= {v["sym"] for v in m.lihat().get("open", {}).values()}
        except Exception:
            pass
    return out


def sinyal():
    """Tiap candle 4J tutup: kelola posisi lab, lalu kirim sinyal baru teknik aktif."""
    d = _baca()
    ak = {k: v for k, v in d["teknik"].items() if v["status"] in AKTIF}
    if not ak and not d["open"]:
        return []
    now = _now()
    uni = list(dict.fromkeys(_universe() + [tr["sym"] for tr in d["open"].values()]))
    dfs = {}
    for s in uni:
        try:
            df = data4j(s)
            df = df[df.index + H4 <= now * 1000]
            dfs[s] = df.iloc[-1200:]
        except Exception as ex:
            _log(f"data {s} gagal: {ex}")
    btc = btc_arah(dfs["BTCUSDT"]) if "BTCUSDT" in dfs else None
    FSd = {s: fitur(df, btc) for s, df in dfs.items() if len(df) >= 300}
    tick = {}
    if not LOKAL:
        try:
            import bybit_fetch as B
            tick = B.get_symbols()
        except Exception:
            pass
    pesan = _kelola_open(d, FSd, tick)
    tahan, ST = "", None
    try:
        import qse_strat as ST
    except Exception:
        pass
    if not LOKAL:
        try:
            import qse_pagi as PG
            tahan = PG.short_tahan()
        except Exception:
            pass
    try:
        import qse_saya as SY
    except Exception:
        SY = None
    calon = []
    for k, v in ak.items():
        spec = v["spec"]
        tipe, slk, x = spec["ex"]
        for sym, F in FSd.items():
            if f"{k}|{sym}" in d["open"]:
                continue
            i = len(F["c"]) - 1
            if F["t"][i] + 2 * H4 < now * 1000:
                continue                      # data terlambat: lewati
            for s in _arah(spec):
                idx = sinyal_idx(F, spec, s)
                if not len(idx) or idx[-1] != i:
                    continue
                if s == -1 and (tahan or (ST and ST.pump_tolak(dfs[sym], "SHORT"))):
                    break                     # aturan robot untuk semua SHORT: hari condong naik dan koin habis pump
                px = F["c"][i]
                if SY and not LOKAL:
                    px = SY.harga_live(sym) or px
                risk = slk * F["atr"][i]
                if not (risk > 0) or risk / px < 0.003 or risk / px > 0.10:
                    break
                tr = dict(id=k, sym=sym, s=s, entry=float(px), risk=float(risk), atr=float(F["atr"][i]), sl=float(px - s * risk),
                          best=float(px), tp=float(px + s * x * risk) if tipe == "tp" else None, tipe=tipe, x=x,
                          H=60 if tipe == "trail" else 45, bar=0, last=int(F["t"][i]), t=int(now), kirim=False)
                d["open"][f"{k}|{sym}"] = tr
                calon.append((v, tr))
                break
    robot = _posisi_robot()
    calon.sort(key=lambda z: (z[0]["status"] != "TERBUKTI LAB", -min(z[0]["uji"]["pf_dev"], z[0]["uji"]["pf_uji"])))
    kartu, dipakai = [], set()
    for v, tr in calon:
        if len(kartu) < MAKS_KARTU and tr["sym"] not in robot and tr["sym"] not in dipakai:
            tr["kirim"] = True
            dipakai.add(tr["sym"])
            kartu.append(_kartu(v, tr, SY, tick.get(tr["sym"])))
    _simpan(d)
    if not (kartu or pesan):
        _log(f"sinyal: tidak ada yang baru ({len(calon)} dicatat diam-diam)")
        return []
    teks = ("🧪 <b>QSE v148 | SINYAL TEKNIK LAB</b>\nTeknik temuan robot sendiri, lolos uji 2021-2023 dan 2024-sekarang, sedang uji maju "
            "di harga live. KANDIDAT lot 0.25x, TERBUKTI LAB lot 0.5x dari lot biasa.\n\n" + "\n\n".join(pesan + kartu))
    _kirim(teks)
    return [teks]


def _kartu(v, tr, SY, tick=None):
    L = tr["s"] == 1
    arah = "LONG" if L else "SHORT"
    t = tick or (SY.tick_of(None, tr["entry"]) if SY else 0.0001)
    m, mj = v["uji"], v.get("maju", [])
    lot = "0.5x" if v["status"] == "TERBUKTI LAB" else "0.25x"
    if SY:
        if tr.get("tp"):
            blok = SY.blok_salin(tr["entry"], tr["sl"], tr["tp"], tr["tp"], "MARKET", t, sym=tr["sym"], arah=arah)
        else:
            blok = SY.blok_salin(tr["entry"], tr["sl"], order="MARKET", tick=t, catatan_tp="tanpa, pakai trailing", sym=tr["sym"], arah=arah)
    else:
        blok = (f"<pre>{tr['sym']} {arah}\nEntry {tr['entry']:.6g} MARKET\nSL    {tr['sl']:.6g}"
                + (f"\nTP    {tr['tp']:.6g}" if tr.get("tp") else "") + "</pre>")
    jam = time.strftime("%d/%m %H:%M", time.gmtime((tr["last"] + 2 * H4) / 1000 + 7 * 3600))
    rows = [f"{'🟢' if L else '🔴'} <b>{tr['sym']} {arah}</b>  ·  {'✅ TERBUKTI LAB' if v['status'] == 'TERBUKTI LAB' else '🧪 KANDIDAT'}"
            f"  ·  lot {lot}",
            f"📐 {html.escape(v['nama'])}",
            f"📊 Uji 2021-23 PF {m['pf_dev']}, 2024-sekarang PF {m['pf_uji']}, {m['n_dev'] + m['n_uji']} trade, WR {m['wr']:.0f}%"
            f"  ·  uji maju {len(mj)} trade" + (f" PF {_pf(mj):.2f}" if mj else ""),
            blok,
            f"🎯 Entry valid sampai {jam} WIB selama harga dalam Range",
            f"⏳ Lama trade (uji): rata {m.get('lama', 0):g} hari, paling lama {tr['H'] * 4 // 24} hari"]
    if len(mj) >= 40 and _pf(mj[-40:]) < 0.8:
        rows.append(f"⚠️ 40 trade maju terakhir PF {_pf(mj[-40:]):.2f}. Di uji ini terjadi di 36% waktu walau tekniknya bagus, "
                    "karena trade datang bergerombol. Lot tetap kecil, jangan dinaikkan.")
    if tr["tipe"] == "trail" and SY:
        rows.append(SY.isi_trailing(tr["x"] * tr["atr"], tr["sl"], t))
    return "\n".join(rows)


# ---------------------------------------------------------------- bulanan: saran SL dan open interest
def _bybit(path, params):
    import bybit_fetch as B
    return B._get(path, params)


def uji_oi():
    """Uji pola open interest BTC (risiko likuidasi massal) dengan data Bybit 4J. Disimpan untuk /cek BTC."""
    rows, cur = [], ""
    for _ in range(80):
        p = {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "4h", "limit": 200}
        if cur:
            p["cursor"] = cur
        res = _bybit("/v5/market/open-interest", p)
        lst = res.get("list", [])
        rows += [(int(x["timestamp"]), float(x["openInterest"])) for x in lst]
        cur = res.get("nextPageCursor", "")
        if not cur or not lst:
            break
    if len(rows) < 1500:
        return None
    oi = pd.Series(dict(rows)).sort_index()
    px = data4j("BTCUSDT")["close"]
    df = pd.DataFrame({"oi": oi, "c": px}).dropna()      # OI dianggap baru diketahui saat candle tutup (aman, tanpa lihat masa depan)
    df["oi24"] = df.oi / df.oi.shift(6) - 1
    df["p24"] = df.c / df.c.shift(6) - 1
    df["f24"] = df.c.shift(-6) / df.c - 1
    df = df.dropna()
    if len(df) < 1500:
        return None
    mid = df.index[len(df) // 2]
    q90, q10 = float(df.oi24.quantile(0.9)), float(df.oi24.quantile(0.1))
    kond = {"long_menumpuk": (df.oi24 >= q90) & (df.p24 > 0), "short_menumpuk": (df.oi24 >= q90) & (df.p24 < 0),
            "oi_rontok": df.oi24 <= q10}
    hasil = {}
    for k, m in kond.items():
        st = []
        for part in (df.index < mid, df.index >= mid):
            x, b = df[m & part].f24, df[part].f24
            st.append(dict(n=int(len(x)), naik=round(float((x > 0).mean() * 100), 1) if len(x) else 0.0,
                           gerak3=round(float((x.abs() > 0.03).mean() * 100), 1) if len(x) else 0.0,
                           base_naik=round(float((b > 0).mean() * 100), 1), base_gerak3=round(float((b.abs() > 0.03).mean() * 100), 1)))
        cukup = all(s["n"] >= 30 for s in st)
        naik = cukup and all(s["naik"] - s["base_naik"] >= 5 for s in st)
        turun = cukup and all(s["naik"] - s["base_naik"] <= -5 for s in st)
        gerak = cukup and all(s["gerak3"] - s["base_gerak3"] >= 5 for s in st)
        hasil[k] = dict(periode=st, arah=1 if naik else -1 if turun else 0, gerak=bool(gerak))
    out = dict(t=int(time.time()), q90=q90, q10=q10, hasil=hasil, dari=int(df.index[0]), sampai=int(df.index[-1]))
    with open(os.path.join(LAB, "oi_hasil.json"), "w") as f:
        json.dump(out, f)
    return out


NAMA_OI = {"long_menumpuk": "OI naik tajam saat harga naik (LONG menumpuk)",
           "short_menumpuk": "OI naik tajam saat harga turun (SHORT menumpuk)",
           "oi_rontok": "OI turun tajam (posisi dilikuidasi atau ditutup)"}


def oi_info():
    """Untuk /cek BTC: perubahan open interest BTC 24 jam dan pola yang cocok dari uji bulanan.
    Return dict(rows, arah 24 jam +1/-1/0, gerak True kalau peluang gerak besar lebih tinggi dari biasa)."""
    try:
        res = _bybit("/v5/market/open-interest", {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "4h", "limit": 7})
        lst = sorted((int(x["timestamp"]), float(x["openInterest"])) for x in res.get("list", []))
        oi24 = lst[-1][1] / lst[0][1] - 1
    except Exception as ex:
        _log("oi sekarang gagal", ex)
        return {}
    o = _json("oi_hasil.json")
    rows = [f"📊 Open interest BTC 24 jam {oi24 * 100:+.1f}%."]
    if not o:
        rows[0] += " Pola open interest belum diuji (uji otomatis bulanan dari VPS)."
        return {"rows": rows, "arah": 0, "gerak": False}
    try:
        import qse_saya as SY
        k = SY._kline("BTCUSDT", "240", 8)
        p24 = k[-1][3] / k[-7][3] - 1
    except Exception:
        p24 = 0.0
    cocok = "long_menumpuk" if oi24 >= o["q90"] and p24 > 0 else "short_menumpuk" if oi24 >= o["q90"] and p24 < 0 else \
        "oi_rontok" if oi24 <= o["q10"] else None
    if not cocok:
        rows[0] += " Normal, tidak ada penumpukan posisi."
        return {"rows": rows, "arah": 0, "gerak": False}
    v = o["hasil"][cocok]
    p = v["periode"]
    rows.append(f"{'✅' if v['arah'] or v['gerak'] else '➖'} Pola {NAMA_OI[cocok]}. Sejarah 24 jam kemudian: BTC naik di {p[0]['naik']}% dan "
                f"{p[1]['naik']}% kasus (biasanya {p[0]['base_naik']}% dan {p[1]['base_naik']}%), gerak lebih dari 3% di "
                f"{p[0]['gerak3']}% dan {p[1]['gerak3']}% (biasanya {p[0]['base_gerak3']}% dan {p[1]['base_gerak3']}%)."
                + ("" if v["arah"] or v["gerak"] else " Tidak konsisten, info saja."))
    if v["gerak"]:
        rows.append("⚠️ Peluang gerak besar 24 jam lebih tinggi dari biasa. Pasang SL, jangan tambah posisi melawan arah.")
    return {"rows": rows, "arah": v["arah"], "gerak": v["gerak"]}


def _sim_1j(hi_, lo_, cl_, s, e, sl0, risk, tp, tra, atr, maks, interval, k):
    """Satu trade di candle 1 jam. interval None = aturan jalur saja. Return R atau None kalau belum selesai."""
    import qse_slsaran as SLS
    sl, best, hw = sl0, e, 0
    arah = "LONG" if s == 1 else "SHORT"
    for n in range(len(cl_)):
        hi, lo = hi_[n], lo_[n]
        if (lo <= sl) if s == 1 else (hi >= sl):
            return (sl - e) * s / risk
        if tp and ((hi >= tp) if s == 1 else (lo <= tp)):
            return (tp - e) * s / risk
        best = max(best, hi) if s == 1 else min(best, lo)
        if tra and n % 4 == 3:
            sl = max(sl, best - tra * atr) if s == 1 else min(sl, best + tra * atr)
        if interval:
            lvl = int(((best - e) * s / e * 100) // interval)
            if lvl > hw:
                hw = lvl
                nsl = SLS.saran_sl(e, arah, lvl, dict(k, interval=interval))
                sl = max(sl, nsl) if s == 1 else min(sl, nsl)
        if n >= maks:
            return (cl_[n] - e) * s / risk
    return None


def uji_slsaran():
    """Bandingkan aturan jalur dengan saran SL (interval 1, 2, 3, 5%) di sinyal robot sendiri 180 hari terakhir, data 1 jam.
    Aktif otomatis hanya kalau total R dan PF saran SL lebih tinggi dari aturan jalur, minimal 150 trade."""
    import qse_catat as CT
    import qse_slsaran as SLS
    import bybit_fetch as B
    k = SLS.konfig(baku=True)
    batas = time.time() - 180 * 86400
    trades = []
    for _, _, c in CT._tutup_terbukti():
        sl0 = c.get("sl0") or (c.get("sl") if c.get("tp") else None)
        if c.get("t", 0) >= batas and c.get("entry") and sl0 and c.get("arah") in ("LONG", "SHORT"):
            trades.append((c, sl0))
    hasil = {"dasar": []}
    hasil.update({iv: [] for iv in INTERVAL_SL})
    cache = {}
    for c, sl0 in trades:
        sym = c["sym"]
        if sym not in cache:
            try:
                cache[sym] = B._raw(sym, "60", int((time.time() - batas) / 3600) + 300)
            except Exception:
                cache[sym] = None
        h = cache[sym]
        if h is None or not len(h):
            continue
        x = h[h.index > int(c["t"] * 1000) - 3600 * 1000]
        if len(x) < 5:
            continue
        s = 1 if c["arah"] == "LONG" else -1
        e = float(c["entry"])
        risk = abs(e - sl0)
        if risk <= 0:
            continue
        tp = c.get("tp")
        tra = None if tp else (c.get("trail_atr") or 3.0)
        atr = risk / (c.get("sl_atr") or 2.0)
        maks = int(c.get("maks_bar") or 60) * 4
        hi_, lo_, cl_ = x["high"].values.astype(float), x["low"].values.astype(float), x["close"].values.astype(float)
        R0 = _sim_1j(hi_, lo_, cl_, s, e, sl0, risk, tp, tra, atr, maks, None, k)
        if R0 is None:
            continue
        hasil["dasar"].append(R0 - BIAYA * e / risk)
        for iv in INTERVAL_SL:
            R1 = _sim_1j(hi_, lo_, cl_, s, e, sl0, risk, tp, tra, atr, maks, iv, k)
            hasil[iv].append((R1 if R1 is not None else R0) - BIAYA * e / risk)
    dasar = hasil["dasar"]
    n = len(dasar)
    terbaik = None
    for iv in INTERVAL_SL:
        r = hasil[iv]
        if n >= 150 and sum(r) >= sum(dasar) and _pf(r) >= _pf(dasar) and (terbaik is None or sum(r) > sum(hasil[terbaik])):
            terbaik = iv
    out = dict(t=int(time.time()), n=n, total_dasar=round(sum(dasar), 1), pf_dasar=round(_pf(dasar), 2),
               hasil={str(iv): dict(total=round(sum(hasil[iv]), 1), pf=round(_pf(hasil[iv]), 2),
                                    wr=round(float(np.mean(np.array(hasil[iv]) > 0) * 100), 0) if n else 0.0) for iv in INTERVAL_SL},
               aktif=terbaik is not None, interval=terbaik)
    with open(os.path.join(LAB, "slsaran_auto.json"), "w") as f:
        json.dump(out, f)
    return out


def bulanan():
    os.makedirs(LAB, exist_ok=True)
    rows = ["🗓 <b>QSE v148 | LAB BULANAN</b>"]
    try:
        r = uji_slsaran()
        if r["n"] < 150:
            rows.append(f"📶 Saran pindah SL belum bisa diuji di sinyal live: baru {r['n']} sinyal robot selesai dalam 180 hari, "
                        "butuh 150. Tetap MATI. Uji 2021-2026 di 12 ribu sinyal: saran SL tiap 1% memotong total profit 55-78%.")
        else:
            detil = ", ".join(f"tiap {iv:g}% {r['hasil'][str(iv)]['total']:+.1f}R PF {r['hasil'][str(iv)]['pf']}" for iv in INTERVAL_SL)
            rows.append(f"📶 Saran pindah SL diuji di {r['n']} sinyal robot 180 hari terakhir. Aturan jalur {r['total_dasar']:+.1f}R "
                        f"(PF {r['pf_dasar']}). Saran SL: {detil}. "
                        + (f"AKTIF otomatis bulan ini dengan jarak {r['interval']:g}%." if r["aktif"]
                           else "Tetap MATI karena belum lebih untung dari aturan jalur."))
    except Exception as ex:
        rows.append(f"📶 Uji saran SL gagal: {html.escape(str(ex))}")
    try:
        o = uji_oi()
        if o:
            for k, v in o["hasil"].items():
                p = v["periode"]
                rows.append(f"📊 {NAMA_OI[k]}: 24 jam kemudian BTC naik {p[0]['naik']}% dan {p[1]['naik']}% kasus (biasanya "
                            f"{p[0]['base_naik']}% dan {p[1]['base_naik']}%), gerak lebih dari 3% {p[0]['gerak3']}% dan {p[1]['gerak3']}% "
                            f"(biasanya {p[0]['base_gerak3']}% dan {p[1]['base_gerak3']}%). "
                            + ("Konsisten, dipakai di /cek BTC." if v["arah"] or v["gerak"] else "Tidak konsisten, info saja."))
        else:
            rows.append("📊 Data open interest belum cukup untuk diuji.")
    except Exception as ex:
        rows.append(f"📊 Uji open interest gagal: {html.escape(str(ex))}")
    _kirim("\n\n".join(rows))
    return rows


if __name__ == "__main__":
    perintah = sys.argv[1] if len(sys.argv) > 1 else "status"
    os.makedirs(LAB, exist_ok=True)
    try:
        if perintah == "riset":
            riset()
        elif perintah == "sinyal":
            sinyal()
        elif perintah == "bulanan":
            bulanan()
        else:
            print(status_teks())
    except Exception as ex:
        import traceback
        traceback.print_exc()
        _log("gagal:", perintah, ex)
        sys.exit(1)
