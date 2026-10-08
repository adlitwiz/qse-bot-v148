"""QSE v148 - SKILL TAMBAHAN (konfirmasi, tidak mengubah vonis DASBOR).
Diport dari dua Pine tambahan milik pengguna:
  1. Money Flow Profile: POC, value area 70%, sentimen beli atau jual di POC (200 candle, 25 baris)
  2. Smarter SnR: S1-S3 dan R1-R3 dari pivot swing 20
  3. Cumulative Delta Volume: delta dengan bobot sumbu dan badan candle
  4. Order Block Finder: OB bullish atau bearish terakhir yang belum ditembus (5 candle beruntun)
  5. MSB dan OB probability: OB dari market structure break dengan skor momentum dan volume
  6. Smart Money Concepts: tren struktur swing (50) dan internal (5), BOS atau CHoCH terakhir,
     posisi premium, equilibrium, atau diskon
Semua hanya dihitung di candle terakhir, jadi tidak memperlambat scan."""
import numpy as np
import pandas as pd
import qse_ta as T


def _profil(o, h, l, c, v, e, n=200, rows=25):
    s = max(0, e - n + 1)
    H, L, V = h[s:e + 1], l[s:e + 1], v[s:e + 1]
    bull = c[s:e + 1] > o[s:e + 1]
    lo, hi = float(np.nanmin(L)), float(np.nanmax(H))
    step = (hi - lo) / rows
    if not step > 0:
        return None
    ed = lo + step * np.arange(rows + 1)
    top = np.minimum(H[:, None], ed[None, 1:])
    bot = np.maximum(L[:, None], ed[None, :-1])
    rng = (H - L)[:, None]
    frac = np.where(rng > 0, np.clip(top - bot, 0, None) / np.where(rng > 0, rng, 1), 0.0)
    vol = (frac * V[:, None]).sum(0)
    beli = (frac * (V * bull)[:, None]).sum(0)
    k = int(np.argmax(vol))
    poc = lo + (k + 0.5) * step
    urut = np.argsort(-vol)
    tot, acc, pilih = vol.sum(), 0.0, []
    for j in urut:
        pilih.append(j)
        acc += vol[j]
        if acc >= 0.7 * tot:
            break
    return dict(poc=poc, vah=lo + (max(pilih) + 1) * step, val=lo + min(pilih) * step,
                sentimen="beli" if 2 * beli[k] - vol[k] > 0 else "jual")


def _snr(h, l, c, e, per=20, n=600):
    s = max(0, e - n)
    ph = T.pivothigh(h[s:e + 1], per, per)
    pl = T.pivotlow(l[s:e + 1], per, per)
    px = c[e]
    lv = [x for x in np.r_[ph[~np.isnan(ph)], pl[~np.isnan(pl)]]]
    sup = sorted({round(x, 12) for x in lv if x < px}, reverse=True)[:3]
    res = sorted({round(x, 12) for x in lv if x > px})[:3]
    return sup, res


def _cdv(o, h, l, c, v, e):
    tw = h - np.maximum(o, c)
    bw = np.minimum(o, c) - l
    body = np.abs(c - o)
    den = tw + bw + body

    def rate(cond):
        with np.errstate(divide="ignore", invalid="ignore"):
            r = 0.5 * (tw + bw + np.where(cond, 2 * body, 0)) / den
        return np.where(np.isnan(r) | (r == 0), 0.5, r)
    delta = np.where(c >= o, v * rate(o <= c), -v * rate(o > c))
    cum = np.cumsum(np.nan_to_num(delta))[: e + 1]
    ema = T.ema(cum, 21)
    naik = cum[e] > ema[e] and cum[e] > cum[max(0, e - 5)]
    turun = cum[e] < ema[e] and cum[e] < cum[max(0, e - 5)]
    return "naik" if naik else "turun" if turun else "datar"


def _ob_finder(o, h, l, c, e, per=5, n=400):
    """OB bullish: candle turun terakhir sebelum 5 candle naik beruntun. Zona low sampai open."""
    bull = bear = None
    s = max(per + 1, e - n)
    for i in range(s, e + 1):
        j = i - (per + 1)
        up = all(c[i - k] > o[i - k] for k in range(1, per + 1))
        dn = all(c[i - k] < o[i - k] for k in range(1, per + 1))
        if c[j] < o[j] and up:
            bull = [l[j], o[j], i]
        if c[j] > o[j] and dn:
            bear = [o[j], h[j], i]
        if bull and c[i] < bull[0]:
            bull = None
        if bear and c[i] > bear[1]:
            bear = None
    return (bull[:2] if bull else None), (bear[:2] if bear else None)


