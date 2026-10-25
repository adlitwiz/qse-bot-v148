"""QSE v148 - JALUR ICHIMOKU TREN + RANTAI EKSEKUSI 5 PILAR (candle 4J).
Ditingkatkan dengan 5 Pilar Utama:
  1. Penyaring Utama Aliran Dana Besar (fokus koin searah aliran dana besar & kondisi pasar kuat/penembusan).
  2. Konfirmasi Zona Pantulan/Struktur Terkunci (minimal 2 konfirmasi struktur pasar bila dekat zona OB/SnR/MSB/FVG).
  3. Rantai Konfirmasi Eksekusi (Ichimoku TK cross di luar awan yang menyatu dengan garis dinamis McGinley, Bollinger Bands,
     pola lilin, dan dorongan momentum penutupan lilin).
  4. Pemicu Gerak Dini & Rem Otomatis Saringan Anti-Terlambat (batal jika harga sudah bergerak terlalu jauh dari zona Order Block).
  5. Perlindungan Modal & Pengawalan Garis EMA (SL volatilitas + pemotong risiko cepat saat struktur pasar rusak +
     pengunci keuntungan bertahap + target berjalan mengikuti garis EMA + amankan profit saat momentum melemah).
"""
import fcntl
import json
import os
import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import bybit_fetch as B
import telegram_notify as TG
import qse_penyaring as PY
import qse_rantai as RN
import qse_pagi as PG
import qse_proteksi as PR
import qse_smccore as K
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "ichimoku.json")
H4 = 4 * 3600 * 1000
SL_ATR, TRAIL_ATR, MAKS_BAR = 1.5, 4.0, 60
TOP_KOIN = 150
TOP_LIKUID = 20
MAKS_BARU = 5
MAKS_BUKA = 8
BIAYA = 0.0015
BT = ("111 koin perp 2021-2026, sinyal hanya dari 20 koin paling likuid, maks 8 posisi: 3084 trade, WR 38%, PF 1.29, "
      "positif 18 dari 22 kuartal, untung tiap tahun. Ditingkatkan dengan Rantai Konfirmasi 5 Pilar, Rem Anti-Terlambat, "
      "dan Pengawal Target Garis EMA")
BT_PENDEK = "111 koin perp 2021-2026, 20 koin paling likuid: PF 1.29 + Rantai Konfirmasi 5 Pilar"


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
        a[n - 1] = tr[:n].mean()
        for i in range(n, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def _hh(x, n):
    return pd.Series(x).rolling(n).max().values


def _ll(x, n):
    return pd.Series(x).rolling(n).min().values


TELAT_ATR = 0.5
MAKS_JARAK_OB_ATR = 1.8
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
    """Sinyal di candle tutup terakhir yang diikat dengan Rantai Konfirmasi Pilar 3. Return (arah atau None, atr)."""
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
    arah = None
    if c[i] > max(sa[i], sb[i]) and tk[i] > kj[i] and tk[i - 1] <= kj[i - 1]:
        arah = "LONG"
    elif c[i] < min(sa[i], sb[i]) and tk[i] < kj[i] and tk[i - 1] >= kj[i - 1]:
        arah = "SHORT"
    if arah is None:
        return None, float(a[i])
    # Pilar 3: Pastikan rantai konfirmasi (McGinley + Bollinger + Lilin + Momentum) tidak berlawanan
    if len(c) >= 220:
        rn = RN.evaluasi_rantai(df, arah_target=arah)
        if not rn.get("aktif"):
            return None, float(a[i])
    return arah, float(a[i])


def _k4(sym, bars=300):
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] ichimoku {sym}: {ex}")
        return None


def _kelola(it, df):
    """Jalankan aturan keluar terpadu Pilar 5 (SL volatilitas + pemotong risiko cepat + pengunci bertahap + pengawal EMA + momentum)."""
    st, R, sl_lama, info_p5 = PR.kelola_posisi_pilar5(it, df, biaya=BIAYA, maks_bar=MAKS_BAR)
    return st, R, sl_lama, info_p5


