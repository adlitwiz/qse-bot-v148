"""QSE v148 - SCAN MOMENTUM 15 DAN 30 MENIT (dipanggil listener tiap 15 menit).
Koin yang dipantau: rapor 4J A/B dari scan terakhir dan koin yang sedang kamu pegang.
Tanda awal pump atau dump: candle tutup terakhir dengan volume minimal 3 kali median 50 candle, badan candle
minimal 1,2 ATR, dan menembus high atau low 20 candle.
Seperti Golden Zone Hunter, momentum hanya dikirim sebagai SARAN kalau lolos penilaian semua aspek
(bias 4J searah wajib, tren 1 jam, BTC 15 menit, volume, jarak ke entry), lengkap dengan entry, SL, TP.
Momentum di koin yang sedang kamu pegang tetap dikabarkan sebagai info posisi. Tiap koin paling sering sekali per 2 jam."""
import json
import os
import time
import numpy as np
import requests
from config import STATE_DIR, BYBIT_URL

FILE = os.path.join(STATE_DIR, "momentum.json")
MIN_SKOR = 65


def _kline(sym, iv, limit=80):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/kline", timeout=10,
                         params={"category": "linear", "symbol": sym, "interval": iv, "limit": limit})
        rows = sorted(r.json()["result"]["list"], key=lambda x: int(x[0]))
        return np.array([[float(v) for v in x[1:6]] for x in rows[:-1]])      # buang candle berjalan
    except Exception:
        return None


def _hist(sym, iv, halaman=3):
    """Sejarah candle tutup (maks 1000 x halaman) untuk backtest. Return array o,h,l,c,v urut waktu."""
    rows, end = {}, None
    for _ in range(halaman):
        try:
            p = {"category": "linear", "symbol": sym, "interval": iv, "limit": 1000}
            if end:
                p["end"] = end
            lst = requests.get(BYBIT_URL + "/v5/market/kline", params=p, timeout=15).json()["result"]["list"]
        except Exception:
            break
        if not lst:
            break
        for x in lst:
            rows[int(x[0])] = [float(v) for v in x[1:6]]
        end = min(int(x[0]) for x in lst) - 1
        if len(lst) < 1000:
            break
    if not rows:
        return None
    ks = sorted(rows)
    return np.array([rows[k] for k in ks[:-1]])           # buang candle berjalan


BERLAKU = {"15": 8, "30": 4}          # LIMIT berlaku 2 jam
TAHAN = {"15": 96, "30": 48}          # posisi paling lama 24 jam, lalu ditutup di harga pasar
PER1J = {"15": 4, "30": 2}


