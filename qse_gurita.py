"""QSE v150 - 🐙 Gurita bionik. Hidup berdampingan dengan 🪰 lalat: lalat berburu order Limit di support/resistance koin medali,
gurita mengoordinasi sinyal jalur utama v150 (EMA, RSI, McGinley, SnR, SMC, Ichimoku, Order Block, Sektor).

Arsitektur dari fakta otak gurita (Octopus vulgaris):
  - Sekitar 500 juta neuron, sekitar dua per tiga di lengan. Lengan memproses dan memutuskan sendiri, lengan saling berbagi lewat
    cincin saraf tanpa lewat otak (Gire dan Sivitilli, Univ. Washington 2019).
    -> 8 LENGAN = 8 jalur sinyal. Tiap lengan punya ingatan lokal hasil jalurnya dan boleh menolak sinyalnya sendiri.
    -> CINCIN SARAF: dua lengan atau lebih menunjuk koin dan arah yang sama = sinyal diperkuat.
  - Vertical lobe (VL) pusat belajar: sekitar 25 juta neuron, input dari superior frontal lobe (SFL) sekitar 1.8 juta akson.
    Tiap amacrine sederhana (SAM) hanya menerima SATU akson SFL, satu akson menyebar ke sekitar 12 SAM (fan-out 1:12),
    lalu sekitar 400 amacrine berkumpul ke satu neuron besar keluaran (LN). Belajar = LTP presinaptik SFL->SAM, tidak lewat NMDA,
    dijaga nitric oxide. Amacrine kompleks (CAM) GABA menyeimbangkan. Serotonin dan katekolamin memodulasi
    (Bidel dkk., eLife 2023, doi:10.7554/eLife.84257; Shomrat dkk. 2011; Turchetti-Maia dkk. 2017).
    -> Tiap ciri (lengan, koin, arah, koin+arah, rezim BTC) = satu akson SFL yang menyebar ke 12 SAM dengan laju belajar
       berbeda (cepat sampai lambat). TP = LTP di jalur mendekat, SL = LTP di jalur CAM penghambat.
       LN = jumlah semua SAM aktif. Tanpa kombinasi antar ciri di SAM, sesuai temuan eLife 2023.
  - Belajar dengan mengamati gurita lain (Fiorito dan Scotto, Science 1992).
    -> Gurita menonton hasil SEMUA sinyal jalur (ledger kertas robot) dan trade kamu, bukan hanya yang ia ambil.
  - Tidur dua fase (aktif dan tenang). -> Tiap hari ingatan cepat dipadatkan ke ingatan lambat (konsolidasi).
  - Kamuflase cepat. -> Ciri rezim pasar (BTC naik atau turun) ikut jadi akson SFL, gurita menyesuaikan warna (pilihan) per rezim.
Gurita MENAMBAH sinyal (buru): sinyal 8 jalur yang ditahan robot tapi didukung 3+ lengan lain. Sinyal jalur, combo, dan lalat
tetap semua jalan. Uji: riset/upgrade/run_v158_gurita.py (penyaring, QC 49) dan run_v158_gurita3.py (penambah, QC 50).
State: STATE_DIR/gurita.json."""
import qse_modal as MD          # kelas margin di kartu (9 Nov 2026)
import json
import math
import os
import threading
import time
from config import STATE_DIR

F_STATE = os.path.join(STATE_DIR, "gurita.json")
F_BAWAAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gurita_bawaan.json")
_KUNCI = threading.RLock()
N_SAM = 12                                   # fan-out SFL -> SAM
TAU = [0.25 * (16 ** (i / (N_SAM - 1))) for i in range(N_SAM)]       # laju belajar relatif tiap SAM, 0.25 sampai 4
# parameter (diisi dari riset, lihat PARAM_UJI)
ETA = 0.01            # laju LTP, dipilih di latih 2024 (run_v158_gurita.py)
LUPA = 0.02           # peluruhan per kejadian (dikalikan TAU)
AMBANG = -0.05        # nilai LN minimal supaya gurita mau mengikuti sinyal
VETO_N, VETO_MIN = 20, -0.3                  # lengan menolak sinyalnya bila rata R 20 hasil terakhir jalurnya di bawah ini
CINCIN_BONUS = 0.0
SARING = False        # True = pendapat gurita menyaring sinyal. Mati: uji 2025-2026 menyaring = +203R lawan ikut semua +271R (QC 49)
PARAM_UJI = ("Uji 4330 sinyal 8 jalur: latih 2024 saring +261.7R lawan semua +258.7R. Uji 2025-2026 saring +203.0R lawan "
             "semua +271.3R, jadi gurita hanya mengamati dan belajar, tidak menyaring sinyal (QC 49).")


def fitur(jalur, sym, arah, rezim=None):
    """Akson SFL yang menyala untuk satu sinyal."""
    f = [f"lengan:{jalur}", f"koin:{sym}", f"arah:{arah}", f"koinarah:{sym}:{arah}", f"lenganarah:{jalur}:{arah}"]
    if rezim is not None:
        f.append(f"rezim:{rezim}:{arah}")
    return f


class Otak:
    """Vertical lobe: akson -> 12 SAM (laju TAU) dengan dua kolam: mendekat (LTP saat TP) dan CAM penghambat (LTP saat SL)."""

    def __init__(self, d=None):
        d = d or {}
        self.w = {k: [list(v[0]), list(v[1])] for k, v in d.get("w", {}).items()}
        self.lengan = {k: list(v) for k, v in d.get("lengan", {}).items()}
        self.n = dict(d.get("n", {}))

    def ke_dict(self):
        return dict(w=self.w, lengan=self.lengan, n=self.n)

    def _sam(self, k):
        if k not in self.w:
            self.w[k] = [[0.0] * N_SAM, [0.0] * N_SAM]
        return self.w[k]

    def nilai(self, f):
        """LN: rata semua akson aktif dari jumlah SAM (mendekat - penghambat) / N_SAM."""
        tot = 0.0
        for k in f:
            if k in self.w:
                a, b = self.w[k]
                tot += (sum(a) - sum(b)) / N_SAM
        return tot / max(len(f), 1)

    def belajar(self, f, R, eta=None, lupa=None):
        eta = ETA if eta is None else eta
        lupa = LUPA if lupa is None else lupa
        if not eta:
            return
        r = max(-2.0, min(2.0, R))
        for k in f:
            a, b = self._sam(k)
            for s in range(N_SAM):
                d = min(0.5, lupa * TAU[s])
                a[s] *= (1 - d); b[s] *= (1 - d)
                if r > 0:
                    a[s] += eta * TAU[s] * r
                else:
                    b[s] += eta * TAU[s] * (-r)
            self.n[k] = self.n.get(k, 0) + 1

    def tidur(self):
        """Konsolidasi: separuh selisih ingatan cepat (SAM 0-3) dipindah ke ingatan lambat (SAM 8-11)."""
        for k, (a, b) in self.w.items():
            for pool in (a, b):
                cepat = sum(pool[:4]) / 4
                for s in range(8, N_SAM):
                    pool[s] += 0.1 * (cepat - pool[s])

    def lengan_catat(self, jalur, R):
        x = self.lengan.setdefault(jalur, [])
        x.append(round(float(R), 3))
        del x[:-VETO_N]

    def lengan_ok(self, jalur):
        x = self.lengan.get(jalur, [])
        return len(x) < 5 or sum(x) / len(x) >= VETO_MIN

    def putuskan(self, jalur, sym, arah, rezim=None, kawan=0):
        """Return (ikut, nilai, alasan). kawan = jumlah lengan lain yang menunjuk koin dan arah yang sama (cincin saraf)."""
        if not self.lengan_ok(jalur):
            return False, 0.0, f"lengan {jalur} menolak: hasil {VETO_N} sinyal terakhirnya jelek"
        v = self.nilai(fitur(jalur, sym, arah, rezim)) + (CINCIN_BONUS if kawan else 0.0)
        return v > AMBANG, v, ("cincin saraf: " + str(kawan + 1) + " lengan setuju" if kawan else "")


