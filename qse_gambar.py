"""QSE v150 - gambar chart sinyal (PNG) tanpa library tambahan: numpy + zlib.
Candle 4J terakhir, garis entry (biru), SL (merah), TP sebagian (hijau muda), TP (hijau), support dan resistance (abu putus-putus),
skala harga di kanan dengan angka kecil (font 3x5 buatan sendiri). Dipakai sebagai gambar di gelembung sinyal Telegram."""
import struct
import zlib
import numpy as np

W, H = 900, 520
KANAN = 110                      # ruang skala harga
BG = (17, 20, 27)
GRID = (34, 39, 50)
NAIK = (38, 166, 154)
TURUN = (239, 83, 80)
WARNA = dict(entry=(66, 133, 244), sl=(239, 83, 80), tps=(129, 199, 132), tp=(46, 204, 113), sr=(150, 150, 150), teks=(200, 205, 215))
# font angka 3x5
_F = {"0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111", "4": "101101111001001",
      "5": "111100111001111", "6": "111100111101111", "7": "111001001001001", "8": "111101111101111", "9": "111101111001111",
      ".": "000000000000010", "-": "000000111000000", " ": "000000000000000"}


def _png(img):
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _teks(img, x, y, s, warna, sk=2):
    for ch in s:
        g = _F.get(ch)
        if g is None:
            x += 4 * sk
            continue
        for i, bit in enumerate(g):
            if bit == "1":
                r, c = divmod(i, 3)
                img[y + r * sk:y + (r + 1) * sk, x + c * sk:x + (c + 1) * sk] = warna
        x += 4 * sk


def _angka(v):
    if v >= 1000:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.2f}"
    if v >= 0.1:
        return f"{v:.4f}"
    return f"{v:.6f}"


def chart(df, garis, maks=70):
    """df: DataFrame candle (open high low close). garis: dict nama -> harga (entry, sl, tps, tp, sup, res). Return bytes PNG."""
    d = df.iloc[-maks:]
    o, h, l, c = (d[k].values.astype(float) for k in ("open", "high", "low", "close"))
    lv = [v for v in garis.values() if v]
    lo, hi = min(l.min(), *lv), max(h.max(), *lv)
    pad = (hi - lo) * 0.06 or hi * 0.01
    lo, hi = lo - pad, hi + pad
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = BG
    pw = W - KANAN
    y_ = lambda p: int(round((hi - p) / (hi - lo) * (H - 20))) + 10
    for k in range(1, 6):
        img[int(H * k / 6), :pw] = GRID
    n = len(c)
    lebar = pw / n
    for i in range(n):
        x0 = int(i * lebar + lebar * 0.15)
        x1 = max(x0 + 1, int((i + 1) * lebar - lebar * 0.15))
        xm = (x0 + x1) // 2
        w_ = NAIK if c[i] >= o[i] else TURUN
        img[min(y_(h[i]), y_(l[i])):max(y_(h[i]), y_(l[i])) + 1, xm] = w_
        a, b = sorted((y_(o[i]), y_(c[i])))
        img[a:b + 1, x0:x1] = w_
    for nm, p in garis.items():
        if not p:
            continue
        y = min(max(y_(p), 0), H - 3)
        col = WARNA["sr"] if nm in ("sup", "res") else WARNA[nm]
        if nm in ("sup", "res"):
            for x in range(0, pw, 12):
                img[y, x:x + 6] = col
        else:
            img[y:y + 2, :pw] = col
        img[max(y - 7, 0):max(y - 7, 0) + 14, pw + 2:W - 2] = col
        _teks(img, pw + 6, max(y - 5, 0), _angka(p), BG, 2)
    return _png(img)


def chart_sinyal(sym, arah, entry, sl, tps=None, tp=None, sup=None, res=None, df=None):
    """Ambil candle 4J dari Bybit kalau df tidak diberi. Gagal = None."""
    try:
        if df is None:
            import time
            import bybit_fetch as B
            ms = int(time.time() * 1000)
            df = B._raw(sym, "240", 90)
            df = df[df.index <= ms]
        if df is None or len(df) < 20:
            return None
        return chart(df, dict(entry=entry, sl=sl, tps=tps, tp=tp, sup=sup, res=res))
    except Exception as ex:
        print("[WARN] chart", sym, ex)
        return None
