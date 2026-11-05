"""QSE v150 - 🪰 Lalat Bionik. Satu ekor lalat digital yang hidup di dalam robot dan makan dari trading.

Arsitektur meniru otak Drosophila dari codex (data/brain_regions.py, neurotransmitters.py, connections.py), tanpa data
koneksi mentah 2GB: sinapsis dibangkitkan sendiri secara tetap (seed dari nomor wilayah codex) lalu dilatih oleh hasil trade.
  OL  Optic Lobe (LA, ME, LO, LOP)        : mata. Membaca candle 4J, jarak ke support/resistance, RSI, volume, arah BTC dan tren,
                                            lalu mengubahnya jadi token pola (koin, jam, indikator).
  MB  Mushroom Body (CA, PED, VL, ML)     : memori belajar. Tiap token menyalakan beberapa Kenyon cell (kode jarang). Bobot
                                            Kenyon cell ke neuron keluaran MB naik saat dopamin (TP) dan turun saat GABA (SL).
  CX  Central Complex (PB, FB, EB, NO)    : keputusan. Menimbang nilai MB, ambang dari serotonin dan GABA, dan dorongan lapar,
                                            lalu memilih koin, arah LONG/SHORT, dan angka order.
Neuromodulator (nama codex): DA dopamin, SER serotonin (5-HT), GABA, ACH asetilkolin, OCT oktopamin (rangsang lapar).
  Lapar 0-100%: naik 6.7% per jam tanpa makan (12 jam = 80%, 15 jam = 100%). Makan = robot atau kamu membuka posisi, dan TP kena.
  DA naik saat TP kena (lalat atau trade kamu), GABA naik saat SL kena. Bobot sinapsis memakai bekal 2023-2024 (LR 0.0 terpilih
  dari data latih). belajar() siap menguatkan atau melemahkan pola kalau LR dinaikkan.
  5-HT naik saat menang beruntun dan pasar tenang: ambang lebih tinggi, lalat memilih setup paling akurat.
  ACh = perhatian, menentukan seberapa cepat belajar. OCT = rangsang lapar, menurunkan ambang saat lapar.
Trade lalat: order LIMIT di support/resistance 4J (qse_rencana), SL di luar level, Fix Profit bertahap: TP1 0.5 ATR 4J tutup 50%
lalu SL ke entry, TP2 0.8 ATR. Order berlaku 24 jam, posisi terisi paling lama 24 jam.
Lapar bertingkat (jam sejak posisi terakhir terisi): 1-8 jam kenyang, 9-14 jam ambang turun 15% dan 50 koin terdekat level,
15 jam ke atas wajib makan dari 183 koin atau sinyal Sektor/jalur utama. Pagar modal: lot 0.25x, maks 2 posisi, maks 3 trade baru per hari. Lalat tidak pernah berhenti makan: saat 3 rugi beruntun
atau rem 7 hari aktif, lalat masuk Mode Berburu Ketat (lot 0.1x, ambang naik, hanya koin rasio menang tertinggi) sampai 1 TP.
Refleks optik 1-5 menit (refleks()) memantau order dan posisi lalat tiap menit. Semua trade lalat dicatat di ledger jalur 'lalat'.
State: lalat.json (hormon, posisi, riwayat) dan lalat_memori.json (bobot sinapsis), di STATE_DIR, berkembang tiap jam."""
import functools
import hashlib
import html
import json
import math
import os
import threading
import time
import numpy as np
from config import STATE_DIR

F_STATE = os.path.join(STATE_DIR, "lalat.json")
F_MEMORI = os.path.join(STATE_DIR, "lalat_memori.json")
F_BAWAAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lalat_bawaan.json")
_KUNCI = threading.RLock()
JAM = 3600.0

# wilayah otak dari codex brain_regions.py: singkatan -> nomor wilayah (dipakai sebagai seed generator sinapsis)
WILAYAH = {
    "OL": {"LA_L": 76, "ME_L": 43, "LO_L": 51, "LOP_L": 6},
    "MB": {"MB_CA_L": 66, "MB_PED_L": 48, "MB_VL_L": 4, "MB_ML_L": 10},
    "CX": {"PB": 68, "FB": 65, "EB": 35, "NO": 58},
}
NT = {"DA": "dopamine", "SER": "serotonin", "GABA": "gabaergic", "GLUT": "glutamate", "ACH": "acetylcholine", "OCT": "octopamine"}
N_KC = 2000              # Kenyon cell
KC_PER_TOKEN = 8         # tiap token menyalakan 8 Kenyon cell (kode jarang, sekitar 3% sel aktif per pola)
LOT = 0.25
MAKS_BUKA, MAKS_HARIAN = 2, 3
MAKS_HARIAN_PILIH = 2       # lalat pemilih QC 46: maks 2 trade baru per hari
TP1_ATR, TP2_ATR, SL_ATR = 0.5, 0.8, 1.0
BERLAKU_JAM, TAHAN_JAM = 24, 24
LAPAR_PER_JAM = 80.0 / 12.0
MEDALI_BONUS = 0.10      # tambahan skor koin medali (PSG, ACM, BAR, CITY, NEXO, PORTO, LAZIO)
PAKSA_MIN = -0.15
LOT_KETAT = 0.1          # Mode Berburu Ketat
KETAT_PLUS = 0.10        # ambang naik saat mode ketat
LR = 0.005               # laju belajar bobot sinapsis dari trade lalat. Pilihan pemilik (5 Nov). Di latih 2024: lr 0.0 R akun +12.32,
#                          0.005 +12.21 (selisih 0.11R). Sinapsis tetap hidup dan bergeser dari TP (dopamin) dan SL (GABA).
LR_USER = 0.005          # trade kamu (Rifqi, Adli) yang kena TP atau SL
LR_LEDGER = 0.0          # hasil kertas semua jalur robot: setup berbeda dari lalat, tidak dipakai untuk bobot


def _seed():
    s = 0
    for g in WILAYAH.values():
        for v in g.values():
            s = s * 131 + v
    return s % (2 ** 31)


SEED = _seed()


@functools.lru_cache(maxsize=50000)
def _kc_token(tok):
    """Generator sinapsis: token -> indeks Kenyon cell yang dinyalakan. Tetap (deterministik), tanpa file koneksi besar."""
    h = hashlib.blake2b(f"{SEED}|{tok}".encode(), digest_size=32).digest()
    out, i = [], 0
    while len(out) < KC_PER_TOKEN:
        x = int.from_bytes(h[(2 * i) % 32:(2 * i) % 32 + 2], "big") % N_KC
        if x not in out:
            out.append(x)
        i += 1
        if i > 64:
            h = hashlib.blake2b(h, digest_size=32).digest(); i = 0
    return tuple(out)


# ---------- simpan dan muat ----------
def _baca(path, bawaan):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return bawaan()


