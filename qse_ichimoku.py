"""QSE v148 - JALUR ICHIMOKU TREN (TK cross di luar awan + trailing stop), candle 4J.
Backtest entry open candle berikutnya, biaya 0.15% pulang pergi:
30 koin awal: 4843 trade, WR 38%, PF 1.33. 82 koin baru yang tidak dipakai memilih aturan: 13730 trade, PF 1.17.
Gabungan 112 koin: PF 1.21, SHORT PF 1.30, LONG PF 1.10. Filter BTC 1J, ramalan BTC 4J, tren harian,
kekuatan relatif, dan volume sudah diuji: tidak ada yang menaikkan PF di 82 koin baru, jadi tidak dipakai.
Aturan (sama dengan backtest dan Pine "QSE Ichimoku TK Awan Trail"):
  LONG : close di atas awan dan Tenkan memotong Kijun ke atas. SHORT kebalikannya.
  SL awal 1.5 ATR dari entry (sejak 19 Okt 2026, sebelumnya 2). Tiap candle 4J tutup: cek SL kena dulu, lalu SL digeser ke puncak - 4 ATR (tidak pernah mundur, sebelumnya 3).
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
# 19 Okt 2026: SL 1.5 ATR dan trailing 4 ATR (dipilih di 2020-2023). Rata R per trade 2024-2026 +0.109 -> +0.147R,
# 2017-2020 +0.265 -> +0.365R, total 2021-2026 1874R -> 3007R, rasio profit/drawdown 5.0 -> 5.9. Win rate turun 38% -> 30%.
SL_ATR, TRAIL_ATR, MAKS_BAR = 1.5, 4.0, 60
TOP_KOIN = 150          # koin paling likuid yang dipantau (backtest memakai koin likuid)
TOP_LIKUID = 20         # sinyal hanya dari 20 koin dengan nilai transaksi 30 hari terbesar
MAKS_BARU = 5           # sinyal baru paling banyak per candle 4J
MAKS_BUKA = 8           # posisi jalur ini paling banyak terbuka bersamaan
BIAYA = 0.0015
BT = ("111 koin perp 2021-2026, sinyal hanya dari 20 koin paling likuid, maks 8 posisi: 3084 trade, WR 38%, PF 1.29, "
      "positif 18 dari 22 kuartal, untung tiap tahun. Risiko 0.5% dengan rem drawdown: +198%, turun terdalam 17.6%, "
      "rugi beruntun terpanjang 24")
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


TELAT_ATR = 0.5          # robot telat lebih dari 30 menit: sinyal tetap dikirim kalau harga belum lari 0.5 ATR
REM_DD_R, REM_RUGI = 16.0, 6      # rem drawdown: uji 5 tahun top 20 likuid, drawdown 28.4% -> 17.6%, profit tetap +198%


def rem():
    """Rem drawdown jalur Ichimoku dari catatan robot: lot setengah saat hasil turun lebih dari 16R dari puncak
    (sekitar 8% modal di risiko 0.5%) atau rugi 6 kali beruntun. Kembali normal setelah keduanya lewat. Return alasan atau ''."""
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


def ST_tpc(it):
    try:
        import qse_strat as ST
        return ST.batas_masuk_teks(it, "ichimoku") + ST.tp_cepat_teks(it, k="ichimoku")
    except Exception:
        return []


def ST_combo(it):
    try:
        import qse_strat as ST
        return ST.combo_teks(it) + ST.mutu_teks(it)
    except Exception:
        return []


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
                it["sl"] = max(it["sl"], it["best"] - it.get("trail_atr", 3.0) * a[k])
        else:
            it["best"] = min(it["best"], l)
            if not np.isnan(a[k]):
                it["sl"] = min(it["sl"], it["best"] + it.get("trail_atr", 3.0) * a[k])
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


def _jalankan(baru_ok=True):
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
    # posisi tetap dikelola dan dicatat untuk semua sinyal, tapi pesan GESER SL dan SELESAI hanya untuk posisi
    # yang benar-benar kamu catat lewat /entry (koin dan arah sama), supaya grup tidak ramai
    try:
        import qse_saya as SY
        pegang = {(v["sym"], v["arah"]) for v in SY.lihat()["open"].values() if v.get("status") in ("TERISI", "TP1")}
    except Exception:
        pegang = set()
    for key, (it, st, R, sl_lama) in hasil.items():
        t = tick.get(it["sym"], it.get("tick", 0.0001))
        kabar = (it["sym"], it["arah"]) in pegang
        if st in ("SL", "WAKTU"):
            _catat_ledger(it, R)
            if not kabar:
                continue
            out.append(f"{'✅' if R > 0 else '🛑'} <b>ICHIMOKU SELESAI  ·  {it['sym']} {it['arah']}  ·  {R:+.2f}R</b>\n"
                       + (f"Harga balik dan kena SL berjalan di sekitar {TG.fp(it['sl'], t)}. Kalau SL di Bybit sudah ikut digeser, "
                          f"posisi sudah tertutup sendiri. Kalau belum, tutup sekarang."
                          if st == "SL" else f"Sudah {MAKS_BAR} candle 4J (10 hari). Tutup posisi sekarang di harga pasar, "
                          f"sekitar {TG.fp(it['close'], t)}.")
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
            if st in ("SL", "WAKTU"):
                dd["open"].pop(key)
                dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
            else:
                dd["open"][key] = it
    _ubah(simpan_kelola)

    # 2. sinyal baru
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
    pindai = list(koin)          # semua koin dipindai untuk peringkat likuiditas 30 hari
    tutup_kini = {it["sym"] for it, st, _, _ in hasil.values() if st in ("SL", "WAKTU")}
    koin = [s for s in koin if s not in {it["sym"] for it in d["open"].values()} and s not in tutup_kini]   # sama backtest

    def cek(sym):
        df = _k4(sym, 300)
        if df is None or len(df) < 120:
            return sym, None, None, None, 0.0
        arah, a = _sinyal(df)
        return sym, arah, a, df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    # hanya koin paling likuid (nilai transaksi 30 hari): uji 5 tahun 111 koin, top 20 PF 1.29 dan drawdown 17.6%,
    # semua koin PF 1.16 dan drawdown 27%. Makin likuid makin bagus (top 20 > 30 > 50 > 80 > semua)
    likuid = {x[0] for x in sorted(semua, key=lambda x: -x[4])[:TOP_LIKUID]}
    boleh = set(koin)
    hasil_s = sorted([x[:4] for x in semua if x[1] and x[0] in likuid and x[0] in boleh],
                     key=lambda x: -next(z[4] for z in semua if z[0] == x[0]))
    import qse_saya as SY
    tahan = {x[0]: SY.cek_lintas(x[0], x[1]) for x in hasil_s}
    for sym, why in tahan.items():
        if why:
            print(f"[ICHIMOKU] {sym} ditahan: {why}")
    hasil_s = [x for x in hasil_s if not tahan[x[0]]]
    now = time.time()
    baru = []
    for sym, arah, a, df in hasil_s[:slot]:          # sudah urut dari koin paling likuid
        px = tk[sym]["last"] or float(df["close"].iloc[-1])
        telat = time.time() * 1000 - (int(df.index[-1]) + H4)
        if telat > 1800000 and abs(px - float(df["close"].iloc[-1])) > TELAT_ATR * a:
            print(f"[ICHIMOKU] {sym} dilewati: robot telat {telat / 60000:.0f} menit dan harga sudah lari dari harga sinyal")
            continue
        import qse_porto as PO
        why = PO.izin(sym, arah, "ichimoku")
        if why:
            print(f"[ICHIMOKU] {sym} ditahan: {why}")
            continue
        L = arah == "LONG"
        risk = SL_ATR * a
        if risk / px > 0.10:  # SL lebih dari 10% dilewati: uji 2021-2026 SL 10-15% PF 1.05, di atas 15% PF 0.75
            print(f"[ICHIMOKU] {sym} dilewati: SL {risk / px * 100:.1f}% lebih dari 10%")
            continue
        try:
            import qse_strat as ST
            sk, mp, mm = ST.mutu(df, arah)
        except Exception as ex:
            print("[WARN] mutu ichimoku", ex)
            sk, mp, mm = 0, [], []
        if mp is not None and len(mp) - len(mm) <= -2:
            print(f"[ICHIMOKU] {sym} dilewati: mutu rendah ({', '.join(mm)})")
            continue
        try:
            import qse_strat as ST
            if ST.pump_tolak(df, arah):
                print(f"[ICHIMOKU] {sym} dilewati: {ST.pump_tolak(df, arah)}")
                continue
            import qse_pagi as PG
            if arah == "SHORT" and PG.short_tahan():
                print(f"[ICHIMOKU] {sym} SHORT dilewati: {PG.short_tahan()}")
                continue
        except Exception as ex:
            print("[WARN] pump ichimoku", ex)
        sl = px - risk if L else px + risk
        t = tick.get(sym, 0.0001)
        it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=risk, best=px, bar=0, t=now, mutu=sk, mutu_plus=mp,
                  last=int(df.index[-1]), close=px, tick=t, sl_atr=SL_ATR, trail_atr=TRAIL_ATR)
        try:
            import qse_strat as ST
            it["combo"] = ST._combo(df, "ichimoku", arah, ST.btc_naik(), sym)
            it["combo_emas"] = ST.combo_emas("ichimoku", it["combo"])
            it["combo_fix"] = ST.combo_fix("ichimoku", it["combo"])
            it["combo_raja"] = ST.combo_raja(it["combo"])
            it["vol_tinggi"] = ST.vol_tinggi()
            if arah == "SHORT":
                import qse_pagi as PG
                it["dom_turun"] = PG.dom_turun("ichimoku", arah)
        except Exception as ex:
            print("[WARN] combo ichimoku", ex)
        import qse_porto as PO_s
        if PO_s.senin_tolak(it.get("combo"), it.get("combo_emas")):
            print(f"[ICHIMOKU] {sym} dilewati: {PO_s.senin_tolak(it.get('combo'), it.get('combo_emas'))}")
            continue
        baru.append(it)
        PO.pesan(sym, arah)
        try:
            import qse_modal as MD
            lot = MD.baris_lot(px, sl)
        except Exception:
            lot = ""
        pc = risk / px * 100
        jarak = TRAIL_ATR * a
        _, tkb, ik, lot_b = SY.boleh_ikut("saran ichimoku", arah)
        import qse_porto as PO
        rm = rem() or PO.rem()
        if rm:
            lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
        lot_b, cat_hari = PO.lot_hari(lot_b)
        try:
            import qse_modal as MD
            lot = MD.baris_lot(px, sl, SY.lot_angka(lot_b))
        except Exception:
            lot = ""
        out.append("\n".join([
            SY.GARIS,
            f"{'🟢' if L else '🔴'} <b>{len(baru)}. {sym} {arah}</b>  ·  Ichimoku 4J",
            f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
            *ST_combo(it),
            *([cat_hari] if cat_hari else []),
            SY.GARIS,
            SY.blok_salin(px, sl, order="MARKET", tick=t, catatan_tp="tidak ada, pakai SL berjalan", sym=sym, arah=arah),
            *ST_tpc(dict(entry=px, sl=sl, arah=arah, tick=t, t=now, risk=risk)),
            *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Tetap boleh entry, pakai lot setengah sampai pulih. Di uji 5 tahun rem ini "
                f"menurunkan drawdown dari 28% ke 18% tanpa mengurangi profit"] if rm else []),
            "💡 <b>Kenapa</b>",
            f"• Tenkan baru memotong Kijun {'ke atas' if L else 'ke bawah'} dan harga {'di atas' if L else 'di bawah'} awan: "
            f"tren {'naik' if L else 'turun'} baru mulai",
            f"• Koin ini termasuk {TOP_LIKUID} koin paling likuid 30 hari terakhir. Makin likuid, makin bagus hasil Ichimoku",
            "• Bukti: uji 5 tahun 111 koin, 3084 trade, PF 1.29, untung tiap tahun, positif 18 dari 22 kuartal",
            "🛠 <b>Cara</b>",
            f"1. Masuk MARKET sekarang. Pasang SL di {TG.fp(sl, t)} ({pc:.1f}% dari entry). Pasang TP sebagian 20% di +0.5R saja "
            f"(lihat baris 💰), setelah kena SL ke entry. Sisanya tanpa TP",
            "2. Tiap candle 4J tutup, robot kirim pesan GESER SL. Ubah SL di Bybit ke angka di pesan itu",
            "3. SL hanya maju searah profit, tidak pernah mundur. Saat harga balik menyentuh SL, posisi tutup sendiri dengan profit yang sudah terkunci",
            "4. Kalau 10 hari belum kena SL, robot mengingatkan untuk tutup manual",
            f"5. Catat dengan /entry supaya pesan GESER SL dikirim. Tanpa /entry, robot tidak mengirim pesan lanjutan untuk koin ini",
            "❓ <b>Kenapa sisanya tanpa TP</b>",
            "Untungnya datang dari sedikit trade yang lari jauh, bisa +3R sampai +10R. TP penuh akan memotong trade besar itu. "
            "TP sebagian 20% di +0.5R lalu SL ke entry menaikkan win rate jalur ini dari 34% ke 70% di uji 2021-2026",
            "📐 Cara mudah: tetap pasang SL awal di atas, lalu tambahkan Trailing Stop di Bybit. Tidak perlu geser SL manual\n"
            + SY.isi_trailing(jarak, sl, t)
            + (f"\n{lot}" if lot else ""),
        ]))

    def simpan_baru(dd):
        for it in baru:
            dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
    if baru:
        _ubah(simpan_baru)
    return out


def status_singkat():
    """Ringkas status jalur Ichimoku untuk laporan 4 jam: slot posisi robot, sinyal terakhir, rem, dan jeda berita."""
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


_ALASAN = [""]


def jalankan(baru_ok=True):
    """Bungkus _jalankan: catat kapan terakhir dicek, jumlah sinyal baru, dan alasan kalau kosong, untuk laporan 4 jam."""
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
    """Contoh: 'dicek 07:03 WIB: 0 sinyal baru, tidak ada koin yang lolos semua syarat'."""
    c = lihat().get("cek")
    if not c:
        return "belum pernah dicek sejak update"
    jam = time.strftime("%H:%M", time.gmtime(c["t"] + 7 * 3600))
    return f"dicek {jam} WIB: {c['n']} sinyal baru" + (f", {c['why']}" if c.get("why") and not c["n"] else "")
