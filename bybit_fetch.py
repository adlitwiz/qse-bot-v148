"""QSE v148 - ambil data Bybit publik (tanpa API key): daftar perpetual, ticker, candle 4H/1H/D/W dengan paging."""
import time
import threading
import requests
import numpy as np
import pandas as pd
import os
from config import BYBIT_URL, REQ_PER_SEC, STATE_DIR

_S = requests.Session()
_S.headers.update({"User-Agent": "qse-bot/148"})
_lock = threading.Lock()
_last = [0.0]
IV_MS = {"240": 4 * 3600000, "60": 3600000, "D": 86400000, "W": 7 * 86400000}
CACHE = os.path.join(STATE_DIR, "cache")


def _get(path, params, tries=5):
    for k in range(tries):
        with _lock:
            wait = _last[0] + 1.0 / REQ_PER_SEC - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            r = _S.get(BYBIT_URL + path, params=params, timeout=20)
            if r.status_code == 403:
                raise RuntimeError("Bybit menolak IP ini (403). Jalankan dari VPS, bukan runner GitHub.")
            r.raise_for_status()
            j = r.json()
            if j.get("retCode") == 10006:
                time.sleep(2 + k * 2)
                continue
            if j.get("retCode") != 0:
                raise RuntimeError(f"Bybit {path}: {j.get('retMsg')}")
            return j["result"]
        except RuntimeError as e:
            if "403" in str(e):
                raise
            if k == tries - 1:
                raise
            time.sleep(1 + k * 2)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(1 + k * 2)


def get_symbols(quote="USDT"):
    out, cursor = {}, ""
    while True:
        p = {"category": "linear", "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        res = _get("/v5/market/instruments-info", p)
        for it in res.get("list", []):
            if it.get("quoteCoin") == quote and it.get("status") == "Trading" and it.get("contractType") == "LinearPerpetual":
                out[it["symbol"]] = float(it["priceFilter"]["tickSize"])
        cursor = res.get("nextPageCursor", "")
        if not cursor:
            break
    return dict(sorted(out.items()))


def get_tickers():
    res = _get("/v5/market/tickers", {"category": "linear"})
    t = {}
    for it in res.get("list", []):
        try:
            bid, ask = float(it.get("bid1Price") or 0), float(it.get("ask1Price") or 0)
            t[it["symbol"]] = dict(
                turnover=float(it.get("turnover24h") or 0), funding=float(it.get("fundingRate") or 0),
                last=float(it.get("lastPrice") or 0),
                spread=(ask - bid) / ((ask + bid) / 2) * 100 if bid > 0 and ask > 0 else 99.0)
        except (TypeError, ValueError):
            pass
    return t


def _raw(symbol, interval, bars):
    rows, end = [], None
    while len(rows) < bars:
        p = {"category": "linear", "symbol": symbol, "interval": interval, "limit": 1000}
        if end is not None:
            p["end"] = end
        lst = _get("/v5/market/kline", p).get("list", [])
        if not lst:
            break
        rows.extend(lst)
        end = int(lst[-1][0]) - 1
        if len(lst) < 1000:
            break
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)
    a = np.array([[float(x) for x in r[:6]] for r in rows])
    df = pd.DataFrame(a[:, 1:6], columns=["open", "high", "low", "close", "volume"], index=a[:, 0].astype(np.int64))
    return df[~df.index.duplicated()].sort_index()


def get_klines(symbol, interval="240", bars=5000, closed_only=True, cache=True):
    """`bars` candle terakhir. Riwayat disimpan di disk, tiap run hanya ambil 1 halaman terbaru.
    closed_only=False menyertakan candle yang sedang berjalan (dibutuhkan pemetaan TF lebih tinggi)."""
    iv = IV_MS[interval]
    now = int(time.time() * 1000)
    path = os.path.join(CACHE, f"{symbol}_{interval}.pkl")
    old = None
    if cache and os.path.exists(path):
        try:
            old = pd.read_pickle(path)
        except Exception:
            old = None
    full = False
    if old is not None and (len(old) >= bars or old.attrs.get("habis", False)):
        new = _raw(symbol, interval, 1000)
        if len(new) and new.index.min() <= old.index.max():
            df = pd.concat([old[old.index < new.index.min()], new])
            full = old.attrs.get("habis", False)
        else:
            df = _raw(symbol, interval, bars + 2)
            full = len(df) < bars + 2
    else:
        df = _raw(symbol, interval, bars + 2)
        full = len(df) < bars + 2
    keep = max(bars + 50, len(old) if old is not None else 0)
    df = df.iloc[-keep:]
    df.attrs["habis"] = bool(full)
    if cache and len(df):
        os.makedirs(CACHE, exist_ok=True)
        df.to_pickle(path + ".tmp")
        os.replace(path + ".tmp", path)
    if closed_only:
        df = df[df.index + iv <= now]
    if bars and len(df) > bars:
        df = df.iloc[-bars:]
    df = df.copy()
    df.index = pd.to_datetime(df.index, unit="ms", utc=True)
    return df
