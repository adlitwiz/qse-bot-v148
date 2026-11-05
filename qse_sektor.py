"""QSE v150 - SINYAL PELENGKAP: PEMIMPIN-PENGIKUT SEKTOR 4J (kantong kedua, tidak memakan slot v150).
Aturan sama dengan backtest riset/upgrade/run_v154.py dan run_v156.py (data Binance 2022-2026, biaya 0.15% harga):
  1. Candle 4J tutup: di satu sektor (peta riset/orderblock/sektor.py), koin dengan gerak candle terbesar searah naik
     (atau turun) minimal 8% dan volume minimal 3x rata 20 candle = PEMIMPIN.
  2. Koin lain di sektor itu yang di candle yang sama baru bergerak kurang dari 1.5% = calon PENGIKUT.
  3. Dalam 2 candle 4J berikutnya: pengikut menutup di atas high 20 candle (SHORT: di bawah low 20 candle) dengan volume minimal 1.5x.
     Masuk MARKET di open candle sesudahnya. SL 1.5 x rata rentang 14 candle 4J. SL harus 0.4% sampai 8% dari entry.
  4. Keluar aturan v150: TPawal 20% di +0.5R lalu SL ke entry, trailing 3 x rata rentang 4J tiap 4 jam,
     jam ke-12 belum TPawal dan rugi 0.5R tutup (rugi kurang dari itu: SL ke -0.5R), 30 jam belum TPawal tutup.
  5. Kantong sendiri: maksimal 2 posisi, satu posisi per koin, lot 0.5x, jeda 24 jam setelah 3 rugi beruntun.
Hasil kantong (lot 0.5x) bersama v150: 2023-2024 +8.2R, 2025-2026 +26.7R. v150 2025-2026 +93R jadi +121R, bulan rugi tetap 4 dari 22,
PF gabungan 1.46. Kantong sendiri 2025-2026: 170 trade, 1.8 per minggu, WR 62%.
Pengaman turun kasta otomatis (10 trade terakhir jelek jadi kertas) sudah diuji dan TIDAK dipakai: memotong 2025-2026 dari +26.7R ke +7.7R."""
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

FILE = os.path.join(STATE_DIR, "sektor.json")
H1, H4 = 3600 * 1000, 4 * 3600 * 1000
LEAD, VOL_LEAD, DIAM, VOL_IKUT, N_HI = 0.08, 3.0, 0.015, 1.5, 20
SL_K, TRAIL_K, TPS_LV, TPS_POR, BE_LV, JAM_K, JAM_STOP, MAKS_JAM = 1.5, 3.0, 0.5, 0.2, 0.5, 12, 30, 240
MAKS_BUKA, LOT, JEDA_RUGI, JEDA_JAM = 2, 0.5, 3, 24
TOP_KOIN = 150
BIAYA = 0.0015
SEKTOR = {}
for _sec, _cs in {"L1": "ADA ALGO APT ATOM AVAX BCH CELO CFX CKB DOT EGLD ETC HBAR ICP ICX IOTA KAVA KSM LTC MINA NEAR NEO ONE ONT QTUM ROSE SEI SOL SUI TRX VET XLM XRP XTZ ZIL DASH RVN ZEC TIA INJ",
                  "L2": "ARB OP IMX LRC SKL STX", "DEFI": "1INCH AAVE COMP CRV DYDX GMX JUP KNC LDO PENDLE SNX SUSHI UNI YFI ZRX RUNE ENA WOO UMA",
                  "ORACLE": "API3 BAND LINK PYTH TRB GRT", "MEME": "1000BONK 1000FLOKI 1000PEPE 1000SHIB DOGE WIF BONK FLOKI PEPE SHIB",
                  "AI": "FET WLD NMR ARPA IOTX", "GAME": "ALICE APE AXS ENJ GALA GMT MANA SAND HOOK CHZ THETA", "DEPIN": "AR FIL STORJ ANKR JASMY"}.items():
    for _c in _cs.split():
        SEKTOR[_c + "USDT"] = _sec