def _tulis(path, d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def _state_baru():
    now = time.time()
    return dict(lahir=now, t=now, lapar=40.0, DA=30.0, SER=50.0, GABA=10.0, ACH=40.0, OCT=40.0, makan_t=now,
                open={}, riwayat=[], n_tp=0, n_sl=0, n_be=0, ketat=False, ketat_reset=0, rem7_ep=False, cek_user=now * 1000, cek_ledger=now, harian={}, kejadian=[])


def _memori_baru():
    pri = {}
    try:
        with open(F_BAWAAN) as f:
            pri = json.load(f).get("token", {})
    except Exception:
        pass
    return dict(kc=[1.0] * N_KC, token={k: float(v) for k, v in pri.items()}, n={}, bawaan=bool(pri))


def state():
    return _baca(F_STATE, _state_baru)


def memori():
    m = _baca(F_MEMORI, _memori_baru)
    if len(m.get("kc", [])) != N_KC:
        m["kc"] = [1.0] * N_KC
    return m


# ---------- Optic Lobe: candle -> token ----------
def _jam_wib(ts):
    return int(((ts + 7 * 3600) % 86400) // 3600)


def token_rencana(r, btc_naik=None, ts=None):
    L = r["arah"] == "LONG"
    ts = ts or time.time()
    tk = [f"koin:{r['sym']}", f"arah:{r['arah']}", f"jam:{_jam_wib(ts) // 4 * 4:02d}", "jalur:sniper",
          f"spesialis:{r['sym']}:{r['arah']}"]
    d = r.get("dist", 9)
    tk.append("jarak:<0.5ATR" if d < 0.5 else "jarak:0.5-1ATR" if d < 1 else "jarak:1-2ATR")
    rsi = r.get("rsi")
    if rsi is not None:
        tk.append("rsi:<30" if rsi < 30 else "rsi:30-45" if rsi < 45 else "rsi:45-55" if rsi < 55 else "rsi:55-70" if rsi < 70 else "rsi:>70")
    if r.get("vr") is not None:
        tk.append("vol:sepi" if r["vr"] < 0.8 else "vol:normal" if r["vr"] < 1.5 else "vol:ramai")
    if r.get("atrp") is not None:
        tk.append("atr:kecil" if r["atrp"] < 1.5 else "atr:sedang" if r["atrp"] < 3 else "atr:besar")
    if r.get("slope") is not None:
        tk.append("ema50:searah" if (r["slope"] > 0) == L else "ema50:lawan")
    if "tren" in r:
        tk.append("ema200:searah" if r["tren"] else "ema200:lawan")
    if btc_naik is not None:
        tk.append("btc:searah" if btc_naik == L else "btc:lawan")
    if r.get("body") is not None:
        b = r["body"] * (1 if L else -1)
        tk.append("candle:searah" if b > 0.3 else "candle:lawan" if b < -0.3 else "candle:doji")
    return tk


def token_trade(sym, arah, ts, jalur):
    return [f"koin:{sym}", f"arah:{arah}", f"jam:{_jam_wib(ts) // 4 * 4:02d}", f"jalur:{jalur}", f"spesialis:{sym}:{arah}"]


# ---------- Mushroom Body asli (FlyWire FAFB v783) ----------
MB_ETA = 0.006           # laju belajar DAN di otak asli (tiap TP atau SL lalat dan trade kamu)
MB_LOT = True            # lot dari valensi otak asli: > 0 lot 0.5x, < 0 lot 0.1x. Latih 2024 +12.21R -> +4.15R, uji 2025-2026
#                          +25.51R -> +33.32R (QC 52). Dipasang atas permintaan pemilik. Matikan: MB_LOT = False
MB_SUARA = 0.0           # bobot valensi otak asli di keputusan. Dipilih di latih 2024: 0 (k 2, 5, 10, 20 menurunkan R akun). QC 48
_OTAK = [None]


def otak():
    """Otak Mushroom Body asli dari data FlyWire pemilik (qse_mb). Bobot hidup di STATE_DIR/lalat_mb.npy,
    lahir dengan pengalaman masa kecil 2023-2024 (mb_bawaan.npy)."""
    if _OTAK[0] is None:
        try:
            import qse_mb as MB
            o = MB.Otak()
            if os.path.exists(MB.F_BOBOT):
                o.muat()
            else:
                o.muat(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mb_bawaan.npy"))
            _OTAK[0] = o
        except Exception as ex:
            print("[WARN] otak MB", ex)
            _OTAK[0] = False
    return _OTAK[0] or None


def _tok_mb(tokens):
    return tuple(t for t in tokens if not t.startswith("jam:"))


def valensi_mb(tokens):
    o = otak()
    return o.valensi(_tok_mb(tokens)) if o else 0.0


def belajar_mb(tokens, R):
    o = otak()
    if o:
        o.belajar(_tok_mb(tokens), R, MB_ETA)
        try:
            o.simpan()
        except Exception as ex:
            print("[WARN] simpan otak MB", ex)


# ---------- Mushroom Body ----------
def nilai(tokens, m=None):
    """Nilai pola: rata bobot Kenyon cell aktif minus 1, ditambah rata bobot sinapsis token. Positif = disukai."""
    m = m or memori()
    kc = m["kc"]
    aktif = sorted({i for t in tokens for i in _kc_token(t)})
    v_mb = sum(kc[i] for i in aktif) / max(len(aktif), 1) - 1.0
    tw = [m["token"].get(t, 0.0) for t in tokens if not t.startswith("spesialis:")]
    sp = sum(m["token"].get(t, 0.0) for t in tokens if t.startswith("spesialis:"))     # bekal lahir + belajar per koin+arah, bobot penuh
    v = v_mb + (sum(tw) / max(len(tw), 1)) + sp
    if MB_SUARA:
        v += MB_SUARA * valensi_mb(tokens)
    return v, aktif


def belajar(tokens, R, lr, st, m):
    """Plastisitas MB dengan galat prediksi dopamin (aturan Rescorla-Wagner / LMS): nilai pola = tebakan hasil (3 x R).
    Hasil lebih baik dari tebakan = lonjakan dopamin, bobot naik. Lebih buruk = GABA, bobot turun (sedikit lebih kuat, kapok).
    Bobot menuju rata hasil nyata pola itu, tidak meledak dan tidak jatuh terus karena satu dua SL."""
    ach = 0.5 + st["ACH"] / 100
    target = max(-1.5, min(1.5, 3.0 * R))
    pred, aktif = nilai(tokens, m)
    err = target - pred
    g = lr * ach * err * (1.15 if err < 0 else 1.0)
    lain = [t for t in tokens if not t.startswith("spesialis:")]
    for t in tokens:
        bag = g if t.startswith("spesialis:") else g / max(len(lain), 1)
        m["token"][t] = max(-1.5, min(1.5, m["token"].get(t, 0.0) + bag))
        m["n"][t] = m["n"].get(t, 0) + 1
    for i in aktif:
        m["kc"][i] = max(0.2, min(3.0, m["kc"][i] + 0.3 * g))
    return err


def _suntik(st, R, sumber):
    if R > 0.05:
        st["DA"] = min(100.0, st["DA"] + 20 + 15 * min(R, 2))
        st["lapar"] = max(0.0, st["lapar"] - 40)
        st["makan_t"] = time.time()
        st["kejadian"].append([time.time(), f"💉 Dopamin naik: {sumber} untung {R:+.2f}R"])
    elif R < -0.05:
        st["GABA"] = min(100.0, st["GABA"] + 25 + 10 * min(-R, 1.5))
        st["lapar"] = max(0.0, st["lapar"] - 10)
        st["kejadian"].append([time.time(), f"🩹 GABA naik: {sumber} rugi {R:+.2f}R, pola ini dilemahkan"])
    st["kejadian"] = st["kejadian"][-30:]


# ---------- tubuh: hormon dan lapar tiap jalan ----------
def _hidup(st, now=None):
    now = now or time.time()
    dt = max(0.0, min(48.0, (now - st.get("t", now)) / JAM))
    st["t"] = now
    st["lapar"] = lapar_dari_jam((now - st.get("makan_t", now)) / JAM)
    st["DA"] = 20 + (st["DA"] - 20) * 0.5 ** (dt / 12)
    st["GABA"] = 10 + (st["GABA"] - 10) * 0.5 ** (dt / 24)
    r10 = [x["R"] for x in st["riwayat"][-10:] if x.get("R") is not None]
    wr = (sum(1 for x in r10 if x > 0) / len(r10)) if r10 else 0.5
    tenang = 0.0
    try:
        import qse_strat as ST
        tenang = 10.0 if getattr(ST, "btc_atr_pct", lambda: 2.0)() < 1.2 else 0.0
    except Exception:
        pass
    target = max(0.0, min(100.0, 50 + 60 * (wr - 0.5) + tenang + (10 if sum(r10[-3:]) > 0 else 0)))
    st["SER"] = st["SER"] + (target - st["SER"]) * min(1.0, 0.2 * dt)
    st["OCT"] = st["lapar"]
    st["ACH"] = max(10.0, min(100.0, 25 + 0.45 * st["lapar"] + 0.2 * st["GABA"]))


def _makan_posisi_user(st, m):
    """Robot atau kamu membuka posisi = lalat ikut makan. TP atau SL trade kamu = dopamin atau GABA untuk pola itu."""
    import qse_saya as SY
    ada = False
    batas = st.get("cek_user", 0)
    baru_batas = batas
    for u in SY.daftar_pengguna():
        try:
            d = SY._baca(SY._path_uid(u))
        except Exception:
            continue
        for it in d.get("open", {}).values():
            t0 = it.get("fill_ts") or it.get("created_ts") or 0
            if t0 > batas:
                st["lapar"] = max(0.0, st["lapar"] - 30); st["makan_t"] = time.time()
                baru_batas = max(baru_batas, t0)
        for c in d.get("closed", []):
            tc = c.get("closed_ts") or 0
            if tc <= batas or c.get("result_r") is None:
                continue
            R = float(c["result_r"])
            tok = token_trade(c.get("sym", "?"), c.get("arah", "?"), (c.get("fill_ts") or c.get("created_ts") or tc) / 1000,
                              c.get("jalur") or c.get("sumber") or "manual")
            belajar(tok, R, LR_USER, st, m)
            belajar_mb(tok, R)
            _suntik(st, R, f"trade {SY.nama_pengguna(u)} {c.get('sym', '')}")
            baru_batas = max(baru_batas, tc); ada = True
    st["cek_user"] = baru_batas
    return ada


def _belajar_ledger(st, m):
    """Hasil semua jalur robot (ledger kertas) = makanan kecil tiap jam supaya sinapsis terus berkembang."""
    try:
        import qse_catat as CT
        cl = CT._baca()["closed"]
    except Exception:
        return False
    batas = st.get("cek_ledger", 0); ada = False; maks = batas
    for c in cl:
        s = c.get("selesai") or 0
        if s <= batas or c.get("status") != "SELESAI" or c.get("R") is None or c.get("jalur") == "lalat":
            continue
        belajar(token_trade(c.get("sym", "?"), c.get("arah", "?"), c.get("t") or s, c.get("jalur", "?")), float(c["R"]), LR_LEDGER, st, m)
        maks = max(maks, s); ada = True
    st["cek_ledger"] = maks
    return ada


# ---------- kelola posisi lalat ----------
def _k1j(sym, sejak_ms):
    import bybit_fetch as B
    df = B._raw(sym, "60", 80)
    ms = int(time.time() * 1000)
    df = df[(df.index >= sejak_ms - 3600000) & (df.index + 3600000 <= ms)]
    return df


def _catat_ledger(it, R):
    try:
        import qse_catat as CT

        def f(d):
            d["closed"].append(dict(jalur="lalat", sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl"], tp1=it["tp1"],
                                    tp2=it["tp2"], t=it["t"], status="SELESAI", R=round(R, 2), isi=it.get("isi_t", it["t"]),
                                    selesai=time.time(), ket=f"lalat bionik lot {it.get('lot', LOT):g}x"))
        CT._ubah(f)
    except Exception as ex:
        print("[WARN] lalat ledger", ex)


def _tutup(st, m, key, it, R, why, out):
    """Posisi atau order lalat selesai: catat, belajar, suntik hormon, cek mode ketat."""
    st["open"].pop(key, None)
    if R is None or why.startswith(("order tidak terisi", "refleks batal")):
        st["riwayat"].append(dict(it, R=None, why=why, selesai=time.time()))
        out.append(f"🪰 {it['sym']} {it['arah']}: {why}.")
        return
    st["riwayat"].append(dict(it, R=round(R, 3), why=why, selesai=time.time()))
    st["riwayat"] = st["riwayat"][-300:]
    belajar(it["tokens"], R, LR, st, m)
    belajar_mb(it["tokens"], R)
    _suntik(st, R, f"lalat {it['sym']}")
    if R > 0.05:
        st["n_tp"] += 1
        if lepas_ketat(st):
            out.append("🎉 🪰 TP kena saat Mode Berburu Ketat. Dopamin masuk, lot lalat kembali 0.25x.")
    elif R < -0.05:
        st["n_sl"] += 1
    else:
        st["n_be"] += 1
    _catat_ledger(it, R)
    ikon = "✅" if R > 0.05 else "🛑" if R < -0.05 else "➖"
    lt = it.get("lot", LOT)
    out.append(f"{ikon} 🪰 <b>{it['sym']} {it['arah']}</b> selesai: {why}, hasil {R:+.2f}R (lot {lt:g}x, {R * lt:+.2f}R akun).")
    if cek_ketat(st):
        out.append(f"🛡️ 🪰 Masuk Mode Berburu Ketat ({st['ketat_sebab']}). Lalat tetap makan tiap hari: lot 0.1x, "
                   "ambang naik, hanya koin rasio menang tertinggi. Kembali 0.25x setelah 1 TP.")


def _kelola(st, m):
    """Jalan ulang tiap posisi dari candle 1J: terisi, TP1 (50% + SL ke entry), TP2, SL, atau habis waktu. Return pesan."""
    import qse_saya as SY
    out = []
    for key, it in list(st["open"].items()):
        L = it["arah"] == "LONG"
        try:
            df = _k1j(it["sym"], int(it["t"] * 1000))
        except Exception as ex:
            print("[WARN] lalat candle", it["sym"], ex)
            continue
        h, l, c, idx = df["high"].values, df["low"].values, df["close"].values, df.index.values
        risk = abs(it["entry"] - it["sl"]); fee = 0.0011 * it["entry"] / risk if risk else 0
        r1 = abs(it["tp1"] - it["entry"]) / risk if risk else 0
        r2 = abs(it["tp2"] - it["entry"]) / risk if risk else 0
        isi, tp1k, R, why = it.get("isi_t"), it.get("tp1k", False), None, ""
        for j in range(len(c)):
            tj = idx[j] / 1000
            if tj < it["t"] - 3600:
                continue
            if isi is None:
                if tj > it["t"] + BERLAKU_JAM * JAM:
                    R, why = 0.0, "order tidak terisi 24 jam, batal"; break
                if it.get("refleks"):
                    continue          # order refleks hanya diisi oleh refleks() dari candle 5 menit
                if (L and l[j] <= it["entry"]) or ((not L) and h[j] >= it["entry"]):
                    isi = tj
                    if (L and l[j] <= it["sl"]) or ((not L) and h[j] >= it["sl"]):
                        R, why = -1.0 - fee, "SL kena di candle terisi"; break
                continue
            if tj <= isi:
                continue
            stop = it["entry"] if tp1k else it["sl"]
            if (L and l[j] <= stop) or ((not L) and h[j] >= stop):
                R, why = ((0.5 * r1, "TP1 sudah dikunci, sisa kena SL di entry") if tp1k else (-1.0, "SL kena"))
                R -= fee; break
            if not tp1k and ((L and h[j] >= it["tp1"]) or ((not L) and l[j] <= it["tp1"])):
                tp1k = True
                out.append(f"🪰💰 <b>{it['sym']} {it['arah']}</b>: TP1 Fix Profit kena di {SY.fp(it['tp1'], it.get('tick'))}. "
                           "Tutup 50%, pindah SL ke entry. Lalat dapat dopamin.")
                st["DA"] = min(100.0, st["DA"] + 15)
            if tp1k and ((L and h[j] >= it["tp2"]) or ((not L) and l[j] <= it["tp2"])):
                R, why = 0.5 * r1 + 0.5 * r2 - fee, "TP2 Fix Profit kena"; break
            if tj >= isi + it.get("tahan_jam", TAHAN_JAM) * JAM:
                rr = (c[j] - it["entry"]) / risk * (1 if L else -1)
                R, why = (0.5 * r1 + 0.5 * rr if tp1k else rr) - fee, "24 jam, tutup market"; break
        if R is None:
            if isi and not it.get("isi_t"):
                st["makan_t"] = max(st.get("makan_t", 0), isi)          # posisi terisi = lalat makan
                out.append(f"🪰 <b>{it['sym']} {it['arah']}</b>: order LIMIT terisi di {SY.fp(it['entry'], it.get('tick'))}. SL dan TP siap.")
            it["isi_t"], it["tp1k"] = isi, tp1k
            continue
        _tutup(st, m, key, it, R, why, out)
    return out


# ---------- Central Complex: memilih ----------
def cek_ketat(st, rem7=None):
    """Mode Berburu Ketat. Lalat tidak pernah berhenti makan. Saat 3 rugi beruntun atau rem 7 hari robot menyala, lalat masuk
    mode ketat: lot 0.1x, ambang naik, hanya koin dengan rasio menang tertinggi (nilai spesialis >= 0.30).
    Keluar dari mode ketat setelah 1 kali TP (dopamin). Return alasan kalau baru masuk mode ketat, selain itu ''."""
    baru = ""
    cl = [x for x in st["riwayat"] if x.get("R") is not None and x.get("selesai", 0) > st.get("ketat_reset", 0)][-3:]
    if not st.get("ketat") and len(cl) == 3 and all(x["R"] <= 0 for x in cl):
        st["ketat"], baru = True, "3 rugi beruntun"
    if rem7 is None:
        try:
            import qse_catat as CT
            rem7 = bool(CT.rem7()["aktif"])
        except Exception:
            rem7 = False
    if rem7 and not st.get("rem7_ep"):
        st["rem7_ep"] = True
        if not st.get("ketat"):
            st["ketat"], baru = True, "rem 7 hari robot aktif"
    elif not rem7:
        st["rem7_ep"] = False
    if baru:
        st["ketat_sebab"] = baru
        st["kejadian"].append([time.time(), f"🛡️ Mode Berburu Ketat: {baru}. Lot 0.1x, hanya koin rasio menang tertinggi"])
    return baru


def lepas_ketat(st, now=None):
    """Dipanggil saat TP kena: dopamin masuk, lot kembali 0.25x."""
    if st.get("ketat"):
        st["ketat"] = False
        st["ketat_reset"] = now or time.time()
        st["kejadian"].append([now or time.time(), "🎉 TP kena saat mode ketat. Dopamin masuk, lot kembali 0.25x"])
        return True
    return False


def lot_sekarang(st):
    return LOT_KETAT if st.get("ketat") else LOT


def _sp(tokens, m):
    return sum(m["token"].get(t, 0.0) for t in tokens if t.startswith("spesialis:"))


_DAFTAR = {}


def daftar_spesialis():
    """Koin spesialis dari lalat_bawaan.json: sym -> dict(arah, tier, wr_latih, ex_latih, wr_uji, ex_uji).
    Tier 1 = PSG, ACM, BAR (uji +0.117R). Tier 2 = cadangan, lolos aturan latih WR >= 70% (uji gabungan impas)."""
    if not _DAFTAR:
        try:
            with open(F_BAWAAN) as f:
                _DAFTAR.update(json.load(f).get("spesialis", {}))
        except Exception:
            pass
    return _DAFTAR


_KETAT = {}


def _boleh_ketat(p):
    """Mode ketat QC 46: 11 koin-sisi lolos aturan latih (ketat_daftar di lalat_bawaan.json)."""
    if not _KETAT:
        try:
            with open(F_BAWAAN) as f:
                _KETAT.update(json.load(f).get("ketat_daftar", {}))
        except Exception:
            pass
    if _KETAT:
        return _KETAT.get(p["sym"]) == p["arah"]
    d = daftar_spesialis().get(p["sym"])
    return bool(d) and d["arah"] == p["arah"]


def lapar_dari_jam(jam):
    """Lapar dari jam sejak makan terakhir (posisi terisi). 1-8 jam kenyang (0-60%), 9-14 jam lapar (70-85%),
    15 jam ke atas sangat lapar (90-100%)."""
    if jam < 9:
        return max(0.0, jam / 8 * 60)
    if jam < 15:
        return 70 + (jam - 9) * 3
    return min(100.0, 90 + (jam - 15) * 2)


def tingkat_lapar(jam):
    return 1 if jam < 9 else 2 if jam < 15 else 3


def ambang(st):
    """Ambang dasar pilih CX. Serotonin dan GABA menaikkan, mode ketat menambah KETAT_PLUS. Lapar mengatur lewat tingkat (pilih_lapar)."""
    return 0.25 + 0.004 * (st["SER"] - 50) + 0.004 * max(0.0, st["GABA"] - 30) + (KETAT_PLUS if st.get("ketat") else 0.0)


def medali(p):
    d = daftar_spesialis().get(p["sym"])
    return bool(d) and d["arah"] == p["arah"]


ALT_URUT = {"jalur": 0, "gzh": 1, "sektor": 2}          # urut rata R latih 2023-2024: jalur +0.119, GZH +0.072, Sektor -0.045
MODE_LAPAR = False       # False = lalat pemilih (bawaan): makan hanya koin medali dari rencana 07:00 WIB: hanya tingkat 1 (koin medali, rencana 07:00 WIB), tanpa paksaan lapar
ALT_DULU = True          # saat lapar, sinyal jalur lain (Sektor, jalur utama) dimakan sebelum rencana S/R koin umum
TINGKAT1_JAM_WIB = 7     # tingkat 1 (kenyang) hanya memilih rencana candle 4J yang tutup 07:00 WIB, sama dengan riset harian. None = tiap jam


def pilih_lama(calon, st, m, slot, buka, paksa=False):
    """Keputusan lalat pemilih QC 46 (uji 2025-2026 +25.5R akun): ambang dasar dikurangi lapar di atas 60%, tanpa bonus medali.
    Kalau tidak ada yang enak dan lapar >= 80% (GABA < 70 atau mode ketat), makan satu pola terbaik yang tidak dibenci."""
    if slot <= 0:
        return [], False
    ketat = st.get("ketat")
    th = ambang(st) - 0.006 * max(0.0, st["lapar"] - 60)
    ok = lambda z: z[1]["sym"] not in buka and not z[1].get("jauh") and (not ketat or _boleh_ketat(z[1]))
    pil = [z for z in calon if z[0] > th and ok(z)][:slot]
    if pil:
        return pil, False
    if (paksa or st["lapar"] >= 80) and (ketat or st["GABA"] < 70):
        z = next((z for z in calon if ok(z) and z[0] > PAKSA_MIN), None)
        if z:
            return [z], True
    return [], False


def pilih_lapar(calon, alt, st, m, slot, buka, jam, now=None):
    """Keputusan CX bertingkat lapar, dipakai live dan replay (paritas).
    calon = [(nilai, rencana, token)], rencana punya dist (ATR) dan distp (% dari level). alt = makanan jalur lain
    [dict(sym, arah, sumber, ...)] yang sedang aktif. Return list (jenis, isi), jenis 'rencana' atau 'alt', dan tingkat.
    Tingkat 1 (jam 1-8): ambang penuh, koin medali dapat bonus. Tingkat 2 (jam 9-14): ambang turun 15%, 50 koin terdekat level,
    kalau kosong makan sinyal jalur lain. Tingkat 3 (jam 15+): wajib makan. Terbaik di jarak < 0.5% dari level, lalu sinyal
    jalur lain, lalu rencana terdekat dari semua koin."""
    if not MODE_LAPAR:                    # lalat pemilih (bawaan): aturan QC 46
        pil, dip = pilih_lama(sorted(calon, key=lambda z: -z[0]), st, m, min(slot, MAKS_HARIAN_PILIH), buka)
        return [("rencana", z) for z in pil], (3 if dip else 1)
    tk = tingkat_lapar(jam)
    if slot <= 0:
        return [], tk
    ketat = st.get("ketat")
    ok = lambda p: p["sym"] not in buka and not p.get("jauh")
    sk = [(v + (MEDALI_BONUS if medali(p) else 0.0), p, tok) for v, p, tok in calon if ok(p)]
    sk.sort(key=lambda z: -z[0])
    th = ambang(st)
    a = sorted((x for x in alt if x["sym"] not in buka), key=lambda x: ALT_URUT.get(str(x.get("sumber", "")).split()[0], 9))
    if tk == 1:
        if TINGKAT1_JAM_WIB is not None and _jam_wib(now or time.time()) != TINGKAT1_JAM_WIB:
            return [], tk
        pil = [z for z in sk if z[0] > th and (not ketat or medali(z[1]))][:slot]
        return [("rencana", z) for z in pil], tk
    if tk == 2:
        if ALT_DULU and a:
            return [("alt", a[0])], tk
        dekat = sorted(sk, key=lambda z: z[1].get("dist", 9))[:50]
        pil = [z for z in sorted(dekat, key=lambda z: -z[0]) if z[0] > th * 0.85][:slot]
        if pil:
            return [("rencana", z) for z in pil], tk
        return ([("alt", a[0])] if a else []), tk
    if ALT_DULU and a:
        return [("alt", a[0])], tk
    rapat = [z for z in sk if z[1].get("distp", 99) < 0.5]
    if rapat:
        return [("rencana", rapat[0])], tk
    if a:
        return [("alt", a[0])], tk
    if sk:
        return [("rencana", min(sk, key=lambda z: z[1].get("distp", 99)))], tk
    return [], tk


def pilih_harian(calon, st, m, slot, buka, paksa=False):
    """Dipakai replay QC 46: mode pemilih langsung, mode lapar lewat tingkat dari makan_t. Return (pilihan rencana, dipaksa)."""
    if not MODE_LAPAR:
        return pilih_lama(sorted(calon, key=lambda z: -z[0]), st, m, slot, buka, paksa)
    jam = 15.0 if paksa else (time.time() - st.get("makan_t", time.time())) / JAM
    pil, tk = pilih_lapar(calon, [], st, m, slot, buka, jam)
    return [z for j, z in pil if j == "rencana"], tk >= 2


def nilai_calon(st=None, m=None, maks=400):
    """Semua rencana Sniper hari ini dengan nilai lalat. Return list (nilai, rencana, token)."""
    import qse_rencana as RC
    st = st or state(); m = m or memori()
    try:
        import qse_strat as ST
        bn = ST.btc_naik()
    except Exception:
        bn = None
    out = []
    for r in RC.daftar(maks=maks, semua=True):
        p = dict(r)
        a = p["atr"]; L = p["arah"] == "LONG"; d_ = 1 if L else -1
        p["entry"] = p["level"]; p["sl"] = p["level"] - d_ * SL_ATR * a
        p["tp1"] = p["entry"] + d_ * TP1_ATR * a; p["tp2"] = p["entry"] + d_ * TP2_ATR * a
        tok = token_rencana(p, bn)
        v, _ = nilai(tok, m)
        p["spesialis"] = r.get("spesialis", False)
        out.append((v, p, tok))
    out.sort(key=lambda z: -z[0])
    return out


def _hari(ts=None):
    return time.strftime("%Y-%m-%d", time.gmtime((ts or time.time()) + 7 * 3600))


def makanan_jalur(tk=None):
    """Sinyal jalur lain yang sedang aktif untuk lalat saat lapar: jalur utama v150 (EMA/RSI/SMC/Ichimoku/Order Block, masih
    dalam 0.5R dari entry robot) dan kantong Sektor yang baru buka (8 jam terakhir). Return list dict."""
    out = []
    try:
        import bybit_fetch as B
        import qse_sesi as SS
        tk = tk or B.get_tickers()
        for sym, arah, k, dR, it in sorted(SS._valid_jalur(tk), key=lambda z: abs(z[3])):
            px = (tk.get(sym) or {}).get("last") or it["entry"]
            out.append(dict(sumber=f"jalur {k}", sym=sym, arah=arah, entry=px, sl=it["sl"], tp=it.get("tp"), atr=it.get("atr") or abs(px - it["sl"])))
    except Exception as ex:
        print("[WARN] lalat makanan jalur", ex)
    try:
        import qse_sektor as SKT
        for it in SKT.lihat()["open"].values():
            if time.time() - it.get("t", 0) < 8 * JAM:
                out.append(dict(sumber="sektor", sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl"], tp=None,
                                atr=abs(it["entry"] - it["sl"])))
    except Exception as ex:
        print("[WARN] lalat makanan sektor", ex)
    return out


def _berburu(st, m, paksa=False):
    """Lalat wajib makan tiap hari. Tingkat lapar (jam sejak posisi terakhir terisi) mengatur ambang dan luas pencarian."""
    import qse_saya as SY
    cek_ketat(st)
    global MODE_LAPAR
    MODE_LAPAR = bool(st.get("mode_lapar", False)) or paksa
    maks_hari = MAKS_HARIAN if MODE_LAPAR else MAKS_HARIAN_PILIH
    hari = _hari()
    n_hari = st["harian"].get(hari, 0)
    slot = min(MAKS_BUKA - len(st["open"]), maks_hari - n_hari)
    if slot <= 0:
        st["buru"] = f"kenyang hari ini ({maks_hari} trade) atau {MAKS_BUKA} posisi masih jalan"
        return []
    jam = 15.0 if paksa else (time.time() - st.get("makan_t", time.time())) / JAM
    calon = nilai_calon(st, m)
    alt = makanan_jalur() if tingkat_lapar(jam) >= 2 else []
    buka = {it["sym"] for it in st["open"].values()}
    pilih, tk = pilih_lapar(calon, alt, st, m, slot, buka, jam)
    if not pilih:
        st["buru"] = f"tingkat lapar {tk}: belum ada pola di atas ambang {ambang(st) * (0.85 if tk == 2 else 1):+.3f}"
        return []
    out = []
    for jenis, z in pilih:
        key = f"{z[1]['sym'] if jenis == 'rencana' else z['sym']}|{int(time.time())}"
        if jenis == "rencana":
            v, p, tok = z
            lot_ = lot_sekarang(st)
            va_ = valensi_mb(tok)
            if MB_LOT and not st.get("ketat") and va_ != 0:
                lot_ = 0.5 if va_ > 0 else 0.1          # otak MB asli: disukai lot 0.5x, dijauhi 0.1x (permintaan pemilik, QC 52)
            it = dict(sym=p["sym"], arah=p["arah"], entry=p["entry"], sl=p["sl"], tp1=p["tp1"], tp2=p["tp2"], atr=p["atr"],
                      t=time.time(), tokens=tok, nilai=round(v, 4), paksa=tk >= 2, tingkat=tk, tick=SY.tick_of(None, p["entry"]),
                      lot=lot_, ketat=bool(st.get("ketat")), level=p.get("level", p["entry"]),
                      refleks=bool(st.get("refleks_masuk")), medali=medali(p), valensi=round(va_, 4))
        else:
            a = z; L = a["arah"] == "LONG"; d = 1 if L else -1; r = abs(a["entry"] - a["sl"]) or a["entry"] * 0.02
            it = dict(sym=a["sym"], arah=a["arah"], entry=a["entry"], sl=a["sl"], tp1=a["entry"] + d * 0.5 * r,
                      tp2=a.get("tp") or a["entry"] + d * 1.5 * r, atr=r, t=time.time(), isi_t=time.time(), tahan_jam=30,
                      tokens=token_trade(a["sym"], a["arah"], time.time(), a["sumber"].split()[0]), nilai=0.0, paksa=True,
                      tingkat=tk, tick=SY.tick_of(None, a["entry"]), lot=lot_sekarang(st), ketat=bool(st.get("ketat")),
                      sumber=a["sumber"], level=a["entry"])
            st["makan_t"] = time.time()          # masuk market: langsung makan
        st["open"][key] = it
        st["harian"][hari] = st["harian"].get(hari, 0) + 1
        out.append(kartu(it, baru=True))
    st["harian"] = {k: v for k, v in st["harian"].items() if k >= _hari(time.time() - 7 * 86400)}
    st["buru"] = f"tingkat lapar {tk}: memilih {len(out)} trade" + (" (mode ketat, lot 0.1x)" if st.get("ketat") else "")
    return out


def kartu(it, baru=False):
    import qse_saya as SY
    t = it.get("tick")
    jenis_o = "MARKET" if it.get("sumber") else "LIMIT"
    blok = SY.blok_salin(it["entry"], it["sl"], it["tp1"], it["tp2"], jenis_o, t, sym=it["sym"], arah=it["arah"])
    st_ = ("⏳ menunggu terisi" if not it.get("isi_t") else "✅ TP1 terkunci, SL di entry" if it.get("tp1k") else "🟢 jalan")
    suka = [x.split(":", 1)[1] + " " + x.split(":", 1)[0] for x in it.get("tokens", [])[5:9]]
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], kali=it.get("lot", LOT))
    except Exception:
        lot = ""
    lab = {1: "kenyang", 2: "lapar, ambang turun 15%", 3: "sangat lapar, wajib makan"}.get(it.get("tingkat"), "")
    asal = (f"🍽️ makan sinyal {it['sumber']}" if it.get("sumber") else ("🏅 koin medali" if it.get("medali") else "koin umum"))
    if it.get("sumber"):
        cara = (f"\n📲 Masuk <b>Market</b> sekarang, isi SL. TP1 +0.5R tutup 50% lalu SL ke entry, sisa ke TP2. "
                f"Paling lama {it.get('tahan_jam', 30)} jam.")
    else:
        cara = ("\n📲 Pasang <b>Limit</b> di entry, isi SL. TP1 = Fix Profit 0.5 ATR, tutup 50% lalu SL ke entry. TP2 0.8 ATR. "
                "Order batal 24 jam, posisi terisi tutup paling lambat 24 jam.")
    return ((f"🪰 <b>{'PILIHAN BARU' if baru else 'PILIHAN'} LALAT: {it['sym']} {it['arah']} {jenis_o}</b>  ·  {st_}\n")
            + f"{asal}" + (f"  ·  tingkat lapar {it['tingkat']} ({lab})" if it.get("tingkat") else "")
            + f"  ·  nilai pola {it.get('nilai', 0):+.3f}  ·  valensi otak asli {valensi_mb(it.get('tokens', [])):+.3f}"
            + (f"  ·  {', '.join(suka)}" if suka else "") + "\n" + blok + cara
            + f" Lot {it.get('lot', LOT):g}x" + (" (Mode Berburu Ketat)" if it.get("ketat") else "") + "." + ("\n" + lot if lot else ""))


# ---------- jalan tiap 15 menit dari listener ----------
def jalankan():
    """Return daftar pesan untuk grup. Hormon dan sinapsis disimpan tiap jalan (berkembang tiap jam)."""
    with _KUNCI:
        st = state(); m = memori()
        _hidup(st)
        try:
            _makan_posisi_user(st, m)
        except Exception as ex:
            print("[WARN] lalat user", ex)
        out = []
        try:
            out += _kelola(st, m)
        except Exception as ex:
            print("[WARN] lalat kelola", ex)
        if time.time() - st.get("ledger_t", 0) >= JAM:
            st["ledger_t"] = time.time()
            _belajar_ledger(st, m)
        if time.time() - st.get("buru_t", 0) >= JAM or st["lapar"] >= 80:
            st["buru_t"] = time.time()
            try:
                out += _berburu(st, m)
            except Exception as ex:
                print("[WARN] lalat buru", ex)
                st["buru"] = f"gagal memindai: {str(ex)[:80]}"
        _tulis(F_STATE, st); _tulis(F_MEMORI, m)
        return out


# ---------- Optic Lobe cepat: refleks 5 menit ----------
# Mata majemuk lalat membaca candle 5 menit tiap menit, tidak menunggu candle 1J atau 4J tutup.
# 1. Refleks pantau (selalu aktif): order terisi dan TP1 terdeteksi dalam 1-6 menit, langsung kabar geser SL ke entry.
# 2. Refleks masuk (penolakan jarum 5 menit di support) dan refleks keluar (candle 5 menit berbalik dengan volume besar):
#    terpasang, bawaan MATI karena uji menolak. Bisa dinyalakan dari menu Otak Lalat.
# Uji riset/upgrade/run_v158_refleks.py, PSG/ACM/BAR LONG, data 5 menit 2023-2026, pilih di 2023-2024:
REFLEKS_UJI = ("Uji 5 menit PSG/ACM/BAR 2023-2026: Limit dasar uji +213.9R (WR 79%, PF 1.78) dan terbaik di latih. "
               "Refleks keluar terbaik uji +157.5R, refleks masuk terbaik uji +89.0R, gabungan +22.2R. Semua lebih kecil dari dasar.")
REFLEKS_W, REFLEKS_VK = 0.3, 1.0          # refleks masuk terbaik di latih: ekor >= 0.3 rentang, volume >= 1.0x rata 48 candle
REFLEKS_X, REFLEKS_VK2 = 0.5, 3.0         # refleks keluar terbaik di latih: 0.5 ATR melawan, volume >= 3x rata


def _k5(sym):
    import bybit_fetch as B
    df = B._raw(sym, "5", 80)
    ms = int(time.time() * 1000)
    df = df[df.index + 300000 <= ms]                  # hanya candle 5 menit yang sudah tutup
    v = df["volume"].values.astype(float)
    vm = np.r_[np.full(1, np.nan), [v[max(0, i - 48):i].mean() for i in range(1, len(v))]]
    return df, vm


def _angka(x):
    return f"{x:.6g}"


def tombol_refleks(it, jenis):
    """Tombol cepat di notifikasi refleks. Bentuk baris (teks, data) untuk qse_menu._inline.
    isi: catat posisi (entry, SL, TP1, TP2, terisi) dan SL ke entry. tp1: SL ke entry (Break Even) dan TP 50%. keluar: tutup."""
    k = it["sym"].replace("USDT", "")
    catat = (f"c:/entry {it['arah']} LIMIT {k} {_angka(it['entry'])} SL {_angka(it['sl'])} TP1 {_angka(it['tp1'])} "
             f"TP2 {_angka(it['tp2'])} TERISI")
    if len(catat.encode()) > 64:
        catat = f"c:/entry {it['arah']} LIMIT {k} {_angka(it['entry'])} SL {_angka(it['sl'])} TERISI"
    if len(catat.encode()) > 64:
        catat = "t:/entry"
    be = (f"🛡️ SL ke entry (Break Even)", f"c:/modify {k} SL ENTRY")
    if jenis == "isi":
        return [[("📝 Catat posisi ini", catat)], [be], [("📊 Posisi saya", "c:/status")]]
    if jenis == "tp1":
        return [[be], [("💰 TP 50%", f"c:/tp {k} 50%"), ("📊 Posisi saya", "c:/status")]]
    if jenis == "keluar":
        return [[("✋ Tutup posisi saya", f"y:/tutup {k}")], [("📊 Posisi saya", "c:/status")]]
    return []


def refleks():
    """Dipanggil tiap menit oleh listener. ACh naik saat mata melihat isi, TP, penolakan, atau bahaya.
    Return list: teks biasa, atau (teks, baris tombol) untuk notifikasi darurat dengan tombol cepat."""
    with _KUNCI:
        st = state()
        if not st["open"]:
            return []
        m = memori(); out = []; ubah = False
        r_masuk, r_keluar = bool(st.get("refleks_masuk")), bool(st.get("refleks_keluar"))
        import qse_saya as SY
        for key, it in list(st["open"].items()):
            L = it["arah"] == "LONG"; d = 1 if L else -1
            try:
                df, vm = _k5(it["sym"])
            except Exception as ex:
                print("[WARN] refleks candle", it["sym"], ex)
                continue
            mk = df.index >= int(it["t"] * 1000)
            df, vm = df[mk], vm[mk]
            if not len(df):
                continue
            o, h, l, c, v = (df[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
            ts = df.index.values / 1000
            a = it["atr"]; lvl = it.get("level", it["entry"]); t = it.get("tick")
            if not it.get("isi_t"):
                if it.get("refleks") and r_masuk:
                    jebol = (l <= it["sl"]) if L else (h >= it["sl"])
                    if jebol.any():
                        st["ACH"] = min(100.0, st["ACH"] + 20)
                        _tutup(st, m, key, it, None, "refleks batal: level jebol sebelum ada penolakan, order dihindari", out)
                        ubah = True
                        continue
                    if ((l <= lvl) if L else (h >= lvl)).any():
                        k = len(c) - 1; rg = h[k] - l[k]
                        ekor = (min(o[k], c[k]) - l[k]) if L else (h[k] - max(o[k], c[k]))
                        balik = (c[k] > lvl) if L else (c[k] < lvl)
                        dekat = (l[k] <= lvl + 0.2 * a) if L else (h[k] >= lvl - 0.2 * a)
                        if rg > 0 and balik and dekat and ekor >= REFLEKS_W * rg and np.isfinite(vm[k]) and v[k] >= REFLEKS_VK * vm[k]:
                            e = float(c[k])
                            it.update(entry=e, tp1=e + d * TP1_ATR * a, tp2=e + d * TP2_ATR * a, isi_t=float(ts[k]))
                            st["makan_t"] = max(st.get("makan_t", 0), float(ts[k]))
                            st["ACH"] = min(100.0, st["ACH"] + 25)
                            out.append((f"⚡ 🪰 <b>REFLEKS MASUK {it['sym']} {it['arah']} MARKET SEKARANG</b>\n"
                                        f"Candle 5 menit menolak {'support' if L else 'resistance'}, volume {v[k] / vm[k]:.1f}x rata.\n"
                                        + SY.blok_salin(e, it["sl"], it["tp1"], it["tp2"], "MARKET", t, sym=it["sym"], arah=it["arah"]),
                                        tombol_refleks(it, "isi")))
                            ubah = True
                    continue
                kena = np.nonzero((l <= it["entry"]) if L else (h >= it["entry"]))[0]
                if len(kena):
                    it["isi_t"] = float(ts[kena[0]])
                    st["makan_t"] = max(st.get("makan_t", 0), it["isi_t"])
                    st["ACH"] = min(100.0, st["ACH"] + 10)
                    out.append((f"🚨 🪰 <b>ORDER TERISI · {it['sym']} {it['arah']}</b>\nLimit terisi di {SY.fp(it['entry'], t)} "
                                f"(terbaca dari candle 5 menit). Pastikan SL {SY.fp(it['sl'], t)} dan TP1 {SY.fp(it['tp1'], t)} 50% terpasang. "
                                "Tekan 📝 Catat supaya robot menjaga posisi kamu.", tombol_refleks(it, "isi")))
                    ubah = True
                else:
                    continue
            sesudah = ts > it["isi_t"]
            if not it.get("tp1k"):
                if r_keluar:
                    k = len(c) - 1
                    if sesudah[k] and (c[k] - it["entry"]) * d <= -REFLEKS_X * a and np.isfinite(vm[k]) and v[k] >= REFLEKS_VK2 * vm[k]:
                        risk = abs(it["entry"] - it["sl"])
                        R = (c[k] - it["entry"]) * d / risk - 0.0011 * it["entry"] / risk
                        st["ACH"] = min(100.0, st["ACH"] + 30)
                        out.append((f"⚡ 🪰 <b>REFLEKS KELUAR {it['sym']} {it['arah']}</b>: candle 5 menit berbalik "
                                    f"{abs(c[k] - it['entry']) / a:.1f} ATR, volume {v[k] / vm[k]:.1f}x. Tutup Market sekarang di sekitar {SY.fp(c[k], t)}.",
                                    tombol_refleks(it, "keluar")))
                        _tutup(st, m, key, it, R, "refleks keluar 5 menit", out)
                        ubah = True
                        continue
                tp = np.nonzero(sesudah & ((h >= it["tp1"]) if L else (l <= it["tp1"])))[0]
                sl = np.nonzero(sesudah & ((l <= it["sl"]) if L else (h >= it["sl"])))[0]
                if len(tp) and (not len(sl) or tp[0] < sl[0]):
                    it["tp1k"] = True
                    st["DA"] = min(100.0, st["DA"] + 15); st["ACH"] = min(100.0, st["ACH"] + 10)
                    out.append((f"🚨 🪰 <b>TP1 KENA · {it['sym']} {it['arah']}</b>\nTP1 Fix Profit {SY.fp(it['tp1'], t)} tersentuh (candle 5 menit). "
                                f"Tutup 50% dan geser SL ke entry {SY.fp(it['entry'], t)} sekarang. Satu tekan 🛡️ di bawah, posisi kamu jadi "
                                "Break Even. Lalat dapat dopamin.", tombol_refleks(it, "tp1")))
                    ubah = True
        if ubah:
            _tulis(F_STATE, st); _tulis(F_MEMORI, m)
        return out


def atur_refleks(args):
    """Menu: nyalakan atau matikan refleks masuk dan keluar. Bawaan mati karena uji menolak."""
    with _KUNCI:
        st = state()
        a = [x.upper() for x in args]
        if "MASUK" in a:
            st["refleks_masuk"] = not st.get("refleks_masuk")
        if "KELUAR" in a:
            st["refleks_keluar"] = not st.get("refleks_keluar")
        _tulis(F_STATE, st)
    return (f"⚡ <b>Refleks optik lalat</b>\nPantau 5 menit: NYALA (order terisi dan TP1 terkabar dalam 1-6 menit).\n"
            f"Refleks masuk: {'NYALA' if st.get('refleks_masuk') else 'MATI'}  ·  Refleks keluar: {'NYALA' if st.get('refleks_keluar') else 'MATI'}\n"
            f"🧪 {REFLEKS_UJI}")


# ---------- tampilan ----------
def mood(st):
    if st.get("ketat"):
        return f"🛡️ Mode Berburu Ketat ({st.get('ketat_sebab', '')}): lot 0.1x, hanya koin rasio menang tertinggi"
    if st["lapar"] >= 80:
        return "🔥 Sangat haus profit, sedang memburu koin"
    if st["DA"] >= 65:
        return "🤩 Dopamin tinggi, baru makan profit"
    if st["GABA"] >= 55:
        return "🤕 Kapok, berburu lebih hati-hati"
    if st["SER"] >= 65:
        return "😌 Tenang dan selektif, hanya setup paling akurat"
    if st["open"]:
        return "🎯 Sedang menjaga posisi"
    return "🙂 Sehat, mengamati pasar"


def _baris_mb():
    o = otak()
    if not o:
        return "🧬 Otak asli FlyWire: file mb_sirkuit.npz tidak terbaca"
    r = o.ringkas()
    return (f"🧬 Otak asli FlyWire FAFB v783: {r['pn']} PN, {r['kc']} Kenyon cell, 1 APL, {r['mbon']} MBON, {r['sinapsis']} sinapsis "
            f"KC ke MBON. Sinapsis berubah karena pengalaman {r['melemah']}. Suara di keputusan {MB_SUARA:g} (dipilih di uji latih, QC 48)")


def _bar(x):
    n = int(round(max(0, min(100, x)) / 10))
    return "▰" * n + "▱" * (10 - n)


def _sinapsis(m, maks=6):
    tw = [(k, v) for k, v in m["token"].items() if m["n"].get(k, 0) >= 1 or m.get("bawaan")]
    suka = sorted([z for z in tw if z[1] > 0.01], key=lambda z: -z[1])[:maks]
    benci = sorted([z for z in tw if z[1] < -0.01], key=lambda z: z[1])[:maks]
    f = lambda z: (f"{html.escape(z[0].replace('spesialis:', ''))} ({z[1]:+.2f}, "
                   + (f"{m['n'][z[0]]}x makan" if m["n"].get(z[0]) else "bekal uji") + ")")
    return suka, benci, f


def teks(lengkap=False):
    with _KUNCI:
        st = state(); m = memori()
        _hidup(st)
    umur = (time.time() - st["lahir"]) / 86400
    tanpa = (time.time() - st.get("makan_t", time.time())) / JAM
    suka, benci, f = _sinapsis(m, 12 if lengkap else 5)
    rows = [f"🪰 <b>QSE v150 | OTAK LALAT</b>",
            f"❤️ <b>Nyawa</b>: hidup {umur:.1f} hari  ·  makan profit {st['n_tp']}x  ·  luka SL {st['n_sl']}x  ·  impas {st['n_be']}x",
            f"🧠 <b>Mood</b>: {mood(st)}",
            "",
            f"🍽️ Lapar   {_bar(st['lapar'])} {st['lapar']:.0f}%  ({tanpa:.1f} jam sejak posisi terakhir terisi, tingkat {tingkat_lapar(tanpa)}: "
            + {1: "kenyang, hanya koin medali", 2: "lapar, ambang turun 15%, 50 koin terdekat level, sinyal Sektor/jalur",
               3: "sangat lapar, wajib makan dari 183 koin"}[tingkat_lapar(tanpa)] + ")",
            f"💉 DA      {_bar(st['DA'])} {st['DA']:.0f}  dopamin, hadiah TP",
            f"😌 5-HT    {_bar(st['SER'])} {st['SER']:.0f}  serotonin, selektif",
            f"🩹 GABA    {_bar(st['GABA'])} {st['GABA']:.0f}  rem rasa sakit SL",
            f"👁️ ACh     {_bar(st['ACH'])} {st['ACH']:.0f}  perhatian, laju belajar",
            _baris_mb(),
            f"🎚️ Ambang pilih {ambang(st):+.3f}  ·  lot {lot_sekarang(st):g}x" + ("  ·  🛡️ MODE BERBURU KETAT" if st.get("ketat") else "")
            + f"  ·  status buru: {html.escape(st.get('buru', 'belum berburu'))}",
            "",
            "💚 <b>Sinapsis disukai</b> (sering memberi makan TP, atau untung di uji 2023-2024): " + (", ".join(f(z) for z in suka) or "belum ada"),
            "💔 <b>Sinapsis dibenci</b> (pernah kena SL, atau rugi di uji 2023-2024): " + (", ".join(f(z) for z in benci) or "belum ada")]
    if lengkap:
        kc = np.array(m["kc"])
        rows.append(f"🧬 Mushroom Body: {N_KC} Kenyon cell, kuat {int((kc > 1.2).sum())}, lemah {int((kc < 0.8).sum())}. "
                    f"Seed sinapsis dari wilayah codex {', '.join(k for g in WILAYAH.values() for k in g)}")
        for t, x in st["kejadian"][-8:]:
            rows.append(f"• {time.strftime('%d/%m %H:%M', time.gmtime(t + 7 * 3600))} {html.escape(x)}")
    rows.append("")
    if st["open"]:
        rows.append("🎯 <b>Sinyal harian pilihan lalat</b>")
        rows += [kartu(it) for it in st["open"].values()]
    else:
        try:
            calon = nilai_calon(st, m, maks=6)[:2]
        except Exception:
            calon = []
        if calon:
            rows.append("🎯 <b>Calon pilihan lalat hari ini</b> (belum dipilih, nilai di bawah ambang atau masih kenyang)")
            for v, p, tok in calon:
                it = dict(p, tokens=tok, nilai=v, tick=None)
                rows.append(kartu(it))
        else:
            rows.append("🎯 Belum ada koin likuid di dekat support/resistance. Lalat memindai lagi tiap jam.")
    sel = [x for x in st["riwayat"] if x.get("R") is not None][-10:]
    if sel:
        tot = sum(x["R"] for x in sel); wr = sum(1 for x in sel if x["R"] > 0) / len(sel) * 100
        akun = sum(x["R"] * x.get("lot", LOT) for x in sel)
        rows.append(f"\n📒 {len(sel)} trade lalat terakhir: WR {wr:.0f}%, total {tot:+.2f}R per posisi = {akun:+.2f}R akun")
    return "\n".join(rows)


def perintah(args=None):
    a = [x.upper() for x in (args or [])]
    if a and a[0] in ("SINAPSIS", "LENGKAP", "OTAK"):
        return teks(lengkap=True)
    if a and a[0] == "LAPAR":
        with _KUNCI:
            st = state(); st["mode_lapar"] = not st.get("mode_lapar", False); _tulis(F_STATE, st)
        return ("🍽️ Lapar bertingkat " + ("NYALA: lalat wajib makan tiap hari dari 183 koin dan sinyal jalur lain." if st["mode_lapar"] else
                "MATI: lalat hanya makan koin medali dari rencana 07:00 WIB (mode lama, lebih jarang).")
                + "\nUji 2025-2026: nyala 1.58 trade per hari, +2.3R akun. Mati 1.35 trade per hari, +20.1R akun (QC 48).")
    if a and a[0] == "REFLEKS":
        return atur_refleks(a[1:])
    if a and a[0] in ("BURU", "MAKAN", "PAKSA"):
        with _KUNCI:
            st = state(); m = memori(); _hidup(st)
            st["lapar"] = max(st["lapar"], 85.0)
            out = _berburu(st, m, paksa=True)
            _tulis(F_STATE, st); _tulis(F_MEMORI, m)
        return ("\n\n".join(out) if out else f"🪰 Lalat belum makan: {html.escape(st.get('buru', ''))}") + "\n\n" + teks()
    return teks()


def pilihan_teks():
    """Ringkas untuk tombol Sinyal 4J: posisi dan order lalat yang masih jalan."""
    st = state()
    if not st["open"]:
        return ""
    return "🪰 <b>PILIHAN LALAT HARI INI</b>\n\n" + "\n\n".join(kartu(it) for it in st["open"].values())
