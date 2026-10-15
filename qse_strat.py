"""QSE v148 - JALUR STRATEGI TAMBAHAN yang lolos uji 14 strategi umum (candle 4J, 111 koin perp, Jul 2020 - Okt 2026).
Aturan dipilih dari data 2020-2023, lalu diuji di 2024-2026 tanpa diubah. Biaya 0.15%. Maks 8 posisi per jalur.
Yang lolos dan dipasang:
  ema_short : EMA 20 memotong EMA 50 ke bawah, close di bawah EMA 200, BTC 4J di bawah EMA 50. Hanya SHORT.
              1812 trade, WR 42%, PF 1.42 (2020-23 PF 1.37, 2024-26 PF 1.47), turun terdalam 16%, untung tiap tahun.
  rsi_vol   : RSI 14 memotong 50 searah tren (close dan EMA 50 di sisi yang sama dari EMA 200), volume candle masuk
              20% tertinggi dari 100 candle, koin 30 paling likuid. LONG dan SHORT.
              2380 trade, WR 40%, PF 1.34 (2020-23 PF 1.26, 2024-26 PF 1.45), turun terdalam 15%, positif 21 dari 26 kuartal.
Keluar (sama dengan Ichimoku): SL awal 2 ATR, tiap candle 4J tutup SL digeser ke puncak - 3 ATR, tutup paksa 60 candle.
Yang gagal: Donchian 20/55, Supertrend, Bollinger squeeze, Bollinger dan RSI 2 mean reversion, pullback 3 candle,
inside bar, momentum 30 hari, funding ekstrem (searah atau lawan), breakout volume (lolos per trade tapi tidak di portofolio)."""
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

H4 = 4 * 3600 * 1000
SL_ATR, TRAIL_ATR, MAKS_BAR = 2.0, 3.0, 60
MAKS_BARU, MAKS_BUKA, TOP_KOIN = 5, 8, 150
BIAYA = 0.0015
TELAT_ATR = 0.5
STRAT = {
    "ema_short": dict(nama="EMA Cross 20/50 SHORT", likuid=0,
                      bt="uji 6 tahun 111 koin: 1812 trade, PF 1.42, uji ulang 2024-2026 PF 1.47, untung tiap tahun",
                      kenapa=["EMA 20 baru memotong EMA 50 ke bawah: momentum turun mulai",
                              "Harga di bawah EMA 200: tren besar turun",
                              "BTC 4J di bawah EMA 50: pasar ikut menekan"]),
    "rsi_vol": dict(nama="RSI 50 + Volume", likuid=30,
                    bt="uji 6 tahun 111 koin, 30 paling likuid: 2380 trade, PF 1.34, uji ulang 2024-2026 PF 1.45",
                    kenapa=["RSI 14 baru melewati 50 searah tren besar (EMA 50 dan harga di sisi yang sama dari EMA 200)",
                            "Volume candle masuk 20% tertinggi dari 100 candle: dorongan nyata",
                            "Koin termasuk 30 paling likuid"]),
}


def _file(k):
    return os.path.join(STATE_DIR, f"strat_{k}.json")


def _ubah(k, fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    f_ = _file(k)
    with open(f_ + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(f_) as f:
                d = json.load(f)
        except Exception:
            d = {"open": {}, "closed": []}
        hasil = fn(d)
        d["closed"] = d["closed"][-500:]
        with open(f_ + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(f_ + ".tmp", f_)
        return hasil


def lihat(k):
    try:
        with open(_file(k)) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    return _rma(np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))), 14)


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = _rma(np.maximum(d, 0), n), _rma(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


def sinyal(df, btc_naik):
    """Cek candle tutup terakhir untuk semua strategi. Return dict kunci -> (arah, atr). Aturan persis backtest."""
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    i = len(c) - 1
    if i < 260:
        return {}
    a = _atr(h, l, c)
    e20, e50, e200 = _ema(c, 20), _ema(c, 50), _ema(c, 200)
    out = {}
    if e20[i] < e50[i] and e20[i - 1] >= e50[i - 1] and c[i] < e200[i] and btc_naik is False:
        out["ema_short"] = ("SHORT", float(a[i]))
    r = _rsi(c)
    vp = (v[i - 100:i] <= v[i]).mean() * 100
    if vp >= 80:
        if r[i] > 50 and r[i - 1] <= 50 and c[i] > e200[i] and e50[i] > e200[i]:
            out["rsi_vol"] = ("LONG", float(a[i]))
        elif r[i] < 50 and r[i - 1] >= 50 and c[i] < e200[i] and e50[i] < e200[i]:
            out["rsi_vol"] = ("SHORT", float(a[i]))
    return out


def _k4(sym, bars=600):
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] strat {sym}: {ex}")
        return None