# ---------- simpan ----------
def _baca():
    for p in (F_STATE, F_BAWAAN):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(F_STATE + ".tmp", "w") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(F_STATE + ".tmp", F_STATE)


def otak():
    d = _baca()
    return Otak(d.get("otak")), d


def simpan(o, d):
    d["otak"] = o.ke_dict()
    _tulis(d)


def _rezim():
    try:
        import qse_strat as ST
        b = ST.btc_naik()
        return None if b is None else ("naik" if b else "turun")
    except Exception:
        return None


# ---------- berburu: gurita menambah sinyal lewat cincin saraf ----------
# Sinyal 8 jalur yang DITAHAN robot (nilai rendah atau ditahan otak) tapi didukung 3 lengan lain atau lebih (combo >= 3).
# Riset run_v158_gurita3.py: latih 2023-2024 +104.6R (lot 1, tiap tahun positif), uji 2025-2026 -9.6R (2025 +20.8, 2026 -30.4).
# Karena uji belum untung, sinyal gurita mulai sebagai UJI KERTAS (lot 0.1x) dan baru AKTIF (lot 0.25x) setelah rapor
# 20 sinyal gurita terakhir WR >= 60% dan total R positif, sama dengan aturan papan Lab.
COMBO_MIN, MAKS_HARI, MAKS_BUKA, RAPOR_N, RAPOR_WR = 3, 5, 8, 20, 0.60
TAHAN_JAM = 30


def _sumber():
    out = []
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            out += [(k, it) for it in ST.lihat(k)["open"].values()]
    except Exception as ex:
        print("[WARN] gurita sumber strat", ex)
    for mod, k in (("qse_ichimoku", "ichimoku"), ("qse_ob", "orderblock")):
        try:
            m = __import__(mod)
            out += [(k, it) for it in m.lihat()["open"].values()]
        except Exception:
            pass
    return out


def _ditahan(k, it):
    """True kalau sinyal ini tidak dikirim robot v150 (ditahan otak atau nilai di bawah mode)."""
    if it.get("otak_saring"):
        return True
    try:
        import qse_strat as ST
        return not ST.lolos_mode(ST.prioritas(k, it))
    except Exception:
        return False


def rapor(d):
    r = [p["R"] for p in d.get("pick", []) if p.get("R") is not None][-RAPOR_N:]
    wr = sum(1 for x in r if x > 0) / len(r) if r else 0.0
    return dict(n=len(r), wr=wr, tot=sum(r), aktif=len(r) >= RAPOR_N and wr >= RAPOR_WR and sum(r) > 0)


def _kelola(d):
    """Jalan ulang sinyal gurita dari candle 1J: SL, TP1 +0.5R (tutup 50%, SL ke entry), TP2, batas 30 jam."""
    import bybit_fetch as B
    out = []
    for p in d.get("pick", []):
        if p.get("R") is not None:
            continue
        try:
            df = B._raw(p["sym"], "60", 60)
        except Exception:
            continue
        ms = int(time.time() * 1000)
        df = df[(df.index >= p["t"] * 1000) & (df.index + 3600000 <= ms)]
        L = p["arah"] == "LONG"; dd = 1 if L else -1
        e, sl = p["entry"], p["sl"]; risk = abs(e - sl) or e * 0.02
        tp1 = p.get("tp1") or e + dd * 0.5 * risk; tp2 = p.get("tp") or e + dd * 1.5 * risk
        r1 = abs(tp1 - e) / risk; r2 = abs(tp2 - e) / risk; fee = 0.0011 * e / risk; k1 = p.get("tp1k", False); R = None
        for ts, h, l, c in zip(df.index, df["high"].values, df["low"].values, df["close"].values):
            st = e if k1 else sl
            if (L and l <= st) or ((not L) and h >= st):
                R = (0.5 * r1 if k1 else -1.0) - fee; break
            if not k1 and ((L and h >= tp1) or ((not L) and l <= tp1)):
                k1 = True
            if k1 and ((L and h >= tp2) or ((not L) and l <= tp2)):
                R = 0.5 * r1 + 0.5 * r2 - fee; break
            if ts / 1000 >= p["t"] + p.get("tahan", TAHAN_JAM) * 3600:
                rr = (c - e) * dd / risk
                R = (0.5 * r1 + 0.5 * rr if k1 else rr) - fee; break
        p["tp1k"] = k1
        if R is not None:
            p["R"] = round(R, 3); p["selesai"] = time.time()
            suntik(d, p, R)
            asal = (f"{p['jalur']} + {p['combo']} lengan" if p.get("combo") else "8 lengan: " + ", ".join(p.get("lengan", [])))
            out.append(f"{'✅' if R > 0 else '🛑'} 🐙 Sinyal gurita {p['sym']} {p['arah']} ({asal}) selesai {R:+.2f}R"
                       + (f". 🦑💨 Semburan tinta: {p['sym']} {p['arah']} ditutup {TINTA_JAM} jam" if R < -0.05 else ""))
    return out


def buru(o, d):
    """Cari sinyal tambahan. Return pesan kartu baru."""
    import qse_saya as SY
    now = time.time()
    hari = time.strftime("%Y-%m-%d", time.gmtime(now + 7 * 3600))
    pick = d.setdefault("pick", [])
    sudah = {p["key"] for p in pick}
    buka = [p for p in pick if p.get("R") is None]
    n_hari = sum(1 for p in pick if p.get("hari") == hari)
    kena = {p["sym"]: p["t"] for p in pick}
    rp = rapor(d)
    out = []
    calon = []
    for k, it in _sumber():
        t0 = it.get("t", 0)
        key = f"{k}|{it.get('sym')}|{int(t0)}"
        if key in sudah or now - t0 > 4 * 3600 or not _ditahan(k, it):
            continue
        n_combo = len(it.get("combo") or [])
        if n_combo < COMBO_MIN or now - kena.get(it["sym"], 0) < 86400:
            continue
        if not o.lengan_ok(k):
            continue
        calon.append((n_combo, o.nilai(fitur(k, it["sym"], it["arah"])), k, it, key))
    calon.sort(key=lambda z: (-z[0], -z[1]))
    for n_combo, v, k, it, key in calon:
        if len(buka) >= MAKS_BUKA or n_hari >= MAKS_HARI or it["sym"] in {p["sym"] for p in buka}:
            break
        px = SY.harga_live(it["sym"]) or it["entry"]
        p = dict(key=key, jalur=k, sym=it["sym"], arah=it["arah"], entry=px, sl=it["sl"], tp=it.get("tp"), t=now, hari=hari,
                 combo=n_combo + 1, nilai=round(v, 3), aktif=rp["aktif"], R=None)
        L = p["arah"] == "LONG"
        if (L and px <= p["sl"]) or ((not L) and px >= p["sl"]):
            continue
        pick.append(p); buka.append(p); n_hari += 1; kena[p["sym"]] = now
        t = it.get("tick")
        risk = abs(px - p["sl"]); dd = 1 if L else -1
        tp1 = px + dd * 0.5 * risk; tp2 = p["tp"] or px + dd * 1.5 * risk
        lot = 0.25 if rp["aktif"] else 0.1
        status = ("✅ AKTIF" if rp["aktif"] else f"🧪 UJI KERTAS (rapor {rp['n']}/{RAPOR_N}, WR {rp['wr'] * 100:.0f}%)")
        try:
            import qse_modal as MD
            lotb = MD.baris_lot(px, p["sl"], kelas="UTAMA" if lot >= 0.25 else "RINGAN")
        except Exception:
            lotb = ""
        out.append(f"🐙 <b>SINYAL GURITA: {p['sym']} {p['arah']} MARKET</b>  ·  {status}\n"
                   f"🔗 Cincin saraf: {p['combo']} lengan setuju ({k} dan {n_combo} jalur lain). Sinyal ini ditahan robot v150, "
                   f"gurita mengambilnya sebagai makanan tambahan.\n"
                   + SY.blok_salin(px, p["sl"], tp1, tp2, "MARKET", t, sym=p["sym"], arah=p["arah"])
                   + f"\n📲 TP1 tutup 50% lalu SL ke entry, sisa ke TP2. Paling lama {TAHAN_JAM} jam. {MD.teks_kelas(1.0 if lot >= 0.25 else 0.1)}."
                   + ("\n" + lotb if lotb else ""))
    d["pick"] = pick[-400:]
    return out


