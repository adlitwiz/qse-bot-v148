"""QSE OTAK ROBOT (28 Okt 2026): penilai sinyal plus analisa celah mingguan. Tanpa perintah, semua otomatis.

1. PENILAI SINYAL. Tiap sinyal jalur baru (EMA, RSI, McGinley, SnR, MSB, SMC, Ichimoku, Order Block) diberi peluang untung
   dari model pohon keputusan (otak_model.json, dilatih riset/upgrade/latih_otak.py). Fitur: jalur, arah, volume, gerak 24
   dan 48 jam, letak harga di rentang 50 candle, ATR, jam, hari, BTC 24 jam dan 7 hari, koin lawan BTC 7 hari, mutu.
   10% sinyal dengan peluang terendah disaring: tetap dicatat robot (supaya hasilnya bisa dinilai), tapi tidak dikirim.
   Uji walk-forward 2023-2026 (model hanya belajar dari tahun-tahun sebelumnya, sama dengan pemakaian live), data Binance
   96 koin, satu orang 5+2 slot: semua sinyal WR 55.9 ke 56.9%, PF 1.13 ke 1.21, total +162R ke +260R, DD sama 55R.
   Sinyal NILAI 8 ke atas WR 56.6 ke 58.0%, PF 1.21 ke 1.30, total +183R ke +250R, DD 52R ke 55R. Lolos aturan P di 2023-24
   dan 2025-26. Sinyal yang disaring rata -0.01R. Model lemah (AUC 0.52-0.56): hanya memilah, bukan meramal.
   Uji lipat dua (latih 2024-26, uji 2021-23) gagal, karena itu penjaga di bawah wajib ada.
   Batas peluang = 10% terendah dari 300 sinyal live terakhir (sebelum ada 100 sinyal: batas dari uji).
2. PENJAGA. Tiap minggu robot membandingkan hasil live sinyal yang disaring lawan yang dikirim. Kalau sudah 30 sinyal
   disaring selesai dan rata-ratanya 0.10R lebih baik dari yang dikirim, penyaring mati sendiri. Nyala lagi kalau
   kebalikannya terbukti.
3. CELAH. Tiap minggu robot membedah trade robot 120 hari terakhir per kelompok (jalur dan arah, kondisi BTC, letak harga
   di rentang, jam, volume, kekuatan koin lawan BTC). Kelompok disebut celah hanya kalau rugi di DUA paruh waktu (lama dan
   baru), minimal 10 trade per paruh, rata-rata -0.15R atau lebih buruk di tiap paruh, dan membuangnya menaikkan PF di dua
   paruh. Celah yang lolos ikut disaring 30 hari, lalu diuji ulang. Semua dilaporkan di laporan mingguan."""
import json
import math
import os
import time
import numpy as np
from config import STATE_DIR

DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_F = os.path.join(DIR, "otak_model.json")
STATE_F = os.path.join(STATE_DIR, "otak.json")
H4 = 4 * 3600 * 1000
JALUR_SKOR = ("ema_short", "ichimoku", "mcginley", "msb_hpz", "orderblock", "rsi_vol", "smc_choch", "snr_vol")
_M = {}


# ---------------- model ----------------
def _muat(path=MODEL_F):
    if path not in _M:
        with open(path) as f:
            m = json.load(f)
        m["_pohon"] = [dict(f=np.array(p["f"]), t=np.array(p["t"]), l=np.array(p["l"]), r=np.array(p["r"]),
                            leaf=np.array(p["leaf"], bool), v=np.array(p["v"]), kn=np.array(p["kiri_nan"], bool),
                            kat=np.array(p.get("kat", [0] * len(p["f"])), bool), bi=np.array(p.get("bi", [0] * len(p["f"]))),
                            bits=[list(map(int, b)) for b in p.get("bits", [])]) for p in m["pohon"]]
        _M[path] = m
    return _M[path]


def peluang_x(m, x):
    """Peluang untung dari vektor fitur x (urutan m['kolom']). Sama dengan sklearn HistGradientBoosting predict_proba."""
    z = m["awal"]
    for p in m["_pohon"]:
        i = 0
        while not p["leaf"][i]:
            v = x[p["f"][i]]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                kiri = p["kn"][i]
            elif p["kat"][i]:          # fitur kategori (jalur): kiri kalau bit kategori menyala
                b = p["bits"][p["bi"][i]]
                kv = int(v)
                kiri = kv // 32 < len(b) and bool((b[kv // 32] >> (kv % 32)) & 1)
            else:
                kiri = v <= p["t"][i]
            i = p["l"][i] if kiri else p["r"][i]
        z += p["v"][i]
    return 1.0 / (1.0 + math.exp(-z))


