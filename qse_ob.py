"""QSE v148 - JALUR ORDER BLOCK + VOLUME (koin unggulan), candle 4J. Juga analisa volume saat kena SL.
Aturan:
  Candle merah, lalu 5 candle hijau beruntun, naik minimal 2% dari close candle merah.
  Close di atas EMA 200, volume candle ke-5 masuk 20% tertinggi dari 100 candle, koin masuk 50 paling likuid
  (nilai transaksi 30 hari), BTC 4J close di atas EMA 50.
  Entry MARKET. SL Aman berbasis struktur OB + buffer ekor candle (dibatasi 0.6% s/d 5.5%) dan TP Strategis (1.8R s/d 2.8R)."""
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

FILE = os.path.join(STATE_DIR, "orderblock.json")
FILE_SL = os.path.join(STATE_DIR, "sl_volume.json")
H4 = 4 * 3600 * 1000
P_OB, MIN_GERAK, BUF_ATR, TP_R, MAKS_BAR = 5, 2.0, 0.3, 2.6, 60
VP_MIN, TOP_LIKUID, TOP_KOIN = 80, 50, 150
MAKS_BARU, MAKS_BUKA = 5, 8
BIAYA = 0.0015
TELAT_ATR = 0.35
BT = ("111 koin perp Jul 2020 - Okt 2026, maks 8 posisi: 969 trade, WR 41%, PF 1.45, positif 16 dari 26 kuartal. "
      "Uji ulang 2024-2026: PF 1.26, turun terdalam 10.1%.")
BT_PENDEK = "uji 6 tahun 111 koin: 969 trade, PF 1.45, uji ulang 2024-2026 PF 1.26"