def _ob_msb(o, h, l, c, v, e, piv=7, zmin=0.5, n=600):
    """OB dari market structure break, skor = |z momentum| x 20 + persentil volume x 0.5 (maks 100)."""
    s = max(0, e - n)
    chg = pd.Series(c).diff()
    sd = chg.rolling(50).std(ddof=0)
    z = ((chg - chg.rolling(50).mean()) / sd.replace(0, np.nan)).fillna(0).values
    vp = np.nan_to_num(T.percentrank(v, 100))
    ph, pl = T.pivothigh(h, piv, piv), T.pivotlow(l, piv, piv)
    lastPh = lastPl = np.nan
    obs = []
    for i in range(s, e + 1):
        if not np.isnan(ph[i]):
            lastPh = ph[i]
        if not np.isnan(pl[i]):
            lastPl = pl[i]
        bu = (not np.isnan(lastPh)) and c[i] > lastPh and c[i - 1] <= lastPh and z[i] > zmin
        bd = (not np.isnan(lastPl)) and c[i] < lastPl and c[i - 1] >= lastPl and z[i] < -zmin
        if bu or bd:
            k = 0
            for q in range(1, 11):
                if (bu and c[i - q] < o[i - q]) or (bd and c[i - q] > o[i - q]):
                    k = q
                    break
            obs.append(dict(top=h[i - k], bot=l[i - k], bull=bool(bu), skor=min(100.0, abs(z[i]) * 20 + vp[i] * 0.5),
                            aktif=True))
            if bu:
                lastPh = np.nan
            else:
                lastPl = np.nan
        for ob in obs:
            if ob["aktif"] and ((ob["bull"] and l[i] < ob["bot"]) or ((not ob["bull"]) and h[i] > ob["top"])):
                ob["aktif"] = False
        obs = obs[-10:]
    akt = [x for x in obs if x["aktif"]]
    bull = next((x for x in reversed(akt) if x["bull"]), None)
    bear = next((x for x in reversed(akt) if not x["bull"]), None)
    return bull, bear


def _smc(h, l, c, e, size, n=1500):
    s = max(size + 1, e - n)
    rmax = pd.Series(h).rolling(size).max().values
    rmin = pd.Series(l).rolling(size).min().values
    leg, trend = 0, 0
    sh = sl = np.nan
    ch = cl = True
    top = bot = np.nan
    ev = None
    for i in range(s, e + 1):
        prev = leg
        if h[i - size] > rmax[i]:
            leg = 0
        elif l[i - size] < rmin[i]:
            leg = 1
        if leg != prev:
            if leg == 1:
                sl, cl, bot = l[i - size], False, l[i - size]
            else:
                sh, ch, top = h[i - size], False, h[i - size]
        top = h[i] if np.isnan(top) else max(top, h[i])
        bot = l[i] if np.isnan(bot) else min(bot, l[i])
        if (not ch) and c[i] > sh and c[i - 1] <= sh:
            ev = ("CHoCH" if trend == -1 else "BOS", "LONG")
            trend, ch = 1, True
        if (not cl) and c[i] < sl and c[i - 1] >= sl:
            ev = ("CHoCH" if trend == 1 else "BOS", "SHORT")
            trend, cl = -1, True
    return trend, ev, top, bot


def analisa(v, e):
    """Semua skill tambahan di candle e. v = hasil qse_features.build."""
    o, h, l, c = v["open"], v["high"], v["low"], v["close"]
    vol = v["volume"]
    a = float(v["atr"][e]) if v["atr"][e] == v["atr"][e] else 0.0
    px = float(c[e])
    out = dict(harga=px)
    try:
        out["profil"] = _profil(o, h, l, c, vol, e)
    except Exception:
        out["profil"] = None
    try:
        out["sup"], out["res"] = _snr(h, l, c, e)
    except Exception:
        out["sup"], out["res"] = [], []
    try:
        out["cdv"] = _cdv(o, h, l, c, vol, e)
    except Exception:
        out["cdv"] = "datar"
    try:
        out["obf_bull"], out["obf_bear"] = _ob_finder(o, h, l, c, e)
    except Exception:
        out["obf_bull"] = out["obf_bear"] = None
    try:
        out["msb_bull"], out["msb_bear"] = _ob_msb(o, h, l, c, vol, e)
    except Exception:
        out["msb_bull"] = out["msb_bear"] = None
    try:
        tr, ev, top, bot = _smc(h, l, c, e, 50)
        out["smc_swing"], out["smc_event"] = tr, ev
        out["pd"] = float((px - bot) / (top - bot) * 100) if top > bot else 50.0
        out["smc_int"] = _smc(h, l, c, e, 5, 600)[0]
    except Exception:
        out["smc_swing"], out["smc_event"], out["pd"], out["smc_int"] = 0, None, 50.0, 0
    out["atr"] = a
    return out


