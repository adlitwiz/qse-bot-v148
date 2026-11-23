"""QSE v150 - gambar chart sinyal (PNG) tanpa library tambahan: numpy + zlib.
Candle 4J terakhir, garis entry (biru), SL (merah), TP sebagian (hijau muda), TP (hijau), support dan resistance (abu putus-putus),
skala harga di kanan dengan label (font 3x5 buatan sendiri). Dipakai sebagai gambar di gelembung sinyal Telegram.
QC 138: setup dicoret di gambar. Indikator teknik ikut digambar (EMA 20/50/200, McGinley 34, RSI 14 untuk teknik RSI), panel volume,
panah di candle sinyal, zona risiko (entry-SL merah tipis) dan zona untung (entry-TP hijau tipis), label huruf di tiap garis, judul."""
import struct
import zlib
import numpy as np

W, H = 900, 560
KANAN = 130                      # ruang skala harga dan label
ATAS, VOL_H, RSI_H = 26, 70, 80
BG = (17, 20, 27)
GRID = (34, 39, 50)
NAIK = (38, 166, 154)
TURUN = (239, 83, 80)
WARNA = dict(entry=(66, 133, 244), sl=(239, 83, 80), tps=(129, 199, 132), tp=(46, 204, 113), sr=(150, 150, 150), teks=(200, 205, 215))
IND = {"EMA20": (255, 214, 0), "EMA50": (255, 145, 0), "EMA200": (186, 104, 200), "MCG34": (0, 229, 255), "RSI": (255, 214, 0)}
LABEL = dict(entry="ENTRY", sl="SL", tps="TP20", tp="TP", sup="SUP", res="RES")
# font 3x5: angka, tanda, huruf besar
_F = {"0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111", "4": "101101111001001",
      "5": "111100111001111", "6": "111100111101111", "7": "111001001001001", "8": "111101111101111", "9": "111101111001111",
      ".": "000000000000010", "-": "000000111000000", " ": "000000000000000", "+": "000010111010000", "%": "101001010100101",
      ":": "000010000010000", "/": "001001010100100",
      "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110", "E": "111100110100111",
      "F": "111100110100100", "G": "011100101101011", "H": "101101111101101", "I": "111010010010111", "J": "001001001101010",
      "K": "101101110101101", "L": "100100100100111", "M": "101111111101101", "N": "110101101101101", "O": "010101101101010",
      "P": "110101110100100", "Q": "010101101111011", "R": "110101110101101", "S": "011100010001110", "T": "111010010010010",
      "U": "101101101101111", "V": "101101101101010", "W": "101101111111101", "X": "101101010101101", "Y": "101101010010010",
      "Z": "111001010100111"}


def _png(img):
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _teks(img, x, y, s, warna, sk=2):
    for ch in str(s).upper():
        g = _F.get(ch)
        if g is None:
            x += 4 * sk
            continue
        for i, bit in enumerate(g):
            if bit == "1":
                r, c = divmod(i, 3)
                y0, x0 = y + r * sk, x + c * sk
                if 0 <= y0 < img.shape[0] - sk and 0 <= x0 < img.shape[1] - sk:
                    img[y0:y0 + sk, x0:x0 + sk] = warna
        x += 4 * sk
    return x


def _angka(v):
    if v >= 1000:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.2f}"
    if v >= 0.1:
        return f"{v:.4f}"
    return f"{v:.6f}"


def _ema(x, n):
    a = 2 / (n + 1); o = np.empty(len(x)); o[0] = x[0]
    for i in range(1, len(x)):
        o[i] = o[i - 1] + a * (x[i] - o[i - 1])
    return o


def _mcg(c, n=34):
    m = np.empty(len(c)); m[0] = c[0]
    for i in range(1, len(c)):
        m[i] = m[i - 1] + (c[i] - m[i - 1]) / (n * (c[i] / max(m[i - 1], 1e-12)) ** 4)
    return m


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); u = np.where(d > 0, d, 0.0); v = np.where(d < 0, -d, 0.0)
    au, av = np.empty(len(c)), np.empty(len(c)); au[0], av[0] = u[0], v[0]
    for i in range(1, len(c)):
        au[i] = au[i - 1] + (u[i] - au[i - 1]) / n; av[i] = av[i - 1] + (v[i] - av[i - 1]) / n
    return 100 - 100 / (1 + au / np.maximum(av, 1e-12))


