"""QSE v148 - PENYARING UTAMA ALIRAN DANA BESAR (PILAR 1).
Menyatukan 5 kemampuan pembacaan menjadi satu penyaring utama:
  1. Pembacaan arah Bitcoin (qse_btcarah: 9 teknik di 1W, 1D, 4J, EMA 50 resmi, sentimen FnG & funding)
  2. Musim altcoin (qse_altseason: indeks keranjang 9 altcoin besar vs BTC 7 hari & 30 hari)
  3. Kondisi makro (qse_makro: US Treasury 10Y yield DGS10 & indeks dolar DTWEXBGS)
  4. Rotasi sektor (kekuatan relatif 7 hari & 30 hari di 8 sektor: L1, L2, DEFI, ORACLE, MEME, AI, GAME, DEPIN)
  5. Reaksi berita (qse_news & qse_berita: dampak berita 24 kategori sejarah + kalender USD berdampak tinggi)

Fungsi utama:
- Mengunci fokus robot hanya pada koin yang searah dengan aliran dana besar (smart money / big flow).
- Otomatis mengaktifkan Kombo Strategi Penembusan (Breakout) saat pasar kuat (ADX >= 22 / skor aliran tinggi)
  dan Kombo Strategi Pantulan (Bounce) saat pasar mendatar (ADX < 22 / sideways).
"""
import json
import os
import time
import numpy as np
import pandas as pd
import bybit_fetch as B
import qse_btcarah as BA
import qse_altseason as AS
import qse_makro as MK
import qse_berita as BR
import qse_news as NW
from config import STATE_DIR

CACHE_FILE = os.path.join(STATE_DIR, "penyaring_utama.json")

# Pemetaan sektor koin (sama dengan riset/orderblock/sektor.py)
SEKTOR_KOIN = {}
for _sec, _cs in {
    "L1": "ADA ALGO APT ATOM AVAX BCH CELO CFX CKB DOT EGLD ETC HBAR ICP ICX IOTA KAVA KSM LTC MINA NEAR NEO ONE ONT QTUM ROSE SEI SOL SUI TRX VET XLM XRP XTZ ZIL DASH RVN ZEC TIA INJ TON",
    "L2": "ARB OP IMX LRC SKL STX MANTA STRK ZK",
    "DEFI": "1INCH AAVE COMP CRV DYDX GMX JUP KNC LDO PENDLE SNX SUSHI UNI YFI ZRX RUNE ENA WOO UMA HYPE",
    "ORACLE": "API3 BAND LINK PYTH TRB GRT",
    "MEME": "1000BONK 1000FLOKI 1000PEPE 1000SHIB DOGE WIF BOME MEME",
    "AI": "FET WLD NMR ARPA IOTX RENDER TAO AKT",
    "GAME": "ALICE APE AXS ENJ GALA GMT MANA SAND HOOK CHZ THETA",
    "DEPIN": "AR FIL STORJ ANKR JASMY",
}.items():
    for _c in _cs.split():
        SEKTOR_KOIN[_c + "USDT"] = _sec

# Pengelompokan kombo strategi berdasarkan rezim pasar
KOMBO_PENEMBUSAN = {"ichimoku", "msb_hpz", "ob_terpadu", "orderblock", "rantai_eksekusi", "kombo_ob_awal", "rsi_vol", "ema_short"}
KOMBO_PANTULAN = {"snr_vol", "smc_choch", "GZH", "mcginley", "ob_terpadu", "kombo_ob_awal", "rantai_eksekusi"}

_MEM_CACHE = {}


def sektor_koin(sym):
    return SEKTOR_KOIN.get(sym, "UMUM")


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _adx_4j(df, n=14):
    if df is None or len(df) < 50:
        return 20.0
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    tr = np.r_[h[0] - l[0], np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))]
    sm = lambda z: pd.Series(z).ewm(alpha=1 / n, adjust=False).mean().values
    a = np.maximum(sm(tr), 1e-12)
    up = np.r_[0, h[1:] - h[:-1]]
    dn = np.r_[0, l[:-1] - l[1:]]
    pdi = 100 * sm(np.where((up > dn) & (up > 0), up, 0)) / a
    mdi = 100 * sm(np.where((dn > up) & (dn > 0), dn, 0)) / a
    adx = sm(100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9))[-1]
    return float(adx)


