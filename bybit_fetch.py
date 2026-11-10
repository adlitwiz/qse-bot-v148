"""QSE v150 - ambil data Bybit publik (tanpa API key): daftar perpetual, ticker, candle 4H/1H/D/W dengan paging.
v170 QC 64 (10 Nov 2026): pipeline tahan gagal. (1) _get: 6 percobaan, jeda naik, sesi HTTP dibuat ulang saat koneksi putus, host
cadangan api.bytick.com (domain resmi kedua Bybit). (2) _raw: hasil sukses disimpan sebagai salinan terakhir yang baik per koin dan
TF. Saat API gagal atau kosong, salinan itu dipakai selama umurnya masih wajar (maks separuh panjang candle, paling lama 2 jam),
supaya Sniper Koin Spesialis (PSG, ACM, CITY, dll) dan modul lain tidak kehilangan data karena satu gangguan jaringan.
(3) get_tickers: gagal -> salinan ticker terakhir (maks 30 menit). (4) memo 20 detik untuk permintaan candle yang sama. STAT mencatat
jumlah ulang, pindah host, dan pemakaian salinan (lihat status()).
(5) AKAR MASALAH Sniper Koin Spesialis: token klub (PSG, ACM, BAR, CITY, LAZIO, PORTO) tidak punya kontrak Perpetual di Bybit, hanya
Spot, jadi permintaan kategori linear selalu kosong. Sekarang _raw dan ticker_multi berantai: Bybit Perpetual -> Bybit Spot ->
Binance Spot (data-api.binance.vision). Sumber yang berhasil diingat per koin (sumber_koin.json) dan dicoba lebih dulu."""
import time
import threading
import requests
import numpy as np
import pandas as pd
import os
import json
from config import BYBIT_URL, REQ_PER_SEC, STATE_DIR

_S = requests.Session()
_S.headers.update({"User-Agent": "qse-bot/150"})
_lock = threading.Lock()
_last = [0.0]
IV_MS = {"240": 4 * 3600000, "60": 3600000, "D": 86400000, "W": 7 * 86400000}
CACHE = os.path.join(STATE_DIR, "cache")
HOSTS = [BYBIT_URL] + [h for h in os.environ.get("QSE_BYBIT_CADANGAN", "https://api.bytick.com").split(",") if h and h != BYBIT_URL]
STAT = dict(ulang=0, pindah_host=0, salinan=0, gagal=0, salinan_ticker=0)
_host = [0]
_memo = {}
MEMO_DETIK = 20
SALINAN_DETIK = 600          # salinan terakhir yang baik ditulis ulang paling cepat tiap 10 menit per koin+TF


def _sesi_baru():
    global _S
    try:
        _S.close()
    except Exception:
        pass
    _S = requests.Session()
    _S.headers.update({"User-Agent": "qse-bot/170"})


class SimbolSalah(RuntimeError):
    """Koin tidak ada di kategori yang diminta: tidak diulang, langsung pindah sumber."""


BINANCE_URL = os.environ.get("QSE_BINANCE_URL", "https://data-api.binance.vision")
IV_BINANCE = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h", "240": "4h", "D": "1d", "W": "1w"}
SUMBER_NAMA = {"linear": "Bybit Perpetual", "spot": "Bybit Spot", "binance": "Binance Spot"}
_sumber = {}
_sumber_muat = [False]


def _sumber_path():
    return os.path.join(CACHE, "sumber_koin.json")


def sumber(symbol):
    """Sumber data koin yang terakhir berhasil: 'linear', 'spot', 'binance', atau None kalau belum pernah diambil."""
    if not _sumber_muat[0]:
        _sumber_muat[0] = True
        try:
            with open(_sumber_path()) as f:
                _sumber.update(json.load(f))
        except Exception:
            pass
    v = _sumber.get(symbol)
    if not v:
        return None
    if v[0] != "linear" and time.time() - v[1] > 43200:
        return None          # sumber bukan perpetual dicek ulang tiap 12 jam (jaga kalau perpetual sempat kosong sesaat atau baru listing)
    return v[0]