def _ubah(fn, file=FILE, kosong=None):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(file + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(file) as f:
                d = json.load(f)
        except Exception:
            d = kosong if kosong is not None else {"open": {}, "closed": []}
        hasil = fn(d)
        if "closed" in d:
            d["closed"] = d["closed"][-500:]
        with open(file + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(file + ".tmp", file)
        return hasil


def lihat():
    try:
        with open(FILE) as f:
            d = json.load(f)
        ubah_ada = False
        for key, it in list(d.get("open", {}).items()):
            sl0, tp0 = it.get("sl"), it.get("tp")
            ST.perbaiki_item(it, tp_r=TP_R)
            if it.get("sl") != sl0 or it.get("tp") != tp0:
                ubah_ada = True
        if ubah_ada:
            with open(FILE + ".tmp", "w") as fw:
                json.dump(d, fw)
            os.replace(FILE + ".tmp", FILE)
        return d
    except Exception:
        return {"open": {}, "closed": []}


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    med = pd.Series(tr).rolling(20, min_periods=5).median().bfill().values
    tr_clean = np.minimum(tr, 2.0 * np.maximum(med, c * 0.003))
    a = np.full(len(c), np.nan)
    if len(c) > n:
        a[n] = tr_clean[1:n + 1].mean()
        for i in range(n + 1, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr_clean[i]) / n
    return a


def _ema(x, n):
    k = 2 / (n + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def _cdv(o, h, l, c, v):
    tw = h - np.maximum(o, c)
    bw = np.minimum(o, c) - l
    body = np.abs(c - o)
    rng = tw + bw + body
    with np.errstate(invalid="ignore", divide="ignore"):
        rate = np.where(rng > 0, 0.5 * (tw + bw + 2 * body) / rng, 0.5)
    return np.where(c >= o, v * rate, -v * rate)


def _sinyal(df):
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    s = len(c) - 1
    if s < 210:
        return None
    j = s - P_OB
    if not (c[j] < o[j] and (c[j + 1:s + 1] > o[j + 1:s + 1]).all()):
        return None
    gerak = abs(c[j] - c[s]) / c[j] * 100
    if gerak < MIN_GERAK or gerak > 12.0:
        return None
    e200 = _ema(c, 200)[s]
    if c[s] <= e200:
        return None
    vp = float((v[s - 100:s] <= v[s]).mean() * 100)
    if vp < VP_MIN:
        return None
    a = _atr(h, l, c)[s]
    if np.isnan(a):
        return None
    return dict(ob_low=float(l[j]), ob_top=float(o[j]), atr=float(a), vp=vp, gerak=gerak, close=float(c[s]),
                sl=float(l[j] - BUF_ATR * a), e200=float(e200), ts=int(df.index[-1]))


def _k4(sym, bars=600):
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] orderblock {sym}: {ex}")
        return None


def btc_naik():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    return bool(c[-1] > _ema(c, 50)[-1])


def _kelola(it, df):
    ST.perbaiki_item(it, df, tp_r=TP_R)
    e, risk = it["entry"], max(it.get("risk") or abs(it["entry"] - it["sl"]), 1e-12)
    for k, ts in enumerate(df.index):
        if ts <= it["last"]:
            continue
        hi, lo, cl = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        if lo <= it["sl"]:
            return "SL", (it["sl"] - e) / risk - BIAYA * e / risk
        if it["bar"] > 0 and hi >= it["tp"]:
            return "TP", abs(it["tp"] - e) / risk - BIAYA * e / risk
        it["bar"] += 1
        it["last"] = int(ts)
        it["close"] = cl
        if it["bar"] >= MAKS_BAR:
            return "WAKTU", (cl - e) / risk - BIAYA * e / risk
    return "BUKA", None


def _catat_ledger(it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur="orderblock", sym=it["sym"], arah="LONG", entry=it["entry"], sl=it["sl"],
                                tp1=it.get("tp1", it["tp"]), tp2=it["tp"], t=it["t"], status="SELESAI",
                                R=round(R, 2), isi=it["t"], selesai=time.time(), ket="ob volume"))
    CT._ubah(f)


def rem():
    eq = peak = 0.0
    rugi = 0
    for c in sorted(lihat().get("closed", []), key=lambda c: c.get("selesai", 0)):
        r = float(c.get("R", 0))
        eq += r
        peak = max(peak, eq)
        rugi = rugi + 1 if r < 0 else 0
    if peak - eq > 16:
        return f"hasil jalur ini turun {peak - eq:.0f}R dari puncak"
    if rugi >= 6:
        return f"rugi {rugi} kali beruntun"
    return ""


def _jalankan(baru_ok=True):
    import qse_catat as CT
    import qse_saya as SY
    d = lihat()
    out = []
    try:
        tick = B.get_symbols()
    except Exception:
        tick = {}
    hasil = {}
    for key, it in dict(d["open"]).items():
        df = _k4(it["sym"], 200)
        if df is None or not len(df):
            continue
        it = dict(it)
        st, R = _kelola(it, df)
        hasil[key] = (it, st, R)
    try:
        d_saya = SY.lihat()
        pegang = {v["sym"] for v in d_saya["open"].values()
                  if v.get("status") in ("TERISI", "TP1") and v.get("arah") == "LONG"}
        sudah_entry = {v["sym"] for v in d_saya["open"].values()} | {
            c["sym"] for c in d_saya.get("closed", [])[-100:]
            if time.time() * 1000 - (c.get("closed_ts") or 0) < 12 * 3600000
        }
    except Exception:
        pegang, sudah_entry = set(), set()
    for key, (it, st, R) in hasil.items():
        if st == "BUKA":
            continue
        _catat_ledger(it, R)
        if it["sym"] not in pegang:
            continue
        t = it.get("tick", 0.0001)
        if st == "WAKTU":
            out.append(f"⏰ <b>ORDER BLOCK SELESAI  ·  {it['sym']} LONG  ·  {R:+.2f}R</b>\nSudah {MAKS_BAR} candle 4J (10 hari). "
                       f"Tutup posisi sekarang di harga pasar, sekitar {TG.fp(it['close'], t)}.")
        elif st == "TP":
            out.append(f"✅ <b>ORDER BLOCK TP  ·  {it['sym']} LONG  ·  {R:+.2f}R</b>\nTP strategis {TG.fp(it['tp'], t)} tersentuh.")

    def simpan_kelola(dd):
        for key, (it, st, R) in hasil.items():
            if key not in dd["open"]:
                continue
            if st == "BUKA":
                dd["open"][key] = it
            else:
                dd["open"].pop(key)
                dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
    _ubah(simpan_kelola)

    if CT.mati("orderblock"):
        _ALASAN[0] = "jalur dihentikan karena hasil live jelek"
        out.append("⛔ Jalur Order Block sedang dihentikan karena hasil live-nya jelek. Cek /jalur.")
        return out
    d = lihat()
    slot = min(MAKS_BARU, MAKS_BUKA - len(d["open"]))
    if slot <= 0 or not baru_ok:
        _ALASAN[0] = "slot posisi penuh" if slot <= 0 else "robot telat, hanya kelola posisi"
        return out
    bn = btc_naik()
    if not bn:
        _ALASAN[0] = "BTC 4J di bawah EMA 50, sinyal LONG ditahan"
        return out
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    pindai = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]
    buka = {it["sym"] for it in d["open"].values()} | sudah_entry
    tutup_kini = {it["sym"] for it, st, _ in hasil.values() if st != "BUKA"}

    def cek(sym):
        df = _k4(sym, 600)
        if df is None or len(df) < 260:
            return sym, None, None, 0.0
        return sym, _sinyal(df), df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    likuid = {x[0] for x in sorted(semua, key=lambda x: -x[3])[:TOP_LIKUID]}
    calon = sorted([x for x in semua if x[1] and x[0] in likuid and x[0] not in buka and x[0] not in tutup_kini],
                   key=lambda x: -x[1]["vp"])
    now = time.time()
    baru = []
    for sym, sg, df, _ in calon:
        if len(baru) >= slot:
            break
        import qse_porto as PO
        why = SY.cek_lintas(sym, "LONG") or PO.izin(sym, "LONG", "orderblock")
        if why:
            continue
        px = tk[sym]["last"] or sg["close"]
        telat = now * 1000 - (sg["ts"] + H4)
        if telat > 1800000 and abs(px - sg["close"]) > TELAT_ATR * sg["atr"]:
            continue
        lv = ST.level_strategis(df, px, "LONG", tp_r=TP_R, sl_acuan=sg["sl"])
        if not lv:
            continue
        t = tick.get(sym, 0.0001)
        it = dict(sym=sym, arah="LONG", entry=px, sl=lv["sl"], sl0=lv["sl"], tp=lv["tp"], tp1=lv["tp1"], tp2=lv["tp2"],
                  risk=lv["risk"], bar=0, t=now, last=sg["ts"], close=px, tick=t, vp=sg["vp"])
        baru.append(it)
        PO.pesan(sym, "LONG")
        out.append(kartu(len(baru), it, sg))

    def simpan_baru(dd):
        for it in baru:
            dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
    if baru:
        _ubah(simpan_baru)
    return out