# ---------- QC 79: 🐙 GURITA MODAL. Gurita memilih sinyal untuk modal kecil dan menjalankan buku kertas berbunga ----------
# Riset run_v182_gurita_wr.py dan run_v183_modal150.py (30178 sinyal 2023-2026, latih 2023-2024, uji 2025-2026, biaya 0.15%):
#   - Mode WR (TP penuh dekat, SL dilebarkan): WR 73-87% tapi modal 150 hanya jadi 124-196 di uji, bulan untung 9-13 dari 22. TIDAK dipasang.
#   - Sinyal 2+ teknik searah dan searah BTC, keluar aturan live, risiko 1% saldo, 5 posisi: latih 150 -> 486 (DD 15%, 17/24 bulan untung),
#     uji 150 -> 343 (DD 26%, 15/22 bulan untung). 3 posisi: uji 254 (DD 17%). 8 posisi: uji 564 (DD 28%). Ini yang dipasang.
#   - Sinyal gurita lama (cincin saraf uji -9.6R, 8 lengan -20.9R) tetap dicatat sebagai trade kertas, tidak dikirim (QSE_GURITA_LAMA=1).
MODAL_AWAL = float(os.environ.get("QSE_GURITA_MODAL", "150"))
MODAL_RISIKO = float(os.environ.get("QSE_GURITA_RISIKO", "1.5"))          # persen saldo per posisi (QC 81: 1.0 -> 1.5)
# QC 81 (run_v185_rugi_dolar.py): rugi tetap 5-7 USDT per SL dari modal 150 tumbuh paling cepat (uji 930-1242) tetapi di 2022 saldo
# jatuh ke 21-34 USDT (drawdown 83-90%) dan 12 bulan terakhir ke 40-73. TIDAK jadi bawaan. Jarak SL sinyal gurita 2.4-7.6% (tengah 4.6%),
# bukan 1%, jadi rugi 6 USDT = posisi 79-253 USDT. Yang dipasang: 1.5% saldo + aturan QC 80: latih 690 DD 33% (terendah 116), uji 628
# DD 29%, 4.3 tahun 2571 DD 33%. Rugi per SL ikut saldo: 2.25 USDT di saldo 150, 5-7 USDT saat saldo 330-470.
# QSE_GURITA_RUGI_USD=6 memaksa rugi tetap dolar (pengali 3 teknik mati, rem tetap jalan).
MODAL_RUGI_USD = float(os.environ.get("QSE_GURITA_RUGI_USD", "0"))
# QC 82 (run_v186_12bulan.py): 2 SL penuh searah dalam 24 jam -> arah itu libur 24 jam. Sebelum Nov 2025: 150 -> 2449 (dasar 2218),
# 12 bulan terakhir 188 (dasar 178, DD 27% vs 29%), 4.3 tahun 3006 (dasar 2571). Trade berkurang 3%. 0 = mati.
MODAL_ARAH_SL = int(os.environ.get("QSE_GURITA_ARAH_SL", "2"))
MODAL_ARAH_JAM = float(os.environ.get("QSE_GURITA_ARAH_JAM", "24"))


def modal_libur(m, now=None):
    """Arah yang sedang libur: {arah: jumlah SL penuh dalam MODAL_ARAH_JAM terakhir}."""
    if MODAL_ARAH_SL <= 0:
        return {}
    now = now or time.time(); n = {}
    for x in m.get("tutup", [])[-60:]:
        if x.get("R", 0) <= -0.8 and now - x.get("selesai", 0) <= MODAL_ARAH_JAM * 3600:
            n[x.get("arah")] = n.get(x.get("arah"), 0) + 1
    return {a: c for a, c in n.items() if c >= MODAL_ARAH_SL}
MODAL_SLOT = int(os.environ.get("QSE_GURITA_SLOT", "8"))
# QC 80 (run_v184_gurita5th.py, Jul 2022 sampai Okt 2026): 8 slot, risiko 1.5 kali untuk 3+ teknik, risiko separuh saat saldo turun lebih
# dari 10% dari puncak. Latih (Jul 2022-2024) 150 -> 513 DD 24% (dasar 5 slot 478 DD 22%), uji (2025-Okt 2026) 466 DD 23% (dasar 308 DD 28%),
# 4.3 tahun 1596 DD 24% (dasar 982 DD 28%), 12 bulan terakhir 170 (dasar 175). Lebih buruk dari dasar di 2023 (143 vs 199).
MODAL_KALI3 = float(os.environ.get("QSE_GURITA_KALI3", "1.5"))            # pengali risiko untuk sinyal 3+ teknik
MODAL_REM_DD = float(os.environ.get("QSE_GURITA_REM_DD", "10"))           # persen turun dari puncak, 0 = rem mati
MODAL_REM_KALI = float(os.environ.get("QSE_GURITA_REM_KALI", "0.5"))
MODAL_SEGAR, MODAL_GESER = 2 * 3600, 0.5                                  # sinyal paling lama 2 jam dan harga masih dalam 0.5R dari entry
MODAL_UJI = ("Uji modal 150 USDT (Jul 2022 sampai Okt 2026), sinyal 2+ teknik searah BTC, keluar aturan live, 8 posisi, risiko 1.5% saldo "
             "(3+ teknik x1.5, separuh saat saldo turun lebih dari 10% dari puncak): latih sampai 2024 jadi 690 (drawdown 33%), uji 2025-2026 "
             "jadi 628 (drawdown 29%, 13 dari 22 bulan untung), 12 bulan terakhir jadi 178. Rugi tetap 5-7 USDT per SL lebih cepat tetapi "
             "saldo pernah jatuh ke 21 USDT di 2022, jadi tidak dipakai.")