def _catat_ledger(it, R, ket="trailing + ema"):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur="ichimoku", sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"],
                                tp1=0.0, tp2=0.0, t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"],
                                selesai=time.time(), ket=ket))
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
    # 1. kelola posisi terbuka
    buka = dict(d["open"])
    hasil = {}
    for key, it in buka.items():
        df = _k4(it["sym"], 220)
        if df is None or not len(df):
            continue
        it = dict(it)
        st, R, sl_lama, info_p5 = _kelola(it, df)
        hasil[key] = (it, st, R, sl_lama, info_p5)
    try:
        import qse_saya as SY
        pegang = {(v["sym"], v["arah"]) for v in SY.lihat()["open"].values() if v.get("status") in ("TERISI", "TP1")}
    except Exception:
        pegang = set()
    for key, (it, st, R, sl_lama, info_p5) in hasil.items():
        t = tick.get(it["sym"], it.get("tick", 0.0001))
        kabar = (it["sym"], it["arah"]) in pegang
        if st != "BUKA":
            _catat_ledger(it, R, ket=st.lower())
            if not kabar:
                continue
            out.append(f"{'✅' if R > 0 else '🛑'} <b>ICHIMOKU SELESAI ({st})  ·  {it['sym']} {it['arah']}  ·  {R:+.2f}R</b>\n"
                       + (f"Keuntungan diamankan otomatis saat momentum melemah ({info_p5})." if st == "TP_MOMENTUM" else
                          f"Pemotong risiko cepat aktif ({info_p5}) sebelum kena SL penuh." if st == "CUT_STRUKTUR" else
                          f"Harga menyentuh pengawal SL/EMA ({info_p5 or 'SL berjalan'}) di sekitar {TG.fp(it['sl'], t)}."
                          if st in ("SL", "TP_EMA") else f"Sudah {MAKS_BAR} candle 4J (10 hari). Tutup posisi sekarang di harga pasar, "
                          f"sekitar {TG.fp(it['close'], t)}.")
                       + f"\nEntry tadi {TG.fp(it['entry'], t)}.")
        elif kabar and abs(it["sl"] - sl_lama) >= 0.20 * it["risk"]:
            L = it["arah"] == "LONG"
            kunci = ((it["sl"] - it["entry"]) if L else (it["entry"] - it["sl"])) / it["risk"]
            out.append(f"🔁 <b>ICHIMOKU + PENGAWAL EMA  ·  {it['sym']} {it['arah']}  ·  GESER SL</b>\n"
                       f"Ubah SL di Bybit ke <code>{TG.fp(it['sl'], t)}</code> (sebelumnya {TG.fp(sl_lama, t)})\n"
                       f"Pengawal: {info_p5 or 'Trailing ATR & Garis EMA 20'}  ·  Profit aman: {kunci:+.2f}R  ·  hari ke-{it['bar'] // 6 + 1} dari 10")

    def simpan_kelola(dd):
        for key, (it, st, R, _, _) in hasil.items():
            if key not in dd["open"]:
                continue
            if st != "BUKA":
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
    ev_pasar = PY.evaluasi_pasar()
    koin = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]
    pindai = list(koin)
    tutup_kini = {it["sym"] for it, st, _, _, _ in hasil.values() if st != "BUKA"}
    koin = [s for s in koin if s not in {it["sym"] for it in d["open"].values()} and s not in tutup_kini]

    def cek(sym):
        df = _k4(sym, 300)
        if df is None or len(df) < 220:
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
    for sym, why in tahan.items():
        if why:
            print(f"[ICHIMOKU] {sym} ditahan: {why}")
    hasil_s = [x for x in hasil_s if not tahan[x[0]]]
    now = time.time()
    baru = []
    for sym, arah, a, df in hasil_s[:slot]:
        # Pilar 1: Penyaring Utama Aliran Dana Besar
        lolos_p1, why_p1, _ = PY.saring_koin(sym, arah, df=df, jalur="ichimoku", evaluasi=ev_pasar)
        if not lolos_p1:
            print(f"[ICHIMOKU] {sym} {arah} ditahan Penyaring Utama: {why_p1}")
            continue
        px = tk[sym]["last"] or float(df["close"].iloc[-1])
        # Pilar 2 & 4: Cek zona Order Block terkunci dan rem otomatis saringan anti-terlambat
        o_v, h_v, l_v, c_v, v_v = (df[k_].values.astype(float) for k_ in ("open", "high", "low", "close", "volume"))
        zk = K.zona_pantulan_terkunci(o_v, h_v, l_v, c_v, v_v, arah=1 if arah == "LONG" else -1, min_konfirmasi=2)
        lolos_telat, why_telat, _ = PG.saring_anti_terlambat(
            px, arah, entry_sinyal=float(df["close"].iloc[-1]), ob_zona=zk, atr=a,
            maks_atr_ob=MAKS_JARAK_OB_ATR, maks_atr_entry=TELAT_ATR
        )
        if not lolos_telat:
            print(f"[ICHIMOKU] {sym} dilewati ({why_telat})")
            continue
        import qse_porto as PO
        why = PO.izin(sym, arah, "ichimoku")
        if why:
            print(f"[ICHIMOKU] {sym} ditahan: {why}")
            continue
        L = arah == "LONG"
        sl = PR.hitung_sl_volatilitas(px, arah, a, sl_zona=zk["sl"] if zk else None, sl_atr_mult=SL_ATR)
        risk = abs(px - sl)
        if risk / px > 0.10 or risk / px < 0.003:
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
            if arah == "SHORT" and PG.short_tahan():
                print(f"[ICHIMOKU] {sym} SHORT dilewati: {PG.short_tahan()}")
                continue
        except Exception as ex:
            print("[WARN] pump ichimoku", ex)
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
        except Exception as ex:
            print("[WARN] combo ichimoku", ex)
        import qse_porto as PO_s
        if PO_s.senin_tolak(it.get("combo"), it.get("combo_emas")):
            print(f"[ICHIMOKU] {sym} dilewati: {PO_s.senin_tolak(it.get('combo'), it.get('combo_emas'))}")
            continue
        baru.append(it)
        PO.pesan(sym, arah)
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
            f"{'🟢' if L else '🔴'} <b>{len(baru)}. {sym} {arah}</b>  ·  Ichimoku + Rantai 5 Pilar 4J",
            f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
            *ST_combo(it),
            *([cat_hari] if cat_hari else []),
            SY.GARIS,
            SY.blok_salin(px, sl, order="MARKET", tick=t, catatan_tp="dikawal Pengunci Profit Bertahap & Garis EMA 20", sym=sym, arah=arah),
            *ST_tpc(dict(entry=px, sl=sl, arah=arah, tick=t, t=now, risk=risk)),
            *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot dipotong setengah sampai pulih"] if rm else []),
            "💡 <b>Kenapa (Rantai 5 Pilar)</b>",
            f"• Tenkan memotong Kijun {'ke atas' if L else 'ke bawah'} di luar awan, menyatu dalam rantai McGinley Dynamic + Bollinger Bands + Lilin + Momentum",
            f"• Lolos Penyaring Utama aliran dana besar, rem anti-terlambat dari zona OB, dan dikawal target berjalan garis EMA 20",
            f"• Koin termasuk {TOP_LIKUID} koin paling likuid 30 hari terakhir. Bukti: {BT_PENDEK}",
            "🛠 <b>Cara</b>",
            f"1. Masuk MARKET sekarang. Pasang SL volatilitas di {TG.fp(sl, t)} ({pc:.1f}% dari entry)",
            "2. Tiap candle 4J tutup, robot mengawal posisi dengan pengunci keuntungan bertahap, target garis EMA 20, dan pemotong risiko cepat bila struktur rusak",
            "3. Bila indikator momentum menunjukkan pelemahan tenaga, robot langsung mengamankan keuntungan",
            "📐 Trailing Stop Bybit cadangan:\n"
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
    rows.append(f"dicek tiap candle 4J tutup, hanya {TOP_LIKUID} koin paling likuid (Rantai 5 Pilar)")
    return "  ·  ".join(rows)


def teks():
    d = lihat()
    rows = [f"<b>Jalur Ichimoku Tren + Rantai 5 Pilar 4J</b>\nBacktest: {BT}"]
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
    _ALASAN[0] = ""
    out = _jalankan(baru_ok)
    n = sum(1 for m in out if "BISA DIIKUTI" in m)
    why = _ALASAN[0] or ("" if n else "tidak ada koin yang lolos semua syarat 5 pilar")

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
