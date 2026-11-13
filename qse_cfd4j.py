"""QC 95 📝 CFD 4J MODE CATAT. Kandidat tipis: RSI 50 + Volume di emas dan perak 4J, TP 1.5R, maks 48 candle 1 jam, SL 2 ATR.
TIDAK dikirim ke grup. Robot hanya mencatat sinyal dan hasilnya (trade kertas) supaya terbukti live dulu 1-2 bulan.

Riset run_v199_cfd_mesin.py, v199b_balik, v199c_cek (riset/cfd/hasil_v199_cfd_mesin.txt): 8 mesin bot di 19 instrumen CFD, 4 skema keluar,
arah asli dan dibalik = 128 kombinasi. Satu lolos: RSI 50 + Volume emas, TP 1.5R maks 48 jam.
  Emas PAXG: latih 2020-2024 PF 1.30 (115 trade), uji 2025-Okt 2026 PF 1.37 (44), 12 bulan PF 1.13, 6 bulan PF 1.47.
  Data XAU Yahoo: Jun 2024-Okt 2025 PF 1.37, Nov 2025-Nov 2026 PF 6.29. Perak: PF 3.87 lalu 1.22. Sampel kecil.
Rumus sinyal sama dengan qse_strat.sinyal rsi_vol: volume candle masuk 20% tertinggi dari 100 candle, RSI 14 melewati 50,
harga dan EMA 50 di sisi yang sama dari EMA 200. Candle 4J UTC dari data 1 jam Yahoo (GC=F, SI=F), grup 4 candle penuh.
Saklar QSE_CFD4J=0 mati."""
import json
import os
import time

import numpy as np

STATE_DIR = os.environ.get("QSE_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"))
PATH = os.path.join(STATE_DIR, "cfd4j.json")
INST = [("XAU", "GC=F", "EMAS"), ("XAG", "SI=F", "PERAK")]
BIAYA = {"XAU": 0.0002, "XAG": 0.0004}
SWAP = 0.00015
SL_ATR, TP_R, MAKS = 2.0, 1.5, 48
H4, JAM = 14400000, 3600000
JEDA = 1800


def hidup():
    return os.environ.get("QSE_CFD4J", "1") != "0"


def _baca():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {"akhir": {}, "buka": [], "tutup": [], "coba": 0}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PATH + ".tmp", PATH)


def ke4j(t, o, h, l, c, v):
    """Candle 1 jam (t ms awal candle) -> candle 4J UTC penuh (4 candle). Return T, O, H, L, C, V dan k1 (indeks 1 jam pertama sesudah tutup)."""
    g = t // H4 * H4
    T, O, Hh, Ll, C, V = [], [], [], [], [], []
    i = 0
    n = len(t)
    while i < n:
        j = i
        while j < n and g[j] == g[i]:
            j += 1
        if j - i == 4:
            T.append(g[i]); O.append(o[i]); Hh.append(h[i:j].max()); Ll.append(l[i:j].min()); C.append(c[j - 1]); V.append(v[i:j].sum())
        i = j
    T = np.array(T, dtype=float)
    k1 = np.searchsorted(t, T + H4)
    return T, np.array(O), np.array(Hh), np.array(Ll), np.array(C), np.array(V), k1


def sinyal(C, H, L, V, i, ind=None):
    """Arah sinyal RSI 50 + Volume di candle 4J i (1 LONG, -1 SHORT, 0 tidak ada). Rumus qse_strat.sinyal / run_v173_ev.proses."""
    import qse_strat as ST
    if i < 260:
        return 0, 0.0
    if ind is None:
        ind = indikator(C, H, L)
    e50, e200, r, a = ind
    vp = (V[i - 100:i] <= V[i]).mean() * 100
    if vp < 80:
        return 0, float(a[i])
    if r[i] > 50 and r[i - 1] <= 50 and C[i] > e200[i] and e50[i] > e200[i]:
        return 1, float(a[i])
    if r[i] < 50 and r[i - 1] >= 50 and C[i] < e200[i] and e50[i] < e200[i]:
        return -1, float(a[i])
    return 0, float(a[i])


def indikator(C, H, L):
    import qse_strat as ST
    return ST._ema(C, 50), ST._ema(C, 200), ST._rsi(C), ST._atr(H, L, C)


def kelola(p, t, h, l, c, sampai):
    """Jalankan trade kertas p di candle 1 jam p['k'] .. sampai-1 (yang sudah tutup). Urutan sama dengan v173_sim.sim:
    SL dulu, lalu TP, tutup di close candle ke-48 sesudah masuk. Return R (selesai) atau None (masih jalan)."""
    d, e, risk = p["d"], p["e"], p["risk"]
    stop, tp = e - d * risk, e + d * TP_R * risk
    k0 = p["k0"]
    last = k0 + MAKS
    j = p["k"]
    while j < sampai and j < len(c):
        if (d > 0 and l[j] <= stop) or (d < 0 and h[j] >= stop):
            return _bersih(p, -1.0, t[j] - t[k0])
        if (h[j] - e) * d / risk >= TP_R if d > 0 else (e - l[j]) / risk >= TP_R:
            return _bersih(p, TP_R, t[j] - t[k0])
        if j >= last:
            return _bersih(p, (c[j] - e) * d / risk, t[j] - t[k0])
        j += 1
    p["k"] = j
    return None