def _ingat_sumber(symbol, src):
    if sumber(symbol) == src:
        return
    _sumber[symbol] = [src, time.time()]
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(_sumber_path() + ".tmp", "w") as f:
            json.dump(_sumber, f)
        os.replace(_sumber_path() + ".tmp", _sumber_path())
    except Exception:
        pass


def status():
    return dict(STAT, host=HOSTS[_host[0] % len(HOSTS)], sumber_bukan_perp={k: v[0] for k, v in _sumber.items() if v[0] != "linear"})


def _get(path, params, tries=6):
    n403 = 0
    for k in range(tries):
        with _lock:
            wait = _last[0] + 1.0 / REQ_PER_SEC - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            r = _S.get(HOSTS[_host[0] % len(HOSTS)] + path, params=params, timeout=20)
            if r.status_code == 403:
                raise RuntimeError("Bybit menolak IP ini (403). Jalankan dari VPS, bukan runner GitHub.")
            r.raise_for_status()
            j = r.json()
            if j.get("retCode") == 10006:
                STAT["ulang"] += 1
                time.sleep(2 + k * 2)
                continue
            if j.get("retCode") == 10001:
                raise SimbolSalah(f"Bybit {path}: {j.get('retMsg')}")
            if j.get("retCode") != 0:
                raise RuntimeError(f"Bybit {path}: {j.get('retMsg')}")
            return j["result"]
        except SimbolSalah:
            raise
        except RuntimeError as e:
            if "403" in str(e) and len(HOSTS) < 2:
                raise
            if k == tries - 1:
                STAT["gagal"] += 1
                raise
            STAT["ulang"] += 1
            if "403" in str(e):
                n403 += 1
                if n403 >= len(HOSTS):          # semua host menolak IP ini: tidak ada gunanya mengulang
                    STAT["gagal"] += 1
                    raise
                _host[0] += 1; STAT["pindah_host"] += 1
                continue
            time.sleep(1 + k * 2)
        except Exception:
            if k == tries - 1:
                STAT["gagal"] += 1
                raise
            STAT["ulang"] += 1
            if k >= 1:          # koneksi putus berulang: sesi baru, percobaan ke-3 dst pindah host
                _sesi_baru()
            if k >= 2 and len(HOSTS) > 1:
                _host[0] += 1; STAT["pindah_host"] += 1
            time.sleep(min(1 + k * 2, 8))


def _bukan_saham(s):
    try:
        from config import bukan_saham
        return bukan_saham(s)
    except Exception:
        return True