def modal_risiko(m, konf):
    """Persen saldo yang dipertaruhkan untuk satu posisi baru. Return (persen, catatan)."""
    r = MODAL_RISIKO; cat = []
    if MODAL_RUGI_USD > 0 and m.get("saldo", 0) > 0:
        r = MODAL_RUGI_USD / m["saldo"] * 100; cat.append(f"rugi tetap {MODAL_RUGI_USD:g} USDT")
    elif konf >= 3 and MODAL_KALI3 != 1:
        r *= MODAL_KALI3; cat.append(f"{konf} teknik x{MODAL_KALI3:g}")
    turun = (1 - m["saldo"] / m["puncak"]) * 100 if m.get("puncak", 0) > 0 else 0.0
    if MODAL_REM_DD > 0 and turun > MODAL_REM_DD:
        r *= MODAL_REM_KALI; cat.append(f"rem: saldo turun {turun:.0f}% dari puncak, risiko x{MODAL_REM_KALI:g}")
    return r, ", ".join(cat)


def siar_lama():
    return os.environ.get("QSE_GURITA_LAMA", "0") == "1"


def _modal(d):
    m = d.setdefault("modal", {})
    m.setdefault("awal", MODAL_AWAL); m.setdefault("saldo", m["awal"]); m.setdefault("puncak", m["saldo"]); m.setdefault("dd", 0.0)
    m.setdefault("buka", []); m.setdefault("tutup", [])
    return m


def _buku(k):
    try:
        if k == "ichimoku":
            import qse_ichimoku as IC
            return IC.lihat()
        if k == "orderblock":
            import qse_ob as OB
            return OB.lihat()
        import qse_strat as ST
        return ST.lihat(k)
    except Exception:
        return {"open": {}, "closed": []}


def modal_kelola(d):
    """Posisi gurita modal selesai saat posisi robot di jalur yang sama selesai. Saldo naik turun R x risiko dolar saat masuk."""
    m = _modal(d); out = []; sisa = []
    for p in m["buka"]:
        b = _buku(p["jalur"]); R = None
        for c in reversed(b.get("closed", [])):
            if c.get("sym") == p["sym"] and int(c.get("t", 0)) == p["tk"] and c.get("R") is not None:
                R = float(c["R"]); break
        if R is None and f"{p['sym']}|{p['tk']}" not in b.get("open", {}) and time.time() - p["t"] > 3 * 86400:
            R = 0.0          # catatan robot hilang: ditutup impas supaya slot tidak terkunci
        if R is None:
            sisa.append(p); continue
        usd = R * p["usd"]; m["saldo"] = round(m["saldo"] + usd, 2); m["puncak"] = max(m["puncak"], m["saldo"])
        m["dd"] = max(m["dd"], 1 - m["saldo"] / m["puncak"] if m["puncak"] > 0 else 0.0)
        m["tutup"].append(dict(key=p["key"], sym=p["sym"], arah=p["arah"], jalur=p["jalur"], R=round(R, 2), usd=round(usd, 2),
                               saldo=m["saldo"], selesai=time.time()))
        out.append(f"{'✅' if R > 0 else '➖' if R == 0 else '🛑'} 🐙 Gurita modal {p['sym']} {p['arah']} selesai {R:+.2f}R = {usd:+.2f} USDT. "
                   f"Saldo buku gurita {m['saldo']:.2f} USDT (awal {m['awal']:.0f})")
    m["buka"] = sisa; m["tutup"] = m["tutup"][-500:]
    return out


def modal_buru(d):
    """Pilih sinyal 2+ teknik searah yang searah BTC, paling banyak MODAL_SLOT posisi, satu per koin. Return kartu baru."""
    import qse_saya as SY
    import qse_strat as ST
    m = _modal(d); now = time.time(); out = []
    sudah = {p["key"] for p in m["buka"]} | {x.get("key") for x in m["tutup"][-300:]}
    pakai = {p["sym"] for p in m["buka"]}
    if len(m["buka"]) >= MODAL_SLOT or m["saldo"] <= 5:
        return out
    bj0 = [None, False]
    libur = modal_libur(m, now)
    calon = []
    for k, it in _sumber():
        try:
            t0 = it.get("t", 0); key = f"{k}|{it.get('sym')}|{int(t0)}"
            if key in sudah or now - t0 > MODAL_SEGAR or it.get("uji_live") or it["sym"] in pakai:
                continue
            konf = len(it.get("combo") or []) + 1
            if konf < 2 or it.get("arah") in libur:
                continue
            bj = it.get("btc_j")
            if bj is None:
                if not bj0[1]:
                    bj0[0] = ST.btc_jarak(); bj0[1] = True
                bj = bj0[0]
            L = it["arah"] == "LONG"
            if bj is None or not ST.konf_utama(it["arah"], bj, konf) or (bj < 0 and L) or (bj > 0 and not L):
                continue
            calon.append((-konf, it.get("peringkat") or 999, k, it, key, bj, konf))
        except Exception as ex:
            print("[WARN] gurita modal calon", ex)
    calon.sort(key=lambda z: z[:2])
    for _, pr, k, it, key, bj, konf in calon:
        if len(m["buka"]) >= MODAL_SLOT:
            break
        if it["sym"] in pakai:
            continue
        L = it["arah"] == "LONG"; dd = 1 if L else -1
        e0 = float(it["entry"]); sl = float(it.get("sl0", it["sl"])); r0 = abs(e0 - sl)
        px = SY.harga_live(it["sym"]) or e0
        if r0 <= 0 or abs(px - e0) / r0 > MODAL_GESER or (px - sl) * dd <= 0:
            continue
        risk = abs(px - sl); sl_pct = risk / px * 100
        rp, rcat = modal_risiko(m, konf)
        usd = round(m["saldo"] * rp / 100, 2); nilai = usd / (sl_pct / 100); lev = MD.lev_saran(sl_pct)
        p = dict(key=key, jalur=k, sym=it["sym"], arah=it["arah"], entry=px, sl=sl, t=now, tk=int(it.get("t", 0)), usd=usd, konf=konf)
        m["buka"].append(p); pakai.add(it["sym"])
        t = it.get("tick"); kawan = ", ".join(str(x) for x in (it.get("combo") or [])[:4])
        if k == "ema_short":
            blok = SY.blok_salin(px, sl, order="MARKET", tick=t, catatan_tp="tanpa, pakai SL berjalan", sym=p["sym"], arah=p["arah"])
            atur = "📲 Tanpa TP sebagian. Untung +0.4R: SL ke entry, lalu ikut pesan GESER SL."
        else:
            tp = it.get("tp") or None
            blok = SY.blok_salin(px, sl, tp, tp, "MARKET", t, sym=p["sym"], arah=p["arah"], sebagian=True,
                                 catatan_tp="" if tp else "sisa 80% ikut SL berjalan")
            atur = "📲 TPawal: tutup 20% lalu SL ke entry. Sisa 80% ikut aturan jalur. Belum aman di jam ke-30: tutup."
        out.append(f"🐙 <b>SINYAL GURITA MODAL: {p['sym']} {p['arah']} MARKET</b>  ·  🟦 KELAS UTAMA\n"
                   f"⭐ {konf} teknik searah ({k}" + (f", {kawan}" if kawan else "") + f")  ·  BTC 4J {bj:+.1f}% dari EMA 50, searah\n"
                   + blok + "\n" + atur
                   + f"\n💼 Buku gurita {m['saldo']:.2f} USDT. Risiko {rp:.3g}% = <b>{usd:.2f} USDT</b> kalau SL kena (SL {sl_pct:.1f}% dari harga)"
                   + (f" ({rcat})" if rcat else "")
                   + f". Nilai posisi {nilai:.0f} USDT, leverage {lev}x, margin {nilai / lev:.1f} USDT"
                   + ("  ·  di bawah order minimal 5 USDT, lewati" if nilai < 5 else "")
                   + f"\n🎯 Posisi gurita {len(m['buka'])}/{MODAL_SLOT}, satu koin satu posisi.")
    return out


