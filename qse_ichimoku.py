"""QSE v148 - JALUR ICHIMOKU TREN (TK cross di luar awan + trailing stop), candle 4J.
Backtest 30 koin likuid 2022-2026, entry open candle berikutnya, biaya 0.15% pulang pergi:
4843 trade, WR 38%, PF 1.33, rata +0.15R. 2022-2024 PF 1.35, 2025-2026 PF 1.29, tiap tahun PF 1.13 sampai 1.56.
Aturan (sama dengan backtest dan Pine "QSE Ichimoku TK Awan Trail"):
  LONG : close di atas awan dan Tenkan memotong Kijun ke atas. SHORT kebalikannya.
  SL awal 2 ATR dari entry. Tiap candle 4J tutup: cek SL kena dulu, lalu SL digeser ke puncak - 3 ATR (tidak pernah mundur).
  Tutup paksa setelah 60 candle 4J (10 hari). Satu posisi per koin."""
import fcntl
import json
import os
import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import bybit_fetch as B
import telegram_notify as TG
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "ichimoku.json")
H4 = 4 * 3600 * 1000
SL_ATR, TRAIL_ATR, MAKS_BAR = 2.0, 3.0, 60
TOP_KOIN = 150          # koin paling likuid yang dipantau (backtest memakai koin likuid)
MAKS_BARU = 5           # sinyal baru paling banyak per candle 4J
MAKS_BUKA = 8           # posisi jalur ini paling banyak terbuka bersamaan
BIAYA = 0.0015
BT = "4843 trade, WR 38%, PF 1.33, rata +0.15R (2022-2026)"


