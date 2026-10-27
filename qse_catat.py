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
NAMA = {"momentum": "Momentum 15/30 menit", "news_searah": "News searah engine", "news_mandiri": "News mandiri (sejarah kuat)",
        "ichimoku": "Ichimoku tren 4J (trailing)",
        "orderblock": "Order Block + Volume 4J", "gzh": "GZH SHORT, TP 2R penuh",
        "ema_short": "EMA Cross 20/50 SHORT 4J (trailing)", "rsi_vol": "RSI 50 + Volume 4J (trailing)",
        "mcginley": "McGinley 34 + Volume 4J (TP 3R)",
        "GZH": "GZH Golden Zone 4J (trailing)", "snr_vol": "SnR Pantul + Volume 4J (TP 3R)",
        "msb_hpz": "MSB LuxAlgo HPZ 4J (trailing)", "smc_choch": "SMC CHoCH 4J (TP 3R)"}
BIAYA = 0.08
TAHAN_JAM = 24
TAHAN_JALUR = {"gzh": 240}          # GZH diuji dengan tahan maksimal 10 hari
MIN_N, MIN_PF = 15, 1.0
MIN_N_JALUR = {"ichimoku": 40, "orderblock": 40, "gzh": 30, "ema_short": 40, "rsi_vol": 40, "mcginley": 40, "GZH": 40, "snr_vol": 40, "msb_hpz": 40, "smc_choch": 40}     # jalur tren WR rendah butuh sampel lebih banyak sebelum dinilai


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
    r1, r2 = abs(t1 - e) / risk, abs(t2 - e) / risk          # momentum dan news: 1R dan 2R, GZH: 2R dan 2R
    tahan = TAHAN_JALUR.get(it.get("jalur"), TAHAN_JAM)
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
            return "SELESAI", (0.5 * r1 if tp1 else -1.0) - BIAYA, isi
        if not tp1 and ((L and h >= t1) or ((not L) and l <= t1)):
            tp1 = True
        if tp1 and ((L and h >= t2) or ((not L) and l <= t2)):
            return "SELESAI", 0.5 * r1 + 0.5 * r2 - BIAYA, isi
        if t - isi >= tahan * 3600:
            g = ((c - e) if L else (e - c)) / risk
            return "SELESAI", (0.5 * r1 + 0.5 * g if tp1 else g) - BIAYA, isi
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


TERBUKTI = {"ichimoku", "orderblock", "ema_short", "rsi_vol", "mcginley", "GZH", "gzh", "snr_vol", "msb_hpz", "smc_choch"}


def mati(jalur):
    """Matikan otomatis hanya untuk jalur percobaan. Jalur terbukti tidak dimatikan dari hasil live pendek:
    uji 2021-2026, jendela 40 trade berturut-turut jalur terbukti PF di bawah 1 terjadi 31-55% waktu, bahkan 300 trade
    10-32%. Pengaman jalur terbukti adalah rem portofolio (lot setengah), yang sudah diuji."""
    if jalur in TERBUKTI:
        return False
    s = statistik(jalur)
    return s["n"] >= MIN_N_JALUR.get(jalur, MIN_N) and s["pf"] < MIN_PF


def _tutup_terbukti():
    """Semua posisi robot jalur terbukti yang sudah selesai. Return list (kunci, nama, item)."""
    out = []
    try:
        import qse_ichimoku as IC
        out += [("ichimoku", "Ichimoku", c) for c in IC.lihat().get("closed", [])]
    except Exception:
        pass
    try:
        import qse_ob as OB
        out += [("orderblock", "Order Block + Volume", c) for c in OB.lihat().get("closed", [])]
    except Exception:
        pass
    try:
        import qse_strat as ST
        for k, cfg in ST.STRAT.items():
            out += [(k, cfg["nama"], c) for c in ST.lihat(k).get("closed", [])]
    except Exception:
        pass
    return [z for z in out if z[2].get("R") is not None]


# rata-rata hasil per trade di uji 2021-2026 (R, sudah biaya), pembanding hasil live
EXP_UJI = {"orderblock": 0.18, "snr_vol": 0.18, "mcginley": 0.17, "rsi_vol": 0.16, "ichimoku": 0.13, "ema_short": 0.11,
           "smc_choch": 0.10, "msb_hpz": 0.09, "GZH": 0.07}