def modal_teks(d):
    m = _modal(d); r = [x["R"] for x in m["tutup"]]
    wr = sum(1 for x in r if x > 0) / len(r) * 100 if r else 0
    rows = [f"\n💰 <b>Gurita modal</b>: saldo buku {m['saldo']:.2f} USDT dari {m['awal']:.0f} ({(m['saldo'] / m['awal'] - 1) * 100:+.1f}%), "
            f"drawdown terdalam {m['dd'] * 100:.0f}%. Selesai {len(r)} trade, WR {wr:.0f}%, total {sum(r):+.2f}R. "
            f"Jalan {len(m['buka'])}/{MODAL_SLOT}, risiko {MODAL_RISIKO:g}% saldo per posisi "
            f"(3+ teknik x{MODAL_KALI3:g}, saldo turun lebih dari {MODAL_REM_DD:g}% dari puncak x{MODAL_REM_KALI:g})."]
    for p in m["buka"]:
        rows.append(f"• {p['sym']} {p['arah']} ({p['jalur']}, {p.get('konf', 2)} teknik) risiko {p['usd']:.2f} USDT")
    for a, c in modal_libur(m).items():
        rows.append(f"⏸️ {a} libur: {c} SL searah dalam {MODAL_ARAH_JAM:g} jam terakhir, gurita tidak mengambil {a} baru dulu")
    rows.append("🧪 " + MODAL_UJI)
    return "\n".join(rows)


# ---------- nyawa gurita: lapar, rasa ingin tahu, 5 zat kimia otak, tinta, kamuflase, RNA editing ----------
# Zat kimia (nama dari literatur gurita): DA dopamin (tebakan tepat, TP), OA oktopamin (fokus berburu saat pasar kencang),
# 5-HT serotonin (sabar dan percaya diri saat menang beruntun), ACh asetilkolin (laju belajar vertical lobe),
# GABA + semburan tinta (rasa sakit SL: koin dan arah itu ditutup 72 jam supaya kesalahan tidak diulang).
TINTA_JAM = 72


def _hormon(d):
    h = d.setdefault("hormon", dict(lapar=40.0, ingin_tahu=40.0, DA=30.0, OA=30.0, SER=50.0, ACH=40.0, GABA=10.0, t=time.time(),
                                     makan_t=time.time(), lahir=time.time()))
    return h


def hidup(d, kencang=None):
    """Hormon bergerak tiap jalan: lapar naik tanpa makan, DA dan GABA meluruh, OA ikut kecepatan pasar, 5-HT ikut rapor."""
    h = _hormon(d); now = time.time()
    dt = max(0.0, min(48.0, (now - h.get("t", now)) / 3600)); h["t"] = now
    jam = (now - h.get("makan_t", now)) / 3600
    h["lapar"] = min(100.0, jam / 24 * 100)
    h["DA"] = 20 + (h["DA"] - 20) * 0.5 ** (dt / 12)
    h["GABA"] = 10 + (h["GABA"] - 10) * 0.5 ** (dt / 24)
    if kencang is not None:
        h["OA"] = h["OA"] + (min(100.0, 20 + 400 * kencang) - h["OA"]) * min(1.0, 0.5 * dt + 0.2)
    rp = rapor(d)
    h["SER"] = h["SER"] + ((30 + 50 * rp["wr"] + (10 if rp["tot"] > 0 else 0)) - h["SER"]) * min(1.0, 0.1 * dt + 0.05)
    err = [abs(p["R"] - p.get("pred", 0.0)) for p in d.get("pick", []) if p.get("R") is not None][-20:]
    salah = (sum(err) / len(err)) if err else 0.5
    h["ingin_tahu"] = min(100.0, 0.5 * h["lapar"] + 50 * min(1.0, salah))
    h["ACH"] = min(100.0, 20 + 0.6 * h["ingin_tahu"])
    return h


def suntik(d, p, R):
    """Hasil sinyal gurita: dopamin saat TP, GABA dan semburan tinta saat SL."""
    h = _hormon(d)
    if R > 0.05:
        h["DA"] = min(100.0, h["DA"] + 20 + 15 * min(R, 2)); h["makan_t"] = time.time()
    elif R < -0.05:
        h["GABA"] = min(100.0, h["GABA"] + 30)
        d.setdefault("tinta", {})[f"{p['sym']}:{p['arah']}"] = time.time() + TINTA_JAM * 3600


def tinta_aktif(d, sym, arah):
    return d.get("tinta", {}).get(f"{sym}:{arah}", 0) > time.time()


def mood(d):
    h = _hormon(d)
    if h["GABA"] >= 55 or any(v > time.time() for v in d.get("tinta", {}).values()):
        return "🦑💨 Baru menyemburkan tinta, berburu hati-hati"
    if h["DA"] >= 65:
        return "🤩 Dopamin tinggi, tebakan terakhir tepat"
    if h["OA"] >= 65:
        return "⚡ Oktopamin tinggi, pasar kencang, fokus berburu"
    if h["ingin_tahu"] >= 70:
        return "🔍 Sangat ingin tahu, 8 lengan memindai lebih dalam"
    if h["SER"] >= 65:
        return "😌 Sabar dan percaya diri"
    return "🐙 Tenang, mengamati dasar laut pasar"


def kamuflase(btc_close):
    """Warna kulit dari efficiency ratio 20 candle 4J BTC: >= 0.3 tren (pemburu tren), di bawahnya menyamping (penembak pantulan)."""
    try:
        import numpy as np
        c = np.asarray(btc_close, float)[-21:]
        er = abs(c[-1] - c[0]) / max(np.abs(np.diff(c)).sum(), 1e-12)
        naik = c[-1] > c[0]
    except Exception:
        return "samping", "🟫 belum terbaca", 0.0
    if er >= 0.3:
        return "tren", ("🟥 merah pemburu tren naik" if naik else "🟦 biru pemburu tren turun"), er
    return "samping", "🟩 hijau penembak pantulan (pasar menyamping)", er


def rna_editing_adaptasi(d, bawaan=None):
    """Edit saraf lengan di VPS: bobot tiap lengan x rezim x arah dari 20 hasil live terakhir lengan itu.
    Rata R live negatif -> lengan dibisukan di rezim itu, positif -> diaktifkan. Kurang dari 20 hasil -> pakai bobot bawaan."""
    bw = dict(bawaan or d.get("lengan_bawaan", {}))
    hasil = {}
    for p in d.get("pick", []):
        if p.get("R") is None:
            continue
        for li in p.get("lengan", []):
            hasil.setdefault(f"{li}|{p.get('rezim')}|{1 if p['arah'] == 'LONG' else -1}", []).append(p["R"])
    edit = {}
    for k, v in bw.items():
        x = hasil.get(k, [])[-20:]
        edit[k] = (1 if sum(x) > 0 else 0) if len(x) >= 20 else v
    for k, x in hasil.items():
        if k not in edit and len(x) >= 20:
            edit[k] = 1 if sum(x[-20:]) > 0 else 0
    d["lengan_edit"] = edit
    return edit


