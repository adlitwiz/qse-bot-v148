"""QSE v148 - fungsi TA versi Pine Script v5 (numpy). na = np.nan, bool tidak pernah na."""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv

NAN = np.nan


def f64(x):
    return np.asarray(x, dtype=np.float64)


def sh(x, k=1):
    x = np.asarray(x)
    k = int(k)
    if k == 0:
        return x
    out = np.empty_like(x)
    if x.dtype == bool:
        out[:k] = False
    else:
        out = out.astype(np.float64)
        out[:k] = NAN
    out[k:] = x[:-k]
    return out


def nz(x, y=0.0):
    x = f64(x)
    return np.where(np.isnan(x), y, x)


def na(x):
    return np.isnan(f64(x))


def pmax(*a):
    r = f64(a[0]).copy() if np.ndim(a[0]) else np.float64(a[0])
    for b in a[1:]:
        r = np.maximum(r, b)
    return r


def pmin(*a):
    r = f64(a[0]).copy() if np.ndim(a[0]) else np.float64(a[0])
    for b in a[1:]:
        r = np.minimum(r, b)
    return r


def change(x, k=1):
    x = f64(x)
    return x - sh(x, k)


def _roll(x, n):
    x = f64(x)
    out = np.full((len(x), n), NAN)
    if len(x) >= n:
        out[n - 1:] = swv(x, n)
    return out


def sma(x, n):
    return pd.Series(f64(x)).rolling(n, min_periods=n).mean().values


def stdev(x, n):
    return pd.Series(f64(x)).rolling(n, min_periods=n).std(ddof=0).values


def highest(x, n):
    return pd.Series(f64(x)).rolling(n, min_periods=n).max().values


def lowest(x, n):
    return pd.Series(f64(x)).rolling(n, min_periods=n).min().values


try:
    from numba import njit as _njit
except Exception:
    def _njit(*a, **k):
        return a[0] if a and callable(a[0]) else (lambda f: f)