def _bersih(p, R, lama):
    jam = lama / JAM
    return R - (BIAYA[p["kode"]] + SWAP * (jam // 24)) * p["e"] / p["risk"]


def jalankan_data(d, kode, t, o, h, l, c, v, now_ms, awal=False):
    """Proses satu instrumen: kelola trade kertas, lalu cari sinyal di candle 4J baru yang sudah tutup. Return jumlah sinyal baru."""
    T, O, Hh, Ll, C, V, k1 = ke4j(t, o, h, l, c, v)
    if len(T) < 270:
        return 0
    sampai = int(np.searchsorted(t, now_ms - JAM, side="right"))          # candle 1 jam yang sudah tutup
    for p in [x for x in d["buka"] if x["kode"] == kode]:
        k = int(np.searchsorted(t, p["t1"]))          # indeks dihitung ulang dari waktu, karena jendela data Yahoo bergeser
        p["k0"] = k
        p["k"] = max(k, int(np.searchsorted(t, p.get("t_k", p["t1"]))))
        R = kelola(p, t, h, l, c, sampai)
        if R is not None:
            d["buka"].remove(p)
            d["tutup"].append(dict(kode=kode, d=p["d"], t=p["t"], R=round(float(R), 3)))
            d["tutup"] = d["tutup"][-500:]
        else:
            p["t_k"] = float(t[p["k"]]) if p["k"] < len(t) else float(t[-1]) + JAM
    akhir = d["akhir"].get(kode)
    tutup4 = [i for i in range(len(T)) if T[i] + H4 <= now_ms and k1[i] < len(t) and t[k1[i]] == T[i] + H4]
    if akhir is None or awal:
        d["akhir"][kode] = float(T[tutup4[-1]]) if tutup4 else 0.0
        return 0
    ind = indikator(C, Hh, Ll)
    n = 0
    for i in tutup4:
        if T[i] <= akhir:
            continue
        ar, a = sinyal(C, Hh, Ll, V, i, ind)
        d["akhir"][kode] = float(T[i])
        if ar and a > 0 and 0.001 <= SL_ATR * a / C[i] <= 0.10:
            p = dict(kode=kode, d=ar, t=float(T[i]), t1=float(t[k1[i]]), e=float(C[i]), risk=float(SL_ATR * a))
            k = int(k1[i]); p["k0"] = k; p["k"] = k
            R = kelola(p, t, h, l, c, sampai)
            if R is not None:
                d["tutup"].append(dict(kode=kode, d=ar, t=p["t"], R=round(float(R), 3)))
            else:
                p["t_k"] = float(t[p["k"]]) if p["k"] < len(t) else float(t[-1]) + JAM
                d["buka"].append(p)
            n += 1
            print(f"[CFD4J catat] {kode} {'LONG' if ar > 0 else 'SHORT'} {C[i]}", flush=True)
    return n


def ambil1j(ysym):
    import requests
    r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{ysym}", params={"interval": "1h", "range": "180d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    j = r.json()["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    rows = [(ts, o, h, l, c, v or 0) for ts, o, h, l, c, v in zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
            if None not in (o, h, l, c)]
    a = np.array(rows, dtype=float)
    a[:, 0] = (a[:, 0] // 3600) * 3600 * 1000
    a = a[np.argsort(a[:, 0])]
    a = a[np.r_[True, np.diff(a[:, 0]) > 0]]
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]


def cek(now=None, data=None):
    """Dipanggil tiap menit, ambil data tiap 30 menit. Tidak mengirim pesan apa pun."""
    if not hidup():
        return 0
    now = now or time.time()
    d = _baca()
    if data is None and now - d.get("coba", 0) < JEDA:
        return 0
    d["coba"] = now
    n = 0
    for kode, ysym, _ in INST:
        try:
            arr = data[kode] if data is not None else ambil1j(ysym)
            n += jalankan_data(d, kode, *arr, now_ms=now * 1000)
        except Exception as ex:
            print("[WARN] cfd4j", kode, ex)
    _tulis(d)
    return n


def rapor():
    d = _baca()
    t = d.get("tutup", [])
    rows = ["📝 <b>CFD 4J MODE CATAT</b> (RSI 50 + Volume emas dan perak, TP 1.5R, tidak dikirim ke grup)"]
    if t:
        r = [x["R"] for x in t]
        g = sum(x for x in r if x > 0); k = -sum(x for x in r if x < 0)
        rows.append(f"Catatan live: {len(r)} trade kertas, WR {sum(1 for x in r if x > 0) / len(r) * 100:.0f}%, "
                    f"PF {g / k if k else 99:.2f}, total {sum(r):+.2f}R")
    else:
        rows.append("Catatan live: belum ada trade kertas selesai.")
    if d.get("buka"):
        rows.append(f"Trade kertas jalan: {len(d['buka'])}")
    rows.append("Dipasang ke grup kalau 1-2 bulan catatan live PF di atas 1.3. Uji: PF 1.13-1.47.")
    return "\n".join(rows)