# ---------- 8 lengan otonom dan peta masa depan (riset/upgrade/run_v159_gurita9.py, QC 52) ----------
# Lengan: 1 pantul S/R, 2 aliran taker (Binance, kalau terjangkau), 3 pengikut sektor, 4 sapuan likuiditas, 5 squeeze lepas,
# 6 beta BTC, 7 mean reversion, 8 penjaga bahaya (lawan pompa/buang 24 jam). Bobot lengan per rezim dari latih 2023-2024
# (gurita_lengan.json), diedit live oleh rna_editing_adaptasi. Peta masa depan: 30 ribu potongan memori 2023-2024 (gurita_peta.npz),
# 50 tetangga terdekat -> peluang TP1 (1 ATR) sebelum SL dalam 3 candle 4J dan rata hasil analog.
# Uji: aturan terpilih di latih 2024 (lengan >= 1, peta R > 0.1, peluang TP1 cepat >= 0.5) uji 2025-2026 -20.9R lot 1, 476 sinyal.
# Peluang TP1 cepat terkalibrasi (kuintil 30% -> 45% nyata), rata R tidak. Sinyal 8 lengan masuk UJI KERTAS sampai rapor lulus.
F_PETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gurita_peta.npz")
F_LENGAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gurita_lengan.json")
NAMA_LENGAN = {"l1": "🎯 pantul S/R", "l2": "💸 aliran bandar", "l3": "🧩 pengikut sektor", "l4": "🧹 sapuan likuiditas",
               "l5": "🗜️ squeeze", "l6": "₿ beta BTC", "l7": "↩️ mean reversion", "l8": "🛡️ penjaga bahaya"}
PETA_R, PETA_C, LENGAN_MIN, MAKS_4J = 0.1, 0.5, 1, 3
_PETA = {}


def _peta():
    if not _PETA:
        import numpy as np
        z = np.load(F_PETA)
        _PETA.update({k: z[k] for k in z.files})
    return _PETA


def peta_masa_depan(x):
    """x = vektor 15 fitur (urutan FIT). Return dict peluang TP1 cepat dan rata R analog untuk LONG dan SHORT."""
    import numpy as np
    z = _peta()
    xs = (np.nan_to_num(np.asarray(x, float)) - z["mu"]) / z["sd"]
    Xs = (z["X"] - z["mu"]) / z["sd"]
    nb = np.argpartition(((Xs - xs) ** 2).sum(1), 50)[:50]
    return dict(pRL=float(z["RL"][nb].mean()), pRS=float(z["RS"][nb].mean()), pCL=float(z["CL"][nb].mean()), pCS=float(z["CS"][nb].mean()))


def _atr(h, l, c, n=14):
    import numpy as np
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    o = np.empty(len(tr)); o[0] = tr[0]
    for i in range(1, len(tr)):
        o[i] = o[i - 1] + (tr[i] - o[i - 1]) / n
    return o


def _sr(h, l, c, k=3, lb=150):
    n = len(c); i = n - 1; s, r = -1e18, 1e18
    for j in range(max(k, i - lb + 1), i - k + 1):
        ph = h[j] == max(h[j - k:j + k + 1]); pl = l[j] == min(l[j - k:j + k + 1])
        for lv, ok in ((l[j], pl), (h[j], ph)):
            if ok and lv < c[i] and lv > s:
                s = lv
            if ok and lv > c[i] and lv < r:
                r = lv
    return (s if s > -1e18 else None), (r if r < 1e18 else None)


def _taker_binance(sym):
    """Rasio taker buy candle 4J terakhir yang tutup dari Binance futures. None kalau tidak terjangkau."""
    try:
        import requests
        js = requests.get("https://fapi.binance.com/fapi/v1/klines", params=dict(symbol=sym, interval="4h", limit=3), timeout=4).json()
        k = js[-2]
        return float(k[9]) / max(float(k[5]), 1e-12)
    except Exception:
        return None


def baca_lengan(sym, df, btc_r, taker=None):
    """Suara 8 lengan dan 15 fitur di candle 4J terakhir yang tutup. Rumus sama dengan riset run_v159_gurita9.fitur_koin."""
    import numpy as np, pandas as pd
    h, l, c, o, v = (df[x].values.astype(float) for x in ("high", "low", "close", "open", "volume"))
    if len(c) < 200:
        return None
    a = _atr(h, l, c); A = a[-1]
    sup, res = _sr(h, l, c)
    ds = (c[-1] - sup) / A if sup else np.nan; dr = (res - c[-1]) / A if res else np.nan
    vr = v[-1] / max(v[-21:-1].mean(), 1e-12)
    sma = c[-20:].mean(); sd = c[-20:].std(ddof=1)
    bws = pd.Series(c).rolling(20).std().values * 4 / np.maximum(pd.Series(c).rolling(20).mean().values, 1e-12)
    q10 = np.nanquantile(bws[-121:-1], 0.1); sq = bws[-2] <= q10
    lo20, hi20 = l[-21:-1].min(), h[-21:-1].max()
    rc = np.diff(np.log(c))[-60:]; rb = np.asarray(btc_r[-60:], float)
    cor = float(np.corrcoef(rc, rb)[0, 1]) if len(rb) == 60 and np.std(rb) > 0 else 0.0
    z_ = (c[-1] - sma) / A
    r6 = c[-1] / c[-7] - 1
    er = abs(c[-1] - c[-21]) / max(np.abs(np.diff(c[-21:])).sum(), 1e-12)
    tr = taker
    sv = dict(l1=1 if (ds == ds and ds <= 0.5) else (-1 if (dr == dr and dr <= 0.5) else 0),
              l2=0 if tr is None else (1 if (tr >= 0.55 and vr >= 1.5) else (-1 if (tr <= 0.45 and vr >= 1.5) else 0)),
              l3=0,
              l4=1 if (l[-1] < lo20 and c[-1] > lo20) else (-1 if (h[-1] > hi20 and c[-1] < hi20) else 0),
              l5=1 if (sq and c[-1] > sma + 2 * sd) else (-1 if (sq and c[-1] < sma - 2 * sd) else 0),
              l6=1 if (cor > 0.6 and rb[-1] > 0.01 and rc[-1] < rb[-1] * 0.3) else (-1 if (cor > 0.6 and rb[-1] < -0.01 and rc[-1] > rb[-1] * 0.3) else 0),
              l7=1 if z_ <= -2.5 else (-1 if z_ >= 2.5 else 0),
              l8=-1 if r6 >= 0.12 else (1 if r6 <= -0.12 else 0))
    e50 = pd.Series(c).ewm(span=50, adjust=False).mean().values[-1]
    x = [(c[-1] - c[-1 - k]) / A for k in range(1, 7)] + [z_, bws[-1] / max(q10, 1e-12), np.log(max(vr, 1e-3)),
                                                          0.0 if tr is None else tr - 0.5, min(max(np.nan_to_num(ds, nan=5), 0), 5),
                                                          min(max(np.nan_to_num(dr, nan=5), 0), 5), float(rb[-1]), (c[-1] - e50) / A, er]
    return dict(sym=sym, suara=sv, x=x, er=er, rezim="tren" if er >= 0.3 else "samping", atr=A, close=c[-1], ret=c[-1] / o[-1] - 1)


