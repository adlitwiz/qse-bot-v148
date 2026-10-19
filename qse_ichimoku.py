"""QSE v148 - JALUR ICHIMOKU TREN (TK cross di luar awan + TP strategis & trailing stop), candle 4J.
Backtest entry open candle berikutnya, biaya 0.15% pulang pergi:
30 koin awal: 4843 trade, WR 38%, PF 1.33.
Aturan:
  LONG : close di atas awan dan Tenkan memotong Kijun ke atas. SHORT kebalikannya.
  SL Aman & TP Strategis dihitung dari struktur swing + volatilitas bersih (0.6% s/d 5.5% SL, 1.8R s/d 2.8R TP)
  ditambah pengawalan SL berjalan (trailing) saat profit berkembang."""
import fcntl
import json
import os
import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import bybit_fetch as B
import telegram_notify as TG
import qse_strat as ST
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "ichimoku.json")
H4 = 4 * 3600 * 1000
SL_ATR, TRAIL_ATR, MAKS_BAR = 1.6, 2.5, 60
TOP_KOIN = 150
TOP_LIKUID = 20
MAKS_BARU = 5
MAKS_BUKA = 8
BIAYA = 0.0015
BT = ("111 koin perp 2021-2026, sinyal hanya dari 20 koin paling likuid, maks 8 posisi: 3084 trade, WR 38%, PF 1.29, "
      "positif 18 dari 22 kuartal, untung tiap tahun.")
BT_PENDEK = "111 koin perp 2021-2026, 20 koin paling likuid: PF 1.29, untung tiap tahun"


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
            d = json.load(f)
        ubah_ada = False
        for key, it in list(d.get("open", {}).items()):
            sl0, tp0 = it.get("sl"), it.get("tp")
            ST.perbaiki_item(it, tp_r=2.5)
            if it.get("sl") != sl0 or it.get("tp") != tp0:
                ubah_ada = True
        if ubah_ada:
            with open(FILE + ".tmp", "w") as fw:
                json.dump(d, fw)
            os.replace(FILE + ".tmp", FILE)
        return d
    except Exception:
        return {"open": {}, "closed": [], "t4": 0}


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    med = pd.Series(tr).rolling(20, min_periods=5).median().bfill().values
    tr_clean = np.minimum(tr, 2.0 * np.maximum(med, c * 0.003))
    a = np.full(len(c), np.nan)
    if len(c) > n:
        a[n - 1] = tr_clean[:n].mean()
        for i in range(n, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr_clean[i]) / n
    return a


def _hh(x, n):
    return pd.Series(x).rolling(n).max().values


def _ll(x, n):
    return pd.Series(x).rolling(n).min().values


TELAT_ATR = 0.35
REM_DD_R, REM_RUGI = 16.0, 6


def rem():
    eq = peak = 0.0
    rugi = 0
    for c in sorted(lihat().get("closed", []), key=lambda c: c.get("selesai", 0)):
        r = float(c.get("R", 0))
        eq += r
        peak = max(peak, eq)
        rugi = rugi + 1 if r < 0 else 0
    if peak - eq > REM_DD_R:
        return f"hasil jalur ini turun {peak - eq:.0f}R dari puncak"
    if rugi >= REM_RUGI:
        return f"rugi {rugi} kali beruntun"
    return ""


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
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] ichimoku {sym}: {ex}")
        return None