@_njit(cache=True)
def _rec_core(x, n, alpha):
    out = np.full(len(x), np.nan)
    run = 0
    seed_i = -1
    for i in range(len(x)):
        if x[i] != x[i]:
            run = 0
            continue
        run += 1
        if run >= n:
            seed_i = i
            break
    if seed_i < 0:
        return out
    prev = 0.0
    for k in range(seed_i - n + 1, seed_i + 1):
        prev += x[k]
    prev /= n
    out[seed_i] = prev
    for i in range(seed_i + 1, len(x)):
        if x[i] != x[i]:
            continue
        prev = alpha * x[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def _rec(x, n, alpha):
    return _rec_core(np.ascontiguousarray(f64(x)), int(n), float(alpha))


def ema(x, n):
    return _rec(x, n, 2.0 / (n + 1))


def rma(x, n):
    return _rec(x, n, 1.0 / n)


def tr(h, l, c, handle_na=True):
    c1 = sh(c, 1)
    t = np.maximum(h - l, np.maximum(np.abs(h - c1), np.abs(l - c1)))
    if handle_na:
        t[0] = h[0] - l[0]
    else:
        t[0] = NAN
    return t


def atr(h, l, c, n):
    return rma(tr(h, l, c, True), n)


def rsi(x, n):
    ch = change(x)
    u = np.where(np.isnan(ch), NAN, np.maximum(ch, 0))
    d = np.where(np.isnan(ch), NAN, np.maximum(-ch, 0))
    ru, rd = rma(u, n), rma(d, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(rd == 0, 100.0, np.where(ru == 0, 0.0, 100 - 100 / (1 + ru / rd)))
    r[np.isnan(ru) | np.isnan(rd)] = NAN
    return r


def percentrank(x, n):
    x = f64(x)
    out = np.full(len(x), NAN)
    if len(x) > n:
        w = swv(x, n + 1)
        cur = w[:, -1:]
        prev = w[:, :-1]
        bad = np.isnan(w).any(axis=1)
        pr = (prev <= cur).sum(axis=1) / n * 100.0
        pr[bad] = NAN
        out[n:] = pr
    return out


def correlation(a, b, n):
    return pd.Series(f64(a)).rolling(n, min_periods=n).corr(pd.Series(f64(b))).values


def linreg(x, n, off=0):
    w = _roll(x, n)
    xs = np.arange(n, dtype=np.float64)
    xm = xs.mean()
    ym = w.mean(axis=1)
    slope = ((xs - xm) * (w - ym[:, None])).sum(axis=1) / ((xs - xm) ** 2).sum()
    inter = ym - slope * xm
    return inter + slope * (n - 1 - off)


def pivothigh(x, l, r):
    """Nilai pivot muncul di bar i (pivot di i-r). Kiri wajib lebih rendah, kanan boleh sama."""
    x = f64(x)
    out = np.full(len(x), NAN)
    m = l + r + 1
    if len(x) < m:
        return out
    w = swv(x, m)
    c = w[:, l]
    ok = ~np.isnan(w).any(axis=1)
    ok &= (w[:, :l] < c[:, None]).all(axis=1)
    ok &= (w[:, l + 1:] <= c[:, None]).all(axis=1)
    idx = np.arange(m - 1, len(x))
    out[idx[ok]] = c[ok]
    return out


def pivotlow(x, l, r):
    x = f64(x)
    out = np.full(len(x), NAN)
    m = l + r + 1
    if len(x) < m:
        return out
    w = swv(x, m)
    c = w[:, l]
    ok = ~np.isnan(w).any(axis=1)
    ok &= (w[:, :l] > c[:, None]).all(axis=1)
    ok &= (w[:, l + 1:] >= c[:, None]).all(axis=1)
    idx = np.arange(m - 1, len(x))
    out[idx[ok]] = c[ok]
    return out


def valuewhen(cond, src):
    s = pd.Series(np.where(cond, f64(src), NAN))
    return s.ffill().values


def barssince(cond):
    out = np.full(len(cond), NAN)
    last = -1
    for i, c in enumerate(cond):
        if c:
            last = i
        if last >= 0:
            out[i] = i - last
    return out


def highestbars(x, n):
    """Offset <=0 ke nilai tertinggi. Seri: yang paling baru menang (loop Pine pakai >)."""
    w = _roll(x, n)
    rev = w[:, ::-1]
    ok = ~np.isnan(rev).any(axis=1)
    i = np.argmax(np.where(np.isnan(rev), -np.inf, rev), axis=1)
    out = -i.astype(np.float64)
    out[~ok] = NAN
    return out


def lowestbars(x, n):
    w = _roll(x, n)
    rev = w[:, ::-1]
    ok = ~np.isnan(rev).any(axis=1)
    i = np.argmin(np.where(np.isnan(rev), np.inf, rev), axis=1)
    out = -i.astype(np.float64)
    out[~ok] = NAN
    return out


def cum(x):
    return np.cumsum(nz(x, 0.0))


def crossover(a, b):
    a, b = f64(a), f64(b)
    return (a > b) & (sh(a) <= sh(b))


def crossunder(a, b):
    a, b = f64(a), f64(b)
    return (a < b) & (sh(a) >= sh(b))


def fixnan(x):
    return pd.Series(f64(x)).ffill().values


def dmi(h, l, c, di_len, adx_len):
    up = change(h)
    dn = -change(l)
    pdm = np.where(np.isnan(up), NAN, np.where((up > dn) & (up > 0), up, 0.0))
    mdm = np.where(np.isnan(dn), NAN, np.where((dn > up) & (dn > 0), dn, 0.0))
    trur = rma(tr(h, l, c, False), di_len)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus = fixnan(100 * rma(pdm, di_len) / trur)
        minus = fixnan(100 * rma(mdm, di_len) / trur)
        s = plus + minus
        adx = 100 * rma(np.abs(plus - minus) / np.where(s == 0, 1, s), adx_len)
    return plus, minus, adx


def macd(x, fast, slow, sig):
    m = ema(x, fast) - ema(x, slow)
    s = ema(m, sig)
    return m, s, m - s


def supertrend(h, l, c, factor, n):
    src = (h + l) / 2
    a = atr(h, l, c, n)
    ub0 = src + factor * a
    lb0 = src - factor * a
    N = len(c)
    ub = np.full(N, NAN)
    lb = np.full(N, NAN)
    st = np.full(N, NAN)
    d = np.full(N, NAN)
    for i in range(N):
        plb = lb[i - 1] if i > 0 and not np.isnan(lb[i - 1]) else 0.0
        pub = ub[i - 1] if i > 0 and not np.isnan(ub[i - 1]) else 0.0
        c1 = c[i - 1] if i > 0 else NAN
        lbi, ubi = lb0[i], ub0[i]
        lb[i] = lbi if (lbi > plb or c1 < plb) else plb
        ub[i] = ubi if (ubi < pub or c1 > pub) else pub
        if np.isnan(a[i - 1] if i > 0 else NAN):
            di = 1.0
        elif (st[i - 1] if i > 0 else NAN) == pub:
            di = -1.0 if c[i] > ub[i] else 1.0
        else:
            di = 1.0 if c[i] < lb[i] else -1.0
        d[i] = di
        st[i] = lb[i] if di == -1 else ub[i]
    return st, d


def vwap_daily(ts_ms, src, vol):
    day = np.asarray(ts_ms) // 86400000
    df = pd.DataFrame({"d": day, "pv": f64(src) * f64(vol), "v": f64(vol)})
    g = df.groupby("d")
    with np.errstate(divide="ignore", invalid="ignore"):
        return (g["pv"].cumsum() / g["v"].cumsum()).values


def stoch(src, hi, lo, n):
    ll, hh = lowest(lo, n), highest(hi, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = hh - ll
        return np.where(d == 0, NAN, 100 * (f64(src) - ll) / d)


def ta_highest(x, n):
    return highest(x, n)


def ta_lowest(x, n):
    return lowest(x, n)


def math_abs(x):
    return np.abs(x)


def math_avg(*a):
    return sum(f64(x) for x in a) / len(a)