def kartu(no, it, sg):
    import qse_saya as SY
    t = it["tick"]
    _, tkb, ik, lot_b = SY.boleh_ikut("saran orderblock", "LONG")
    rm = rem()
    if rm:
        lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], SY.lot_angka(lot_b))
    except Exception:
        lot = ""
    pc = it["risk"] / it["entry"] * 100
    tp_pc = abs(it["tp"] - it["entry"]) / it["entry"] * 100
    rr = abs(it["tp"] - it["entry"]) / max(it["risk"], 1e-12)
    return "\n".join([
        SY.GARIS,
        f"🟢 <b>{no}. {it['sym']} LONG</b>  ·  Order Block + Volume 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
        SY.GARIS,
        SY.blok_salin(it["entry"], it["sl"], tp1=it.get("tp1") or it["tp"], tp2=it["tp"], order="MARKET", tick=t, sym=it["sym"], arah="LONG"),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot dipotong setengah sampai pulih"] if rm else []),
        "💡 <b>Kenapa Objektif</b>",
        f"• Order block bullish: candle merah lalu 5 candle hijau beruntun, naik {sg['gerak']:.1f}%",
        f"• Volume candle terakhir masuk {100 - sg['vp']:.0f}% teratas dari 100 candle. Pembeli besar masuk",
        f"• Harga di atas EMA 200 4J dan BTC 4J di atas EMA 50. Koin termasuk {TOP_LIKUID} paling likuid",
        f"• SL Aman di bawah struktur OB ({pc:.2f}%), TP Strategis di target ayunan/SnR ({tp_pc:.2f}%, +{rr:.2f}R)",
        f"• Bukti: {BT_PENDEK}",
        "🛠 <b>Cara</b>",
        f"1. Masuk MARKET sekarang. SL {TG.fp(it['sl'], t)} (-{pc:.2f}%), TP {TG.fp(it['tp'], t)} (+{tp_pc:.2f}%, {rr:.1f}R)",
        "2. Bisa ambil separuh di TP1 lalu sisanya ke TP2",
        "3. Kalau 10 hari belum kena SL atau TP, tutup manual",
        "4. Catat dengan /entry supaya otomatis dipantau tiap menit"
        + (f"\n{lot}" if lot else ""),
    ])