def _kelola(it, df):
    """Jalankan aturan keluar di candle tutup sejak update terakhir. Return (status, R atau None, sl_lama)."""
    ST.perbaiki_item(it, df, tp_r=2.5)
    L = it["arah"] == "LONG"
    e, risk = it["entry"], max(it.get("risk") or abs(it["entry"] - it["sl"]), 1e-12)
    a = _atr(df["high"].values, df["low"].values, df["close"].values)
    sl_lama = it["sl"]
    idx = list(df.index)
    for k, ts in enumerate(idx):
        if ts <= it["last"]:
            continue
        h, l, c = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        if (l <= it["sl"]) if L else (h >= it["sl"]):
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk, sl_lama
        if it.get("tp") and it["bar"] > 0 and ((h >= it["tp"]) if L else (l <= it["tp"])):
            return "TP", abs(it["tp"] - e) / risk - BIAYA * e / risk, sl_lama
        it["bar"] += 1
        if L:
            it["best"] = max(it.get("best", e), h)
            if not np.isnan(a[k]) and (it["best"] - e) >= 1.2 * risk:
                it["sl"] = max(it["sl"], it["best"] - TRAIL_ATR * a[k])
        else:
            it["best"] = min(it.get("best", e), l)
            if not np.isnan(a[k]) and (e - it["best"]) >= 1.2 * risk:
                it["sl"] = min(it["sl"], it["best"] + TRAIL_ATR * a[k])
        it["last"] = int(ts)
        it["close"] = c
        if it["bar"] >= MAKS_BAR:
            return "WAKTU", ((c - e) if L else (e - c)) / risk - BIAYA * e / risk, sl_lama
    return "BUKA", None, sl_lama


def _catat_ledger(it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur="ichimoku", sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it.get("sl0", it["sl"]),
                                tp1=it.get("tp1", it.get("tp", 0.0)), tp2=it.get("tp", 0.0), t=it["t"], status="SELESAI",
                                R=round(R, 2), isi=it["t"], selesai=time.time(), ket="strategis+trailing"))
    CT._ubah(f)