def _garis(img, xs, ys, warna, tebal=1):
    """Polyline: tiap pasangan titik dihubungkan (cukup halus untuk candle)."""
    for i in range(1, len(xs)):
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for t in range(n + 1):
            x = int(round(x0 + (x1 - x0) * t / n)); y = int(round(y0 + (y1 - y0) * t / n))
            if 0 <= y < img.shape[0] - tebal and 0 <= x < img.shape[1] - tebal:
                img[y:y + tebal, x:x + tebal] = warna


def _campur(img, y0, y1, x1, warna, alpha=0.18):
    a, b = sorted((max(y0, 0), min(y1, img.shape[0] - 1)))
    if b > a:
        blk = img[a:b, :x1].astype(float)
        img[a:b, :x1] = (blk * (1 - alpha) + np.array(warna) * alpha).astype(np.uint8)


def indikator_teknik(teknik):
    """Indikator yang digambar menurut nama teknik di kartu."""
    t = (teknik or "").upper()
    if "MCGINLEY" in t:
        return ["MCG34", "EMA200"]
    if "EMA" in t:
        return ["EMA20", "EMA50", "EMA200"]
    if "RSI" in t:
        return ["EMA50", "EMA200", "RSI"]
    return ["EMA50", "EMA200"]


def chart(df, garis, maks=70, judul="", arah=None, teknik=""):
    """df: DataFrame candle (open high low close [volume]). garis: dict nama -> harga (entry, sl, tps, tp, sup, res). Return bytes PNG."""
    ind = indikator_teknik(teknik)
    cs_all = df["close"].values.astype(float)
    seri = {}
    if "EMA20" in ind:
        seri["EMA20"] = _ema(cs_all, 20)
    if "EMA50" in ind:
        seri["EMA50"] = _ema(cs_all, 50)
    if "EMA200" in ind:
        seri["EMA200"] = _ema(cs_all, 200)
    if "MCG34" in ind:
        seri["MCG34"] = _mcg(cs_all, 34)
    rsi = _rsi(cs_all)[-maks:] if "RSI" in ind else None
    d = df.iloc[-maks:]
    o, h, l, c = (d[k].values.astype(float) for k in ("open", "high", "low", "close"))
    v = d["volume"].values.astype(float) if "volume" in d else None
    seri = {k: s_[-maks:] for k, s_ in seri.items()}
    lv = [x for x in garis.values() if x]
    lo, hi = min(l.min(), *lv), max(h.max(), *lv)
    pad = (hi - lo) * 0.06 or hi * 0.01
    lo, hi = lo - pad, hi + pad
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = BG
    pw = W - KANAN
    bawah = H - VOL_H - (RSI_H if rsi is not None else 0) - 8          # batas bawah panel harga
    y_ = lambda p: int(round((hi - p) / (hi - lo) * (bawah - ATAS - 10))) + ATAS + 5
    for k in range(1, 6):
        img[ATAS + int((bawah - ATAS) * k / 6), :pw] = GRID
    n = len(c)
    lebar = pw / n
    xm_ = [int(i * lebar + lebar / 2) for i in range(n)]
    e, s, t2 = garis.get("entry"), garis.get("sl"), garis.get("tp") or garis.get("tps")
    if e and s:
        _campur(img, y_(e), y_(s), pw, WARNA["sl"], 0.14)          # zona risiko
    if e and t2:
        _campur(img, y_(e), y_(t2), pw, WARNA["tp"], 0.12)          # zona untung
    for i in range(n):
        x0 = int(i * lebar + lebar * 0.15)
        x1 = max(x0 + 1, int((i + 1) * lebar - lebar * 0.15))
        xm = xm_[i]
        w_ = NAIK if c[i] >= o[i] else TURUN
        img[min(y_(h[i]), y_(l[i])):max(y_(h[i]), y_(l[i])) + 1, xm] = w_
        a, b = sorted((y_(o[i]), y_(c[i])))
        img[a:b + 1, x0:x1] = w_
    for nm, s_ in seri.items():
        _garis(img, xm_, [min(max(y_(x), ATAS), bawah) for x in s_], IND[nm], 2)
    for nm, p in garis.items():
        if not p:
            continue
        y = min(max(y_(p), ATAS), bawah - 3)
        col = WARNA["sr"] if nm in ("sup", "res") else WARNA[nm]
        if nm in ("sup", "res"):
            for x in range(0, pw, 12):
                img[y, x:x + 6] = col
        else:
            img[y:y + 2, :pw] = col
        img[max(y - 7, 0):max(y - 7, 0) + 14, pw + 2:W - 2] = col
        _teks(img, pw + 5, max(y - 5, 0), f"{LABEL.get(nm, nm)} {_angka(p)}", BG, 2)
    if arah in ("LONG", "SHORT"):          # panah di candle sinyal (terakhir)
        xa = xm_[-1]; col = NAIK if arah == "LONG" else TURUN
        ya = y_(l[-1]) + 14 if arah == "LONG" else y_(h[-1]) - 14
        for k in range(8):
            yy = ya + k if arah == "LONG" else ya - k
            if ATAS <= yy < bawah:
                img[yy, max(xa - k, 0):xa + k + 1] = col
        _teks(img, max(xa - 60, 0), min(ya + 12, bawah - 12) if arah == "LONG" else max(ya - 22, ATAS), arah, col, 2)
    if v is not None and v.max() > 0:          # panel volume
        y0 = bawah + 4; img[y0 - 2, :pw] = GRID
        for i in range(n):
            hv = int(v[i] / v.max() * (VOL_H - 6))
            xa0 = int(i * lebar + lebar * 0.2)
            img[y0 + VOL_H - 4 - hv:y0 + VOL_H - 4, xa0:max(xa0 + 1, int((i + 1) * lebar - lebar * 0.2))] = NAIK if c[i] >= o[i] else TURUN
        _teks(img, 4, y0 + 2, "VOL", WARNA["teks"], 2)
    if rsi is not None:          # panel RSI
        y0 = bawah + VOL_H + 6; img[y0 - 2, :pw] = GRID
        yr = lambda r: y0 + int((100 - r) / 100 * (RSI_H - 6))
        for lvl in (30, 50, 70):
            for x in range(0, pw, 10):
                img[yr(lvl), x:x + 4] = (90, 90, 90) if lvl == 50 else GRID
        _garis(img, xm_, [yr(x) for x in rsi], IND["RSI"], 2)
        _teks(img, 4, y0 + 2, f"RSI 14 {rsi[-1]:.0f}", IND["RSI"], 2)
    x = _teks(img, 6, 6, judul or "", WARNA["teks"], 3) + 12          # judul dan legenda indikator
    for nm in seri:
        img[11:15, x:x + 14] = IND[nm]
        x = _teks(img, x + 18, 8, nm, IND[nm], 2) + 10
    return _png(img)


def chart_sinyal(sym, arah, entry, sl, tps=None, tp=None, sup=None, res=None, df=None, teknik=""):
    """Ambil candle 4J dari Bybit kalau df tidak diberi. Gagal = None."""
    try:
        if df is None:
            import time
            import bybit_fetch as B
            ms = int(time.time() * 1000)
            df = B._raw(sym, "240", 300)          # 300 candle supaya EMA 200 stabil, 70 terakhir yang digambar
            df = df[df.index <= ms]
        if df is None or len(df) < 20:
            return None
        return chart(df, dict(entry=entry, sl=sl, tps=tps, tp=tp, sup=sup, res=res), judul=f"{sym.replace('USDT', '')} {arah} 4J",
                     arah=arah, teknik=teknik)
    except Exception as ex:
        print("[WARN] chart", sym, ex)
        return None