def status_singkat():
    import qse_catat as CT
    d = lihat()
    n = len(d["open"])
    rows = [baris_cek()]
    if CT.mati("orderblock"):
        rows.append("⛔ jalur dihentikan karena hasil live jelek")
    rows.append(f"posisi robot {n}/{MAKS_BUKA}")
    semua = list(d["open"].values()) + d["closed"][-50:]
    if semua:
        x = max(semua, key=lambda z: z.get("t", 0))
        rows.append(f"sinyal terakhir {x['sym']} LONG {time.strftime('%d/%m %H:%M', time.gmtime(x.get('t', 0) + 7 * 3600))} WIB")
    else:
        rows.append("belum pernah ada sinyal tercatat")
    rm = rem()
    if rm:
        rows.append(f"rem drawdown aktif ({rm})")
    rows.append(f"dicek tiap candle 4J tutup, {TOP_LIKUID} koin paling likuid, hanya saat BTC 4J di atas EMA 50")
    return "  ·  ".join(rows)


def baru_berlaku(jam=4):
    now = time.time()
    return [it for it in lihat()["open"].values() if now - it.get("t", 0) <= jam * 3600]


def teks():
    d = lihat()
    rows = [f"<b>Jalur Order Block + Volume 4J (LONG)</b>\nBacktest: {BT}"]
    if d["open"]:
        rows.append(f"\nPosisi berjalan ({len(d['open'])}):")
        for it in d["open"].values():
            g = (it["close"] - it["entry"]) / max(it["risk"], 1e-12)
            rows.append(f"🟢 {it['sym']} | entry {TG.fp(it['entry'], it['tick'])} | SL {TG.fp(it['sl'], it['tick'])} | "
                        f"TP {TG.fp(it['tp'], it['tick'])} | sekarang {g:+.2f}R | candle {it['bar']}/{MAKS_BAR}")
    else:
        rows.append("\nBelum ada posisi berjalan.")
    rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
    if rs:
        w = sum(x for x in rs if x > 0)
        lo = -sum(x for x in rs if x < 0)
        rows.append(f"\nSelesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                    f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
    return "\n".join(rows)


TABEL_SL = {
    ("sumbu", "kecil"): (0.28, 0.20, 2379), ("sumbu", "sedang"): (0.30, 0.23, 7217), ("sumbu", "besar"): (0.38, 0.22, 7869),
    ("tembus", "kecil"): (0.21, 0.33, 3024), ("tembus", "sedang"): (0.18, 0.39, 9281), ("tembus", "besar"): (0.18, 0.51, 10522),
}
SUMBU_SEARAH = (0.86, 0.16, 221)


def antri_sl(sym, arah, entry, sl, t_masuk_ms, sumber="trade kamu"):
    if not sym or not sl or not entry:
        return

    def f(d):
        k = f"{sym}|{arah}|{float(sl):.10g}"
        if k not in d["antri"]:
            d["antri"][k] = dict(sym=sym, arah=arah, entry=float(entry), sl=float(sl), t_masuk=int(t_masuk_ms or 0),
                                 t=time.time(), sumber=sumber)
    _ubah(f, FILE_SL, {"antri": {}})


def analisa_sl(it, df=None):
    if df is None:
        df = _k4(it["sym"], 300)
    if df is None or len(df) < 30:
        return None
    L = it["arah"] == "LONG"
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    ts = df.index.values
    f = max(int(np.searchsorted(ts, it["t_masuk"], side="right")) - 1, 0)
    j = None
    for k in range(f, len(c)):
        if (l[k] <= it["sl"]) if L else (h[k] >= it["sl"]):
            j = k
            break
    if j is None or j < 21:
        return None
    rv = v[j] / max(v[j - 20:j].mean(), 1e-12)
    d = _cdv(o, h, l, c, v)
    fl = d[f:j + 1].sum() / max(v[f:j + 1].sum(), 1e-12) * (1 if L else -1)
    tembus = (c[j] < it["sl"]) if L else (c[j] > it["sl"])
    vk = "besar" if rv > 2 else ("sedang" if rv >= 1 else "kecil")
    kel = "tembus" if tembus else "sumbu"
    if not tembus and fl > 0.15:
        balik, lanjut, n = SUMBU_SEARAH
    else:
        balik, lanjut, n = TABEL_SL[(kel, vk)]
    arah_lawan = "jual" if L else "beli"
    rows = [f"📊 <b>ANALISA VOLUME SL  ·  {it['sym']} {it['arah']}</b>  ({it.get('sumber', '')})",
            f"• Candle 4J yang kena SL: volume {rv:.1f}x rata-rata 20 candle, "
            + ("tutup MENEMBUS SL" if tembus else "hanya SUMBU yang menyentuh SL, tutup kembali di dalam"),
            f"• Aliran volume selama posisi (CDV): {'searah posisi' if fl > 0.15 else ('melawan posisi, tekanan ' + arah_lawan + ' dominan' if fl < -0.15 else 'seimbang')}"]
    if tembus and vk == "besar":
        rows.append(f"🧭 <b>Tekanan nyata.</b> Dari {n} kejadian serupa, {lanjut * 100:.0f}% harga lanjut 1R lagi melewati SL, "
                    f"hanya {balik * 100:.0f}% balik ke entry. Jangan masuk lagi arah {it['arah']} di koin ini dalam 2 hari.")
    elif tembus:
        rows.append(f"🧭 <b>Tembus dengan volume {'biasa' if vk == 'sedang' else 'kecil'}.</b> Dari {n} kejadian serupa, {lanjut * 100:.0f}% "
                    f"lanjut 1R lagi, {balik * 100:.0f}% balik ke entry. Tunggu sinyal baru, jangan buru-buru masuk ulang.")
    else:
        rows.append(f"🧭 <b>Kemungkinan sapuan SL (stop hunt).</b> Dari {n} kejadian serupa, {balik * 100:.0f}% harga balik ke entry "
                    f"dalam 2 hari, hanya {lanjut * 100:.0f}% lanjut 1R lagi. Boleh masuk ulang hanya kalau robot mengirim sinyal baru.")
    rows.append("Data: 40 ribu kejadian SL di 111 koin 2020-2026.")
    return "\n".join(rows)


def proses_sl():
    try:
        with open(FILE_SL) as fh:
            antri = dict(json.load(fh).get("antri", {}))
    except Exception:
        return []
    out, selesai = [], []
    for k, it in antri.items():
        try:
            tx = analisa_sl(it)
        except Exception as ex:
            print("[WARN] analisa SL", it.get("sym"), ex)
            tx = None
        if tx:
            out.append(tx)
            selesai.append(k)
        elif time.time() - it.get("t", 0) > 3 * 86400:
            selesai.append(k)

    def f(d):
        for k in selesai:
            d["antri"].pop(k, None)
    if selesai:
        _ubah(f, FILE_SL, {"antri": {}})
    return out


def baris_unggulan(harga=None, jam=24):
    import qse_saya as SY
    ok, tk, ik, lot = SY.boleh_ikut("saran orderblock", "LONG")
    if not ok:
        return []
    if harga is None:
        try:
            harga = {s: v["last"] for s, v in B.get_tickers().items()}
        except Exception:
            harga = {}
    now = time.time()
    out = []
    for it in sorted(lihat()["open"].values(), key=lambda z: -z.get("t", 0)):
        if now - it.get("t", 0) > jam * 3600:
            continue
        px = harga.get(it["sym"]) or it.get("close")
        if not px or px <= it["sl"] or px > it["entry"] + 0.3 * it["risk"]:
            continue
        t = it.get("tick", 0.0001)
        out.append(f"🟢 <b>{TG.e(it['sym'])} LONG</b>  ·  Order Block + Volume  ·  {ik} {tk}  ·  lot {lot}  ·  "
                   f"sinyal {time.strftime('%d/%m %H:%M', time.gmtime(it['t'] + 7 * 3600))} WIB\n"
                   + SY.blok_salin(px, it["sl"], it.get("tp1") or it["tp"], it["tp"], "MARKET", t, sym=it["sym"], arah="LONG"))
    return out


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