BT = ("Binance 2022-2026, kantong 2 posisi lot 0.5x bersama v150: 2023-2024 +8.2R, 2025-2026 +26.7R, "
      "bulan rugi v150 tetap 4 dari 22, WR 62%, sekitar 1.8 sinyal per minggu")


def _kosong():
    return {"open": {}, "closed": [], "t4": 0}


def _ubah(fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(FILE) as f:
                d = json.load(f)
        except Exception:
            d = _kosong()
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
        return _kosong()


def rentang14(h, l):
    """Rata rentang 14 candle (high - low), sama dengan at4 di backtest."""
    return pd.Series(np.asarray(h) - np.asarray(l)).rolling(14).mean().values


def cari(c4):
    """c4: {sym: DataFrame 4J tutup (open, high, low, close, volume), index ms, urut}. Candle terakhir = candle tembus pengikut.
    Pemimpin boleh di 1 atau 2 candle sebelumnya (backtest: pengikut diberi 2 candle untuk menembus, sinyal di tembusan pertama).
    Return list dict(sym, arah, risk, at4, pemimpin, sektor, gerak)."""
    grup = {}
    for s, df in c4.items():
        if s in SEKTOR and df is not None and len(df) >= N_HI + 4:
            grup.setdefault(SEKTOR[s], []).append(s)
    A = {s: {k: c4[s][k].values.astype(float) for k in ("open", "high", "low", "close", "volume")} for ks in grup.values() for s in ks}

    def ret_vr(s, q):
        x = A[s]; va = x["volume"][q - 20:q].mean()
        return x["close"][q] / x["open"][q] - 1, (x["volume"][q] / va if va > 0 else 0.0)

    def tembus(s, q2, d):
        x = A[s]; va = x["volume"][q2 - 20:q2].mean()
        t_ = x["close"][q2] > x["high"][q2 - N_HI:q2].max() if d == 1 else x["close"][q2] < x["low"][q2 - N_HI:q2].min()
        return bool(t_ and va > 0 and x["volume"][q2] >= VOL_IKUT * va)
    out = []; sudah = set()
    for sec, ks in grup.items():
        t_akhir = {s: int(c4[s].index[-1]) for s in ks}
        t_ref = max(set(t_akhir.values()), key=list(t_akhir.values()).count)
        ks = [s for s in ks if t_akhir[s] == t_ref]                # hanya koin dengan candle di waktu yang sama
        if len(ks) < 3:
            continue
        n = min(len(A[s]["close"]) for s in ks)
        for lag in (1, 2):
            info = {s: ret_vr(s, len(A[s]["close"]) - 1 - lag) for s in ks}
            for d in (1, -1):
                ld = max(ks, key=lambda s: info[s][0] * d)
                if not (info[ld][0] * d >= LEAD and info[ld][1] >= VOL_LEAD):
                    continue
                for s in ks:
                    if s == ld or (s, d) in sudah or not abs(info[s][0]) < DIAM:
                        continue
                    m = len(A[s]["close"])
                    if lag == 2 and tembus(s, m - 2, d):
                        continue                                    # sudah tembus di candle sebelumnya, sinyal saat itu
                    if tembus(s, m - 1, d):
                        at = rentang14(A[s]["high"], A[s]["low"])[m - 1]
                        if np.isfinite(at):
                            sudah.add((s, d))
                            out.append(dict(sym=s, arah="LONG" if d == 1 else "SHORT", at4=float(at), risk=SL_K * float(at),
                                            pemimpin=ld, sektor=sec, gerak=info[ld][0] * 100))
    return out


def simulasi(e, d, risk, at4, h, l, c):
    """Aturan keluar v150 di candle 1J sejak entry (sama dengan sim3 backtest). Return (selesai, R kotor, jam, sl_sekarang, aman)."""
    sl = e - d * risk; best = e; sisa = 1.0; real = 0.0; tpsd = False; aman = False
    lvp = e + d * TPS_LV * risk; lvb = e + d * BE_LV * risk
    n = min(len(c), MAKS_JAM)
    for j in range(n):
        hi, lo = h[j], l[j]
        if (d == 1 and lo <= sl) or (d == -1 and hi >= sl):
            return True, real + sisa * (sl - e) * d / risk, j + 1, sl, aman
        if not tpsd and ((d == 1 and hi >= lvp) or (d == -1 and lo <= lvp)):
            real += TPS_POR * TPS_LV; sisa = 1.0 - TPS_POR; tpsd = True
            if (d == 1 and e > sl) or (d == -1 and e < sl):
                sl = e                                   # TPawal kena: SL ke entry (sl_aft 0 di backtest)
            aman = True
        if tpsd and not aman and ((d == 1 and hi >= lvb) or (d == -1 and lo <= lvb)):
            if (d == 1 and e > sl) or (d == -1 and e < sl):
                sl = e
            aman = True
        best = max(best, hi) if d == 1 else min(best, lo)
        if j % 4 == 3:
            nsl = best - d * TRAIL_K * at4
            if (d == 1 and nsl > sl) or (d == -1 and nsl < sl):
                sl = nsl
        if not tpsd and j + 1 == JAM_K:
            rn = (c[j] - e) * d / risk
            if rn <= -0.5:
                return True, real + sisa * rn, j + 1, sl, aman
            if rn < 0:
                nsl = e - d * 0.5 * risk
                if (d == 1 and nsl > sl) or (d == -1 and nsl < sl):
                    sl = nsl
        if not tpsd and j + 1 == JAM_STOP:
            return True, real + sisa * (c[j] - e) * d / risk, j + 1, sl, aman
    if n >= MAKS_JAM:
        return True, real + sisa * (c[n - 1] - e) * d / risk, n, sl, aman
    return False, real + sisa * ((c[n - 1] - e) * d / risk if n else 0.0), n, sl, aman


def _k(sym, iv, bars):
    try:
        df = B._raw(sym, iv, bars)
        now = int(time.time() * 1000)
        return df[df.index + (H4 if iv == "240" else H1) <= now]
    except Exception as ex:
        print(f"[WARN] sektor {sym}: {ex}")
        return None


def _jeda(closed):
    """Jeda 24 jam setelah 3 rugi beruntun (sama dengan backtest kantong). Return alasan atau ''."""
    rs = sorted([c for c in closed if c.get("R") is not None], key=lambda c: c.get("selesai", 0))
    k = 0
    for c in rs:
        k = k + 1 if c["R"] <= 0 else 0
    if k >= JEDA_RUGI and time.time() - rs[-1].get("selesai", 0) < JEDA_JAM * 3600:
        return f"{k} rugi beruntun, jeda {JEDA_JAM} jam"
    return ""


def _catat_ledger(it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur="sektor", sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"],
                                tp1=0.0, tp2=0.0, t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"],
                                selesai=time.time(), ket="pelengkap lot 0.5x"))
    CT._ubah(f)