def _bt(k, iv):
    """Backtest aturan momentum yang sama di sejarah koin ini: candle momentum, tren 1 jam searah, LIMIT di retest
    berlaku 2 jam, TP1 tutup separuh lalu SL ke entry, TP2. Kalau satu candle kena SL dan TP, dihitung SL dulu.
    Bias 4J dan BTC tidak ikut diuji (datanya tidak tersedia per candle). Return dict n, wr, pf, avg."""
    if k is None or len(k) < 200:
        return dict(n=0, wr=0.0, pf=0.0, avg=0.0)
    o, h, l, c, v = k.T
    s = PER1J[iv]
    hasil = []
    t = 55
    n = len(c)
    while t < n - 2:
        m = _cek(k[t - 79:t + 1] if t >= 79 else k[:t + 1])
        if not m:
            t += 1
            continue
        L = m["arah"] == "NAIK"
        c1 = c[max(0, t - 40 * s):t + 1][::-1][::s][::-1]          # close 1 jam (tiap s candle)
        if len(c1) >= 25 and (c1[-1] > _ema(c1, 20)) != L:
            t += 1
            continue
        rc = _rencana(m)
        e, sl, t1, t2 = rc["entry"], rc["sl"], rc["tp1"], rc["tp2"]
        isi = None
        for j in range(t + 1, min(n, t + 1 + BERLAKU[iv])):
            if (L and h[j] >= t1) or ((not L) and l[j] <= t1):
                break                                          # harga lari tanpa retest, saran batal
            if (L and l[j] <= e) or ((not L) and h[j] >= e):
                isi = j
                break
        if isi is None:
            t += BERLAKU[iv]
            continue
        r, tp1 = None, False
        akhir = min(n, isi + TAHAN[iv])
        for j in range(isi, akhir):
            kena_sl = (l[j] <= (e if tp1 else sl)) if L else (h[j] >= (e if tp1 else sl))
            if kena_sl:
                r = 0.5 if tp1 else -1.0
                break
            if not tp1 and ((L and h[j] >= t1) or ((not L) and l[j] <= t1)):
                tp1 = True
            if tp1 and ((L and h[j] >= t2) or ((not L) and l[j] <= t2)):
                r = 1.5
                break
        if r is None:
            j = akhir - 1
            gerak = ((c[j] - e) if L else (e - c[j])) / abs(e - sl)
            r = (0.5 + 0.5 * gerak) if tp1 else gerak
        hasil.append(r - 0.08)                               # biaya fee dan slippage kira kira 0.08R
        t = j + 1
    if not hasil:
        return dict(n=0, wr=0.0, pf=0.0, avg=0.0)
    a = np.array(hasil)
    pos, neg = a[a > 0].sum(), -a[a < 0].sum()
    return dict(n=int(len(a)), wr=float((a > 0).mean() * 100), pf=float(pos / neg) if neg > 0 else 9.99,
                avg=float(a.mean()))


def _bt_koin(sym, iv, st):
    """Backtest per koin, disimpan 12 jam supaya tidak mengambil data berulang."""
    bt = st.setdefault("bt", {})
    kunci = f"{sym}|{iv}"
    lama = bt.get(kunci)
    if lama and time.time() - lama["t"] < 43200:
        return lama
    b = dict(_bt(_hist(sym, iv), iv), t=time.time())
    bt[kunci] = b
    return b


def uji(simbol, maks=20):
    """Perintah /ujimomentum: backtest momentum di koin rapor A/B, TF 15 dan 30 menit. Return teks."""
    gab = {"15": [], "30": []}
    rows = []
    for sym in list(simbol)[:maks]:
        for iv in ("15", "30"):
            k = _hist(sym, iv, 2)
            b = _bt(k, iv)
            if b["n"]:
                gab[iv].append(b)
                if iv == "15":
                    rows.append(f"{sym}: {b['n']}x | WR {b['wr']:.0f}% | PF {b['pf']:.2f} | rata {b['avg']:+.2f}R")
    out = []
    for iv, nama in (("15", "15 menit"), ("30", "30 menit")):
        lst = gab[iv]
        n = sum(b["n"] for b in lst)
        if not n:
            out.append(f"{nama}: belum ada kejadian")
            continue
        avg = sum(b["avg"] * b["n"] for b in lst) / n
        wr = sum(b["wr"] * b["n"] for b in lst) / n
        lolos = sum(1 for b in lst if b["n"] >= 8 and b["pf"] >= 1.2)
        out.append(f"<b>{nama}</b>: {n} trade di {len(lst)} koin | WR {wr:.0f}% | rata {avg:+.2f}R per trade | "
                   f"koin yang lolos syarat kirim (8x, PF 1.2) {lolos}")
    return ("Backtest aturan momentum di sejarah sekitar 3 minggu (15 menit) dan 6 minggu (30 menit). "
            "Sudah dipotong biaya 0.08R per trade.\n\n" + "\n".join(out)
            + ("\n\nPer koin (15 menit):\n" + "\n".join(rows[:15]) if rows else "")
            + "\n\nSaran momentum hanya dikirim di koin yang backtest-nya minimal 8 kejadian dengan PF minimal 1.2.")


def _ema(x, n):
    k, e = 2 / (n + 1), x[0]
    for y in x[1:]:
        e = y * k + e * (1 - k)
    return e