def delapan_lengan(d, maks_koin=183):
    """Tiap candle 4J tutup: 8 lengan memindai, otak pusat menimbang, peta masa depan diramal. Return (sinyal baru, peta)."""
    import numpy as np
    import bybit_fetch as B
    from concurrent.futures import ThreadPoolExecutor
    tk = B.get_tickers()
    koin = sorted((s for s in tk if s.endswith("USDT") and tk[s]["spread"] < 0.2 and tk[s]["turnover"] >= 3e6), key=lambda s: -tk[s]["turnover"])[:maks_koin]
    ms = int(time.time() * 1000)

    def ambil(s):
        try:
            df = B._raw(s, "240", 300)
            return s, df[df.index + 14400000 <= ms]
        except Exception:
            return s, None
    with ThreadPoolExecutor(8) as ex:
        dfs = dict(ex.map(ambil, list(dict.fromkeys(["BTCUSDT"] + koin))))
    bt = dfs.get("BTCUSDT")
    if bt is None or len(bt) < 200:
        return [], []
    btc_r = np.diff(np.log(bt["close"].values.astype(float)))
    rz, warna, er_b = kamuflase(bt["close"].values.astype(float))
    d["kulit"] = dict(rezim=rz, warna=warna, er=round(er_b, 3))
    pakai_taker = _taker_binance("BTCUSDT") is not None
    baca = {}
    for s in koin:
        df = dfs.get(s)
        if df is None or len(df) < 200 or int(df.index[-1]) != int(bt.index[-1]):
            continue
        r = baca_lengan(s, df, btc_r, _taker_binance(s) if pakai_taker else None)
        if r:
            baca[s] = r
    # lengan 3: pengikut sektor (pemimpin sektor >= 8% di candle ini, koin diam < 1.5%)
    try:
        import qse_sektor as SK
        grup = {}
        for s, r in baca.items():
            if s in SK.SEKTOR:
                grup.setdefault(SK.SEKTOR[s], []).append(r)
        for rs in grup.values():
            mx = max(x["ret"] for x in rs); mn = min(x["ret"] for x in rs)
            for x in rs:
                if abs(x["ret"]) < 0.015:
                    x["suara"]["l3"] = 1 if mx >= 0.08 else (-1 if mn <= -0.08 else 0)
    except Exception as ex:
        print("[WARN] gurita lengan sektor", ex)
    bobot = dict(json.load(open(F_LENGAN))) if os.path.exists(F_LENGAN) else {}
    d["lengan_bawaan"] = bobot
    bobot = rna_editing_adaptasi(d, bobot)
    kencang = float(np.mean([abs(r["ret"]) > 0.03 for r in baca.values()])) if baca else 0.0
    hidup(d, kencang)
    sinyal, peta = [], []
    for s, r in baca.items():
        kL = sum(1 for li, v in r["suara"].items() if v == 1 and bobot.get(f"{li}|{r['rezim']}|1"))
        kS = sum(1 for li, v in r["suara"].items() if v == -1 and bobot.get(f"{li}|{r['rezim']}|-1"))
        pm = peta_masa_depan(r["x"])
        r.update(kL=kL, kS=kS, **pm)
        peta.append(r)
        for arah, k1, k2, pr, pc in (("LONG", kL, kS, pm["pRL"], pm["pCL"]), ("SHORT", kS, kL, pm["pRS"], pm["pCS"])):
            if k1 >= LENGAN_MIN and k2 == 0 and pr > PETA_R and pc >= PETA_C and not tinta_aktif(d, s, arah):
                sinyal.append((pr, s, arah, r))
    sinyal.sort(key=lambda z: -z[0])
    peta.sort(key=lambda r: -max(r["pCL"], r["pCS"]))
    d["peta"] = [dict(sym=r["sym"], close=r["close"], atr=r["atr"], rezim=r["rezim"], pCL=round(r["pCL"], 3), pCS=round(r["pCS"], 3),
                      pRL=round(r["pRL"], 3), pRS=round(r["pRS"], 3), suara=r["suara"], kL=r["kL"], kS=r["kS"]) for r in peta[:8]]
    d["peta_t"] = time.time()
    d["lengan_aktif"] = {li: sum(1 for r in baca.values() if r["suara"][li]) for li in NAMA_LENGAN}
    return sinyal[:MAKS_4J], peta


def kartu_8lengan(d, pr, s, arah, r):
    import qse_saya as SY
    rp = rapor(d)
    L = arah == "LONG"; dd = 1 if L else -1; e = r["close"]; A = r["atr"]
    sl, tp1, tp2 = e - dd * 1.5 * A, e + dd * A, e + dd * 2 * A
    lot = 0.25 if rp["aktif"] else 0.1
    lg = [li for li, v in r["suara"].items() if v == dd]
    p = dict(key=f"8L|{s}|{int(time.time())}", jalur="8lengan", sym=s, arah=arah, entry=e, sl=sl, tp1=tp1, tp=tp2, t=time.time(),
             hari=time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600)), combo=0, lengan=lg, rezim=r["rezim"],
             pred=round(pr, 3), tahan=48, aktif=rp["aktif"], R=None)
    d.setdefault("pick", []).append(p)
    pc = r["pCL"] if L else r["pCS"]
    status = "✅ AKTIF" if rp["aktif"] else f"🧪 UJI KERTAS (rapor {rp['n']}/{RAPOR_N}, WR {rp['wr'] * 100:.0f}%)"
    try:
        import qse_modal as MD
        lotb = MD.baris_lot(e, sl, kelas="UTAMA" if rp["aktif"] else "RINGAN")
    except Exception:
        lotb = ""
    return (f"🐙 <b>SINYAL GURITA 8 LENGAN: {s} {arah} MARKET</b>  ·  {status}\n"
            f"🦑 Lengan setuju: {', '.join(NAMA_LENGAN[x] for x in lg)}  ·  rezim {r['rezim']}\n"
            f"🔮 Peta 3 candle 4J ke depan (analog 50 potongan memori): peluang TP1 sebelum SL {pc * 100:.0f}%, rata hasil analog {pr:+.2f}R\n"
            + SY.blok_salin(e, sl, tp1, tp2, "MARKET", SY.tick_of(None, e), sym=s, arah=arah)
            + f"\n📲 SL 1.5 ATR, TP1 1 ATR tutup 50% lalu SL ke entry, TP2 2 ATR, maks 48 jam. {'🟦 KELAS UTAMA' if rp['aktif'] else '🟨 KELAS RINGAN'}."
            + ("\n" + lotb if lotb else ""))