def _kelola():
    """Hitung ulang tiap posisi dari candle 1J sejak entry. Return pesan selesai."""
    d = lihat(); out = []; hasil = {}
    for key, it in d["open"].items():
        df = _k(it["sym"], "60", 260)
        if df is None:
            continue
        df = df[df.index >= it["t_bar"]]
        if not len(df):
            continue
        dd = 1 if it["arah"] == "LONG" else -1
        sel, R, jam, sl, aman = simulasi(it["entry"], dd, it["risk"], it["at4"], df["high"].values, df["low"].values, df["close"].values)
        hasil[key] = (sel, R - BIAYA * it["entry"] / it["risk"], jam, sl, aman)

    def simpan(dd):
        for key, (sel, R, jam, sl, aman) in hasil.items():
            if key not in dd["open"]:
                continue
            it = dd["open"][key]
            it.update(sl=sl, jam=jam, aman=aman, R_kini=round(R, 2))
            if sel:
                dd["open"].pop(key)
                dd["closed"].append(dict(it, R=round(R, 2), selesai=time.time()))
    _ubah(simpan)
    for key, (sel, R, jam, sl, aman) in hasil.items():
        if sel:
            it = d["open"][key]
            _catat_ledger(it, R)
            out.append(f"{'✅' if R > 0 else '🛑'} <b>PELENGKAP SEKTOR SELESAI  ·  {it['sym']} {it['arah']}  ·  {R * LOT:+.2f}R (lot {LOT}x)</b>\n"
                       f"Ditutup aturan v150 setelah {jam} jam. Kalau posisi Kamu masih terbuka, tutup sekarang.")
    return out