def _cek(k):
    if k is None or len(k) < 55:
        return None
    o, h, l, c, v = k.T
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = tr[-15:-1].mean()
    vol_x = v[-1] / max(np.median(v[-51:-1]), 1e-12)
    badan = abs(c[-1] - o[-1])
    if atr <= 0 or vol_x < 3 or badan < 1.2 * atr:
        return None
    base = dict(pct=(c[-1] / o[-1] - 1) * 100, vol=vol_x, ema=_ema(c, 20), atr=atr, close=c[-1],
                hi=h[-1], lo=l[-1])
    if c[-1] > h[-21:-1].max():
        return dict(base, arah="NAIK", level=h[-21:-1].max())
    if c[-1] < l[-21:-1].min():
        return dict(base, arah="TURUN", level=l[-21:-1].min())
    return None


def _fp(x, tick):
    if not tick or tick <= 0:
        return f"{x:.6g}"
    d = max(0, int(round(-np.log10(tick))))
    return f"{round(x / tick) * tick:.{d}f}"


def _rencana(m):
    """Entry LIMIT di retest level yang ditembus atau EMA20 (yang lebih dekat ke harga), SL di balik candle momentum."""
    L = m["arah"] == "NAIK"
    a, c = m["atr"], m["close"]
    e = max(m["level"], m["ema"]) if L else min(m["level"], m["ema"])
    if (L and e >= c) or ((not L) and e <= c):
        e = c - 0.5 * a if L else c + 0.5 * a
    sl0 = (min(m["lo"], e - a) - 0.2 * a) if L else (max(m["hi"], e + a) + 0.2 * a)
    dist = min(max(abs(e - sl0), 1.0 * a), 2.5 * a)
    sl = e - dist if L else e + dist
    return dict(arah="LONG" if L else "SHORT", entry=e, sl=sl, tp1=e + dist if L else e - dist,
                tp2=e + 2 * dist if L else e - 2 * dist, dist=dist)


def _nilai(sym, m, rc, info, btc15):
    """Skor 0-100 dan alasan. Bias 4J searah wajib, selain itu skor minimal MIN_SKOR."""
    L = rc["arah"] == "LONG"
    plus, minus, sk = [], [], 0
    i = info.get(sym) or {}
    if i.get("bias") != rc["arah"]:
        return 0, plus, ["bias 4J tidak searah"]
    sk += 30
    plus.append(f"bias 4J {rc['arah']} searah")
    sk += 10 if i.get("rapor") == "A" else 5
    plus.append(f"rapor robot {i.get('rapor', '-')}")
    k1 = _kline(sym, "60", 40)
    if k1 is not None and len(k1) >= 25:
        e1 = _ema(k1[:, 3], 20)
        if (k1[-1, 3] > e1) == L:
            sk += 20
            plus.append("tren 1 jam searah")
        else:
            minus.append("tren 1 jam belum searah")
    if (L and btc15 >= 0.15) or ((not L) and btc15 <= -0.15):
        sk += 15
        plus.append(f"BTC 45 menit {btc15:+.2f}% searah")
    elif abs(btc15) < 0.15:
        sk += 7
        plus.append("BTC tenang")
    else:
        minus.append(f"BTC 45 menit {btc15:+.2f}% melawan")
    if m["vol"] >= 4:
        sk += 10
        plus.append(f"volume {m['vol']:.1f}x")
    jarak = abs(m["close"] - rc["entry"]) / m["atr"]
    if jarak <= 1.5:
        sk += 15
        plus.append(f"entry dekat ({jarak:.1f} ATR)")
    else:
        minus.append(f"entry jauh ({jarak:.1f} ATR), peluang terisi kecil")
    return sk, plus, minus