def hitung_rotasi_sektor(df_map=None):
    """Hitung kekuatan relatif 7 hari (42 candle 4J) per sektor dibanding rata-rata pasar."""
    now = time.time()
    if "rotasi" in _MEM_CACHE and now - _MEM_CACHE["rotasi"][0] < 1800 and df_map is None:
        return _MEM_CACHE["rotasi"][1]
    ret7 = {}
    if df_map:
        for sym, df in df_map.items():
            if df is not None and len(df) >= 45:
                c = df["close"].values.astype(float)
                ret7[sym] = (c[-1] / c[-43] - 1) * 100
    else:
        try:
            tk = B.get_tickers()
            top = sorted([s for s in tk if s.endswith("USDT")], key=lambda s: -tk[s]["turnover"])[:60]
            for sym in top:
                try:
                    df = B._raw(sym, "240", 50)
                    if df is not None and len(df) >= 44:
                        c = df["close"].values.astype(float)
                        ret7[sym] = (c[-2] / c[-44] - 1) * 100
                except Exception:
                    continue
        except Exception:
            pass
    if not ret7:
        return {"mkt7": 0.0, "sektor": {}, "kuat": [], "lemah": []}
    mkt7 = float(np.mean(list(ret7.values())))
    sec_vals = {}
    for sym, r in ret7.items():
        sec = sektor_koin(sym)
        if sec != "UMUM":
            sec_vals.setdefault(sec, []).append(r)
    sektor_rs = {sec: round(float(np.mean(vals) - mkt7), 2) for sec, vals in sec_vals.items() if vals}
    urut = sorted(sektor_rs.items(), key=lambda z: -z[1])
    kuat = [s for s, v in urut if v >= 1.5]
    lemah = [s for s, v in urut if v <= -1.5]
    out = {"mkt7": round(mkt7, 2), "sektor": sektor_rs, "kuat": kuat, "lemah": lemah}
    _MEM_CACHE["rotasi"] = (now, out)
    return out