def _kartu(no, it, tick):
    L = it["arah"] == "LONG"; t = tick
    e, sl = it["entry"], it["sl0"]; pc = it["risk"] / e * 100
    try:
        import qse_saya as SY
        blok = SY.blok_salin(e, sl, order="MARKET", tick=t, catatan_tp="tanpa, pakai SL berjalan", sym=it["sym"], arah=it["arah"], sebagian=True)
        garis = SY.GARIS
    except Exception:
        blok = f"<pre>{it['sym']} {it['arah']}\nEntry  {TG.fp(e, t)} MARKET\nSL     {TG.fp(sl, t)}</pre>"
        garis = "━━━━━━━━━━━━━━━━━━"
    try:
        import qse_modal as MD
        lot = MD.baris_lot(e, sl, LOT)
    except Exception:
        lot = ""
    return "\n".join([
        garis,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  🧩 SINYAL PELENGKAP Sektor 4J",
        f"✅ <b>BISA DIIKUTI</b>  ·  kantong kedua, tidak memakan slot v150  ·  lot <b>{LOT}x lot normal</b>",
        garis,
        blok,
        "💡 <b>Kenapa</b>",
        f"• {it['pemimpin']} (pemimpin sektor {it['sektor']}) bergerak {it['gerak']:+.1f}% dalam satu candle 4J dengan volume minimal 3x rata-rata",
        f"• {it['sym']} di sektor yang sama belum ikut bergerak, lalu candle ini menembus {'high' if L else 'low'} 20 candle dengan volume minimal 1.5x",
        f"• Bukti: {BT}",
        "🛠 <b>Cara</b>",
        f"1. Masuk MARKET sekarang. SL di {TG.fp(sl, t)} ({pc:.1f}% dari entry). TP sebagian 20% di baris TPawal, setelah kena SL ke entry",
        f"2. Sisa posisi pakai SL berjalan: tiap 4 jam SL digeser ke harga terbaik {'dikurangi' if L else 'ditambah'} {TRAIL_K:g} x rentang 4J "
        f"({TG.fp(TRAIL_K * it['at4'], t)})",
        "3. Jam ke-12 belum kena TPawal dan rugi 0.5R: tutup. Rugi kurang dari itu: SL ke -0.5R. 30 jam belum kena TPawal: tutup market",
        f"4. Kantong pelengkap maksimal {MAKS_BUKA} posisi. Robot mengabari saat posisi selesai",
        *([lot] if lot else []),
    ])


