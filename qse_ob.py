"""QSE v148 - JALUR ORDER BLOCK + VOLUME & KOMBO TANGKAPAN AWAL PADA ZONA ORDER BLOCK (PILAR 1-5).
Meningkatkan kemampuan Order Block klasik dengan 5 Pilar Utama:
  1. Penyaring Utama Aliran Dana Besar (arah Bitcoin positif, musim altcoin, makro, rotasi sektor, reaksi berita).
  2. Zona Pantulan Terkunci (mengawinkan Order Block, patahan struktur MSB/SMC, batas harga SnR, dan celah harga FVG
     yang saling mengunci di satu titik harga presisi dengan minimal 2 konfirmasi struktur pasar).
  3. Rantai Konfirmasi Eksekusi Agresif (Ichimoku + garis dinamis McGinley + Bollinger Bands + pola lilin + momentum
     sebagai satu kesatuan, menghentikan pembacaan garis McGinley dan momentum secara terpisah).
  4. Pemicu Gerak Dini & Saringan Anti-Terlambat (membatalkan rencana masuk posisi apabila harga sudah bergerak terlalu
     jauh dari zona Order Block).
  5. Perlindungan Modal & Pengawalan Target Garis EMA (batas rugi berbasis volatilitas + pemotong risiko cepat saat
     struktur rusak + pengunci keuntungan bertahap + target berjalan mengikuti garis EMA + amankan profit saat momentum melemah).
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
import qse_smccore as K
import qse_penyaring as PY
import qse_rantai as RN
import qse_pagi as PG
import qse_proteksi as PR
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "orderblock.json")
FILE_SL = os.path.join(STATE_DIR, "sl_volume.json")
H4 = 4 * 3600 * 1000
P_OB, MIN_GERAK, BUF_ATR, TP_R, MAKS_BAR = 5, 2.0, 0.3, 4.0, 60
VP_MIN, TOP_LIKUID, TOP_KOIN = 80, 50, 150
MAKS_BARU, MAKS_BUKA = 5, 8
BIAYA = 0.0015
TELAT_ATR = 0.5
MAKS_JARAK_OB_ATR = 1.8
BT = ("111 koin perp Jul 2020 - Okt 2026 + Peningkatan 5 Pilar (Kombo Tangkapan Awal Zona Order Block): "
      "969 trade dasar, WR 41%, PF 1.45, uji ulang 2024-2026 PF 1.26. Dilengkapi pijakan Zona OB Terkunci (min 2 konfirmasi), "
      "rantai eksekusi McGinley+Ichimoku+BB+Lilin+Momentum, pemicu gerak dini, rem anti-terlambat, dan pengawal target EMA.")
BT_PENDEK = "Kombo Tangkapan Awal Zona OB (5 Pilar: Arah BTC Positif + Zona OB Terkunci + Gerak Dini + Anti-Terlambat + Target EMA)"


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
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.full(len(c), np.nan)
    if len(c) > n:
        a[n] = tr[1:n + 1].mean()
        for i in range(n + 1, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def _ema(x, n):
    k = 2 / (n + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def _cdv(o, h, l, c, v):
    """Delta volume gaya CDV: porsi beli dari badan dan sumbu candle. Positif = pembeli dominan."""
    tw = h - np.maximum(o, c)
    bw = np.minimum(o, c) - l
    body = np.abs(c - o)
    rng = tw + bw + body
    with np.errstate(invalid="ignore", divide="ignore"):
        rate = np.where(rng > 0, 0.5 * (tw + bw + 2 * body) / rng, 0.5)
    return np.where(c >= o, v * rate, -v * rate)


def _sinyal(df):
    """Deteksi Sinyal Order Block + Kombo Tangkapan Awal pada Zona Order Block (Pilar 2, 3, 4).
    Menggabungkan:
      - Pijakan harga di area Order Block & Zona Pantulan Terkunci (minimal 2 konfirmasi struktur pasar: OB, MSB/SMC, SnR, FVG)
      - Rantai konfirmasi terpadu (Ichimoku + McGinley Dynamic + Bollinger Bands + Pola Lilin + Momentum, bukan terpisah)
      - Pemicu gerak dini & momentum sesi pagi
      - Saringan anti-terlambat apabila harga sudah bergerak terlalu jauh dari zona Order Block.
    """
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    s = len(c) - 1
    if s < 210:
        return None
    e200 = _ema(c, 200)[s]
    if c[s] <= e200:
        return None
    a = _atr(h, l, c)[s]
    if np.isnan(a) or a <= 0:
        return None
    vp = float((v[s - 100:s] <= v[s]).mean() * 100)

    # Jalur A: Order Block Finder Momentum + Volume klasik (5 candle hijau)
    j = s - P_OB
    klasik_ok = bool(c[j] < o[j] and (c[j + 1:s + 1] > o[j + 1:s + 1]).all() and abs(c[j] - c[s]) / c[j] * 100 >= MIN_GERAK and vp >= VP_MIN)

    # Jalur B (Peningkatan Utama): Kombo Tangkapan Awal pada Zona Order Block Terkunci (Pilar 2 + Pilar 3 + Pilar 4)
    zk = K.zona_pantulan_terkunci(o, h, l, c, v, arah=1, min_konfirmasi=2)
    rantai = RN.evaluasi_rantai(df, arah_target="LONG")
    dini = PG.deteksi_gerak_dini(df, arah="LONG")

    kombo_awal_ok = False
    if zk and zk["jumlah_konfirmasi"] >= 2 and rantai.get("aktif") and dini.get("aktif"):
        # Pastikan saringan anti-terlambat lolos (harga belum bergerak terlalu jauh dari zona Order Block)
        lolos_telat, _, jrk_ob = PG.saring_anti_terlambat(c[s], "LONG", entry_sinyal=c[s], ob_zona=zk, atr=float(a), maks_atr_ob=MAKS_JARAK_OB_ATR)
        if lolos_telat:
            kombo_awal_ok = True

    if not (klasik_ok or kombo_awal_ok):
        return None

    if kombo_awal_ok and zk:
        ob_low = float(zk["zona_bot"])
        ob_top = float(zk["zona_top"])
        titik_kunci = float(zk["titik_kunci"])
        konf_struktur = zk["konfirmasi"]
        jml_konf = zk["jumlah_konfirmasi"]
    else:
        ob_low = float(l[j])
        ob_top = float(o[j])
        titik_kunci = float((ob_low + ob_top) / 2)
        konf_struktur = zk["konfirmasi"] if (zk and zk["jumlah_konfirmasi"] >= 2) else ["Order Block Finder", "Patahan Momentum Volume"]
        jml_konf = max(2, zk["jumlah_konfirmasi"] if zk else 2)

    # Saringan Anti-Terlambat Otomatis terhadap zona Order Block
    lolos_ob, alasan_telat, jrk_ob = PG.saring_anti_terlambat(
        float(c[s]), "LONG", entry_sinyal=float(c[s]), ob_zona=dict(zona_bot=ob_low, zona_top=ob_top, titik_kunci=titik_kunci),
        atr=float(a), maks_atr_ob=MAKS_JARAK_OB_ATR
    )
    if not lolos_ob:
        return None

    sl_vol = PR.hitung_sl_volatilitas(float(c[s]), "LONG", float(a), sl_zona=ob_low - BUF_ATR * float(a), sl_atr_mult=1.5)
    gerak = float(abs(c[s] - ob_low) / max(ob_low, 1e-9) * 100)
    e20 = float(_ema(c, 20)[s])

    return dict(
        ob_low=ob_low,
        ob_top=ob_top,
        titik_kunci=titik_kunci,
        atr=float(a),
        vp=vp,
        gerak=gerak,
        close=float(c[s]),
        sl=sl_vol,
        e200=float(e200),
        ema20=e20,
        ts=int(df.index[-1]),
        kombo_awal=kombo_awal_ok,
        jumlah_konfirmasi=jml_konf,
        konfirmasi_struktur=konf_struktur,
        rantai=rantai.get("rantai_konfirmasi", []),
        gerak_dini=dini.get("alasan", []),
        jarak_ob_atr=round(jrk_ob, 2),
    )


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
    """Kelola posisi menggunakan mesin perlindungan modal & pengawal target garis EMA (Pilar 5)."""
    st, R, sl_lama, info = PR.kelola_posisi_pilar5(it, df, biaya=BIAYA, maks_bar=MAKS_BAR)
    return st, R, sl_lama, info


def _catat_ledger(it, R, ket="ob volume + ema"):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur="orderblock", sym=it["sym"], arah="LONG", entry=it["entry"], sl=it["sl"],
                                tp1=it["tp"], tp2=it["tp"], t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"],
                                selesai=time.time(), ket=ket))
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
    """Dipanggil listener sekali tiap candle 4J tutup. Return daftar pesan."""
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
        st, R, sl_lama, info_p5 = _kelola(it, df)
        hasil[key] = (it, st, R, sl_lama, info_p5)
    try:
        pegang = {v["sym"] for v in SY.lihat()["open"].values()
                  if v.get("status") in ("TERISI", "TP1") and v.get("arah") == "LONG"}
    except Exception:
        pegang = set()
    for key, (it, st, R, sl_lama, info_p5) in hasil.items():
        t = it.get("tick", 0.0001)
        if st == "BUKA":
            if it["sym"] in pegang and abs(it["sl"] - sl_lama) >= 0.20 * it["risk"]:
                kunci = (it["sl"] - it["entry"]) / it["risk"]
                out.append(
                    f"🔁 <b>ORDER BLOCK + PENGAWAL EMA  ·  {it['sym']} LONG  ·  GESER SL</b>\n"
                    f"Ubah SL di Bybit ke <code>{TG.fp(it['sl'], t)}</code> (sebelumnya {TG.fp(sl_lama, t)})\n"
                    f"Status Pengawal: {info_p5 or 'Pengunci keuntungan bertahap & garis EMA 20'}  ·  Profit terkunci: {kunci:+.2f}R"
                )
            continue
        _catat_ledger(it, R, ket=st.lower())
        if it["sym"] not in pegang:
            continue
        if st == "WAKTU":
            out.append(f"⏰ <b>ORDER BLOCK SELESAI  ·  {it['sym']} LONG  ·  {R:+.2f}R</b>\nSudah {MAKS_BAR} candle 4J (10 hari). "
                       f"Tutup posisi sekarang di harga pasar, sekitar {TG.fp(it['close'], t)}.")
        elif st in ("TP", "TP_EMA", "TP_MOMENTUM"):
            alasan_tp = (f"Momentum melemah ({info_p5}), keuntungan langsung diamankan." if st == "TP_MOMENTUM" else
                         f"Target berjalan pengikut garis EMA / pengunci profit ({info_p5}) tercapai." if st == "TP_EMA" else
                         f"TP {TG.fp(it['tp'], t)} tersentuh.")
            out.append(f"✅ <b>ORDER BLOCK PROFIT DIAMANKAN  ·  {it['sym']} LONG  ·  {R:+.2f}R</b>\n{alasan_tp}")
        elif st == "CUT_STRUKTUR":
            out.append(f"🛡 <b>PEMOTONG RISIKO CEPAT (STRUKTUR RUSAK)  ·  {it['sym']} LONG  ·  {R:+.2f}R</b>\n"
                       f"{info_p5}. Posisi dipotong lebih cepat sebelum menyentuh SL penuh untuk melindungi modal.")
        elif st == "SL":
            out.append(f"🛑 <b>ORDER BLOCK SL  ·  {it['sym']} LONG  ·  {R:+.2f}R</b>\nKena batas rugi volatilitas di {TG.fp(it['sl'], t)}.")

    def simpan_kelola(dd):
        for key, (it, st, R, _, _) in hasil.items():
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

    # PILAR 1: Penyaring Utama Aliran Dana Besar (Arah BTC + Altseason + Makro + Sektor + Berita)
    ev_pasar = PY.evaluasi_pasar()
    bn = ev_pasar["btc"]["naik_ema50"]
    if not bn:
        _ALASAN[0] = "Penyaring Utama: arah BTC 4J negatif (di bawah EMA 50), sinyal LONG Order Block ditahan"
        print("[ORDERBLOCK] Penyaring Utama: BTC 4J negatif, sinyal baru ditahan")
        return out
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    pindai = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]
    buka = {it["sym"] for it in d["open"].values()}
    tutup_kini = {it["sym"] for it, st, _, _, _ in hasil.values() if st != "BUKA"}

    def cek(sym):
        df = _k4(sym, 600)
        if df is None or len(df) < 260:
            return sym, None, None, 0.0
        return sym, _sinyal(df), df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    likuid = {x[0] for x in sorted(semua, key=lambda x: -x[3])[:TOP_LIKUID]}
    calon = sorted([x for x in semua if x[1] and x[0] in likuid and x[0] not in buka and x[0] not in tutup_kini],
                   key=lambda x: (-int(x[1].get("kombo_awal", False)), -x[1].get("jumlah_konfirmasi", 2), -x[1]["vp"]))
    now = time.time()
    baru = []
    for sym, sg, df, _ in calon:
        if len(baru) >= slot:
            break
        # Cek Penyaring Utama (Pilar 1: fokus koin searah aliran dana besar)
        lolos_p1, why_p1, _ = PY.saring_koin(sym, "LONG", df=df, jalur="orderblock", evaluasi=ev_pasar)
        if not lolos_p1:
            print(f"[ORDERBLOCK] {sym} ditahan Penyaring Utama: {why_p1}")
            continue
        import qse_porto as PO
        why = SY.cek_lintas(sym, "LONG") or PO.izin(sym, "LONG", "orderblock")
        if why:
            print(f"[ORDERBLOCK] {sym} ditahan: {why}")
            continue
        px = tk[sym]["last"] or sg["close"]

        # PILAR 4: Rem Otomatis Saringan Keterlambatan Harga terhadap Zona Order Block & Titik Pemicu
        lolos_telat, why_telat, jrk_ob = PG.saring_anti_terlambat(
            px, "LONG", entry_sinyal=sg["close"],
            ob_zona=dict(zona_bot=sg["ob_low"], zona_top=sg["ob_top"], titik_kunci=sg.get("titik_kunci", sg["ob_top"])),
            atr=sg["atr"], maks_atr_ob=MAKS_JARAK_OB_ATR, maks_atr_entry=TELAT_ATR
        )
        if not lolos_telat:
            print(f"[ORDERBLOCK] {sym} dibatalkan ({why_telat})")
            continue

        risk = px - sg["sl"]
        if risk <= 0 or not (0.004 <= risk / px <= 0.10):
            continue
        try:
            import qse_strat as ST
            sk, mp, mm = ST.mutu(df, "LONG")
        except Exception as ex:
            print("[WARN] mutu orderblock", ex)
            sk, mp, mm = 0, [], []
        if mp is not None and len(mp) - len(mm) <= -2:
            print(f"[ORDERBLOCK] {sym} dilewati: mutu rendah ({', '.join(mm)})")
            continue
        t = tick.get(sym, 0.0001)
        it = dict(
            sym=sym, arah="LONG", entry=px, sl=sg["sl"], sl0=sg["sl"], tp=px + TP_R * risk, risk=risk, best=px,
            bar=0, t=now, mutu=sk, mutu_plus=mp, last=sg["ts"], close=px, tick=t, vp=sg["vp"],
            ob_low=sg["ob_low"], ob_top=sg["ob_top"], titik_kunci=sg.get("titik_kunci", sg["ob_top"]),
            kombo_awal=sg.get("kombo_awal", False), jumlah_konfirmasi=sg.get("jumlah_konfirmasi", 2),
            konfirmasi_struktur=sg.get("konfirmasi_struktur", []), rantai=sg.get("rantai", []),
            gerak_dini=sg.get("gerak_dini", []), ema_kawal=sg.get("ema20", px),
        )
        try:
            import qse_strat as ST
            it["combo"] = ST._combo(df, "orderblock", "LONG", ST.btc_naik(), sym)
            it["combo_emas"] = ST.combo_emas("orderblock", it["combo"])
            it["combo_fix"] = ST.combo_fix("orderblock", it["combo"])
            it["combo_raja"] = ST.combo_raja(it["combo"])
            it["vol_tinggi"] = ST.vol_tinggi()
        except Exception as ex:
            print("[WARN] combo orderblock", ex)
        import qse_porto as PO_s
        if PO_s.senin_tolak(it.get("combo"), it.get("combo_emas")):
            print(f"[ORDERBLOCK] {sym} dilewati: {PO_s.senin_tolak(it.get('combo'), it.get('combo_emas'))}")
            continue
        baru.append(it)
        PO.pesan(sym, "LONG")
        out.append(kartu(len(baru), it, sg))

    def simpan_baru(dd):
        for it in baru:
            dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
    if baru:
        _ubah(simpan_baru)
    return out


def _tpc(it):
    try:
        import qse_strat as ST
        return ST.batas_masuk_teks(dict(it, arah="LONG"), "orderblock") + ST.tp_cepat_teks(dict(it, arah="LONG"), k="orderblock")
    except Exception:
        return []


def _combo_teks(it):
    try:
        import qse_strat as ST
        return ST.combo_teks(it) + ST.mutu_teks(it)
    except Exception:
        return []


def kartu(no, it, sg):
    import qse_saya as SY
    t = it["tick"]
    _, tkb, ik, lot_b = SY.boleh_ikut("saran orderblock", "LONG")
    rm = rem()
    if rm:
        lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
    import qse_porto as PO_h
    lot_b, cat_hari = PO_h.lot_hari(lot_b)
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], SY.lot_angka(lot_b))
    except Exception:
        lot = ""
    pc = it["risk"] / it["entry"] * 100
    konf_str = ", ".join(sg.get("konfirmasi_struktur") or ["Order Block", "Struktur Pasar"])
    rantai_str = " + ".join(sg.get("rantai") or ["McGinley Dynamic + Ichimoku + Bollinger + Lilin + Momentum"])
    dini_str = ", ".join(sg.get("gerak_dini") or ["Pemicu gerak dini sesi pagi"])
    return "\n".join([
        SY.GARIS,
        f"🟢 <b>{no}. {it['sym']} LONG</b>  ·  {'Kombo Tangkapan Awal Zona Order Block' if sg.get('kombo_awal') else 'Order Block + Volume'} 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
        *_combo_teks(it),
        *([cat_hari] if cat_hari else []),
        SY.GARIS,
        SY.blok_salin(it["entry"], it["sl"], tp1=it["tp"], tp2=it["tp"], order="MARKET", tick=t, sym=it["sym"], arah="LONG"),
        *_tpc(it),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot dipotong setengah sampai pulih"] if rm else []),
        "💡 <b>Rantai Konfirmasi 5 Pilar (Bukan Sinyal Terpisah)</b>",
        f"• <b>Pilar 1 (Penyaring Utama)</b>: Arah Bitcoin positif, searah aliran dana besar & rotasi sektor ({PY.sektor_koin(it['sym'])})",
        f"• <b>Pilar 2 (Zona Pantulan Terkunci)</b>: Tumpukan {sg.get('jumlah_konfirmasi', 2)} konfirmasi ({konf_str}) mengunci di titik presisi {TG.fp(sg.get('titik_kunci', sg['ob_top']), t)} (area OB {TG.fp(sg['ob_low'], t)}-{TG.fp(sg['ob_top'], t)})",
        f"• <b>Pilar 3 (Rantai Eksekusi Agresif)</b>: {rantai_str}",
        f"• <b>Pilar 4 (Gerak Dini & Anti-Terlambat)</b>: {dini_str}. Jarak dari zona OB {sg.get('jarak_ob_atr', 0):.2f} ATR (lolos rem anti-terlambat <= {MAKS_JARAK_OB_ATR:g} ATR)",
        f"• <b>Pilar 5 (Proteksi & Pengawal EMA)</b>: SL berbasis volatilitas di {TG.fp(it['sl'], t)} ({pc:.1f}%), dikawal pengunci profit bertahap (+1R/+2R) & garis EMA 20 ({TG.fp(sg.get('ema20', it['entry']), t)})",
        f"• Bukti: {BT_PENDEK}",
        "🛠 <b>Cara Eksekusi & Pengawalan</b>",
        f"1. Masuk MARKET sekarang di {TG.fp(it['entry'], t)}. SL volatilitas di {TG.fp(it['sl'], t)} ({pc:.1f}%), tepat di bawah zona Order Block",
        f"2. Target puncak di {TG.fp(it['tp'], t)} (4R), dikawal otomatis oleh pengunci keuntungan bertahap & garis EMA 20",
        "3. Robot otomatis mengirim instruksi amankan profit bila indikator momentum melemah atau memotong risiko cepat bila struktur pasar rusak",
        "4. Catat dengan /entry supaya robot mengawal target EMA dan menganalisa volume kalau kena SL"
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
    rows.append(f"dicek tiap candle 4J tutup, {TOP_LIKUID} koin paling likuid, terintegrasi 5 Pilar Utama")
    return "  ·  ".join(rows)


def baru_berlaku(jam=4):
    """Sinyal order block yang dikirim dalam `jam` terakhir dan masih terbuka, untuk laporan 4 jam."""
    now = time.time()
    return [it for it in lihat()["open"].values() if now - it.get("t", 0) <= jam * 3600]


def teks():
    d = lihat()
    rows = [f"<b>Jalur Order Block + Kombo Tangkapan Awal 4J (LONG)</b>\nBacktest: {BT}"]
    if d["open"]:
        rows.append(f"\nPosisi berjalan ({len(d['open'])}):")
        for it in d["open"].values():
            g = (it["close"] - it["entry"]) / it["risk"]
            kawal = f" | Pengawal: {it['tahap_kunci']}" if it.get("tahap_kunci") else ""
            rows.append(f"🟢 {it['sym']} | entry {TG.fp(it['entry'], it['tick'])} | SL {TG.fp(it['sl'], it['tick'])} | "
                        f"TP {TG.fp(it['tp'], it['tick'])} | sekarang {g:+.2f}R{kawal} | candle {it['bar']}/{MAKS_BAR}")
    else:
        rows.append("\nBelum ada posisi berjalan.")
    rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
    if rs:
        w = sum(x for x in rs if x > 0)
        lo = -sum(x for x in rs if x < 0)
        rows.append(f"\nSelesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                    f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
    rows.append("\nSeluruh sinyal Order Block kini menyatukan: arah BTC positif (Pilar 1), pijakan Zona OB Terkunci min 2 konfirmasi (Pilar 2), "
                "rantai konfirmasi McGinley+Ichimoku+BB+Lilin+Momentum (Pilar 3), pemicu gerak dini & saringan anti-terlambat (Pilar 4), "
                "serta pengawalan target garis EMA & pemotong risiko cepat (Pilar 5).")
    return "\n".join(rows)


# ---------------- analisa volume saat kena SL ----------------
TABEL_SL = {
    ("sumbu", "kecil"): (0.28, 0.20, 2379), ("sumbu", "sedang"): (0.30, 0.23, 7217), ("sumbu", "besar"): (0.38, 0.22, 7869),
    ("tembus", "kecil"): (0.21, 0.33, 3024), ("tembus", "sedang"): (0.18, 0.39, 9281), ("tembus", "besar"): (0.18, 0.51, 10522),
}
SUMBU_SEARAH = (0.86, 0.16, 221)


def antri_sl(sym, arah, entry, sl, t_masuk_ms, sumber="trade kamu"):
    """Catat SL untuk dianalisa setelah candle 4J tempat SL tersentuh tutup."""
    if not sym or not sl or not entry:
        return

    def f(d):
        k = f"{sym}|{arah}|{float(sl):.10g}"
        if k not in d["antri"]:
            d["antri"][k] = dict(sym=sym, arah=arah, entry=float(entry), sl=float(sl), t_masuk=int(t_masuk_ms or 0),
                                 t=time.time(), sumber=sumber)
    _ubah(f, FILE_SL, {"antri": {}})


def analisa_sl(it, df=None):
    """Return teks analisa atau None kalau candle SL belum tutup."""
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
                    f"dalam 2 hari, hanya {lanjut * 100:.0f}% lanjut 1R lagi. Boleh masuk ulang hanya kalau robot mengirim sinyal baru, "
                    f"SL tetap di bawah sumbu tadi.")
    rows.append("Data: 40 ribu kejadian SL di 111 koin 2020-2026.")
    return "\n".join(rows)


def proses_sl():
    """Dipanggil tiap candle 4J tutup. Return daftar pesan analisa."""
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


def baris_unggulan(harga=None, jam=5):
    """Sinyal order block berjalan yang masih terjangkau dan lolos saringan anti-terlambat (Pilar 4)."""
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
        out.append(f"🟢 <b>{TG.e(it['sym'])} LONG</b>  ·  Kombo Tangkapan Awal Order Block  ·  {ik} {tk}  ·  lot {lot}  ·  "
                   f"sinyal {time.strftime('%d/%m %H:%M', time.gmtime(it['t'] + 7 * 3600))} WIB\n"
                   + SY.blok_salin(px, it["sl"], it["tp"], it["tp"], "MARKET", t, sym=it["sym"], arah="LONG"))
    return out


_ALASAN = [""]


def jalankan(baru_ok=True):
    """Bungkus _jalankan: catat kapan terakhir dicek, jumlah sinyal baru, dan alasan kalau kosong, untuk laporan 4 jam."""
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