def _dalam(z, px, a):
    return z is not None and min(z[0], z[1]) - 0.5 * a <= px <= max(z[0], z[1]) + 0.5 * a


def konfirmasi(sk, arah):
    """Daftar skill yang searah dengan arah. Return (jumlah, total, nama[])."""
    if not sk:
        return 0, 0, []
    L = arah == "LONG"
    px, a = sk["harga"], sk.get("atr", 0)
    ok = []
    pr = sk.get("profil")
    if pr:
        if (px > pr["poc"]) == L:
            ok.append("POC")
        if (pr["sentimen"] == "beli") == L:
            ok.append("sentimen")
    if sk.get("cdv") == ("naik" if L else "turun"):
        ok.append("CDV")
    obs = [sk.get("obf_bull"), sk.get("msb_bull") and [sk["msb_bull"]["bot"], sk["msb_bull"]["top"]]] if L else \
        [sk.get("obf_bear"), sk.get("msb_bear") and [sk["msb_bear"]["bot"], sk["msb_bear"]["top"]]]
    if any(_dalam(z, px, a) for z in obs if z):
        ok.append("OB")
    if sk.get("smc_swing") == (1 if L else -1):
        ok.append("SMC swing")
    if sk.get("smc_int") == (1 if L else -1):
        ok.append("SMC internal")
    if (sk.get("pd", 50) < 50) == L:
        ok.append("diskon" if L else "premium")
    lv = sk.get("sup") if L else sk.get("res")
    if lv and a > 0 and abs(px - lv[0]) <= a:
        ok.append("dekat support" if L else "dekat resisten")
    return len(ok), 8, ok


def ringkas(sk, arah, fp):
    """Satu baris untuk pesan sinyal dan pantauan."""
    n, tot, ok = konfirmasi(sk, arah)
    return f"Konfirmasi skill tambahan {n}/{tot}" + (f" ({', '.join(ok)})" if ok else "")


def detail(sk, arah, fp):
    """Beberapa baris untuk /cek."""
    if not sk:
        return []
    rows = []
    pr = sk.get("profil")
    if pr:
        rows.append(f"Volume profile: POC {fp(pr['poc'])} | value area {fp(pr['val'])}-{fp(pr['vah'])} | "
                    f"harga {'di atas' if sk['harga'] > pr['poc'] else 'di bawah'} POC | sentimen {pr['sentimen']}")
    if sk.get("sup") or sk.get("res"):
        rows.append("SnR: " + " ".join(f"S{i + 1} {fp(x)}" for i, x in enumerate(sk.get("sup", []))) +
                    (" | " if sk.get("sup") and sk.get("res") else "") +
                    " ".join(f"R{i + 1} {fp(x)}" for i, x in enumerate(sk.get("res", []))))
    tr = {1: "NAIK", -1: "TURUN", 0: "belum jelas"}
    ev = sk.get("smc_event")
    pd_ = sk.get("pd", 50)
    zona = "premium" if pd_ > 52.5 else "diskon" if pd_ < 47.5 else "equilibrium"
    rows.append(f"SMC: struktur swing {tr.get(sk.get('smc_swing'), '-')}" + (f" ({ev[0]} {ev[1]})" if ev else "") +
                f" | internal {tr.get(sk.get('smc_int'), '-')} | posisi {zona} {pd_:.0f}% | CDV {sk.get('cdv')}")
    ob = []
    for nama, z in (("OB bull", sk.get("obf_bull")), ("OB bear", sk.get("obf_bear"))):
        if z:
            ob.append(f"{nama} {fp(min(z))}-{fp(max(z))}")
    for nama, z in (("OB MSB bull", sk.get("msb_bull")), ("OB MSB bear", sk.get("msb_bear"))):
        if z:
            ob.append(f"{nama} {fp(z['bot'])}-{fp(z['top'])} skor {z['skor']:.0f}" + (" HPZ" if z["skor"] > 80 else ""))
    if ob:
        rows.append("Order block aktif: " + " | ".join(ob))
    rows.append(ringkas(sk, arah, fp))
    return rows
