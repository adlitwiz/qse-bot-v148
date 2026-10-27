"""QSE v148 - tebakan arah BTC 24 jam dan perkiraan rentang gerak. Dipakai info pasar 06, 12, 18, 00 WIB, /cek BTC,
laporan arah harian, dan baris BTC di kartu sinyal. Model di arah_model.json (riset/arah_harian).

Arah: regresi logistik 6 fitur. Koefisiennya stabil di semua uji maju 2019-2026 (tanda tidak pernah berbalik):
 4 aturan naik lama (BTC turun 9% dalam 7 hari, 10% di atas EMA20 harian, RSI harian 71+, tutup di dasar rentang 24 jam),
 akhir pekan (BTC naik 56% hari akhir pekan, hari kerja 50%, konsisten 10 tahun 2017-2026),
 gerak pasar 24 jam (rata BTC, ETH, altcoin): naik kuat cenderung terkoreksi, turun kuat cenderung memantul.
Uji maju jam 06:00 WIB 2019-2026 (2854 hari): benar 53.3% semua hari, 56.1% saat keyakinan KUAT (46% hari).
96 fitur lain (funding, OI, rasio long short, taker, Coinbase premium, DVOL, stablecoin, Fear and Greed, breadth)
tidak menaikkan akurasi uji maju, jadi tidak dipakai. Tidak dipakai menyaring sinyal: uji 2021-2026 membuang sinyal
yang melawan tebakan tidak konsisten menaikkan hasil (PF naik di satu periode, turun di periode lain).
Rentang: regresi log rentang 24 jam (rentang 24 jam dan 7 hari, volatilitas 30 hari, akhir pekan, Senin, volume, gerak 24 jam).
LATIH ULANG OTOMATIS (27 Okt 2026): tiap Senin 05:30 WIB qse_latih melatih ulang model dari sejarah riset + catatan live bot
(tiap tebakan yang sudah lewat 24 jam dicatat ke arah_live.json). Model baru dipakai hanya kalau lolos penjaga kualitas
(tanda koefisien sama, akurasi uji maju tidak turun lebih dari 1 poin, keyakinan KUAT tidak turun lebih dari 2 poin).
Uji maju: batas 80% berisi seluruh gerak 24 jam di 79-82% hari tiap periode, R2 log rentang 0.42 (rata 7 hari saja 0.22)."""
import json
import math
import os
import time

SESI_JAM = {"pagi": 23, "siang": 5, "malam": 11, "tengah": 17}
NAMA_JAM = {23: "06:00", 5: "12:00", 11: "18:00", 17: "00:00"}
STABIL = ("USDCUSDT", "USDEUSDT", "FDUSDUSDT", "DAIUSDT", "TUSDUSDT", "USD1USDT", "BUSDUSDT")
ATURAN = (("a_r7", "BTC turun lebih dari 9% dalam 7 hari, biasanya memantul"),
          ("a_e20", "BTC lebih dari 10% di atas EMA20 harian, tren kuat biasanya lanjut"),
          ("a_rsi", "RSI harian BTC di atas 71, momentum kuat biasanya lanjut"),
          ("a_cp", "BTC 24 jam terakhir tutup di dasar rentangnya, biasanya memantul"))
LAMA_NAIK = 57.0          # BTC naik di hari aturan lama aktif (uji 2019-2026)
# Hasil sinyal mode seimbang (cara keluar sekarang) menurut tingkat gerak dari sesi terakhir (maks 7 jam), uji 2021-2023
# dan 2024-2026: PF, PF, menang%. Konsisten di dua periode (rendah terbaik, tinggi terburuk). Di gerak TINGGI yang lemah
# hanya SHORT: PF 0.99 dan 0.98, LONG 1.58 dan 1.83. SHORT lot setengah di gerak TINGGI: drawdown 200R jadi 190R, profit sama.
# Menahan SHORT di kondisi ini (dengan syarat ATR koin) diuji dan tidak dipasang: 2025-2026 justru PF 1.30.
SINYAL_GERAK = {"rendah": (1.89, 2.05, 75), "sedang": (1.56, 1.30, 73), "tinggi": (1.15, 1.17, 71)}
_MODEL = [None]
_MEM = {}