def get_symbols(quote="USDT"):
    out, cursor = {}, ""
    while True:
        p = {"category": "linear", "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        res = _get("/v5/market/instruments-info", p)
        for it in res.get("list", []):
            if it.get("quoteCoin") == quote and it.get("status") == "Trading" and it.get("contractType") == "LinearPerpetual" and _bukan_saham(it["symbol"]):
                out[it["symbol"]] = float(it["priceFilter"]["tickSize"])
        cursor = res.get("nextPageCursor", "")
        if not cursor:
            break
    return dict(sorted(out.items()))


def get_tickers():
    """Ticker semua perpetual. API gagal -> salinan terakhir (maks 30 menit), supaya pemindaian tidak berhenti."""
    path = os.path.join(CACHE, "tickers_terakhir.json")
    try:
        t = _tickers_api()
        if t:
            try:
                os.makedirs(CACHE, exist_ok=True)
                with open(path + ".tmp", "w") as f:
                    json.dump(dict(t=time.time(), tk=t), f)
                os.replace(path + ".tmp", path)
            except Exception:
                pass
            return t
        raise RuntimeError("ticker kosong")
    except Exception:
        try:
            with open(path) as f:
                d = json.load(f)
            if time.time() - d["t"] <= 1800:
                STAT["salinan_ticker"] += 1
                print(f"[WARN] ticker Bybit gagal, pakai salinan {int(time.time() - d['t'])} detik lalu")
                return d["tk"]
        except Exception:
            pass
        raise


_tk_lain = {}


def ticker_multi(symbols, tk=None):
    """Ticker untuk koin yang TIDAK ada di Bybit Perpetual: Bybit Spot lalu Binance Spot. Return dict sym -> dict ticker + 'sumber'.
    Gagal di semua sumber -> salinan terakhir (maks 30 menit). Koin yang ada di tk (perpetual) dilewati."""
    tk = tk or {}
    perlu = [s for s in symbols if s not in tk]
    out = {}
    if not perlu:
        return out
    spot = {}
    try:
        for it in _get("/v5/market/tickers", {"category": "spot"}).get("list", []):
            spot[it.get("symbol")] = it
    except Exception as ex:
        print("[WARN] ticker spot Bybit", ex)
    for s in perlu:
        try:
            it = spot.get(s)
            if it and float(it.get("lastPrice") or 0) > 0:
                bid, ask = float(it.get("bid1Price") or 0), float(it.get("ask1Price") or 0)
                out[s] = dict(turnover=float(it.get("turnover24h") or 0), funding=0.0, last=float(it["lastPrice"]),
                              chg24=float(it.get("price24hPcnt") or 0),
                              spread=(ask - bid) / ((ask + bid) / 2) * 100 if bid > 0 and ask > 0 else 99.0, sumber="spot")
                continue
            j = _binance_get("/api/v3/ticker/24hr", {"symbol": s})
            bid, ask = float(j.get("bidPrice") or 0), float(j.get("askPrice") or 0)
            if float(j.get("lastPrice") or 0) > 0:
                out[s] = dict(turnover=float(j.get("quoteVolume") or 0), funding=0.0, last=float(j["lastPrice"]),
                              chg24=float(j.get("priceChangePercent") or 0) / 100,
                              spread=(ask - bid) / ((ask + bid) / 2) * 100 if bid > 0 and ask > 0 else 99.0, sumber="binance")
        except Exception as ex:
            print("[WARN] ticker", s, ex)
        if s in out:
            _tk_lain[s] = (time.time(), out[s])
        elif s in _tk_lain and time.time() - _tk_lain[s][0] <= 1800:
            out[s] = _tk_lain[s][1]
            STAT["salinan_ticker"] += 1
    return out


def harga(symbol):
    """Harga terakhir satu koin dari sumber mana pun (perpetual, spot Bybit, Binance). 0.0 kalau semua gagal."""
    try:
        if sumber(symbol) in (None, "linear"):
            lst = _get("/v5/market/tickers", {"category": "linear", "symbol": symbol}, tries=2).get("list", [])
            if lst and float(lst[0].get("lastPrice") or 0) > 0:
                return float(lst[0]["lastPrice"])
    except Exception:
        pass
    try:
        return float(ticker_multi([symbol]).get(symbol, {}).get("last", 0.0))
    except Exception:
        return 0.0


def _tickers_api():
    res = _get("/v5/market/tickers", {"category": "linear"})
    t = {}
    for it in res.get("list", []):
        if not _bukan_saham(it.get("symbol", "")):
            continue
        try:
            bid, ask = float(it.get("bid1Price") or 0), float(it.get("ask1Price") or 0)
            t[it["symbol"]] = dict(
                turnover=float(it.get("turnover24h") or 0), funding=float(it.get("fundingRate") or 0),
                last=float(it.get("lastPrice") or 0), chg24=float(it.get("price24hPcnt") or 0),
                spread=(ask - bid) / ((ask + bid) / 2) * 100 if bid > 0 and ask > 0 else 99.0)
        except (TypeError, ValueError):
            pass
    return t


def _umur_salinan_maks(interval):
    iv = IV_MS.get(str(interval)) or (int(interval) * 60000 if str(interval).isdigit() else 3600000)
    return min(iv / 2000.0, 7200.0)


def _raw(symbol, interval, bars):
    """Candle mentah dengan pengaman: memo 20 detik, salinan terakhir yang baik saat API gagal atau kosong."""
    key = (symbol, str(interval), int(bars))
    now = time.time()
    m = _memo.get(key)
    if m and now - m[0] <= MEMO_DETIK:
        return m[1].copy()
    path = os.path.join(CACHE, f"raw_{symbol}_{interval}.pkl")
    err = None
    try:
        df = _raw_api(symbol, interval, bars)
    except Exception as ex:
        df, err = None, ex
    if df is not None and len(df):
        if len(_memo) > 4000:
            _memo.clear()
        _memo[key] = (now, df)
        try:
            if (not os.path.exists(path)) or now - os.path.getmtime(path) >= SALINAN_DETIK:
                os.makedirs(CACHE, exist_ok=True)
                df.to_pickle(path + ".tmp")
                os.replace(path + ".tmp", path)
        except Exception:
            pass
        return df.copy()
    try:          # API gagal atau kosong: salinan terakhir yang baik
        if os.path.exists(path) and now - os.path.getmtime(path) <= _umur_salinan_maks(interval):
            old = pd.read_pickle(path)
            if len(old):
                STAT["salinan"] += 1
                print(f"[WARN] {symbol} {interval} gagal ({err or 'kosong'}), pakai salinan {int(now - os.path.getmtime(path))} detik lalu")
                old = old.iloc[-int(bars):] if bars else old
                old.attrs["salinan"] = True
                return old
    except Exception:
        pass
    if err is not None:
        raise err
    return df


def _binance_get(path, params, tries=4):
    for k in range(tries):
        try:
            r = requests.get(BINANCE_URL + path, params=params, timeout=20)
            if r.status_code == 400:
                raise SimbolSalah(f"Binance {path}: {r.text[:80]}")
            r.raise_for_status()
            return r.json()
        except SimbolSalah:
            raise
        except Exception:
            if k == tries - 1:
                raise
            STAT["ulang"] += 1
            time.sleep(1 + k * 2)


def _raw_binance(symbol, interval, bars):
    iv = IV_BINANCE.get(str(interval))
    if not iv:
        raise SimbolSalah(f"TF {interval} tidak ada di Binance")
    rows, end = [], None
    while len(rows) < bars:
        p = {"symbol": symbol, "interval": iv, "limit": 1000}
        if end is not None:
            p["endTime"] = end
        lst = _binance_get("/api/v3/klines", p)
        if not lst:
            break
        rows = lst + rows
        end = int(lst[0][0]) - 1
        if len(lst) < 1000:
            break
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)
    a = np.array([[float(x) for x in r[:6]] for r in rows])
    df = pd.DataFrame(a[:, 1:6], columns=["open", "high", "low", "close", "volume"], index=a[:, 0].astype(np.int64))
    return df[~df.index.duplicated()].sort_index().iloc[-int(bars):]


def _raw_api(symbol, interval, bars):
    """Berantai: sumber yang diingat dulu, lalu Bybit Perpetual -> Bybit Spot -> Binance Spot. Kosong di semua sumber = DataFrame kosong."""
    urut = ["linear", "spot", "binance"]
    ingat = sumber(symbol)
    if ingat in urut:
        urut = [ingat] + [x for x in urut if x != ingat]
    err, kosong = None, None
    for src in urut:
        try:
            df = _raw_binance(symbol, interval, bars) if src == "binance" else _raw_bybit(symbol, interval, bars, src)
        except SimbolSalah:
            continue
        except Exception as ex:
            err = err or ex
            continue
        if len(df):
            _ingat_sumber(symbol, src)
            df.attrs["sumber"] = src
            return df
        kosong = df
    if err is not None:
        raise err
    return kosong if kosong is not None else pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)


def _raw_bybit(symbol, interval, bars, category="linear"):
    rows, end = [], None
    while len(rows) < bars:
        p = {"category": category, "symbol": symbol, "interval": interval, "limit": 1000}
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