def _baris(nama, rs, exp=None):
    s_ = dict(n=len(rs))
    if not rs:
        return f"⚪ {nama}: belum ada trade selesai"
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    pf = pos / neg if neg > 0 else 9.99
    avg = sum(rs) / len(rs)
    if len(rs) < 100:
        nilai = "sampel kecil, belum bisa dinilai"
        ik = "⚪"
    elif exp is not None and avg < exp - 0.10:
        nilai = f"di bawah uji ({exp:+.2f}R)"
        ik = "🟠"
    else:
        nilai = "sesuai uji" + (f" ({exp:+.2f}R)" if exp is not None else "")
        ik = "🟢"
    return (f"{ik} {nama}: {s_['n']} trade, WR {sum(r > 0 for r in rs) / len(rs) * 100:.0f}%, PF {pf:.2f}, "
            f"rata {avg:+.2f}R, total {sum(rs):+.1f}R  ·  {nilai}")


def teks():
    """/jalur: hasil live semua jalur terbukti dan semua label, dibanding hasil uji, plus 30 hari terakhir."""
    data = _tutup_terbukti()
    now = time.time()
    rows = ["Hasil live robot (posisi yang dicatat robot sendiri, sudah biaya). Pembanding: rata-rata per trade di uji 2021-2026.",
            "Penilaian baru berarti setelah 100 trade: di uji, 40 trade berturut-turut PF di bawah 1 terjadi 31-55% waktu walau jalurnya untung.",
            "", "📊 <b>PER TEKNIK</b> (semua waktu)"]
    urut = sorted({(k, n) for k, n, _ in data} | {(k, None) for k in EXP_UJI}, key=lambda z: -EXP_UJI.get(z[0], 0))
    sudah = set()
    for k, _ in urut:
        if k in sudah:
            continue
        sudah.add(k)
        nama = next((n for kk, n, _ in data if kk == k), None)
        if nama is None:
            try:
                import qse_strat as ST
                nama = ST.STRAT.get(k, {}).get("nama") or {"ichimoku": "Ichimoku", "orderblock": "Order Block + Volume"}.get(k, k)
            except Exception:
                nama = k
        rows.append(_baris(nama, [c["R"] for kk, _, c in data if kk == k], EXP_UJI.get(k)))
    lab = [("👑 COMBO RAJA", lambda c: c.get("combo_raja"), 0.73),
           ("💎 COMBO FIX PROFIT", lambda c: c.get("combo_fix") and not c.get("combo_raja"), 0.33),
           ("🏆 COMBO EMAS", lambda c: c.get("combo_emas") and not c.get("combo_fix"), 0.21),
           ("⭐ COMBO lain", lambda c: c.get("combo") and not c.get("combo_emas") and not c.get("combo_fix"), 0.12),
           ("💎 MUTU TINGGI", lambda c: len(c.get("mutu_plus") or []) >= 3, 0.18),
           ("🔁 PULLBACK McGinley", lambda c: c.get("pullback"), 0.24),
           ("🔊 VOLUME PASAR TINGGI", lambda c: c.get("vol_tinggi"), 0.30),
           ("📉 BTC.D TURUN (SHORT)", lambda c: c.get("dom_turun"), 0.23),
           ("Tanpa label", lambda c: not (c.get("combo") or len(c.get("mutu_plus") or []) >= 3 or c.get("pullback")), 0.11)]
    rows += ["", "🏷 <b>PER LABEL</b> (label dicatat sejak 20 Okt 2026)"]
    for nm, fn, ex in lab:
        rows.append(_baris(nm, [c["R"] for _, _, c in data if fn(c)], ex))
    try:
        import qse_strat as ST
        sk = lambda k, c: ST.prioritas(k, c)[0]
        rows += ["", "🎖 <b>PER NILAI</b> (dicatat sejak 23 Okt 2026)"]
        for nm, lo, hi, ex in (("👑 NILAI 10", 8, 99, 0.50), ("🔥 NILAI 9", 5, 7, 0.29), ("✅ NILAI 8", 3, 4, 0.14)):
            rows.append(_baris(nm, [c["R"] for k, _, c in data if lo <= sk(k, c) <= hi], ex))
    except Exception as ex_:
        print("[WARN] jalur per nilai", ex_)
    b30 = [c["R"] for _, _, c in data if now - c.get("selesai", 0) <= 30 * 86400]
    rows += ["", "🗓 <b>30 HARI TERAKHIR</b>", _baris("Semua jalur", b30, 0.13)]
    try:
        import qse_porto as PO
        rm = PO.rem()
        rows.append("🛡 Rem portofolio: " + (f"AKTIF, lot setengah ({rm})" if rm else "tidak aktif, lot normal" if PO.REM_LOT else
                                            "mati, diganti batas 5 posisi per orang (uji 2021-2026: rasio profit/drawdown 3.6 jadi 11.1)"))
    except Exception:
        pass
    rows.append("Jalur terbukti tidak dimatikan otomatis dari hasil live pendek. Pengaman yang dipakai: batas 5 posisi per orang "
                "dan risiko tetap per trade.")
    return "\n".join(rows)