def _ubah(fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(FILE) as f:
                d = json.load(f)
        except Exception:
            d = {"open": {}, "closed": [], "t4": 0}
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
        return {"open": {}, "closed": [], "t4": 0}


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.full(len(c), np.nan)
    if len(c) > n:
        a[n - 1] = tr[:n].mean()                     # seperti ta.atr Pine: awal SMA lalu RMA
        for i in range(n, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def _hh(x, n):
    return pd.Series(x).rolling(n).max().values


def _ll(x, n):
    return pd.Series(x).rolling(n).min().values


def _sinyal(df):
    """Sinyal di candle tutup terakhir. Return (arah atau None, atr)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    if len(c) < 120:
        return None, np.nan
    tk = (_hh(h, 9) + _ll(l, 9)) / 2
    kj = (_hh(h, 26) + _ll(l, 26)) / 2
    sa = np.r_[np.full(26, np.nan), ((tk + kj) / 2)[:-26]]
    sb = np.r_[np.full(26, np.nan), ((_hh(h, 52) + _ll(l, 52)) / 2)[:-26]]
    a = _atr(h, l, c)
    i = len(c) - 1
    if np.isnan(sa[i]) or np.isnan(sb[i]) or np.isnan(a[i]):
        return None, np.nan
    if c[i] > max(sa[i], sb[i]) and tk[i] > kj[i] and tk[i - 1] <= kj[i - 1]:
        return "LONG", float(a[i])
    if c[i] < min(sa[i], sb[i]) and tk[i] < kj[i] and tk[i - 1] >= kj[i - 1]:
        return "SHORT", float(a[i])
    return None, float(a[i])


def _k4(sym, bars=300):
    """Candle 4J yang sudah tutup, index ms."""
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] ichimoku {sym}: {ex}")
        return None


def _kelola(it, df):
    """Jalankan aturan keluar di candle tutup sejak update terakhir. Return (status, R atau None, sl_lama)."""
    L = it["arah"] == "LONG"
    e, risk = it["entry"], it["risk"]
    a = _atr(df["high"].values, df["low"].values, df["close"].values)
    sl_lama = it["sl"]
    idx = list(df.index)
    for k, ts in enumerate(idx):
        if ts <= it["last"]:
            continue
        h, l, c = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        if (l <= it["sl"]) if L else (h >= it["sl"]):
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk, sl_lama
        it["bar"] += 1
        if L:
            it["best"] = max(it["best"], h)
            if not np.isnan(a[k]):
                it["sl"] = max(it["sl"], it["best"] - TRAIL_ATR * a[k])
        else:
            it["best"] = min(it["best"], l)
            if not np.isnan(a[k]):
                it["sl"] = min(it["sl"], it["best"] + TRAIL_ATR * a[k])
        it["last"] = int(ts)
        it["close"] = c
        if it["bar"] >= MAKS_BAR:
            return "WAKTU", ((c - e) if L else (e - c)) / risk - BIAYA * e / risk, sl_lama
    return "BUKA", None, sl_lama


def _catat_ledger(it, R):
    """Masukkan hasil ke catatan /jalur."""
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur="ichimoku", sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"],
                                tp1=0.0, tp2=0.0, t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"],
                                selesai=time.time(), ket="trailing"))
    CT._ubah(f)


def jalankan(baru_ok=True):
    """Dipanggil listener sekali tiap candle 4J tutup. baru_ok False = hanya kelola posisi (listener telat jalan).
    Return daftar pesan."""
    import qse_catat as CT
    d = lihat()
    out = []
    tick = {}
    try:
        tick = B.get_symbols()
    except Exception:
        pass
    # 1. kelola posisi terbuka
    buka = dict(d["open"])
    hasil = {}
    for key, it in buka.items():
        df = _k4(it["sym"], 200)
        if df is None or not len(df):
            continue
        it = dict(it)
        st, R, sl_lama = _kelola(it, df)
        hasil[key] = (it, st, R, sl_lama)
    for key, (it, st, R, sl_lama) in hasil.items():
        t = tick.get(it["sym"], it.get("tick", 0.0001))
        if st in ("SL", "WAKTU"):
            _catat_ledger(it, R)
            out.append(f"{'✅' if R > 0 else '🛑'} <b>ICHIMOKU SELESAI {it['sym']} {it['arah']}</b> | {R:+.2f}R\n"
                       + ("Kena trailing SL" if st == "SL" else f"Tutup paksa, sudah {MAKS_BAR} candle 4J. Tutup posisi di harga sekarang")
                       + f". Entry {TG.fp(it['entry'], t)}, keluar sekitar {TG.fp(it['sl'] if st == 'SL' else it['close'], t)}.")
        elif abs(it["sl"] - sl_lama) >= 0.25 * it["risk"]:
            L = it["arah"] == "LONG"
            kunci = ((it["sl"] - it["entry"]) if L else (it["entry"] - it["sl"])) / it["risk"]
            out.append(f"🔁 <b>ICHIMOKU {it['sym']} {it['arah']}</b> geser SL ke <code>{TG.fp(it['sl'], t)}</code> "
                       f"(dari {TG.fp(sl_lama, t)}). Profit terkunci {kunci:+.2f}R. Candle ke {it['bar']}/{MAKS_BAR}.")

    def simpan_kelola(dd):
        for key, (it, st, R, _) in hasil.items():
            if key not in dd["open"]:
                continue
            if st in ("SL", "WAKTU"):
                dd["open"].pop(key)
                dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
            else:
                dd["open"][key] = it
    _ubah(simpan_kelola)

    # 2. sinyal baru
    if CT.mati("ichimoku"):
        out.append("⛔ Jalur Ichimoku sedang dihentikan karena hasil live-nya jelek. Cek /jalur.")
        return out
    d = lihat()
    slot = min(MAKS_BARU, MAKS_BUKA - len(d["open"]))
    if slot <= 0 or not baru_ok:
        return out
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    koin = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]
    tutup_kini = {it["sym"] for it, st, _, _ in hasil.values() if st in ("SL", "WAKTU")}
    koin = [s for s in koin if s not in {it["sym"] for it in d["open"].values()} and s not in tutup_kini]   # sama backtest

    def cek(sym):
        df = _k4(sym, 300)
        if df is None or len(df) < 120:
            return sym, None, None, None
        arah, a = _sinyal(df)
        return sym, arah, a, df
    with ThreadPoolExecutor(8) as ex:
        hasil_s = [x for x in ex.map(cek, koin) if x[1]]
    now = time.time()
    baru = []
    for sym, arah, a, df in hasil_s[:slot]:          # sudah urut dari koin paling likuid
        px = tk[sym]["last"] or float(df["close"].iloc[-1])
        L = arah == "LONG"
        risk = SL_ATR * a
        sl = px - risk if L else px + risk
        t = tick.get(sym, 0.0001)
        it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=risk, best=px, bar=0, t=now,
                  last=int(df.index[-1]), close=px, tick=t)
        baru.append(it)
        try:
            import qse_modal as MD
            lot = MD.baris_lot(px, sl)
        except Exception:
            lot = ""
        out.append(f"{'🟢' if L else '🔴'} <b>ICHIMOKU {arah} {sym}</b> (Tenkan potong Kijun {'di atas' if L else 'di bawah'} awan, 4J)\n"
                   f"<pre>MARKET {TG.fp(px, t)}\nSL     {TG.fp(sl, t)}  -1.00R  -{risk / px * 100:.1f}%\nTP     tidak ada, SL digeser tiap candle 4J</pre>\n"
                   + (f"{lot}\n" if lot else "")
                   + f"↳ Masuk sekarang. Jangan pasang TP. Aku kirim posisi SL baru tiap candle 4J, tutup paksa setelah 10 hari.\n"
                   f"↳ Backtest: {BT}. WR rendah itu wajar, untungnya dari sedikit trade yang lari jauh.")

    def simpan_baru(dd):
        for it in baru:
            dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
    if baru:
        _ubah(simpan_baru)
    return out


def teks():
    d = lihat()
    rows = [f"<b>Jalur Ichimoku tren 4J</b>\nBacktest: {BT}"]
    if d["open"]:
        rows.append(f"\nPosisi berjalan ({len(d['open'])}):")
        for it in d["open"].values():
            L = it["arah"] == "LONG"
            g = ((it["close"] - it["entry"]) if L else (it["entry"] - it["close"])) / it["risk"]
            rows.append(f"{'🟢' if L else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])} | sekarang {g:+.2f}R | candle {it['bar']}/{MAKS_BAR}")
    else:
        rows.append("\nBelum ada posisi berjalan.")
    rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
    if rs:
        w = sum(x for x in rs if x > 0)
        lo = -sum(x for x in rs if x < 0)
        rows.append(f"\nSelesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                    f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
    return "\n".join(rows)
