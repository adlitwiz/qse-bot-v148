"""QSE v148 - LATIH ULANG OTOMATIS model arah BTC 24 jam dan perkiraan rentang (qse_tebak).

Jalan sendiri tiap Senin 05:30 WIB dari qse_listener, sebelum sesi 06:00 WIB. Tidak ada perintah.
Data latih = sejarah riset 2017-2026 (arah_data.csv.gz, 4 sesi 06/12/18/00 WIB) + catatan live bot sendiri
(STATE_DIR/arah_live.json, ditulis qse_tebak setiap tebakan sudah lewat 24 jam).
Cara latih sama persis dengan riset/arah_harian/latih_final.py, tanpa sklearn (regresi logistik L2 C=0.01 metode Newton,
regresi linear kuadrat terkecil). Diuji ulang: hasilnya sama dengan model riset (lihat uji_latih di riset).

Penjaga kualitas, model baru hanya dipakai kalau semua lolos:
1. semua koefisien terhingga dan tandanya sama dengan model yang sedang dipakai (uji maju 2019-2026: tanda tidak pernah berbalik)
2. akurasi uji maju (latih tahun sebelumnya, uji tahun berikutnya, 2019 sampai sekarang) tidak turun lebih dari 1 poin
3. akurasi keyakinan KUAT tidak turun lebih dari 2 poin
4. data latih tidak berkurang
Kalau satu gagal, model lama tetap dipakai dan alasannya dikirim ke Telegram. Model baru disimpan di STATE_DIR (bukan folder
repo) supaya git pull tidak bentrok. Model lama dicadangkan ke arah_model_lama.json."""
import json
import math
import os
import time

import numpy as np
import pandas as pd

from config import STATE_DIR

FIT = ["a_r7", "a_e20", "a_rsi", "a_cp", "akhir_pekan", "pasar24"]
RFIT = ["l_rng24", "l_rng7", "l_rv30", "pekan", "senin", "l_vrel", "abs_r1"]
C = 0.01
KLIP = 4.0
SESI = (23, 5, 11, 17)
DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "arah_data.csv.gz")
MODEL_REPO = os.path.join(DIR, "arah_model.json")
MODEL_STATE = os.path.join(STATE_DIR, "arah_model.json")
LIVE = os.path.join(STATE_DIR, "arah_live.json")
TOL_AKURASI, TOL_KUAT = 1.0, 2.0