def evaluasi_pasar(df_btc=None, df_map=None, force=False):
    """Satukan 5 pilar pembacaan pasar menjadi satu kesimpulan penyaring utama:
    1. Arah Bitcoin (1W, 1D, 4J + EMA 50 + ADX)
    2. Musim Altcoin (rasio alt/BTC 7h & BTC 30h)
    3. Kondisi Makro (yield 10Y & DXY)
    4. Rotasi Sektor (sektor terkuat & terlemah)
    5. Reaksi Berita (berita berdampak tinggi & arah sentimen berita)
    """
    now = time.time()
    if not force and "pasar" in _MEM_CACHE and now - _MEM_CACHE["pasar"][0] < 300:
        return _MEM_CACHE["pasar"][1]

    # 1. Pembacaan Arah Bitcoin
    btc_skor = {"1W": 0, "1D": 0, "4J": 0}
    btc_naik_ema50 = True
    btc_adx = 22.0
    btc_kond = "lain"
    try:
        if df_btc is None:
            df_btc = B._raw("BTCUSDT", "240", 400)
            if df_btc is not None:
                df_btc = df_btc[df_btc.index + 4 * 3600000 <= int(now * 1000)]
        if df_btc is not None and len(df_btc) >= 100:
            c = df_btc["close"].values.astype(float)
            e50 = _ema(c, 50)
            btc_naik_ema50 = bool(c[-1] > e50[-1])
            btc_adx = _adx_4j(df_btc)
            _, s4, _ = BA._teknik(df_btc)
            btc_skor["4J"] = int(s4)
        for nm, iv, n in (("1W", "W", 260), ("1D", "D", 400)):
            dfb = BA._ambil(iv, n)
            if dfb is not None:
                _, sb, _ = BA._teknik(dfb)
                btc_skor[nm] = int(sb)
        btc_kond = BA._kondisi(btc_skor["1W"], btc_skor["1D"], btc_skor["4J"])
    except Exception as ex:
        print("[WARN] penyaring btc:", ex)

    # Arah utama BTC (+1 positif/bullish, -1 negatif/bearish, 0 netral/mendatar)
    total_skor_btc = btc_skor["1W"] + btc_skor["1D"] + btc_skor["4J"]
    btc_arah = 1 if (btc_naik_ema50 and total_skor_btc >= 0) else (-1 if (not btc_naik_ema50 and total_skor_btc <= 0) else (1 if btc_naik_ema50 else -1))

    # 2. Musim Altcoin
    alt_info = {"rezim": "netral", "rasio7": 0.0, "btc30": 0.0, "boleh_long_alt": True}
    try:
        m_alt = AS.ukur()
        if m_alt:
            kn, bn = m_alt["rasio7"] > 0, m_alt["btc30"] > 0
            if kn and bn:
                rez_a, boleh_a = "MUSIM ALT KUAT (alt & BTC naik)", True
            elif kn and not bn:
                rez_a, boleh_a = "JEBAKAN ALT (alt naik saat BTC turun)", False
            elif bn:
                rez_a, boleh_a = "DOMINASI BTC NAIK (alt selektif)", True
            else:
                rez_a, boleh_a = "PASAR LEMAH (alt & BTC turun)", False
            alt_info = {
                "rezim": rez_a,
                "rasio7": round(float(m_alt["rasio7"]), 2),
                "btc30": round(float(m_alt["btc30"]), 2),
                "boleh_long_alt": boleh_a,
            }
    except Exception as ex:
        print("[WARN] penyaring altseason:", ex)

    # 3. Kondisi Makro
    makro_info = {"rezim": "NETRAL", "pengali_lot_long": 1.0, "yield10": None, "d5": None}
    try:
        st_m = MK.status()
        if st_m:
            makro_info = {
                "rezim": st_m.get("rezim", "NETRAL"),
                "pengali_lot_long": 0.5 if st_m.get("rezim") == "TEKANAN MAKRO" else (1.2 if st_m.get("rezim") == "MAKRO LONGGAR" else 1.0),
                "yield10": st_m.get("yield10"),
                "d5": st_m.get("d5"),
            }
    except Exception as ex:
        print("[WARN] penyaring makro:", ex)

    # 4. Rotasi Sektor
    rotasi = hitung_rotasi_sektor(df_map)

    # 5. Reaksi Berita
    berita_info = {"jeda_aktif": False, "judul_jeda": "", "arah_berita": 0, "kategori_terbaru": []}
    try:
        jd = BR.jeda()
        if jd:
            berita_info["jeda_aktif"] = True
            berita_info["judul_jeda"] = jd.get("judul", "Berita USD High Impact")
        c_nw = NW._load()
        kat_list = []
        arah_b = 0
        for it in (c_nw.get("riwayat") or [])[-10:]:
            k = it.get("kat")
            if k:
                kat_list.append(k)
                arah_b += NW.arah_sejarah(k)
        berita_info["arah_berita"] = 1 if arah_b > 0 else (-1 if arah_b < 0 else 0)
        berita_info["kategori_terbaru"] = kat_list[-3:]
    except Exception as ex:
        print("[WARN] penyaring berita:", ex)

    # Penentuan Rezim Pasar: PASAR KUAT (Breakout) vs PASAR MENDATAR (Bounce)
    pasar_kuat = bool(btc_adx >= 22.0 or abs(total_skor_btc) >= 9)
    mode_kombo = "PENEMBUSAN" if pasar_kuat else "PANTULAN"
    strategi_aktif = sorted(KOMBO_PENEMBUSAN if pasar_kuat else KOMBO_PANTULAN)

    # Aliran dana besar keseluruhan (+1 Bullish / Masuk, -1 Bearish / Keluar, 0 Campur)
    skor_dana = btc_arah * 2
    if alt_info["rasio7"] > 0 and alt_info["btc30"] > 0:
        skor_dana += 1
    elif not alt_info["boleh_long_alt"] and btc_arah < 0:
        skor_dana -= 1
    if makro_info["rezim"] == "TEKANAN MAKRO":
        skor_dana -= 1
    elif makro_info["rezim"] == "MAKRO LONGGAR":
        skor_dana += 1
    if berita_info["arah_berita"] != 0:
        skor_dana += berita_info["arah_berita"]

    arah_dana_besar = "LONG" if skor_dana > 0 else ("SHORT" if skor_dana < 0 else ("LONG" if btc_naik_ema50 else "SHORT"))

    hasil = {
        "ts": now,
        "btc": {
            "arah": "POSITIF (NAIK)" if btc_naik_ema50 else "NEGATIF (TURUN)",
            "naik_ema50": btc_naik_ema50,
            "skor_tf": btc_skor,
            "kondisi": BA.NAMA_KOND.get(btc_kond, btc_kond),
            "adx_4j": round(btc_adx, 1),
        },
        "altseason": alt_info,
        "makro": makro_info,
        "rotasi_sektor": rotasi,
        "reaksi_berita": berita_info,
        "skor_aliran_dana": skor_dana,
        "arah_dana_besar": arah_dana_besar,
        "kondisi_pasar": "PASAR KUAT (TRENDING)" if pasar_kuat else "PASAR MENDATAR (SIDEWAYS)",
        "mode_kombo": mode_kombo,
        "strategi_aktif": strategi_aktif,
    }
    _MEM_CACHE["pasar"] = (now, hasil)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(CACHE_FILE + ".tmp", "w") as f:
            json.dump(hasil, f)
        os.replace(CACHE_FILE + ".tmp", CACHE_FILE)
    except Exception:
        pass
    return hasil