def _jalankan(baru_ok=True):
    import qse_catat as CT
    d = lihat()
    out = []
    tick = {}
    try:
        tick = B.get_symbols()
    except Exception:
        pass
    buka = dict(d["open"])
    hasil = {}
    for key, it in buka.items():
        df = _k4(it["sym"], 200)
        if df is None or not len(df):
            continue
        it = dict(it)
        st, R, sl_lama = _kelola(it, df)
        hasil[key] = (it, st, R, sl_lama)
    try:
        import qse_saya as SY
        d_saya = SY.lihat()
        pegang = {(v["sym"], v["arah"]) for v in d_saya["open"].values() if v.get("status") in ("TERISI", "TP1")}
        sudah_entry = {v["sym"] for v in d_saya["open"].values()} | {
            c["sym"] for c in d_saya.get("closed", [])[-100:]
            if time.time() * 1000 - (c.get("closed_ts") or 0) < 12 * 3600000
        }
    except Exception:
        pegang, sudah_entry = set(), set()
    for key, (it, st, R, sl_lama) in hasil.items():
        t = tick.get(it["sym"], it.get("tick", 0.0001))
        kabar = (it["sym"], it["arah"]) in pegang
        if st in ("SL", "WAKTU", "TP"):
            _catat_ledger(it, R)
            if not kabar:
                continue
            out.append(f"{'✅' if R > 0 else '🛑'} <b>ICHIMOKU SELESAI  ·  {it['sym']} {it['arah']}  ·  {R:+.2f}R</b>\n"
                       + (f"TP strategis {TG.fp(it['tp'], t)} tersentuh." if st == "TP" else
                          f"Harga balik dan kena SL di sekitar {TG.fp(it['sl'], t)}." if st == "SL" else
                          f"Sudah {MAKS_BAR} candle 4J (10 hari). Tutup posisi sekarang di harga pasar, sekitar {TG.fp(it['close'], t)}.")
                       + f"\nEntry tadi {TG.fp(it['entry'], t)}.")
        elif kabar and abs(it["sl"] - sl_lama) >= 0.25 * it["risk"]:
            L = it["arah"] == "LONG"
            kunci = ((it["sl"] - it["entry"]) if L else (it["entry"] - it["sl"])) / it["risk"]
            out.append(f"🔁 <b>ICHIMOKU  ·  {it['sym']} {it['arah']}  ·  GESER SL</b>\n"
                       f"Ubah SL di Bybit ke <code>{TG.fp(it['sl'], t)}</code> (sebelumnya {TG.fp(sl_lama, t)})\n"
                       f"Profit yang sudah aman kalau harga balik: {kunci:+.2f}R  ·  hari ke-{it['bar'] // 6 + 1} dari 10")

    def simpan_kelola(dd):
        for key, (it, st, R, _) in hasil.items():
            if key not in dd["open"]:
                continue
            if st in ("SL", "WAKTU", "TP"):
                dd["open"].pop(key)
                dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
            else:
                dd["open"][key] = it
    _ubah(simpan_kelola)

    if CT.mati("ichimoku"):
        _ALASAN[0] = "jalur dihentikan karena hasil live jelek"
        out.append("⛔ Jalur Ichimoku sedang dihentikan karena hasil live-nya jelek. Cek /jalur.")
        return out
    d = lihat()
    slot = min(MAKS_BARU, MAKS_BUKA - len(d["open"]))
    if slot <= 0 or not baru_ok:
        _ALASAN[0] = "slot posisi penuh" if slot <= 0 else "robot telat, hanya kelola posisi"
        return out
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    koin = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]
    pindai = list(koin)
    tutup_kini = {it["sym"] for it, st, _, _ in hasil.values() if st in ("SL", "WAKTU", "TP")}
    koin = [s for s in koin if s not in {it["sym"] for it in d["open"].values()} and s not in tutup_kini and s not in sudah_entry]

    def cek(sym):
        df = _k4(sym, 300)
        if df is None or len(df) < 120:
            return sym, None, None, None, 0.0
        arah, a = _sinyal(df)
        return sym, arah, a, df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    likuid = {x[0] for x in sorted(semua, key=lambda x: -x[4])[:TOP_LIKUID]}
    boleh = set(koin)
    hasil_s = sorted([x[:4] for x in semua if x[1] and x[0] in likuid and x[0] in boleh],
                     key=lambda x: -next(z[4] for z in semua if z[0] == x[0]))
    import qse_saya as SY
    tahan = {x[0]: SY.cek_lintas(x[0], x[1]) for x in hasil_s}
    hasil_s = [x for x in hasil_s if not tahan[x[0]]]
    now = time.time()
    baru = []
    for sym, arah, a, df in hasil_s[:slot]:
        px = tk[sym]["last"] or float(df["close"].iloc[-1])
        telat = time.time() * 1000 - (int(df.index[-1]) + H4)
        if telat > 1800000 and abs(px - float(df["close"].iloc[-1])) > TELAT_ATR * a:
            continue
        import qse_porto as PO
        why = PO.izin(sym, arah, "ichimoku")
        if why:
            continue
        lv = ST.level_strategis(df, px, arah, tp_r=2.5)
        if not lv:
            continue
        L = arah == "LONG"
        sl, tp, tp1, tp2, risk = lv["sl"], lv["tp"], lv["tp1"], lv["tp2"], lv["risk"]
        t = tick.get(sym, 0.0001)
        it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, tp=tp, tp1=tp1, tp2=tp2,
                  risk=risk, best=px, bar=0, t=now, last=int(df.index[-1]), close=px, tick=t)
        baru.append(it)
        PO.pesan(sym, arah)
        pc = risk / px * 100
        tp_pc = abs(tp - px) / px * 100
        rr = abs(tp - px) / max(risk, 1e-12)
        jarak = TRAIL_ATR * lv["atr_ef"]
        _, tkb, ik, lot_b = SY.boleh_ikut("saran ichimoku", arah)
        rm = rem() or PO.rem()
        if rm:
            lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
        try:
            import qse_modal as MD
            lot = MD.baris_lot(px, sl, SY.lot_angka(lot_b))
        except Exception:
            lot = ""
        out.append("\n".join([
            SY.GARIS,
            f"{'🟢' if L else '🔴'} <b>{len(baru)}. {sym} {arah}</b>  ·  Ichimoku 4J",
            f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
            SY.GARIS,
            SY.blok_salin(px, sl, tp1, tp2, order="MARKET", tick=t, sym=sym, arah=arah),
            *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot dipotong setengah sampai pulih"] if rm else []),
            "💡 <b>Kenapa Objektif</b>",
            f"• Tenkan baru memotong Kijun {'ke atas' if L else 'ke bawah'} dan harga {'di atas' if L else 'di bawah'} awan: tren {'naik' if L else 'turun'} baru mulai",
            f"• Koin ini termasuk {TOP_LIKUID} koin paling likuid 30 hari terakhir",
            f"• SL Aman di balik struktur swing ({pc:.2f}%), TP Strategis di target ayunan/SnR ({tp_pc:.2f}%, +{rr:.2f}R)",
            "• Bukti: uji 5 tahun 111 koin, 3084 trade, PF 1.29, untung tiap tahun",
            "🛠 <b>Cara</b>",
            f"1. Masuk MARKET sekarang. Pasang SL di {TG.fp(sl, t)} (-{pc:.2f}%) dan TP di {TG.fp(tp, t)} (+{tp_pc:.2f}%, {rr:.1f}R)",
            f"2. Bisa juga aktifkan Trailing Stop Bybit jarak {TG.fp(jarak, t)} ({jarak / px * 100:.1f}%) atau ikuti pesan GESER SL",
            "3. Catat dengan /entry supaya otomatis dipantau tiap menit"
            + (f"\n{lot}" if lot else ""),
        ]))

    def simpan_baru(dd):
        for it in baru:
            dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
    if baru:
        _ubah(simpan_baru)
    return out