def _kelola(it, df):
    """Sama dengan backtest: SL dicek dulu, lalu puncak dan SL berjalan 3 ATR, tutup paksa 60 candle."""
    L = it["arah"] == "LONG"
    e, risk = it["entry"], it["risk"]
    a = _atr(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float))
    sl_lama = it["sl"]
    for k, ts in enumerate(df.index):
        if ts <= it["last"]:
            continue
        hi, lo, cl = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        if (lo <= it["sl"]) if L else (hi >= it["sl"]):
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk, sl_lama
        if L:
            it["best"] = max(it["best"], hi)
            it["sl"] = max(it["sl"], it["best"] - TRAIL_ATR * a[k])
        else:
            it["best"] = min(it["best"], lo)
            it["sl"] = min(it["sl"], it["best"] + TRAIL_ATR * a[k])
        it["bar"] += 1
        it["last"] = int(ts)
        it["close"] = cl
        if it["bar"] >= MAKS_BAR:
            return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk, sl_lama
    return "BUKA", None, sl_lama


def _catat_ledger(k, it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur=k, sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"], tp1=0.0, tp2=0.0,
                                t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"], selesai=time.time(), ket="trailing"))
    CT._ubah(f)


def rem(k):
    eq = peak = 0.0
    rugi = 0
    for c in sorted(lihat(k).get("closed", []), key=lambda c: c.get("selesai", 0)):
        r = float(c.get("R", 0))
        eq += r
        peak = max(peak, eq)
        rugi = rugi + 1 if r < 0 else 0
    if peak - eq > 16:
        return f"hasil jalur ini turun {peak - eq:.0f}R dari puncak"
    if rugi >= 6:
        return f"rugi {rugi} kali beruntun"
    return ""


def btc_naik():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    return bool(c[-1] > _ema(c, 50)[-1])


def jalankan(baru_ok=True):
    """Dipanggil listener tiap candle 4J tutup. Return dict kunci -> daftar pesan."""
    import qse_catat as CT
    import qse_saya as SY
    out = {k: [] for k in STRAT}
    try:
        tick = B.get_symbols()
    except Exception:
        tick = {}
    try:
        pegang = {(v["sym"], v["arah"]) for v in SY.lihat()["open"].values() if v.get("status") in ("TERISI", "TP1")}
    except Exception:
        pegang = set()
    # 1. kelola posisi
    for k in STRAT:
        hasil = {}
        for key, it in dict(lihat(k)["open"]).items():
            df = _k4(it["sym"], 300)
            if df is None or not len(df):
                continue
            it = dict(it)
            st, R, sl_lama = _kelola(it, df)
            hasil[key] = (it, st, R, sl_lama)
        for key, (it, st, R, sl_lama) in hasil.items():
            t = it.get("tick", 0.0001)
            kabar = (it["sym"], it["arah"]) in pegang
            if st in ("SL", "WAKTU"):
                _catat_ledger(k, it, R)
                if kabar:
                    out[k].append(f"{'✅' if R > 0 else '🛑'} <b>{STRAT[k]['nama'].upper()} SELESAI  ·  {it['sym']} {it['arah']}  ·  {R:+.2f}R</b>\n"
                                  + (f"Kena SL berjalan di sekitar {TG.fp(it['sl'], t)}. Kalau SL di Bybit sudah digeser, posisi sudah tutup."
                                     if st == "SL" else f"Sudah {MAKS_BAR} candle 4J (10 hari). Tutup sekarang di harga pasar."))
            elif kabar and abs(it["sl"] - sl_lama) >= 0.25 * it["risk"]:
                L = it["arah"] == "LONG"
                kunci = ((it["sl"] - it["entry"]) if L else (it["entry"] - it["sl"])) / it["risk"]
                out[k].append(f"🔁 <b>{STRAT[k]['nama'].upper()}  ·  {it['sym']} {it['arah']}  ·  GESER SL</b>\n"
                              f"Ubah SL di Bybit ke <code>{TG.fp(it['sl'], t)}</code> (sebelumnya {TG.fp(sl_lama, t)})\n"
                              f"Profit aman kalau harga balik: {kunci:+.2f}R  ·  hari ke-{it['bar'] // 6 + 1} dari 10")

        def simpan(dd, hasil=hasil):
            for key, (it, st, R, _) in hasil.items():
                if key not in dd["open"]:
                    continue
                if st in ("SL", "WAKTU"):
                    dd["open"].pop(key)
                    dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
                else:
                    dd["open"][key] = it
        _ubah(k, simpan)
    if not baru_ok:
        return out
    # 2. sinyal baru
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    bn = btc_naik()
    pindai = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]

    def cek(sym):
        df = _k4(sym, 600)
        if df is None or len(df) < 261:
            return sym, {}, None, 0.0
        return sym, sinyal(df, bn), df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    urut = [x[0] for x in sorted(semua, key=lambda x: -x[3])]
    now = time.time()
    for k, cfg in STRAT.items():
        if CT.mati(k):
            _CEK[k] = (0, "jalur dihentikan karena hasil live jelek")
            continue
        d = lihat(k)
        slot = min(MAKS_BARU, MAKS_BUKA - len(d["open"]))
        if slot <= 0:
            _CEK[k] = (0, "slot posisi penuh")
            continue
        boleh = set(urut[:cfg["likuid"]]) if cfg["likuid"] else set(urut)
        buka = {it["sym"] for it in d["open"].values()}
        calon = [x for x in semua if k in x[1] and x[0] in boleh and x[0] not in buka]
        calon.sort(key=lambda x: urut.index(x[0]))
        baru = []
        for sym, sg, df, _ in calon:
            if len(baru) >= slot:
                break
            arah, a = sg[k]
            why = SY.cek_lintas(sym, arah)
            if why:
                print(f"[STRAT {k}] {sym} ditahan: {why}")
                continue
            px = tk[sym]["last"] or float(df["close"].iloc[-1])
            telat = now * 1000 - (int(df.index[-1]) + H4)
            if telat > 1800000 and abs(px - float(df["close"].iloc[-1])) > TELAT_ATR * a:
                continue
            L = arah == "LONG"
            risk = SL_ATR * a
            if risk / px < 0.003:
                continue
            sl = px - risk if L else px + risk
            t = tick.get(sym, 0.0001)
            it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=risk, best=px, bar=0, t=now,
                      last=int(df.index[-1]), close=px, tick=t)
            baru.append(it)
            out[k].append(kartu(k, len(baru), it, a))

        def simpan_baru(dd, baru=baru):
            for it in baru:
                dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
        if baru:
            _ubah(k, simpan_baru)
        _CEK[k] = (len(baru), "" if baru else ("BTC 4J di atas EMA 50, SHORT ditahan" if k == "ema_short" and bn
                                               else "tidak ada koin yang lolos semua syarat"))
    for k, (n, why) in _CEK.items():
        _ubah(k, lambda d, n=n, why=why: d.update(cek=dict(t=time.time(), n=n, why=why)))
    return out