# ---------------------------------------------------------------- model numpy
def logreg(X, y, c=C, iters=100):
    """Regresi logistik L2 sama dengan sklearn LogisticRegression(C=c): minimum jumlah log-loss + ||w||^2 / (2c),
    intersep tidak dipenalti. Metode Newton. Return (w, b)."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    lam = np.r_[0.0, np.full(k, 1.0 / c)]
    w = np.zeros(k + 1)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xb @ w, -35, 35)))
        g = Xb.T @ (p - y) + lam * w
        Hm = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(lam)
        step = np.linalg.solve(Hm, g)
        w -= step
        if np.max(np.abs(step)) < 1e-12:
            break
    return w[1:], float(w[0])


def proba(Xz, w, b):
    return 1.0 / (1.0 + np.exp(-np.clip(np.asarray(Xz, float) @ np.asarray(w) + b, -35, 35)))


def linreg(X, y):
    X = np.asarray(X, float)
    Xb = np.hstack([np.ones((len(X), 1)), X])
    coef, *_ = np.linalg.lstsq(Xb, np.asarray(y, float), rcond=None)
    return coef[1:], float(coef[0])


def zfit(X):
    return X.mean(), X.std().replace(0, 1)


def z(X, mu, sd):
    return ((X - mu) / sd).clip(-KLIP, KLIP).fillna(0)


def per_tingkat(p, y):
    k = (p - 0.5).abs()
    benar = (p > 0.5) == (y > 0)
    out = {}
    for nm, lo, hi in (("kuat", 0.03, 1), ("sedang", 0.01, 0.03), ("tipis", 0, 0.01)):
        m = (k >= lo) & (k < hi)
        out[nm] = [round(float(m.mean()) * 100, 1), round(float(benar[m].mean()) * 100, 1) if m.any() else 50.0]
    return out


# ---------------------------------------------------------------- data
def _baca_live():
    try:
        with open(LIVE) as f:
            return json.load(f)
    except Exception:
        return []


def catat_live(baris):
    """Tambah satu baris data latih live (dipanggil qse_tebak setelah tebakan lewat 24 jam). Unik per (T, H)."""
    try:
        data = _baca_live()
        if any(r.get("T") == baris["T"] and r.get("H") == baris["H"] for r in data):
            return
        data.append(baris)
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LIVE + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(LIVE + ".tmp", LIVE)
    except Exception as ex:
        print("[WARN] catat live arah", ex)


def data_latih():
    """Sejarah + live, satu tabel. Baris live dipakai kalau T-nya lebih baru dari sejarah sesi itu."""
    A = pd.read_csv(DATA)
    L = pd.DataFrame(_baca_live())
    n_live = 0
    if len(L):
        L = L[[c for c in A.columns if c in L.columns]]
        akhir = A.groupby("H")["T"].max().to_dict()
        L = L[L.apply(lambda r: r["T"] > akhir.get(int(r["H"]), 0), axis=1)]
        n_live = len(L)
        A = pd.concat([A, L], ignore_index=True)
    A = A.drop_duplicates(["H", "T"], keep="last").sort_values(["H", "T"]).reset_index(drop=True)
    A.index = pd.to_datetime(A["T"], unit="s", utc=True)
    return A.replace([np.inf, -np.inf], np.nan), n_live


# ---------------------------------------------------------------- latih satu sesi (sama dengan latih_final.py)
def latih_sesi(F):
    D = F[F.y.notna()]
    oos = []
    th_akhir = int(D.index[-1].year)
    for th in range(2019, th_akhir + 1):
        a, b = pd.Timestamp(f"{th}-01-01", tz="UTC"), pd.Timestamp(f"{th + 1}-01-01", tz="UTC")
        tr, te = D[D.index < a], D[(D.index >= a) & (D.index < b)]
        if not len(te):
            continue
        mu, sd = zfit(tr[FIT])
        w, b0 = logreg(z(tr[FIT], mu, sd), (tr.y > 0).astype(int))
        oos.append(pd.DataFrame({"p": proba(z(te[FIT], mu, sd), w, b0), "y": te.y, "ya": te.ya}, index=te.index))
    R = pd.concat(oos)
    benar = (R.p > 0.5) == (R.y > 0)
    nk = R.p > 0.5
    ya_ok = R.ya.notna()
    uji = dict(n=int(len(R)), dari=str(R.index[0].date()), sampai=str(R.index[-1].date()),
               akurasi=round(float(benar.mean()) * 100, 1), tingkat=per_tingkat(R.p, R.y),
               naik_benar=round(float((R.y[nk] > 0).mean()) * 100, 1), turun_benar=round(float((R.y[~nk] <= 0).mean()) * 100, 1),
               alt_naik_benar=round(float((R.ya[nk & ya_ok] > 0).mean()) * 100, 1),
               alt_turun_benar=round(float((R.ya[~nk & ya_ok] <= 0).mean()) * 100, 1),
               per_tahun={int(y): round(float(g.mean()) * 100, 1) for y, g in benar.groupby(R.index.year)},
               pekan_naik=round(float((D.y[D.akhir_pekan == 1] > 0).mean()) * 100, 1),
               kerja_naik=round(float((D.y[D.akhir_pekan == 0] > 0).mean()) * 100, 1),
               ikut_rata=round(float((np.where(R.p > 0.5, 1, -1) * R.y).mean()) * 100, 3))
    mu, sd = zfit(D[FIT])
    w, b0 = logreg(z(D[FIT], mu, sd), (D.y > 0).astype(int))
    arah = dict(mu=[float(v) for v in mu], sd=[float(v) for v in sd], w=[float(v) for v in w], b=float(b0))
    arah["pasar_tabel"] = []
    for lo, hi in ((-9, -0.03), (-0.03, -0.01), (-0.01, 0.01), (0.01, 0.03), (0.03, 9)):
        mk = (D.pasar24 > lo) & (D.pasar24 <= hi)
        arah["pasar_tabel"].append([lo, hi, round(float((D.y[mk] > 0).mean()) * 100, 1), int(mk.sum())])
    # rentang 24 jam
    X = F[RFIT]
    ok = np.isfinite(X).all(axis=1) & F.yrng.notna() & (F.yrng > 0) & F.yup.notna() & F.ydn.notna()
    X, G = X[ok], F[ok]
    ly = np.log(G.yrng)
    ro = []
    for th in range(2019, int(X.index[-1].year) + 1):
        a, b = pd.Timestamp(f"{th}-01-01", tz="UTC"), pd.Timestamp(f"{th + 1}-01-01", tz="UTC")
        tr, te = X.index < a, (X.index >= a) & (X.index < b)
        if not te.any():
            continue
        cw, cb = linreg(X[tr], ly[tr])
        s_tr, s_te = np.exp(X[tr].values @ cw + cb), np.exp(X[te].values @ cw + cb)
        u, d = G.yup[tr] / s_tr, -G.ydn[tr] / s_tr
        o = pd.DataFrame({"s": s_te, "yrng": G.yrng[te], "yup": G.yup[te], "ydn": G.ydn[te]}, index=X.index[te])
        for q in (0.5, 0.9):
            o[f"u{int(q * 100)}"] = u.quantile(q) * s_te
            o[f"d{int(q * 100)}"] = d.quantile(q) * s_te
        ro.append(o)
    RR = pd.concat(ro)
    isi90 = (RR.yup <= RR.u90) & (-RR.ydn <= RR.d90)
    cw, cb = linreg(X, ly)
    s_all = np.exp(X.values @ cw + cb)
    u, d = G.yup / s_all, -G.ydn / s_all
    lv = [float(np.quantile(s_all, 1 / 3)), float(np.quantile(s_all, 2 / 3))]
    tg = pd.cut(pd.Series(s_all, index=X.index), [0, lv[0], lv[1], 9], labels=["rendah", "sedang", "tinggi"])
    rentang = dict(w=[float(v) for v in cw], b=float(cb),
                   q=dict(u50=float(u.quantile(0.5)), d50=float(d.quantile(0.5)), u90=float(u.quantile(0.9)), d90=float(d.quantile(0.9))),
                   lv=lv,
                   gerak5={k: round(float((G.yrng[tg == k] > 0.05).mean()) * 100, 1) for k in ("rendah", "sedang", "tinggi")},
                   median={k: round(float(G.yrng[tg == k].median()) * 100, 2) for k in ("rendah", "sedang", "tinggi")},
                   uji=dict(isi90=round(float(isi90.mean()) * 100, 1),
                            isi_per={nm: round(float(isi90[mk].mean()) * 100, 1) for nm, mk in
                                     (("2019-21", RR.index < "2022"), ("2022-23", (RR.index >= "2022") & (RR.index < "2024")),
                                      ("2024-26", RR.index >= "2024")) if mk.any()},
                            naik50=round(float((RR.yup <= RR.u50).mean()) * 100, 1),
                            turun50=round(float((-RR.ydn <= RR.d50).mean()) * 100, 1),
                            r2=round(float(1 - ((np.log(RR.yrng) - np.log(RR.s)) ** 2).sum()
                                           / ((np.log(RR.yrng) - np.log(RR.yrng).mean()) ** 2).sum()), 3)))
    return dict(arah=arah, uji=uji, rentang=rentang), int(len(D))


def latih(A=None):
    """Latih 4 sesi dari data. Return (model, n_latih per sesi)."""
    if A is None:
        A, _ = data_latih()
    model = {"versi": time.strftime("%Y-%m-%d", time.gmtime()), "fitur": FIT, "rfitur": RFIT, "klip": KLIP, "sesi": {}}
    n = {}
    for H in SESI:
        F = A[A.H == H]
        model["sesi"][str(H)], n[str(H)] = latih_sesi(F)
    model["data_sampai"] = str(A.index.max().date())
    return model, n


# ---------------------------------------------------------------- penjaga dan simpan
def model_aktif():
    """Model yang sedang dipakai: versi latih ulang di STATE_DIR kalau ada dan sah, kalau tidak model riset di repo."""
    for p in (MODEL_STATE, MODEL_REPO):
        try:
            with open(p) as f:
                m = json.load(f)
            if all(str(H) in m.get("sesi", {}) for H in SESI):
                return m, p
        except Exception:
            continue
    raise RuntimeError("arah_model.json tidak ada")


def periksa(baru, lama, n_baru):
    """Return daftar alasan gagal (kosong = lolos)."""
    gagal = []
    for H in SESI:
        sb, sl = baru["sesi"][str(H)], lama["sesi"][str(H)]
        wb, wl = sb["arah"]["w"], sl["arah"]["w"]
        if not all(math.isfinite(v) for v in wb + [sb["arah"]["b"]] + sb["rentang"]["w"]):
            gagal.append(f"sesi {H}: koefisien tidak terhingga")
            continue
        balik = [FIT[i] for i in range(len(FIT)) if wl[i] * wb[i] < 0 and abs(wl[i]) > 1e-4]
        if balik:
            gagal.append(f"sesi {H}: tanda koefisien berbalik ({', '.join(balik)})")
        ub, ul = sb["uji"], sl["uji"]
        if ub["akurasi"] < ul["akurasi"] - TOL_AKURASI:
            gagal.append(f"sesi {H}: akurasi uji maju turun {ul['akurasi']:.1f}% ke {ub['akurasi']:.1f}%")
        if ub["tingkat"]["kuat"][1] < ul["tingkat"]["kuat"][1] - TOL_KUAT:
            gagal.append(f"sesi {H}: akurasi keyakinan KUAT turun {ul['tingkat']['kuat'][1]:.1f}% ke {ub['tingkat']['kuat'][1]:.1f}%")
        if n_baru[str(H)] < ul.get("n", 0):
            gagal.append(f"sesi {H}: data latih berkurang")
    return gagal


def _simpan(model, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(model, f, indent=1)
    os.replace(path + ".tmp", path)


def jalankan(kirim=True):
    """Latih ulang, periksa, simpan kalau lolos. Return teks laporan Telegram."""
    lama, sumber = model_aktif()
    A, n_live = data_latih()
    baru, n = latih(A)
    baru["sumber"] = "latih ulang otomatis"
    baru["n_live"] = n_live
    gagal = periksa(baru, lama, n)
    sl, sb = lama["sesi"]["23"]["uji"], baru["sesi"]["23"]["uji"]
    rows = ["🧠 <b>QSE v148 | MODEL ARAH BTC DILATIH ULANG</b>",
            f"Data: {n['23']} hari per sesi (sejarah 2017-2026 + {n_live} catatan live bot), sampai {baru['data_sampai']}.",
            f"Uji maju sesi 06:00 WIB: benar {sb['akurasi']:.1f}% (model lama {sl['akurasi']:.1f}%), keyakinan KUAT "
            f"{sb['tingkat']['kuat'][1]:.1f}% (lama {sl['tingkat']['kuat'][1]:.1f}%)."]
    if gagal:
        rows.append("⏸️ <b>Model lama tetap dipakai</b>, penjaga kualitas menolak model baru:")
        rows += [f"• {g}" for g in gagal[:4]]
    else:
        if sumber == MODEL_STATE:
            _simpan(lama, os.path.join(STATE_DIR, "arah_model_lama.json"))
        _simpan(baru, MODEL_STATE)
        try:
            import qse_tebak as TB
            TB._MODEL[0] = None
            TB._MEM.clear()
        except Exception:
            pass
        rows.append("✅ <b>Model baru dipakai</b> mulai sesi berikutnya. 4 sesi lolos semua penjaga (tanda koefisien sama, "
                    f"akurasi tidak turun lebih dari {TOL_AKURASI:g} poin).")
    teks = "\n".join(rows)
    print(teks.replace("<b>", "").replace("</b>", ""), flush=True)
    if kirim:
        try:
            import telegram_notify as TG
            TG.send([teks])
        except Exception as ex:
            print("[WARN] kirim latih", ex)
    return teks


if __name__ == "__main__":
    import sys
    jalankan(kirim="kirim" in sys.argv)