# ---------------- fitur live, rumus sama dengan riset/upgrade/bt_prep.py dan latih_otak.py ----------------
def fitur(df, kunci, arah, btc=None):
    """df = candle 4J yang sudah tutup, baris terakhir = candle sinyal. btc = candle 4J BTC (sudah tutup).
    Return dict kolom -> nilai, atau None kalau data kurang."""
    import qse_strat as ST
    if df is None or len(df) < 120:
        return None
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    i = len(c) - 1
    a = ST._atr(h, l, c)[i]
    px = c[i]
    if not (a > 0 and px > 0):
        return None
    d = 1 if arah == "LONG" else -1
    f = {"jalur": float(JALUR_SKOR.index(kunci))}
    f["arah"] = float(d)
    f["vp"] = float(np.mean(v[i - 100:i] <= v[i]) * 100)
    cl = lambda x: float(min(20.0, max(-20.0, x)))
    f["drop6"] = cl((h[i - 5:i + 1].max() - px) / a)
    f["pump6"] = cl((px - l[i - 5:i + 1].min()) / a)
    f["drop12"] = cl((h[i - 11:i + 1].max() - px) / a)
    f["pump12"] = cl((px - l[i - 11:i + 1].min()) / a)
    f["body"] = cl((o[i] - px) / a)
    lo50, hi50 = l[i - 50:i].min(), h[i - 50:i].max()
    f["dist_lo50"] = cl((px - lo50) / a)
    f["dist_hi50"] = cl((hi50 - px) / a)
    f["pos50"] = float(min(2.0, max(-1.0, (px - lo50) / (hi50 - lo50)))) if hi50 > lo50 else float("nan")
    f["atr_pct"] = float(a / px * 100)
    jam_masuk = int(df.index[i]) + H4          # masuk di open candle berikutnya
    f["jam"] = float((jam_masuk // 3600000) % 24)
    f["hari"] = float((jam_masuk // 86400000 + 3) % 7)
    if btc is not None and len(btc):
        bc = btc[btc.index <= df.index[i]]["close"].values.astype(float)
    else:
        bc = np.array([])
    if len(bc) >= 43:
        f["btc24"] = float((bc[-1] / bc[-7] - 1) * 100)
        f["btc168"] = float((bc[-1] / bc[-43] - 1) * 100)
    else:
        f["btc24"] = f["btc168"] = float("nan")
    f["koin168"] = float((px / c[i - 42] - 1) * 100 - f["btc168"]) if i >= 42 and not math.isnan(f["btc168"]) else float("nan")
    try:
        _, mp, mm = ST.mutu(df.iloc[max(0, i - 299):i + 1], arah)
        f["mp"], f["mm"] = float(len(mp)), float(len(mm))
    except Exception:
        f["mp"] = f["mm"] = float("nan")
    return f


# ---------------- status (otak.json) ----------------
def _baca():
    try:
        with open(STATE_F) as fh:
            return json.load(fh)
    except Exception:
        return {}


def _simpan(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_F + ".tmp", "w") as fh:
        json.dump(s, fh)
    os.replace(STATE_F + ".tmp", STATE_F)


def aktif():
    return _baca().get("aktif", True) and os.environ.get("QSE_OTAK", "1") == "1"


def batas(s=None):
    s = s if s is not None else _baca()
    r = s.get("riwayat", [])
    m = _muat()
    if len(r) >= 100:
        return float(np.quantile(r[-300:], m.get("buang", 0.10)))
    return float(m["batas"])


def _cocok_celah(f, arah, kunci, celah):
    for c in celah:
        if c.get("arah") and c["arah"] != arah:
            continue
        if c.get("jalur") and c["jalur"] != kunci:
            continue
        if c.get("fitur"):
            x = f.get(c["fitur"])
            if x is None or (isinstance(x, float) and math.isnan(x)) or not (c["dari"] <= x < c["sampai"]):
                continue
        return c
    return None


def tandai(it, kunci, df, btc=None):
    """Isi it['otak'] (peluang), it['otak_f'] (fitur ringkas), it['otak_saring'] (True = tidak dikirim) dan alasannya.
    Sinyal tetap dicatat robot walau disaring. Gagal apa pun = sinyal tetap dikirim seperti biasa."""
    try:
        if kunci not in JALUR_SKOR:
            return it
        if btc is None:
            import qse_strat as ST
            btc = ST._k4("BTCUSDT", 300)
        f = fitur(df, kunci, it["arah"], btc)
        if f is None:
            return it
        m = _muat()
        p = peluang_x(m, [f[k] for k in m["kolom"]])
        s = _baca()
        bt = batas(s)
        it["otak"] = round(p, 4)
        it["otak_batas"] = round(bt, 4)
        it["otak_f"] = {k: (None if isinstance(f[k], float) and math.isnan(f[k]) else round(f[k], 3))
                        for k in ("btc24", "btc168", "koin168", "pos50", "jam", "hari", "vp", "atr_pct")}
        s["riwayat"] = (s.get("riwayat", []) + [round(p, 4)])[-400:]
        on = s.get("aktif", True) and os.environ.get("QSE_OTAK", "1") == "1"
        cl = _cocok_celah(f, it["arah"], kunci, [c for c in s.get("celah", []) if c.get("sampai_t", 0) > time.time()])
        if on and p < bt:
            it["otak_saring"] = True
            it["otak_why"] = f"peluang {p * 100:.0f}% di bawah batas {bt * 100:.0f}%"
        elif on and cl:
            it["otak_saring"] = True
            it["otak_why"] = "celah live: " + cl["nama"]
        _simpan(s)
        if it.get("otak_saring"):
            print(f"[OTAK] {kunci} {it['sym']} {it['arah']} disaring: {it['otak_why']}")
    except Exception as ex:
        print("[WARN] otak", it.get("sym"), ex)
    return it


def tersaring(it):
    return bool(it.get("otak_saring"))


# ---------------- evaluasi mingguan: penjaga dan celah ----------------
def _ledger():
    """Semua trade robot yang sudah selesai dari jalur yang dinilai, dengan R, waktu, arah, jalur, dan data otak kalau ada."""
    out = []
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            if k in JALUR_SKOR:
                out += [dict(c, jalur=k) for c in ST.lihat(k).get("closed", [])]
    except Exception as ex:
        print("[WARN] otak ledger strat", ex)
    for mod, k in (("qse_ichimoku", "ichimoku"), ("qse_ob", "orderblock")):
        try:
            M = __import__(mod)
            out += [dict(c, jalur=k) for c in M.lihat().get("closed", [])]
        except Exception as ex:
            print("[WARN] otak ledger", k, ex)
    return [c for c in out if c.get("R") is not None and c.get("t")]


def _pf(r):
    r = np.asarray(r, float)
    g, b = r[r > 0].sum(), -r[r < 0].sum()
    return g / b if b > 0 else (9.99 if g > 0 else 0.0)


EMBER = (("btc24", "BTC 24 jam", (-99, -3, -1, 1, 3, 99), "%"), ("pos50", "letak di rentang 50 candle", (-9, 0.114, 0.5, 0.886, 9), ""),
         ("koin168", "koin lawan BTC 7 hari", (-999, -10, 0, 10, 999), "%"), ("vp", "volume persentil", (0, 90, 101), ""),
         ("jam", "jam masuk UTC", (0, 4, 8, 12, 16, 20, 24), ""), ("btc168", "BTC 7 hari", (-99, -5, 0, 5, 99), "%"))


def _kelompok(tr):
    """Daftar kelompok calon celah: (nama, syarat dict, mask)."""
    out = []
    arah = np.array([c["arah"] for c in tr])
    jl = np.array([c["jalur"] for c in tr])
    for j in sorted(set(jl)):
        for a in ("LONG", "SHORT"):
            out.append((f"{j} {a}", dict(jalur=j, arah=a), (jl == j) & (arah == a)))
    for kol, nm, b, sat in EMBER:
        x = np.array([((c.get("otak_f") or {}).get(kol)) if (c.get("otak_f") or {}).get(kol) is not None else np.nan for c in tr], float)
        for a in ("LONG", "SHORT"):
            for lo, hi in zip(b[:-1], b[1:]):
                if lo <= -9:
                    rng = f"di bawah {hi:g}{sat}"
                elif hi >= 99 or (kol == "pos50" and hi >= 9):
                    rng = f"{lo:g}{sat} ke atas"
                else:
                    rng = f"{lo:g} sampai {hi:g}{sat}"
                out.append((f"{a} saat {nm} {rng}", dict(arah=a, fitur=kol, dari=float(lo), sampai=float(hi)),
                            (arah == a) & (x >= lo) & (x < hi)))
    return out


def evaluasi(simpan=True, now=None):
    """Penjaga dan pencari celah. Return teks laporan (HTML Telegram)."""
    now = now or time.time()
    s = _baca()
    tr = sorted([c for c in _ledger() if now - float(c["t"]) <= 120 * 86400], key=lambda c: float(c["t"]))
    rows = ["🧠 <b>OTAK ROBOT</b>"]
    # 1. penjaga penyaring
    dinilai = [c for c in tr if c.get("otak") is not None]
    sar = [float(c["R"]) for c in dinilai if c.get("otak_saring") and not str(c.get("otak_why", "")).startswith("celah")]
    kir = [float(c["R"]) for c in dinilai if not c.get("otak_saring")]
    on = s.get("aktif", True)
    if len(sar) >= 30 and kir:
        ms, mk = float(np.mean(sar)), float(np.mean(kir))
        if on and ms > mk + 0.10:
            on = False
            rows.append(f"⛔ Penyaring dimatikan otomatis: sinyal yang disaring rata {ms:+.2f}R, lebih baik dari yang dikirim {mk:+.2f}R.")
        elif not on and ms < mk - 0.05:
            on = True
            rows.append(f"✅ Penyaring dinyalakan lagi: sinyal yang disaring rata {ms:+.2f}R, lebih jelek dari yang dikirim {mk:+.2f}R.")
    s["aktif"] = on
    rows.append(f"Penyaring peluang: <b>{'NYALA' if on else 'MATI'}</b>, batas peluang {batas(s) * 100:.0f}%. "
                f"Sinyal dinilai {len(dinilai)} trade selesai (120 hari).")
    if sar or kir:
        rows.append(f"Hasil live: dikirim {len(kir)} trade rata {np.mean(kir) if kir else 0:+.2f}R WR {np.mean(np.array(kir) > 0) * 100 if kir else 0:.0f}%"
                    f", disaring {len(sar)} trade rata {np.mean(sar) if sar else 0:+.2f}R WR {np.mean(np.array(sar) > 0) * 100 if sar else 0:.0f}%"
                    + ("" if len(sar) >= 30 else ". Penjaga mulai menilai setelah 30 trade disaring selesai."))
    # 2. celah: dua paruh waktu
    celah_lama = [c for c in s.get("celah", []) if c.get("sampai_t", 0) > now]
    baru = []
    if len(tr) >= 40:
        R = np.array([float(c["R"]) for c in tr])
        tengah = len(tr) // 2
        pa, pb = np.arange(len(tr)) < tengah, np.arange(len(tr)) >= tengah
        for nm, syarat, mk in _kelompok(tr):
            ok = True
            det = []
            for per in (pa, pb):
                x = R[mk & per]
                sisa = R[~mk & per]
                if len(x) < 10 or x.mean() > -0.15 or _pf(sisa) < _pf(R[per]) + 0.02:
                    ok = False
                    break
                det.append(f"{len(x)} trade rata {x.mean():+.2f}R, PF tanpa kelompok ini {_pf(sisa):.2f} lawan {_pf(R[per]):.2f}")
            if ok:
                baru.append(dict(syarat, nama=nm, sampai_t=now + 30 * 86400, bukti=" | ".join(det)))
    nama_lama = {c["nama"] for c in celah_lama}
    for c in baru:
        if c["nama"] not in nama_lama:
            celah_lama.append(c)
        else:
            for x in celah_lama:
                if x["nama"] == c["nama"]:
                    x.update(c)
    s["celah"] = celah_lama
    if len(tr) < 40:
        rows.append(f"Celah: trade robot 120 hari baru {len(tr)}, butuh 40 untuk dibedah.")
    elif not celah_lama:
        rows.append(f"Celah: {len(tr)} trade dibedah per kelompok, tidak ada yang rugi konsisten di dua paruh waktu. Aturan tidak diubah.")
    else:
        rows.append(f"Celah lolos uji dua paruh waktu ({len(tr)} trade robot 120 hari), sinyal seperti ini disaring 30 hari:")
        for c in celah_lama[:5]:
            rows.append(f"• {c['nama']}: {c.get('bukti', '')}")
    if simpan:
        _simpan(s)
    return "\n".join(rows)