_CEK = {}


def kartu(k, no, it, a):
    import qse_saya as SY
    cfg = STRAT[k]
    L = it["arah"] == "LONG"
    t = it["tick"]
    _, tkb, ik, lot_b = SY.boleh_ikut("saran " + k, it["arah"])
    rm = rem(k)
    if rm:
        lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], SY.lot_angka(lot_b))
    except Exception:
        lot = ""
    jarak = TRAIL_ATR * a
    return "\n".join([
        SY.GARIS,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  {cfg['nama']} 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.5% modal per trade)",
        SY.GARIS,
        SY.blok_salin(it["entry"], it["sl"], order="MARKET", tick=t, catatan_tp="tidak ada, pakai SL berjalan"),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot setengah sampai pulih"] if rm else []),
        "💡 <b>Kenapa</b>",
        *[f"• {z}" for z in cfg["kenapa"]],
        f"• Bukti: {cfg['bt']}",
        "🛠 <b>Cara</b>",
        f"1. Masuk MARKET sekarang. SL di {TG.fp(it['sl'], t)} ({it['risk'] / it['entry'] * 100:.1f}%). Jangan pasang TP",
        f"2. Pasang Trailing Stop Bybit dengan jarak {TG.fp(jarak, t)} ({jarak / it['entry'] * 100:.1f}%), atau ikuti pesan GESER SL",
        "3. Kalau 10 hari belum kena SL, tutup manual",
        "4. Catat dengan /entry supaya pesan GESER SL dan analisa volume SL dikirim"
        + (f"\n{lot}" if lot else ""),
    ])


def baris_cek(k):
    c = lihat(k).get("cek")
    if not c:
        return "belum pernah dicek sejak update"
    jam = time.strftime("%H:%M", time.gmtime(c["t"] + 7 * 3600))
    return f"dicek {jam} WIB: {c['n']} sinyal baru" + (f", {c['why']}" if c.get("why") and not c["n"] else "")


def status_singkat(k):
    return f"{baris_cek(k)}  ·  posisi robot {len(lihat(k)['open'])}/{MAKS_BUKA}"


def teks():
    rows = []
    for k, cfg in STRAT.items():
        d = lihat(k)
        rows.append(f"<b>{cfg['nama']}</b>\nBacktest: {cfg['bt']}\n{status_singkat(k)}")
        for it in d["open"].values():
            L = it["arah"] == "LONG"
            g = ((it["close"] - it["entry"]) if L else (it["entry"] - it["close"])) / it["risk"]
            rows.append(f"{'🟢' if L else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])} | {g:+.2f}R | candle {it['bar']}/{MAKS_BAR}")
        rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
        if rs:
            w = sum(x for x in rs if x > 0)
            lo = -sum(x for x in rs if x < 0)
            rows.append(f"Selesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                        f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
        rows.append("")
    rows.append("Gagal uji dan tidak dipakai: Donchian 20/55, Supertrend, Bollinger squeeze, mean reversion Bollinger dan RSI 2, "
                "pullback 3 candle, inside bar, momentum 30 hari, funding ekstrem, breakout volume.")
    return "\n".join(rows)