# ---------- hidup di listener ----------
def jalankan():
    """Tiap 15 menit: menonton hasil jalur di ledger (belajar), tidur sekali sehari. Return pesan (biasanya kosong)."""
    with _KUNCI:
        o, d = otak()
        try:
            import qse_catat as CT
            cl = [dict(c, jalur=k) for k, _, c in CT._tutup_terbukti()]          # hasil 8 jalur terbukti (Jalur Live)
        except Exception:
            cl = []
        batas = d.get("tonton_t", time.time() - 3600)
        maks = batas
        for c in cl:
            s = c.get("selesai") or 0
            if s <= batas or c.get("R") is None:
                continue
            jl = c.get("jalur", "?")
            o.belajar(fitur(jl, c.get("sym", "?"), c.get("arah", "?")), float(c["R"]))
            try:
                import qse_mb as MBJ
                MBJ.belajar_jalur(jl, c.get("sym", "?"), c.get("arah", "?"), float(c["R"]))
            except Exception as ex:
                print("[WARN] MB jalur belajar", ex)
            o.lengan_catat(jl, float(c["R"]))
            maks = max(maks, s)
        d["tonton_t"] = maks
        hari = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600))
        if d.get("tidur") != hari and time.gmtime(time.time() + 7 * 3600).tm_hour >= 3:
            o.tidur(); d["tidur"] = hari
        pesan = []
        try:
            kl = _kelola(d)
            pesan += kl if siar_lama() else []
        except Exception as ex:
            print("[WARN] gurita kelola", ex)
        try:
            lama = buru(o, d)          # QC 79: sinyal cincin saraf tetap dicatat (trade kertas), dikirim hanya bila QSE_GURITA_LAMA=1
            pesan += lama if siar_lama() else []
        except Exception as ex:
            print("[WARN] gurita buru", ex)
        try:
            pesan += modal_kelola(d)
            pesan += modal_buru(d)
        except Exception as ex:
            print("[WARN] gurita modal", ex)
        try:
            c4 = int(time.time() // 14400)
            if d.get("c4") != c4 and time.time() % 14400 >= 300:          # 5 menit sesudah candle 4J tutup
                d["c4"] = c4
                sig, _ = delapan_lengan(d)
                for pr, s, arah, r in sig:
                    kt = kartu_8lengan(d, pr, s, arah, r)
                    if siar_lama():
                        pesan.append(kt)
                if not sig:
                    _hormon(d)
        except Exception as ex:
            print("[WARN] gurita 8 lengan", ex)
        hidup(d)
        simpan(o, d)
        return pesan


def nilai_sinyal(sinyal):
    """sinyal = list dict(jalur, sym, arah). Return list dict dengan ikut, nilai, alasan (cincin saraf dihitung di sini)."""
    o, _ = otak()
    rz = _rezim()
    out = []
    for s in sinyal:
        kawan = sum(1 for x in sinyal if x is not s and x["sym"] == s["sym"] and x["arah"] == s["arah"] and x["jalur"] != s["jalur"])
        ikut, v, why = o.putuskan(s["jalur"], s["sym"], s["arah"], rz, kawan)
        out.append(dict(s, ikut=ikut, nilai=v, alasan=why))
    return out


def baris_kartu(jalur, sym, arah):
    """Satu baris di kartu sinyal jalur: ingatan gurita. Saran ikut/lewati hanya tampil kalau SARING menyala."""
    try:
        r = nilai_sinyal([dict(jalur=jalur, sym=sym, arah=arah)])[0]
        o, _ = otak()
        x = o.lengan.get(jalur, [])
    except Exception:
        return ""
    lg = f"lengan {jalur} {len(x)} hasil terakhir rata {sum(x) / len(x):+.2f}R" if x else f"lengan {jalur} belum punya catatan"
    if SARING:
        return f"🐙 Gurita: {'IKUT' if r['ikut'] else 'LEWATI'} (nilai {r['nilai']:+.3f}, {lg})"
    return f"🐙 Gurita: ingatan pola ini {r['nilai']:+.3f}, {lg}" + (f", {r['alasan']}" if r["alasan"] else "")


def _bar(x):
    n = int(round(max(0, min(100, x)) / 10))
    return "▰" * n + "▱" * (10 - n)


def teks():
    import qse_saya as SY
    o, d = otak()
    h = hidup(d)
    kl = d.get("kulit") or {}
    umur = (time.time() - h.get("lahir", time.time())) / 86400
    rp = rapor(d)
    rows = ["🐙 <b>QSE v150 | OTAK GURITA</b>",
            f"❤️ Hidup {umur:.1f} hari  ·  🧠 <b>Mood</b>: {mood(d)}",
            f"🎨 Kamuflase: {kl.get('warna', 'belum terbaca (menunggu candle 4J tutup)')}",
            "",
            f"🍽️ Lapar      {_bar(h['lapar'])} {h['lapar']:.0f}%",
            f"🔍 Ingin tahu {_bar(h['ingin_tahu'])} {h['ingin_tahu']:.0f}  (naik kalau tebakan peta meleset)",
            f"💉 DA         {_bar(h['DA'])} {h['DA']:.0f}  dopamin, tebakan tepat",
            f"⚡ OA         {_bar(h['OA'])} {h['OA']:.0f}  oktopamin, fokus saat pasar kencang",
            f"😌 5-HT       {_bar(h['SER'])} {h['SER']:.0f}  sabar dan percaya diri",
            f"👁️ ACh        {_bar(h['ACH'])} {h['ACH']:.0f}  laju belajar vertical lobe",
            f"🩹 GABA       {_bar(h['GABA'])} {h['GABA']:.0f}  rasa sakit SL"
            + (f"  ·  🦑💨 tinta menutup {', '.join(k for k, v in d.get('tinta', {}).items() if v > time.time())}"
               if any(v > time.time() for v in d.get("tinta", {}).values()) else ""),
            "", "🦑 <b>8 lengan</b> (jumlah koin yang dicengkeram di candle 4J terakhir, status RNA editing per rezim)"]
    akt = d.get("lengan_aktif", {}); ed = d.get("lengan_edit", {})
    for li, nm in NAMA_LENGAN.items():
        on = [k.split("|", 1)[1] for k, v in ed.items() if k.startswith(li + "|") and v]
        rows.append(f"• Lengan {li[1]} {nm}: {akt.get(li, 0)} koin  ·  " + (f"aktif di {', '.join(on)}" if on else "dibisukan (rugi di latih atau live)"))
    pk = [p for p in d.get("pick", []) if p.get("R") is None]
    rows.append(f"\n🍽️ <b>Sinyal gurita</b>: " + ("✅ AKTIF, kelas utama" if rp["aktif"] else "🧪 UJI KERTAS, kelas ringan")
                + f". Rapor {rp['n']} terakhir WR {rp['wr'] * 100:.0f}%, total {rp['tot']:+.2f}R. Aktif kalau {RAPOR_N} sinyal WR >= "
                f"{RAPOR_WR * 100:.0f}% dan total positif. Jalan sekarang {len(pk)}.")
    rows.append(modal_teks(d))
    pt = d.get("peta") or []
    if pt:
        rows.append(f"\n🔮 <b>Peta masa depan 3 candle 4J</b> (diperbarui {time.strftime('%H:%M', time.gmtime(d.get('peta_t', 0) + 7 * 3600))} WIB). "
                    "Peluang TP1 1 ATR sebelum SL 1.5 ATR dalam 3 candle, dari 50 potongan sejarah paling mirip. Uji: peluang ini "
                    "terkalibrasi (prediksi 30% -> nyata 30%, 45% -> 45%), tapi belum membuat sinyal untung (QC 52).")
        for r in pt[:5]:
            L = r["pCL"] >= r["pCS"]; dd = 1 if L else -1; e, A = r["close"], r["atr"]
            rows.append(f"• <b>{r['sym']} {'LONG' if L else 'SHORT'}</b> peluang {max(r['pCL'], r['pCS']) * 100:.0f}%, analog "
                        f"{(r['pRL'] if L else r['pRS']):+.2f}R, lengan {r['kL'] if L else r['kS']}, rezim {r['rezim']}\n"
                        + SY.blok_salin(e, e - dd * 1.5 * A, e + dd * A, e + dd * 2 * A, "MARKET", SY.tick_of(None, e), sym=r["sym"],
                                        arah="LONG" if L else "SHORT"))
    rows.append("")
    for jl, x in sorted(o.lengan.items()):
        m = sum(x) / len(x) if x else 0
        rows.append(f"📒 Jalur {jl}: {len(x)} hasil terakhir rata {m:+.2f}R (ingatan vertical lobe, menonton)")
    if PARAM_UJI:
        rows.append("🧪 " + PARAM_UJI)
    return "\n".join(rows)