def saring_koin(sym, arah, df=None, jalur=None, evaluasi=None):
    """Kunci fokus robot hanya pada koin yang searah dengan aliran dana besar dan sesuai rezim kombo strategi.
    Return (lolos: bool, alasan: str, detail: dict).
    """
    ev = evaluasi or evaluasi_pasar()
    L = arah == "LONG"

    # 1. Cek jeda berita berdampak tinggi
    if ev["reaksi_berita"]["jeda_aktif"]:
        return False, f"ditahan jeda reaksi berita besar ({ev['reaksi_berita']['judul_jeda']})", ev

    # 2. Cek keselarasan dengan aliran dana besar & arah BTC
    btc_up = ev["btc"]["naik_ema50"]
    if L and not btc_up and ev["skor_aliran_dana"] < 0:
        return False, "aliran dana besar & arah BTC sedang NEGATIF (fokus terkunci pada SHORT / tahan LONG)", ev
    if (not L) and btc_up and ev["skor_aliran_dana"] >= 2:
        return False, "aliran dana besar & arah BTC sedang POSITIF kuat (fokus terkunci pada LONG)", ev

    # 3. Cek jebakan musim altcoin untuk LONG altcoin
    if L and sym != "BTCUSDT" and ev["altseason"]["rezim"].startswith("JEBAKAN ALT"):
        return False, "musim altcoin mendeteksi JEBAKAN ALT (alt naik saat BTC turun), LONG altcoin dikunci", ev

    # 4. Cek rotasi sektor & aliran dana pada koin (CDV / relatif 7 hari)
    sec = sektor_koin(sym)
    rs_sec = ev["rotasi_sektor"]["sektor"].get(sec, 0.0)
    if L and sec in ev["rotasi_sektor"]["lemah"] and rs_sec < -3.0:
        return False, f"rotasi sektor {sec} sedang lemah ({rs_sec:+.1f}% vs pasar), dana besar keluar dari sektor ini", ev
    if (not L) and sec in ev["rotasi_sektor"]["kuat"] and rs_sec > 3.0:
        return False, f"rotasi sektor {sec} sedang sangat kuat ({rs_sec:+.1f}% vs pasar), jangan melawan aliran dana sektor", ev

    # 5. Cek aliran dana langsung pada koin (EMA 200 + volume / CDV) bila df tersedia
    mode_lokal = ev["mode_kombo"]
    if df is not None and len(df) >= 205:
        c = df["close"].values.astype(float)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        o = df["open"].values.astype(float)
        v = df["volume"].values.astype(float)
        e200 = _ema(c, 200)[-1]
        if (L and c[-1] < e200) or ((not L) and c[-1] > e200):
            return False, f"koin {sym} melawan aliran tren besar EMA 200 4J", ev
        # Cek ADX lokal koin untuk menyempurnakan rezim penembusan vs pantulan
        adx_koin = _adx_4j(df)
        if adx_koin >= 25.0:
            mode_lokal = "PENEMBUSAN"
        elif adx_koin < 18.0:
            mode_lokal = "PANTULAN"
        # Cek aliran CDV 20 bar agar searah dana besar
        tw = h - np.maximum(o, c)
        bw = np.minimum(o, c) - l
        body = np.abs(c - o)
        rng = tw + bw + body
        with np.errstate(invalid="ignore", divide="ignore"):
            rate = np.where(rng > 0, 0.5 * (tw + bw + 2 * body) / rng, 0.5)
        cdv = np.where(c >= o, v * rate, -v * rate)
        flow20 = float(cdv[-20:].sum() / max(v[-20:].sum(), 1e-12))
        if (L and flow20 < -0.15) or ((not L) and flow20 > 0.15):
            return False, f"aliran dana CDV 20 candle pada {sym} melawan arah ({flow20:+.2f})", ev

    # 6. Pengaktifan otomatis kombo strategi penembusan vs pantulan
    if jalur:
        aktif_set = KOMBO_PENEMBUSAN if mode_lokal == "PENEMBUSAN" else KOMBO_PANTULAN
        if jalur not in aktif_set:
            return False, f"kondisi {mode_lokal.lower()} aktif, jalur {jalur} dinonaktifkan otomatis", ev

    return True, f"lolos penyaring utama (searah aliran dana besar, mode {mode_lokal})", ev