def scan(daftar, bias, posisi, info=None):
    """daftar = simbol, bias = {sym: 'LONG'/'SHORT'}, posisi = {sym: arah posisi kamu},
    info = {sym: dict(rapor, tick)}. Return pesan."""
    info = info or {}
    info = {s: dict(info.get(s) or {}, bias=bias.get(s)) for s in set(info) | set(bias)}
    try:
        with open(FILE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    now = time.time()
    out = []
    st.setdefault("bt", {})
    b15 = _kline("BTCUSDT", "15", 10)
    btc15 = (b15[-1, 3] / b15[-4, 3] - 1) * 100 if b15 is not None and len(b15) >= 4 else 0.0
    for sym in daftar:
        if not isinstance(st.get(sym, 0), (int, float)) or now - st.get(sym, 0) < 7200:
            continue
        for iv, nama in (("15", "15 menit"), ("30", "30 menit")):
            m = _cek(_kline(sym, iv))
            if not m:
                continue
            st[sym] = now
            rc = _rencana(m)
            tick = (info.get(sym) or {}).get("tick")
            judul = (f"⚡ <b>{sym} {m['arah']} TAJAM</b> di candle {nama}: {m['pct']:+.1f}%, volume {m['vol']:.1f}x, "
                     f"tembus {'high' if m['arah'] == 'NAIK' else 'low'} 20 candle")
            if sym in posisi:
                lawan = (posisi[sym] == "LONG") != (m["arah"] == "NAIK")
                out.append(judul + ("\n↳ Posisi kamu searah, pertimbangkan geser SL ke entry." if not lawan else
                                    "\n↳ Posisi kamu BERLAWANAN, pertimbangkan kurangi risiko sekarang."))
                break
            sk, plus, minus = _nilai(sym, m, rc, info, btc15)
            if sk < MIN_SKOR:
                print(f"[MOMENTUM] {sym} {m['arah']} {nama} tidak dikirim, skor {sk}: {'; '.join(minus)}")
                break
            bt = _bt_koin(sym, iv, st)
            if bt["n"] < 8 or bt["pf"] < 1.2:
                print(f"[MOMENTUM] {sym} {nama} tidak dikirim, backtest {bt['n']}x PF {bt['pf']:.2f}")
                break
            plus.append(f"backtest koin ini {bt['n']}x, WR {bt['wr']:.0f}%, PF {bt['pf']:.2f}, rata {bt['avg']:+.2f}R")
            import qse_catat as CT
            if CT.mati("momentum"):
                print(f"[MOMENTUM] {sym} tidak dikirim, jalur momentum sedang dihentikan karena hasil live jelek")
                break
            CT.tambah("momentum", sym, rc["arah"], rc["entry"], rc["sl"], rc["tp1"], rc["tp2"], 2.0, f"skor {sk}, {nama}")
            e, sl, t1, t2 = rc["entry"], rc["sl"], rc["tp1"], rc["tp2"]
            pc = lambda x: abs(x - e) / e * 100
            batas = time.strftime("%d/%m %H:%M WIB", time.gmtime(now + 7200 + 7 * 3600))
            out.append(
                judul + f"\n{'🟢' if rc['arah'] == 'LONG' else '🔴'} <b>SARAN {rc['arah']} {sym}</b> | skor {sk}/100, "
                + ("LAYAK BANGET DIIKUTI" if sk >= 80 else "LAYAK DIIKUTI")
                + f"\n<pre>LIMIT {_fp(e, tick)}\nSL    {_fp(sl, tick)}  -1.00R  -{pc(sl):.1f}%\n"
                f"TP1   {_fp(t1, tick)}  +1.00R  +{pc(t1):.1f}%\nTP2   {_fp(t2, tick)}  +2.00R  +{pc(t2):.1f}%</pre>\n"
                f"Yang bikin yakin: {'; '.join(plus)}\n"
                + (f"Yang perlu diwaspadai: {'; '.join(minus)}\n" if minus else "")
                + f"Jangan kejar harga. Pasang LIMIT di retest {_fp(e, tick)}, berlaku sampai {batas}. "
                f"Kalau belum terisi, batalkan. Pakai setengah lot karena ini sinyal TF kecil.")
            break
    with open(FILE + ".tmp", "w") as f:
        simpan = {k: v for k, v in st.items() if k != "bt" and now - v < 86400}
        simpan["bt"] = {k: v for k, v in (st.get("bt") or {}).items() if now - v["t"] < 43200}
        json.dump(simpan, f)
    os.replace(FILE + ".tmp", FILE)
    return out