def status_singkat():
    import qse_catat as CT
    d = lihat()
    n = len(d["open"])
    rows = [baris_cek()]
    if CT.mati("ichimoku"):
        rows.append("⛔ jalur dihentikan karena hasil live jelek")
    rows.append(f"posisi robot {n}/{MAKS_BUKA}" + ("  ·  slot penuh, sinyal baru keluar setelah ada posisi selesai"
                                                    if n >= MAKS_BUKA else ""))
    semua = list(d["open"].values()) + d["closed"][-50:]
    if semua:
        x = max(semua, key=lambda z: z.get("t", 0))
        rows.append(f"sinyal terakhir {x['sym']} {x['arah']} {time.strftime('%d/%m %H:%M', time.gmtime(x.get('t', 0) + 7 * 3600))} WIB")
    else:
        rows.append("belum pernah ada sinyal tercatat")
    rm = rem()
    if rm:
        rows.append(f"rem drawdown aktif ({rm}), lot setengah")
    rows.append(f"dicek tiap candle 4J tutup, hanya {TOP_LIKUID} koin paling likuid")
    return "  ·  ".join(rows)


def teks():
    d = lihat()
    rows = [f"<b>Jalur Ichimoku tren 4J</b>\nBacktest: {BT}"]
    if d["open"]:
        rows.append(f"\nPosisi berjalan ({len(d['open'])}):")
        for it in d["open"].values():
            L = it["arah"] == "LONG"
            g = ((it["close"] - it["entry"]) if L else (it["entry"] - it["close"])) / max(it["risk"], 1e-12)
            tp_txt = f" | TP {TG.fp(it['tp'], it['tick'])}" if it.get("tp") else ""
            rows.append(f"{'🟢' if L else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])}{tp_txt} | sekarang {g:+.2f}R | candle {it['bar']}/{MAKS_BAR}")
    else:
        rows.append("\nBelum ada posisi berjalan.")
    rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
    if rs:
        w = sum(x for x in rs if x > 0)
        lo = -sum(x for x in rs if x < 0)
        rows.append(f"\nSelesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                    f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
    return "\n".join(rows)


_ALASAN = [""]


def jalankan(baru_ok=True):
    _ALASAN[0] = ""
    out = _jalankan(baru_ok)
    n = sum(1 for m in out if "BISA DIIKUTI" in m)
    why = _ALASAN[0] or ("" if n else "tidak ada koin yang lolos semua syarat")

    def f(d):
        d["cek"] = dict(t=time.time(), n=n, why=why)
    try:
        _ubah(f)
    except Exception as ex:
        print("[WARN] catat cek", ex)
    return out


def baris_cek():
    c = lihat().get("cek")
    if not c:
        return "belum pernah dicek sejak update"
    jam = time.strftime("%H:%M", time.gmtime(c["t"] + 7 * 3600))
    return f"dicek {jam} WIB: {c['n']} sinyal baru" + (f", {c['why']}" if c.get("why") and not c["n"] else "")