def _jalankan(baru_ok=True):
    out = _kelola()
    import qse_catat as CT
    if CT.mati("sektor"):
        _ALASAN[0] = "jalur dihentikan karena hasil live jelek"
        return out
    d = lihat()
    slot = MAKS_BUKA - len(d["open"])
    jd = _jeda(d["closed"])
    if slot <= 0 or not baru_ok or jd:
        _ALASAN[0] = "kantong penuh" if slot <= 0 else (jd or "robot telat, hanya kelola posisi")
        return out
    try:
        tk = B.get_tickers(); tick = B.get_symbols()
    except Exception as ex:
        print("[WARN] sektor tickers", ex)
        return out
    koin = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick][:TOP_KOIN]
    koin = [s for s in koin if s in SEKTOR]
    with ThreadPoolExecutor(8) as ex:
        c4 = dict(zip(koin, ex.map(lambda s: _k(s, "240", 60), koin)))
    if not c4:
        return out
    t_akhir = max(int(df.index[-1]) for df in c4.values() if df is not None and len(df))
    if time.time() * 1000 - (t_akhir + H4) > 1800000:
        _ALASAN[0] = "robot telat lebih dari 30 menit dari tutup candle"
        return out
    sig = cari({s: df for s, df in c4.items() if df is not None and len(df) and int(df.index[-1]) == t_akhir})
    buka = {it["sym"] for it in d["open"].values()}
    sig = [x for x in sig if x["sym"] not in buka]
    baru = []
    for x in sig:
        if len(baru) >= slot:
            break
        px = tk[x["sym"]]["last"] or float(c4[x["sym"]]["close"].iloc[-1])
        if not (0.004 * px <= x["risk"] <= 0.08 * px):
            continue
        dd = 1 if x["arah"] == "LONG" else -1
        sl = px - dd * x["risk"]
        it = dict(x, entry=px, sl=sl, sl0=sl, t=time.time(), t_bar=t_akhir + H4, tick=tick.get(x["sym"], 0.0001), jam=0, aman=False)
        baru.append(it); buka.add(x["sym"])
        out.append(_kartu(len(baru), it, it["tick"]))
    if baru:
        def simpan(dd):
            for it in baru:
                dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
        _ubah(simpan)
    else:
        _ALASAN[0] = "tidak ada pemimpin sektor yang memicu" if not sig else "SL di luar 0.4% sampai 8%"
    return out


_ALASAN = [""]


def jalankan(baru_ok=True):
    """Dipanggil listener sekali tiap candle 4J tutup."""
    _ALASAN[0] = ""
    out = _jalankan(baru_ok)
    n = sum(1 for m in out if "BISA DIIKUTI" in m)

    def f(d):
        d["cek"] = dict(t=time.time(), n=n, why=_ALASAN[0] or ("" if n else "tidak ada koin yang lolos"))
    try:
        _ubah(f)
    except Exception as ex:
        print("[WARN] sektor catat cek", ex)
    return out


def status_singkat():
    d = lihat(); c = d.get("cek")
    cek = (f"dicek {time.strftime('%H:%M', time.gmtime(c['t'] + 7 * 3600))} WIB: {c['n']} sinyal baru"
           + (f", {c['why']}" if c.get("why") and not c["n"] else "")) if c else "belum pernah dicek"
    return f"🧩 Kantong pelengkap {len(d['open'])}/{MAKS_BUKA}  ·  {cek}"


def teks():
    d = lihat()
    rows = [f"<b>🧩 Sinyal Pelengkap: Pemimpin-Pengikut Sektor 4J</b>\nLot {LOT}x, maksimal {MAKS_BUKA} posisi, tidak memakan slot v150.\nBacktest: {BT}"]
    if d["open"]:
        rows.append(f"\nPosisi berjalan ({len(d['open'])}):")
        for it in d["open"].values():
            rows.append(f"{'🟢' if it['arah'] == 'LONG' else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])} | {it.get('R_kini', 0):+.2f}R | jam {it.get('jam', 0)}")
    else:
        rows.append("\nBelum ada posisi berjalan.")
    rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
    if rs:
        w = sum(x for x in rs if x > 0); lo = -sum(x for x in rs if x < 0)
        rows.append(f"\nSelesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | PF {w / lo if lo > 0 else 9.99:.2f} | "
                    f"total {sum(rs):+.1f}R (lot penuh) = {sum(rs) * LOT:+.1f}R di lot {LOT}x")
    jd = _jeda(d["closed"])
    if jd:
        rows.append(f"⏸ {jd}")
    return "\n".join(rows)
