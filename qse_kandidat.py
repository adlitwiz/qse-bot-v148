"""QSE v150 KANDIDAT TERDEKAT (10 Nov 2026, permintaan user). Saat candle 4J tutup tanpa sinyal Market baru dari 8 teknik, Sinyal 4J
menampilkan 2 koin yang paling dekat (kurang dari 1%) ke garis pemicu EMA Cross 20/50 atau McGinley 34, searah fokus pasar
(kompas merah atau BTC 4J di bawah EMA 50 = SHORT, sebaliknya LONG). Antrean berupa Conditional Stop di ujung candle terakhir.
Ini PANTAUAN, belum sinyal: antrean pemicu ini belum diuji mundur sebagai cara entry, jadi selalu KELAS RINGAN."""
import numpy as np

MAKS_KOIN = 40
JARAK = 1.0          # persen


def _ema(x, n):
    a = 2 / (n + 1)
    out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _mcg(c, n=34):
    md = np.empty(len(c)); md[0] = c[0]
    for i in range(1, len(c)):
        r = c[i] / md[i - 1] if md[i - 1] else 1
        md[i] = md[i - 1] + (c[i] - md[i - 1]) / (n * r ** 4)
    return md


def fokus():
    try:
        import qse_kompas as KP
        k = KP.kompas()
        if k and k["blok_long"]:
            return "SHORT"
        if k and k["status"] in ("FOKUS LONG", "CONDONG LONG"):
            return "LONG"
    except Exception:
        pass
    try:
        import qse_strat as ST
        return "LONG" if ST.btc_naik() else "SHORT"
    except Exception:
        return "SHORT"


def cari(df, arah):
    """Calon dari satu koin. df candle 4J tutup (open/high/low/close). Return list dict."""
    if df is None or len(df) < 60:
        return []
    h, l, c = (df[x].values.astype(float) for x in ("high", "low", "close"))
    e20, e50, md = _ema(c, 20), _ema(c, 50), _mcg(c)
    px = c[-1]
    S = arah == "SHORT"
    out = []
    gap = (e20[-1] - e50[-1]) / px * 100
    if (S and 0 < gap < JARAK and e20[-1] < e20[-3]) or ((not S) and -JARAK < gap < 0 and e20[-1] > e20[-3]):
        out.append(dict(teknik="EMA Cross 20/50", jarak=abs(gap), pemicu=f"EMA 20 ({e20[-1]:.6g}) tinggal {abs(gap):.2f}% dari EMA 50 ({e50[-1]:.6g})"))
    dm = (px - md[-1]) / px * 100
    if (S and 0 < dm < JARAK) or ((not S) and -JARAK < dm < 0):
        out.append(dict(teknik="McGinley 34", jarak=abs(dm), pemicu=f"harga tinggal {abs(dm):.2f}% dari garis McGinley {md[-1]:.6g}"))
    for x in out:
        e = l[-1] if S else h[-1]
        sl = max(h[-3:]) if S else min(l[-3:])
        r = abs(sl - e)
        if r <= 0:
            continue
        x.update(arah=arah, entry=e, sl=sl, tp1=e - r if S else e + r, tp2=e - 2 * r if S else e + 2 * r)
    return [x for x in out if "entry" in x]


def sibuk(now=None, jam=12):
    """QC 83 (kasus AVAX): koin yang TIDAK boleh muncul sebagai kandidat kelas ringan. Isinya koin yang sedang dipegang anggota (order
    atau posisi), koin yang baru disiarkan scan 1 jam atau kartu jalur dalam `jam` jam terakhir, dan koin dengan posisi jalur yang masih
    berjalan. Kandidat untuk koin itu hanya membingungkan: sinyal Market yang lebih kuat sudah ada."""
    import time
    now = now or time.time()
    out = set()
    try:
        import qse_saya as SY
        for u in SY.daftar_pengguna():
            for it in SY._baca(SY._path_uid(u))["open"].values():
                if it.get("status") in ("MENUNGGU", "TERISI", "TP1"):
                    out.add(it.get("sym"))
    except Exception as ex:
        print("[WARN] kandidat sibuk pengguna", ex)
    try:
        import qse_radar as RD
        for k, v in (RD._baca().get("kirim") or {}).items():
            ts = v[0] if isinstance(v, list) else v
            if now - ts < jam * 3600:
                out.add(k.split("|")[0])
    except Exception as ex:
        print("[WARN] kandidat sibuk radar", ex)
    try:
        import qse_ditahan as DT
        for _, _, it in DT._sumber():
            if now - it.get("t", 0) < jam * 3600 and not it.get("uji_live"):
                out.add(it.get("sym"))
    except Exception as ex:
        print("[WARN] kandidat sibuk jalur", ex)
    return out


def teks(harga=None, rs=None, n=2):
    import qse_strat as ST
    import qse_saya as SY
    arah = fokus()
    syms = []
    for r in rs or []:
        if r.get("tf", "240") == "240" and r.get("symbol"):
            syms.append((-(r.get("tk") or {}).get("turnover", 0), r["symbol"]))
    lewati = sibuk()
    syms = [s for _, s in sorted(syms) if s not in lewati][:MAKS_KOIN]
    calon = []
    for s in syms:
        try:
            for x in cari(ST._k4(s, 120), arah):
                calon.append(dict(x, sym=s))
        except Exception as ex:
            print("[WARN] kandidat", s, ex)
    if not calon:
        return ""
    calon.sort(key=lambda x: x["jarak"])
    rows = [f"🎯 <b>KANDIDAT TERDEKAT ({arah}, searah fokus pasar)</b>",
            "Belum ada sinyal Market baru dari 8 teknik. 2 koin ini paling dekat ke garis pemicu. Pasang antrean Conditional Stop "
            "kalau mau masuk lebih awal. PANTAUAN, belum diuji sebagai cara entry: 🟨 KELAS RINGAN."]
    sudah = set()
    for x in calon:
        if x["sym"] in sudah:
            continue
        sudah.add(x["sym"])
        t = SY.tick_of(None, x["entry"])
        rows.append(f"\n{'🔴' if x['arah'] == 'SHORT' else '🟢'} <b>{x['sym']} {x['arah']}</b>  ·  {x['teknik']}  ·  {x['pemicu']}\n"
                    + SY.blok_salin(x["entry"], x["sl"], x["tp1"], x["tp2"], "CONDITIONAL", t, sym=x["sym"], arah=x["arah"]))
        if len(sudah) >= n:
            break
    return "\n".join(rows)