def ringkas_teks(ev=None):
    """Format laporan ringkas Penyaring Utama Aliran Dana Besar untuk Telegram."""
    ev = ev or evaluasi_pasar()
    b = ev["btc"]
    a = ev["altseason"]
    m = ev["makro"]
    r = ev["rotasi_sektor"]
    nw = ev["reaksi_berita"]
    kuat_s = ", ".join(f"{s} ({r['sektor'][s]:+.1f}%)" for s in r["kuat"][:3]) or "belum ada yang menonjol"
    lemah_s = ", ".join(f"{s} ({r['sektor'][s]:+.1f}%)" for s in r["lemah"][:2]) or "-"
    rows = [
        "🧭 <b>PENYARING UTAMA ALIRAN DANA BESAR (PILAR 1)</b>",
        f"• <b>Arah Bitcoin</b>: {b['arah']} | {b['kondisi']} (skor 1W {b['skor_tf']['1W']:+d}, 1D {b['skor_tf']['1D']:+d}, 4J {b['skor_tf']['4J']:+d} | ADX {b['adx_4j']:.1f})",
        f"• <b>Musim Altcoin</b>: {a['rezim']} (alt vs BTC 7h {a['rasio7']:+.1f}%, BTC 30h {a['btc30']:+.1f}%)",
        f"• <b>Kondisi Makro</b>: {m['rezim']} (pengali lot LONG {m['pengali_lot_long']:g}x)",
        f"• <b>Rotasi Sektor</b>: Sektor kuat [{kuat_s}] | Sektor lemah [{lemah_s}]",
        f"• <b>Reaksi Berita</b>: {'⚠️ JEDA AKTIF (' + nw['judul_jeda'] + ')' if nw['jeda_aktif'] else 'Aman (arah sentimen ' + ('positif' if nw['arah_berita'] > 0 else 'negatif' if nw['arah_berita'] < 0 else 'netral') + ')'}",
        f"🎯 <b>Fokus Aliran Dana Besar</b>: <b>{ev['arah_dana_besar']}</b> (skor {ev['skor_aliran_dana']:+d})",
        f"⚙️ <b>Mode Kombo Otomatis</b>: <b>KOMBO {ev['mode_kombo']}</b> ({ev['kondisi_pasar']})",
    ]
    return "\n".join(rows)
