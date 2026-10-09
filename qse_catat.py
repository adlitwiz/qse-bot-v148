"""QSE v148 - CATATAN HASIL LIVE jalur tambahan: momentum, news searah engine, news mandiri.
Tiap saran dicatat saat dikirim, lalu dicek tiap 15 menit dengan candle 15 menit Bybit memakai aturan yang sama
dengan backtest: LIMIT harus tersentuh dalam masa berlaku, TP1 tutup separuh lalu SL ke entry, TP2 selesai,
satu candle kena SL dan TP dihitung SL dulu, posisi ditutup paksa setelah 24 jam. Biaya 0.08R per trade.
Jalur yang sudah 15 trade dengan PF di bawah 1 otomatis berhenti mengirim saran sampai hasilnya membaik."""
import fcntl
import json
import os
import time
import requests
from config import STATE_DIR, BYBIT_URL

FILE = os.path.join(STATE_DIR, "catat_jalur.json")
NAMA = {"momentum": "Momentum 15/30 menit", "news_searah": "News searah engine", "news_mandiri": "News mandiri (sejarah kuat)"}
BIAYA = 0.08
TAHAN_JAM = 24
MIN_N, MIN_PF = 15, 1.0


def _ubah(fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(FILE) as f:
                d = json.load(f)
        except Exception:
            d = {"open": [], "closed": []}
        hasil = fn(d)
        d["closed"] = d["closed"][-2000:]
        with open(FILE + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(FILE + ".tmp", FILE)
        return hasil


def _baca():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {"open": [], "closed": []}


def tambah(jalur, sym, arah, entry, sl, tp1, tp2, berlaku_jam=2.0, ket=""):
    """Catat saran baru. arah LONG/SHORT. Saran yang sama (jalur, koin, arah) yang masih terbuka tidak dicatat dua kali."""
    now = time.time()

    def f(d):
        for it in d["open"]:
            if it["jalur"] == jalur and it["sym"] == sym and it["arah"] == arah:
                return False
        d["open"].append(dict(jalur=jalur, sym=sym, arah=arah, entry=float(entry), sl=float(sl), tp1=float(tp1),
                              tp2=float(tp2), t=now, sampai=now + berlaku_jam * 3600, status="MENUNGGU", ket=ket[:120]))
        return True
    return _ubah(f)


def _k15(sym, mulai_ms):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/kline", timeout=15,
                         params={"category": "linear", "symbol": sym, "interval": "15", "start": int(mulai_ms), "limit": 1000})
        rows = sorted(r.json()["result"]["list"], key=lambda x: int(x[0]))
        return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in rows[:-1]]   # hanya candle tutup
    except Exception:
        return None


def _nilai(it, k):
    """Jalankan ulang saran di candle 15 menit sejak dicatat. Return (status, R atau None, t_isi)."""
    L = it["arah"] == "LONG"
    e, sl, t1, t2 = it["entry"], it["sl"], it["tp1"], it["tp2"]
    risk = abs(e - sl) or 1e-12
    isi, tp1 = None, False
    for ts, h, l, c in k:
        t = ts / 1000
        if isi is None:
            if t >= it["sampai"]:
                return "BATAL", None, None
            if (L and h >= t1) or ((not L) and l <= t1):
                return "BATAL", None, None          # harga lari tanpa menyentuh entry
            if (L and l <= e) or ((not L) and h >= e):
                isi = t
            else:
                continue
        stop = e if tp1 else sl
        if (L and l <= stop) or ((not L) and h >= stop):
            return "SELESAI", (0.5 if tp1 else -1.0) - BIAYA, isi
        if not tp1 and ((L and h >= t1) or ((not L) and l <= t1)):
            tp1 = True
        if tp1 and ((L and h >= t2) or ((not L) and l <= t2)):
            return "SELESAI", 1.5 - BIAYA, isi
        if t - isi >= TAHAN_JAM * 3600:
            g = ((c - e) if L else (e - c)) / risk
            return "SELESAI", (0.5 + 0.5 * g if tp1 else g) - BIAYA, isi
    if isi is None:
        return "MENUNGGU", None, None
    return ("TP1" if tp1 else "TERISI"), None, isi


def cek():
    """Dipanggil listener tiap 15 menit. Return pesan hasil yang baru selesai."""
    d = _baca()
    if not d["open"]:
        return []
    hasil = {}
    for i, it in enumerate(d["open"]):
        k = _k15(it["sym"], it["t"] * 1000 - 15 * 60000)
        if k is None:
            continue
        k = [x for x in k if x[0] / 1000 + 900 > it["t"]]     # candle yang tutup setelah saran dicatat
        hasil[(it["jalur"], it["sym"], it["arah"], it["t"])] = _nilai(it, k)
    pesan = []

    def f(dd):
        tetap = []
        for it in dd["open"]:
            r = hasil.get((it["jalur"], it["sym"], it["arah"], it["t"]))
            if not r:
                tetap.append(it)
                continue
            st, R, isi = r
            if st == "BATAL":
                dd["closed"].append(dict(it, status="BATAL", R=None, selesai=time.time()))
                continue
            if st == "SELESAI":
                dd["closed"].append(dict(it, status="SELESAI", R=round(R, 2), isi=isi, selesai=time.time()))
                pesan.append(f"{'✅' if R > 0 else '🛑'} {NAMA.get(it['jalur'], it['jalur'])} | {it['sym']} {it['arah']} "
                             f"entry {it['entry']:.6g} selesai {R:+.2f}R")
                continue
            it["status"] = st
            tetap.append(it)
        dd["open"] = tetap
    _ubah(f)
    return pesan


def statistik(jalur):
    rs = [it["R"] for it in _baca()["closed"] if it["jalur"] == jalur and it.get("status") == "SELESAI"]
    n = len(rs)
    if not n:
        return dict(n=0, wr=0.0, pf=0.0, avg=0.0, net=0.0)
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    return dict(n=n, wr=sum(r > 0 for r in rs) / n * 100, pf=pos / neg if neg > 0 else 9.99, avg=sum(rs) / n, net=sum(rs))


def mati(jalur):
    s = statistik(jalur)
    return s["n"] >= MIN_N and s["pf"] < MIN_PF


def teks():
    d = _baca()
    rows = ["Hasil live jalur tambahan (dihitung otomatis dari candle 15 menit, sudah dipotong biaya 0.08R):"]
    for j, nama in NAMA.items():
        s = statistik(j)
        buka = sum(1 for it in d["open"] if it["jalur"] == j)
        batal = sum(1 for it in d["closed"] if it["jalur"] == j and it.get("status") == "BATAL")
        if s["n"]:
            rows.append(f"{'⛔' if mati(j) else '✅'} {nama}: {s['n']} trade | WR {s['wr']:.0f}% | PF {s['pf']:.2f} | "
                        f"rata {s['avg']:+.2f}R | total {s['net']:+.1f}R | berjalan {buka} | tidak terisi {batal}")
        else:
            rows.append(f"⚪ {nama}: belum ada trade selesai | berjalan {buka} | tidak terisi {batal}")
    rows.append(f"Jalur dengan minimal {MIN_N} trade dan PF di bawah {MIN_PF:g} otomatis berhenti mengirim saran.")
    return "\n".join(rows)