def model():
    """Model aktif: hasil latih ulang otomatis (STATE_DIR, qse_latih) kalau ada dan sah, kalau tidak model riset di repo."""
    if _MODEL[0] is None:
        try:
            import qse_latih as LT
            _MODEL[0], _ = LT.model_aktif()
        except Exception as ex:
            print("[WARN] model latih ulang", ex)
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "arah_model.json")) as f:
                _MODEL[0] = json.load(f)
    return _MODEL[0]


def titik(H, now=None):
    """Waktu T (detik UTC) jam H UTC terakhir yang sudah lewat."""
    now = time.time() if now is None else now
    return int((now - H * 3600) // 86400) * 86400 + H * 3600


def sesi_terbaru(now=None):
    """Jam sesi (23, 5, 11, 17 UTC) terakhir yang sudah lewat."""
    now = time.time() if now is None else now
    return max(SESI_JAM.values(), key=lambda H: titik(H, now))


def _f(path, isi=None):
    from config import STATE_DIR
    p = os.path.join(STATE_DIR, path)
    if isi is None:
        try:
            with open(p) as fh:
                return json.load(fh)
        except Exception:
            return None
    try:
        with open(p + ".tmp", "w") as fh:
            json.dump(isi, fh)
        os.replace(p + ".tmp", p)
    except Exception as ex:
        print("[WARN] simpan", path, ex)


def _harga_di(s, T):
    """Close candle 1 jam yang tutup tepat di T (indeks = waktu buka ms). None kalau tidak ada."""
    k = (T - 3600) * 1000
    try:
        return float(s.loc[k]) if k in s.index else None
    except Exception:
        return None


def _alt24(T, now):
    """Rata gerak 24 jam 60 altcoin teramai (log, dipotong 50%). Data ticker kalau masih dekat T (30 menit),
    selain itu candle 1 jam (hanya saat tebakan sesi belum tersimpan, misalnya bot baru dinyalakan)."""
    import bybit_fetch as B
    tk = B.get_tickers()
    top = [s for s, _ in sorted(((s, v["turnover"]) for s, v in tk.items()
                                 if s.endswith("USDT") and s != "BTCUSDT" and s not in STABIL), key=lambda z: -z[1])]
    vals = []
    if now - T <= 1800 and all("chg24" in tk[s] for s in top[:5]):
        for s in top[:60]:
            c = tk[s].get("chg24")
            if c is not None and c > -0.99:
                vals.append(max(-0.5, min(0.5, math.log1p(c))))
    else:
        for s in top[:60]:
            try:
                df = B._raw(s, "60", 40)
                a, b = _harga_di(df["close"].astype(float), T), _harga_di(df["close"].astype(float), T - 86400)
                if a and b:
                    vals.append(max(-0.5, min(0.5, math.log(a / b))))
            except Exception:
                continue
    return sum(vals) / len(vals) if len(vals) >= 15 else None


def fitur(H, now=None):
    """Fitur arah dan rentang di T (jam H UTC terakhir). Return dict atau None kalau data belum lengkap."""
    import numpy as np
    import pandas as pd
    import bybit_fetch as B
    now = time.time() if now is None else now
    T = titik(H, now)
    h = B._raw("BTCUSDT", "60", 24 * 150)
    h = h[h.index < T * 1000].astype(float)
    if len(h) < 24 * 60 or h.index[-1] < (T - 2 * 3600) * 1000:
        return None
    t = pd.to_datetime(h.index, unit="ms", utc=True)
    day = (t - pd.Timedelta(hours=H)).floor("D")
    g = h.groupby(day)
    D = pd.DataFrame({"c": g["close"].last(), "hi": g["high"].max(), "lo": g["low"].min()})
    D["q"] = (h["close"] * h["volume"]).groupby(day).sum()
    c = D["c"]
    if len(D) < 60:
        return None
    dd = c.diff()
    up = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = float((100 - 100 / (1 + up / dn)).iloc[-1])
    e20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
    last = D.iloc[-1]
    cp = (last.c - last.lo) / max(last.hi - last.lo, 1e-9)
    wd = time.gmtime(T + 7 * 3600).tm_wday
    x = {"a_r7": float(c.iloc[-1] / c.iloc[-8] - 1 <= -0.0921), "a_e20": float(c.iloc[-1] / e20 - 1 >= 0.0994),
         "a_rsi": float(rsi >= 70.96), "a_cp": float(cp <= 0.1851), "akhir_pekan": float(wd in (5, 6))}
    r1 = math.log(c.iloc[-1] / c.iloc[-2])
    eth = None
    try:
        e = B._raw("ETHUSDT", "60", 40)["close"].astype(float)
        a, b = _harga_di(e, T), _harga_di(e, T - 86400)
        if a and b:
            eth = math.log(a / b)
    except Exception as ex:
        print("[WARN] tebak eth", ex)
    alt = None
    try:
        alt = _alt24(T, now)
    except Exception as ex:
        print("[WARN] tebak alt", ex)
    ada = [v for v in (r1, eth, alt) if v is not None]
    x["pasar24"] = sum(ada) / len(ada)
    lr = np.log(h["close"]).diff().iloc[-720:]
    rng = np.log(D["hi"] / D["lo"])
    rng24 = math.log(h["high"].iloc[-24:].max() / h["low"].iloc[-24:].min())
    xr = {"l_rng24": math.log(max(rng24, 1e-4)), "l_rng7": math.log(max(float(rng.iloc[-8:-1].mean()), 1e-4)),
          "l_rv30": math.log(max(float(lr.std() * math.sqrt(24)), 1e-5)), "pekan": x["akhir_pekan"], "senin": float(wd == 0),
          "l_vrel": math.log(max(float(D["q"].iloc[-1] / D["q"].iloc[-31:-1].mean()), 1e-3)), "abs_r1": abs(r1)}
    return dict(T=T, H=H, x=x, xr=xr, harga=float(c.iloc[-1]), r1=r1, eth=eth, alt=alt, rsi=rsi, h=h)


def hitung(H, now=None):
    """Tebakan arah dan rentang di T. Return (dict hasil, candle 1 jam BTC) atau None kalau data belum lengkap."""
    M = model()
    S = M["sesi"][str(H)]
    fx = fitur(H, now)
    if fx is None:
        return None
    A, k = S["arah"], M["klip"]
    logit, kon = A["b"], {}
    for i, nm in enumerate(M["fitur"]):
        z = max(-k, min(k, (fx["x"][nm] - A["mu"][i]) / (A["sd"][i] or 1)))
        kon[nm] = A["w"][i] * z
        logit += kon[nm]
    p = 1 / (1 + math.exp(-logit))
    lama = [nm for nm, _ in ATURAN if fx["x"][nm] >= 1]
    uji = S["uji"]
    kuat = abs(p - 0.5)
    tingkat = "kuat" if kuat >= 0.03 else "sedang" if kuat >= 0.01 else "tipis"
    arah = "NAIK" if p >= 0.5 else "TURUN"
    benar = uji["tingkat"][tingkat][1]
    pakai_lama = H == 23 and lama and p < 0.5           # aturan lama menang (uji: konflik ini naik 62%, n 34)
    if pakai_lama:
        arah, tingkat, benar = "NAIK", "sedang", LAMA_NAIK
    R = S["rentang"]
    ls = R["b"] + sum(w * fx["xr"][nm] for w, nm in zip(R["w"], M["rfitur"]))
    s = math.exp(ls)
    q = R["q"]
    px = fx["harga"]
    lv = "rendah" if s < R["lv"][0] else "sedang" if s <= R["lv"][1] else "tinggi"
    return dict(T=fx["T"], H=H, p=p, arah=arah, tingkat=tingkat, benar=benar, lama=lama, pakai_lama=bool(pakai_lama),
                kon=kon, x=fx["x"], xr=fx["xr"], r1=fx["r1"], eth=fx["eth"], alt=fx["alt"], harga=px, s=s, lv=lv,
                naik50=px * math.exp(q["u50"] * s), turun50=px * math.exp(-q["d50"] * s),
                atas=px * math.exp(q["u90"] * s), bawah=px * math.exp(-q["d90"] * s)), fx["h"]


def tebak(H=None, now=None):
    """Tebakan sesi H (default sesi terakhir). Disimpan per T, dicatat untuk hitung akurasi nyata. None kalau gagal."""
    now = time.time() if now is None else now
    H = sesi_terbaru(now) if H is None else H
    T = titik(H, now)
    kunci = str(H)
    m = _MEM.get(kunci)
    if m and m["T"] == T:
        return m
    simpan = _f("tebak.json") or {}
    if (simpan.get(kunci) or {}).get("T") == T:
        _MEM[kunci] = simpan[kunci]
        return simpan[kunci]
    try:
        out = hitung(H, now)
    except Exception as ex:
        print("[WARN] tebak hitung", ex)
        return None
    if out is None:
        return None
    r, h = out
    simpan[kunci] = r
    _f("tebak.json", simpan)
    _MEM[kunci] = r
    try:
        _catat(r, h)
    except Exception as ex:
        print("[WARN] tebak catat", ex)
    return r


def _catat(r, h):
    """Catat tebakan dan nilai tebakan lama yang sudah lewat 24 jam (pakai candle 1 jam yang sudah diambil)."""
    log = _f("tebak_log.json") or []
    if not any(e["T"] == r["T"] and e["H"] == r["H"] for e in log):
        log.append(dict(T=r["T"], H=r["H"], p=round(r["p"], 4), arah=r["arah"], tingkat=r["tingkat"], harga=r["harga"],
                        atas=r["atas"], bawah=r["bawah"], x=r.get("x"), xr=r.get("xr")))
    hi, lo, cl = h["high"], h["low"], h["close"]
    for e in log:
        if e.get("hasil") is not None:
            continue
        T = e["T"]
        if (T + 86400 - 3600) * 1000 > h.index[-1]:
            continue
        seg = (h.index >= T * 1000) & (h.index < (T + 86400) * 1000)
        if seg.sum() < 20:
            e["hasil"] = -1
            continue
        akhir = float(cl[seg].iloc[-1])
        e["gerak"] = round(math.log(akhir / e["harga"]) * 100, 2)
        e["hasil"] = int((akhir > e["harga"]) == (e["arah"] == "NAIK"))
        e["isi"] = int(float(hi[seg].max()) <= e["atas"] and float(lo[seg].min()) >= e["bawah"])
        if e.get("x") and e.get("xr") and seg.sum() >= 22:
            # data latih live untuk latih ulang otomatis (qse_latih), sama dengan kolom riset arah_data.csv.gz
            try:
                import qse_latih as LT
                hi_, lo_ = float(hi[seg].max()), float(lo[seg].min())
                LT.catat_live(dict(T=int(T), H=int(e["H"]), **{k: float(v) for k, v in e["x"].items()},
                                   **{k: float(v) for k, v in e["xr"].items()}, y=math.log(akhir / e["harga"]),
                                   yrng=math.log(hi_ / lo_), yup=math.log(hi_ / e["harga"]), ydn=math.log(lo_ / e["harga"])))
            except Exception as ex:
                print("[WARN] catat live arah", ex)
    _f("tebak_log.json", log[-1500:])


def akurasi_nyata(H=None):
    """(n, benar, isi_rentang) tebakan yang sudah dinilai sejak dipasang. H None = semua sesi."""
    log = _f("tebak_log.json") or []
    ev = [e for e in log if e.get("hasil") in (0, 1) and (H is None or e["H"] == H)]
    return len(ev), sum(e["hasil"] for e in ev), sum(e.get("isi", 0) for e in ev)


def _fp(x):
    return f"{x:,.0f}"


def _alasan(r, maks=3):
    """Alasan utama dalam bahasa sederhana, urut pengaruh terbesar. (ikon, teks)."""
    S = model()["sesi"][str(r["H"])]
    M = S["uji"]
    out = []
    for nm, v in sorted(r["kon"].items(), key=lambda z: -abs(z[1])):
        if abs(v) < 0.005:
            continue
        ik = "🟢" if v > 0 else "🔴"
        if nm == "akhir_pekan":
            t = (f"Akhir pekan. Uji 2017-2026: BTC naik di {M['pekan_naik']:.0f}% hari akhir pekan, hari kerja {M['kerja_naik']:.0f}%"
                 if r["x"]["akhir_pekan"] else
                 f"Hari kerja. Uji 2017-2026: BTC naik di {M['kerja_naik']:.0f}% hari kerja, akhir pekan {M['pekan_naik']:.0f}%")
        elif nm == "pasar24":
            g = r["x"]["pasar24"]
            if abs(g) < 0.01:
                continue
            naik = next((b[2] for b in S["arah"].get("pasar_tabel", []) if b[0] < g <= b[1]), None)
            uji = f" (uji: sesudahnya BTC naik di {naik:.0f}% hari)" if naik is not None else ""
            t = (f"Pasar (BTC, ETH, altcoin) naik rata {g * 100:.1f}% dalam 24 jam, biasanya sebagian terkoreksi{uji}" if g > 0 else
                 f"Pasar (BTC, ETH, altcoin) turun rata {-g * 100:.1f}% dalam 24 jam, biasanya sebagian memantul{uji}")
        else:
            t = dict(ATURAN)[nm]
            if not r["x"][nm]:
                continue
        out.append((ik, t))
        if len(out) >= maks:
            break
    return out


def judul(r):
    """'CONDONG NAIK, keyakinan KUAT (uji benar 56%)'."""
    if r.get("pakai_lama"):
        return f"CONDONG NAIK, aturan teruji aktif (sejarah naik {LAMA_NAIK:.0f}%)"
    return f"CONDONG {r['arah']}, keyakinan {r['tingkat'].upper()} (uji benar {r['benar']:.0f}%)"


def baris_keyakinan(r):
    M = model()["sesi"][str(r["H"])]["uji"]
    tk = r["tingkat"].upper()
    if r.get("pakai_lama"):
        return (f"Model condong turun tipis, tapi aturan naik teruji sedang aktif. Uji 2019-2026: saat aturan ini aktif "
                f"BTC naik di {LAMA_NAIK:.0f}% hari, jadi arah dibuat NAIK.")
    per = f"Uji maju {M['dari'][:4]}-{M['sampai'][:4]}"
    if tk == "TIPIS":
        return (f"{per}: tebakan berkeyakinan TIPIS benar {r['benar']:.0f}% hari, sama dengan lempar koin. "
                "Jangan jadikan alasan entry.")
    return (f"{per}: tebakan berkeyakinan {tk} benar {r['benar']:.0f}% hari, muncul di {M['tingkat'][r['tingkat']][0]:.0f}% hari. "
            f"Semua hari rata benar {M['akurasi']:.0f}%.")


def baris_nyata(H=None):
    n, b, isi = akurasi_nyata(H)
    if n < 5:
        return f"📊 Akurasi nyata sejak dipasang: baru {n} tebakan dinilai, ditampilkan setelah 5."
    return (f"📊 Akurasi nyata sejak dipasang: {b} dari {n} tebakan benar ({b / n * 100:.0f}%), "
            f"rentang 80% terisi {isi / n * 100:.0f}%.")


def teks_arah(r, lengkap=True):
    """Blok arah untuk info pasar."""
    M = model()["sesi"][str(r["H"])]["uji"]
    ket = "aturan teruji aktif" if r.get("pakai_lama") else f"keyakinan {r['tingkat'].upper()}"
    rows = [f"🧭 <b>ARAH BTC 24 JAM DARI {NAMA_JAM[r['H']]} WIB: CONDONG {r['arah']}</b>, {ket}", baris_keyakinan(r)]
    al = _alasan(r, 3 if lengkap else 2)
    if al:
        rows += ["Alasan utama:"] + [f"{ik} {t}" for ik, t in al]
    if lengkap:
        rows += [f"Altcoin: saat tebakan NAIK, altcoin ikut naik di {M['alt_naik_benar']:.0f}% hari. "
                 f"Tebakan TURUN belum terbukti untuk altcoin (turun {M['alt_turun_benar']:.0f}% hari).",
                 "Sinyal robot tetap diikuti apa adanya. Uji 2021-2026: membuang sinyal yang melawan tebakan ini tidak "
                 "menaikkan hasil.", baris_nyata(r["H"])]
    return rows


def teks_rentang(r):
    R = model()["sesi"][str(r["H"])]["rentang"]
    px = r["harga"]
    pr = lambda v: (v / px - 1) * 100
    return [f"📏 <b>PERKIRAAN GERAK BTC 24 JAM: {r['lv'].upper()}</b> (rentang sekitar {r['s'] * 100:.1f}%)",
            f"• Titik tengah: tertinggi sekitar {_fp(r['naik50'])} ({pr(r['naik50']):+.1f}%), terendah sekitar "
            f"{_fp(r['turun50'])} ({pr(r['turun50']):+.1f}%).",
            f"• Batas 80%: harga 24 jam ke depan tetap di antara {_fp(r['bawah'])} dan {_fp(r['atas'])} "
            f"(uji 2019-2026 terisi {R['uji']['isi90']:.0f}% hari).",
            f"• Peluang gerak lebih dari 5% di tingkat ini: {R['gerak5'][r['lv']]:.0f}% hari. "
            "Pakai untuk jarak SL dan TP, bukan untuk entry.",
            "• " + baris_sinyal_gerak(r, pendek=True)]


def baris_sinyal_gerak(r, pendek=False):
    """Hasil sinyal robot di tingkat gerak ini dan saran lot."""
    a, b, wr = SINYAL_GERAK[r["lv"]]
    saran = {"rendah": "Kondisi terbaik untuk sinyal robot, lot normal.", "sedang": "Lot normal.",
             "tinggi": "Yang lemah SHORT (PF 0.99 dan 0.98, LONG 1.58 dan 1.83). SHORT pakai lot setengah, "
                       "uji: drawdown turun 5%, profit sama."}[r["lv"]]
    if pendek:
        return f"Sinyal robot di gerak {r['lv'].upper()}: PF {a:.2f} dan {b:.2f}, menang {wr}% (uji 2021-2026). {saran}"
    ik = {"rendah": "🌤", "sedang": "⛅", "tinggi": "🌊"}[r["lv"]]
    return (f"{ik} Gerak BTC 24 jam {r['lv'].upper()} (sekitar {r['s'] * 100:.1f}%). Sinyal di kondisi ini PF {a:.2f} dan "
            f"{b:.2f}, menang {wr}% (uji 2021-2026). {saran}")


def ringkas(r):
    """Satu baris: 'CONDONG NAIK, keyakinan KUAT (uji benar 56%)'."""
    return judul(r)


def dasar(r):
    """Untuk kesimpulan: 'BTC condong naik, keyakinan KUAT (uji benar 56%)'."""
    if r.get("pakai_lama"):
        return f"BTC condong naik, aturan teruji aktif (sejarah naik {LAMA_NAIK:.0f}%)"
    return f"BTC condong {r['arah'].lower()}, keyakinan {r['tingkat'].upper()} (uji benar {r['benar']:.0f}%)"
