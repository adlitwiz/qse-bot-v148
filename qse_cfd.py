"""QC 92 📊 CFD HARIAN (Bybit TradFi). Jalur lambat terpisah: kartu, buku, dan rapor sendiri, tidak memakai slot sinyal 4J.

Riset riset/cfd (run_cfd1.py, run_cfd_harian.py, run_porto.py, hasil_cfd.txt). Diuji di 11 instrumen CFD, sekitar 2.000 varian, biaya CFD
Bybit (komisi + spread + swap, dibuat lebih mahal dari aslinya). Scalping dan intraday CFD semua gagal. Yang lolos hanya 4 aturan harian:
  EMAS (XAUUSD) dan PERAK (XAGUSD): candle harian tutup di atas tertinggi 20 hari dan di atas EMA200 -> BUY. SL 2 ATR(14) harian,
     SL berjalan = harga tertinggi sesudah masuk dikurangi 3 ATR. Tidak ada TP, keluar saat SL berjalan kena.
  NASDAQ 100 (US100) dan S&P 500 (US500): harga di atas SMA200 dan RSI(2) di bawah 5 -> BUY. SL 2 ATR. Jual saat candle harian
     tutup di atas SMA5, paling lama 10 hari.
Gabungan 4 aturan: latih 2005-2018 PF 2.02 (270 trade), uji 2019-2026 PF 2.06 (162 trade), 12 bulan PF 4.21, 6 bulan PF 1.97.
16 dari 22 tahun untung, rugi terdalam uji 7.4R. Sekitar 20 trade per tahun.

Data harian diambil dari Yahoo Finance (kontrak futures GC=F, SI=F, NQ=F, ES=F). Harga futures sedikit beda dengan harga CFD,
jadi kartu memberi SL sebagai JARAK dari harga masuk Anda, dan SL berjalan sebagai besar geseran. Pemeriksaan sesudah candle harian
tutup (17:00 New York, sekitar 05:00 atau 06:00 WIB). Saklar QSE_CFD=0 mati.

QC 96 (13 Nov 2026): analisa karakter pasar 24 instrumen 2000-2026 (riset/cfd/analisa.py, hasil_analisa.txt). Indeks saham cenderung
BALIK ARAH jangka pendek (variance ratio < 1, sesudah turun tajam 5 hari berikutnya naik di tiga era), ikut tren tidak jalan.
Efek forex di data harian Yahoo terbukti cacat data (hilang saat candle dibangun dari data 1 jam), forex dicoret.
888 varian teknik x 14 instrumen (riset/cfd/teknik.py, run_teknik.py, pilih_teknik.py, porto2.py). Dipilih di latih 2000-2014:
  DIP: harga di atas SMA200 dan RSI(2) di bawah 5 -> BUY di close. SL 2 ATR. Jual saat RSI(2) di atas 70, paling lama 10 hari.
  TOM: hari kerja terakhir bulan, harga di atas SMA200 -> BUY di close. SL 2 ATR. Jual sesudah 3 hari dagang.
  8 indeks (US500, US100, US30, US2000, DAX, Nikkei, FTSE, Hang Seng), data indeks kas Yahoo, biaya CFD + swap 0.02%/malam:
  gabungan latih PF 1.55 (1219 trade), uji 2015-2026 PF 1.41 (1218), 12 bulan PF 2.66, 6 bulan PF 3.20, 20 dari 27 tahun untung,
  sekitar 90 trade per tahun. Aturan RSI2 lama di futures NQ=F dan ES=F diganti DIP di indeks kas."""
import json
import os
import time

STATE_DIR = os.environ.get("QSE_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"))
PATH = os.path.join(STATE_DIR, "cfd.json")
INST = [  # kode, simbol Yahoo, nama, simbol Bybit, jenis aturan
    ("XAU", "GC=F", "EMAS", "XAUUSD.s", "donch"),
    ("XAG", "SI=F", "PERAK", "XAGUSD.s", "donch"),
]
INDEKS = [("US500", "^GSPC", "S&amp;P 500", "SP500.s"), ("US100", "^NDX", "NASDAQ 100", "NAS100.s"),
          ("US30", "^DJI", "DOW JONES", "DJ30.s"), ("US2000", "^RUT", "RUSSELL 2000", "US2000.s"),
          ("DAX", "^GDAXI", "DAX JERMAN", "GER40.s"), ("NIKKEI", "^N225", "NIKKEI", "Nikkei225.s"),
          ("FTSE", "^FTSE", "FTSE INGGRIS", "UK100.s"), ("HSI", "^HSI", "HANG SENG", "HK50.s")]
# QC 99: AKHIR BULAN saja untuk 9 indeks tambahan (DIP tidak lolos latih di kelompok ini, PF 1.08). EU50 dibuang (latih PF 0.75).
INDEKS_TOM = [("FRA40", "^FCHI", "CAC 40 PRANCIS", "FRA40.s"), ("ES35", "^IBEX", "IBEX 35 SPANYOL", "ES35.s"),
              ("BVSPX", "^BVSP", "BOVESPA BRASIL", "BVSPX.s"), ("SPI200", "^AXJO", "ASX 200 AUSTRALIA", "SPI200.s"),
              ("TWINDEX", "^TWII", "TAIWAN", "TWINDEX.s"), ("SWI20", "^SSMI", "SWISS 20", "SWI20.s"),
              ("NETH25", "^AEX", "AEX BELANDA", "NETH25.s"), ("CHINAH", "^HSCE", "HK CHINA H-SHARES", "CHINAH.s"),
              ("SGP20", "^STI", "SINGAPURA", "SGP20.s")]
TOM_RISIKO = 0.25          # akhir bulan: sampai 17 indeks sekaligus. Risiko 1x: bulan terburuk -18.4R. 0.25x: -4.6R, PF sama
for _k, _y, _n, _b in INDEKS:
    INST += [(_k + ".DIP", _y, _n, _b, "dip"), (_k + ".TOM", _y, _n, _b, "tom")]
for _k, _y, _n, _b in INDEKS_TOM:
    INST.append((_k + ".TOM", _y, _n, _b, "tom"))
# QC 97: saham CFD yang terlihat di aplikasi Bybit user. DIP RSI2 < 5 di atas SMA200, SL 3 ATR (dipilih di latih), keluar RSI2 > 70.
SAHAM = [("TSLA", "TSLA", "TESLA", "TSLA.s"), ("NVDA", "NVDA", "NVIDIA", "NVIDIA.s"), ("MSTR", "MSTR", "STRATEGY", "MSTR.s"),
         ("AAPL", "AAPL", "APPLE", "AAPL.s"), ("GOOG", "GOOGL", "ALPHABET", "GOOG.s"), ("META", "META", "META", "META.s"),
         ("AMZN", "AMZN", "AMAZON", "AMAZON.s"), ("MSFT", "MSFT", "MICROSOFT", "MSFT.s"), ("NFLX", "NFLX", "NETFLIX", "NFLX.s")]
for _k, _y, _n, _b in SAHAM:
    INST.append((_k + ".DIP", _y, _n, _b, "dipsaham"))
DIP_SL_SAHAM = 3.0
KONTRAK = {"XAUUSD.s": 100}          # unit per 1 lot yang sudah pasti (emas 100 ons). Lainnya: isi lot sampai kolom Value sesuai kartu
DIP_RSI, DIP_SL, DIP_TAHAN, DIP_KELUAR = 5, 2.0, 10, 70
TOM_SL, TOM_TAHAN, TOM_TP = 2.0, 3, 9.0
DONCH_N, DONCH_SL, DONCH_TRAIL = 20, 2.0, 3.0
RSI_BATAS, RSI_SL, RSI_TAHAN = 5, 2.0, 10
JEDA_COBA = 3600
UJI = ("Uji data harian, biaya CFD Bybit. Emas/Perak breakout: latih PF 2.02, uji PF 2.06. Indeks DIP + TOM 8 indeks 2000-2026: "
       "latih PF 1.55, uji 2015-2026 PF 1.41, 12 bulan PF 2.66, 6 bulan PF 3.20, sekitar 90 trade per tahun.")


def hidup():
    return os.environ.get("QSE_CFD", "1") != "0"


# ---------- indikator (sama dengan riset/cfd/mesin.py) ----------
def atr_arr(H, L, C, n=14):
    out = []
    for i in range(len(C)):
        pc = C[i - 1] if i else C[0]
        tr = max(H[i] - L[i], abs(H[i] - pc), abs(L[i] - pc))
        out.append(tr if i == 0 else (out[-1] * (n - 1) + tr) / n)
    return out


def ema(x, n):
    k = 2 / (n + 1)
    out = [x[0]]
    for v in x[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def sma(x, n):
    out, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        out.append(s / min(i + 1, n))
    return out


def rsi2(C):
    up = [0.0] + [max(C[i] - C[i - 1], 0.0) for i in range(1, len(C))]
    dn = [0.0] + [max(C[i - 1] - C[i], 0.0) for i in range(1, len(C))]
    au, ad = ema(up, 3), ema(dn, 3)
    return [100 - 100 / (1 + a / max(b, 1e-12)) for a, b in zip(au, ad)]


# ---------- aturan per bar (inti, dipakai live dan tes paritas) ----------
def indikator(O, H, L, C):
    """Semua indikator kausal: nilai di indeks j hanya memakai candle <= j."""
    return dict(A=atr_arr(H, L, C), e200=ema(C, 200), s200=sma(C, 200), s5=sma(C, 5), r2=rsi2(C))


def akhir_kerja(tgl):
    """True kalau tanggal ini hari kerja (Senin-Jumat) terakhir di bulannya. Bisa dihitung live tanpa melihat hari esok."""
    import calendar
    from datetime import date
    d = date.fromisoformat(tgl)
    last = calendar.monthrange(d.year, d.month)[1]
    return not any(calendar.weekday(d.year, d.month, x) < 5 for x in range(d.day + 1, last + 1))


def sinyal(jenis, ind, H, C, m):
    """Sinyal BUY di candle m yang sudah tutup. Return dict jarak SL dan trailing, atau None."""
    if m < 200:
        return None
    a = ind["A"][m]
    if jenis in ("dip", "tom", "dipsaham"):
        if m < 210 or not C[m] > ind["s200"][m]:
            return None
        if jenis in ("dip", "dipsaham") and ind["r2"][m] < DIP_RSI:
            return dict(jarak=(DIP_SL_SAHAM if jenis == "dipsaham" else DIP_SL) * a, trail=0.0, atr=a)
        if jenis == "tom" and ind.get("tgl") and akhir_kerja(ind["tgl"][m]):
            return dict(jarak=TOM_SL * a, trail=0.0, atr=a)
        return None
    if jenis == "donch":
        if C[m] > max(H[m - DONCH_N:m]) and C[m] > ind["e200"][m]:
            return dict(jarak=DONCH_SL * a, trail=DONCH_TRAIL * a, atr=a)
    elif C[m] > ind["s200"][m] and ind["r2"][m] < RSI_BATAS:
        return dict(jarak=RSI_SL * a, trail=0.0, atr=a)
    return None


def _hari(t0, t1):
    from datetime import date
    return (date.fromisoformat(t1) - date.fromisoformat(t0)).days


def langkah(pos, jenis, ind, tgl, O, H, L, C, j):
    """Proses candle j (sudah tutup) untuk posisi pos. Urutan sama dengan simulasi uji (riset/cfd/mesin.py sim).
    Return (pos atau None, list kejadian)."""
    if jenis in ("dip", "tom", "dipsaham"):          # QC 96: sudah masuk di close candle sinyal. Urutan riset/cfd/teknik.py sim
        risk = pos["e"] - pos["sl0"]
        if O[j] <= pos["sl"]:
            return None, [("SL", (O[j] - pos["e"]) / risk)]
        if L[j] <= pos["sl"]:
            return None, [("SL", (pos["sl"] - pos["e"]) / risk)]
        if jenis == "tom" and H[j] >= pos["e"] + TOM_TP * risk:
            return None, [("TUTUP", (max(O[j], pos["e"] + TOM_TP * risk) - pos["e"]) / risk)]
        if (jenis in ("dip", "dipsaham") and (ind["r2"][j] > DIP_KELUAR or j - pos["j0"] >= DIP_TAHAN)) or (jenis == "tom" and j - pos["j0"] >= TOM_TAHAN):
            return None, [("TUTUP", (C[j] - pos["e"]) / risk)]
        return pos, []
    if pos.get("e") is None:              # candle masuk: harga masuk = open candle sesudah sinyal, hanya cek SL
        pos.update(e=O[j], sl=O[j] - pos["jarak"], sl0=O[j] - pos["jarak"], j0=j, t0=tgl[j],
                   keluar=bool(jenis == "rsi2" and C[j] > ind["s5"][j]))
        if L[j] <= pos["sl"]:
            return None, [("SL", -1.0)]
        return pos, []
    risk = pos["e"] - pos["sl0"]
    if L[j] <= pos["sl"]:
        return None, [("SL", (pos["sl"] - pos["e"]) / risk)]
    ev = []
    if jenis == "donch":
        baru = max(pos["sl"], H[j] - pos["trail"])
        if baru > pos["sl"]:
            ev.append(("GESER", baru - pos["sl"]))
            pos["sl"] = baru
        if _hari(pos["t0"], tgl[j]) >= 400:
            return None, [("TUTUP", (C[j] - pos["e"]) / risk)]
    else:
        if pos.get("keluar") or C[j] > ind["s5"][j] or j - pos["j0"] >= RSI_TAHAN or _hari(pos["t0"], tgl[j]) >= RSI_TAHAN + 4:
            return None, [("TUTUP", (C[j] - pos["e"]) / risk)]
    return pos, ev


# ---------- data ----------
def ambil(ysym, now=None):
    """Candle harian yang sudah tutup dari Yahoo. Return (tanggal, O, H, L, C) list, candle terakhir yang belum tutup dibuang."""
    import requests
    from datetime import datetime, timezone, timedelta
    now = now or time.time()
    r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{ysym}",
                     params={"interval": "1d", "range": "2y"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    j = r.json()["chart"]["result"][0]
    off = int(j["meta"].get("gmtoffset") or -18000)
    q = j["indicators"]["quote"][0]
    rows = []
    for t, o, h, l, c in zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
        if rows and rows[-1][0] == d:
            rows[-1] = (d, o, h, l, c)
        else:
            rows.append((d, o, h, l, c))
    loc = datetime.fromtimestamp(now + off, timezone.utc)
    hari_ini = loc.strftime("%Y-%m-%d")
    rows = [x for x in rows if x[0] < hari_ini or (x[0] == hari_ini and loc.hour >= 17)]
    if loc.hour >= 18 and rows and rows[-1][0] > hari_ini:
        rows = rows[:-1]
    return [x[0] for x in rows], [x[1] for x in rows], [x[2] for x in rows], [x[3] for x in rows], [x[4] for x in rows]


def ambil_kas(ysym, now=None, jeda_tutup=1200):
    """Candle harian indeks kas yang sudah tutup. Candle hari ini dibuang kalau bursa masih buka atau baru tutup kurang dari 20 menit."""
    import requests
    from datetime import datetime, timezone
    now = now or time.time()
    r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{ysym}",
                     params={"interval": "1d", "range": "2y"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    j = r.json()["chart"]["result"][0]
    m = j["meta"]
    off = int(m.get("gmtoffset") or 0)
    q = j["indicators"]["quote"][0]
    rows = []
    for t, o, h, l, c in zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
        if rows and rows[-1][0] == d:
            rows[-1] = (d, o, h, l, c)
        else:
            rows.append((d, o, h, l, c))
    reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    hari_ini = datetime.fromtimestamp(now + off, timezone.utc).strftime("%Y-%m-%d")
    if rows and rows[-1][0] >= hari_ini and not (reg.get("end") and now >= reg["end"] + jeda_tutup):
        rows = rows[:-1]
    return [x[0] for x in rows], [x[1] for x in rows], [x[2] for x in rows], [x[3] for x in rows], [x[4] for x in rows]


# ---------- buku ----------
def _baca():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {"akhir": {}, "buka": {}, "tutup": [], "coba": 0}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PATH + ".tmp", PATH)


def _fp(x):
    return f"{x:,.2f}"


def _pct_lot(jarak, harga):
    sl = jarak / harga * 100
    return f"Jarak SL {sl:.2f}% dari harga. Atur lot supaya rugi di SL = 1% modal."


def baris_lot(bsym, harga, jarak, faktor=1.0):
    """QC 97: ukuran posisi tiap orang dari menu Modal: rugi di SL = risiko% x modal. Value (USD) = rugi / jarak SL%.
    Lot pasti untuk simbol yang ukuran kontraknya diketahui (emas 100 ons per lot), lainnya isi lot sampai kolom Value sama."""
    sl_pct = jarak / harga
    kon = KONTRAK.get(bsym)
    orang = []
    try:
        import qse_modal as MD
        import qse_saya as SY
        uids = list(MD._baca_profil().keys())
        try:
            pem = str(SY._peng().get("pemilik") or "")
            if pem and pem not in uids:
                uids.insert(0, pem)
        except Exception:
            pass
        for u in uids:
            p = MD.profil(u)
            if p:
                try:
                    nm = SY.nama_pengguna(u)
                except Exception:
                    nm = str(u)
                orang.append((str(nm), p["modal"], p["risiko"]))
    except Exception:
        pass
    if not orang:
        orang = [("contoh modal 100 USD", 100.0, 1.0)]
    rows = []
    for nm, modal, risiko in orang:
        risiko = risiko * faktor
        rugi = modal * risiko / 100
        value = rugi / sl_pct
        if kon:
            lot = int(value / (harga * kon) * 100) / 100
            if lot >= 0.01:
                rows.append(f"   • {nm}: <b>{lot:.2f} lot</b> (Value sekitar {lot * harga * kon:,.0f} USD, rugi kalau SL kena sekitar "
                            f"{lot * kon * jarak:,.2f} USD = {risiko:g}% modal {modal:,.0f})")
            else:
                rows.append(f"   • {nm}: lot minimum 0.01 sudah rugi {0.01 * kon * jarak:,.2f} USD di SL, lebih dari risiko {risiko:g}% "
                            f"({rugi:,.2f} USD). Lewati, atau pakai 0.01 lot kalau siap rugi segitu")
        else:
            rows.append(f"   • {nm}: isi lot sampai kolom <b>Value sekitar {value:,.0f} USD</b> (rugi kalau SL kena sekitar "
                        f"{rugi:,.2f} USD = {risiko:g}% modal {modal:,.0f})")
    return rows


def kartu(jenis, nama, bsym, harga, s):
    """Kartu sinyal CFD dengan langkah demi langkah di aplikasi Bybit (QC 97)."""
    jarak = s["jarak"]
    sl = harga - jarak
    if jenis == "donch":
        judul, alasan = "BREAKOUT", "Close harian menembus tertinggi 20 hari, di atas EMA200 (tren naik)."
        keluar_ = (f"Tanpa TP. SL berjalan 3 ATR ({_fp(s['trail'])} poin) di bawah harga tertinggi. Tiap pagi robot kirim besar geseran SL, "
                   f"Anda ubah SL di posisi.")
    elif jenis == "tom":
        judul, alasan = "AKHIR BULAN", "Hari kerja terakhir bulan dan harga di atas SMA200. Awal bulan cenderung naik."
        keluar_ = "Tanpa TP. Tahan 3 hari dagang, lalu robot kirim perintah tutup."
    else:
        judul = "DIP"
        alasan = "Turun tajam 2 hari (RSI2 di bawah 5) di dalam tren naik (di atas SMA200). Biasanya memantul."
        keluar_ = "Tanpa TP. Robot kirim perintah tutup saat RSI(2) di atas 70, paling lama 10 hari dagang."
    k_atr = "3 ATR" if jenis == "dipsaham" else "2 ATR"
    rows = [f"🟢 <b>{nama} · BUY · {judul}</b>",
            f"{alasan} Harga acuan {_fp(harga)}.",
            "",
            "<b>Langkah di Bybit:</b>",
            f"1. Buka tab <b>CFD</b>, cari <b>{bsym}</b>.",
            "2. Pilih <b>Buy</b>, jenis order <b>Market</b>.",
            "3. Isi <b>Quantity (Lots)</b> sesuai baris ukuran di bawah. Cek kolom Value ikut berubah.",
            f"4. Centang <b>TP/SL</b>. Kosongkan TP. Isi SL = harga Buy Anda dikurangi <b>{_fp(jarak)}</b> ({k_atr}). "
            f"Kalau harga Buy sama dengan acuan, SL di <b>{_fp(sl)}</b>.",
            "5. Tekan <b>Buy</b>. Pastikan Free margin cukup (pindahkan USDT ke akun CFD dulu kalau 0).",
            "",
            (f"<b>Ukuran: 1/4 risiko menu Modal</b> (akhir bulan banyak indeks sekaligus, bulan terburuk uji -4.6R dengan 1/4, "
             f"-18.4R dengan risiko penuh). SL {jarak / harga * 100:.2f}% dari harga:" if jenis == "tom" else
             f"<b>Ukuran (rugi di SL = risiko di menu Modal, SL {jarak / harga * 100:.2f}% dari harga):</b>"),
            *baris_lot(bsym, harga, jarak, TOM_RISIKO if jenis == "tom" else 1.0),
            *([] if KONTRAK.get(bsym) else ["   Kalau lot terkecil (0.01) sudah membuat Value lebih besar dari angka itu, modal terlalu kecil "
                                            "untuk risiko ini: lewati, atau terima rugi lebih besar."]),
            "",
            f"🚪 Keluar: {keluar_}"]
    return "\n".join(rows)


def proses(d, kode, jenis, nama, bsym, tgl, O, H, L, C, kirim_baru=True):
    """Jalankan semua candle baru untuk satu instrumen. Return list baris pesan."""
    pesan = []
    akhir = d["akhir"].get(kode)
    if akhir is None:                      # pertama kali: tidak mengejar sinyal lama
        d["akhir"][kode] = tgl[-1] if tgl else None
        return pesan
    baru = [j for j in range(len(tgl)) if tgl[j] > akhir]
    ind = indikator(O, H, L, C) if baru else None
    if ind is not None:
        ind["tgl"] = tgl
    for j in baru:
        pos = d["buka"].get(kode)
        if pos:
            pos, ev = langkah(pos, jenis, ind, tgl, O, H, L, C, j)
            for k, v in ev:
                if k == "SL":
                    pesan.append(f"🔴 <b>{nama} ({bsym})</b>: SL kena di candle {tgl[j]}, {v:+.2f}R. Posisi selesai "
                                 f"(kalau SL belum terpasang di Bybit, tutup Market sekarang).")
                elif k == "TUTUP":
                    why = {"dip": "RSI(2) sudah di atas 70 atau batas 10 hari", "dipsaham": "RSI(2) sudah di atas 70 atau batas 10 hari",
                           "tom": "sudah 3 hari dagang"}.get(jenis, "batas hari")
                    pesan.append(f"✅ <b>{nama} ({bsym})</b>: syarat keluar terpenuhi ({why}). <b>Tutup posisi sekarang</b>: "
                                 f"tab CFD, Positions, pilih {bsym}, tekan Close (Market). Hasil uji {v:+.2f}R.")
                elif k == "GESER" and j == baru[-1]:
                    pesan.append(f"🟢 <b>{nama} ({bsym})</b>: geser SL naik <b>{_fp(v)}</b> poin dari SL lama "
                                 f"(SL berjalan 3 ATR di bawah harga tertinggi). Caranya: tab CFD, Positions, {bsym}, TP/SL, "
                                 f"ubah SL = SL lama + {_fp(v)}.")
                if k in ("SL", "TUTUP"):
                    d["tutup"].append(dict(kode=kode, tgl=tgl[j], R=round(v, 3)))
                    d["tutup"] = d["tutup"][-3000:]
            if pos:
                d["buka"][kode] = pos
            else:
                d["buka"].pop(kode, None)
        if kode not in d["buka"]:
            s = sinyal(jenis, ind, H, C, j)
            if s:
                d["buka"][kode] = dict(jarak=s["jarak"], trail=s["trail"], e=None, tgl=tgl[j])
                if jenis in ("dip", "tom", "dipsaham"):          # QC 96: masuk di close candle sinyal
                    d["buka"][kode].update(e=C[j], sl=C[j] - s["jarak"], sl0=C[j] - s["jarak"], j0=j, t0=tgl[j])
                if j == len(tgl) - 1 and kirim_baru:
                    pesan.append(kartu(jenis, nama, bsym, C[j], s))
        d["akhir"][kode] = tgl[j]
    return pesan


def cek(now=None, data=None):
    """Dipanggil tiap menit. data = dict kode -> (tgl,O,H,L,C) untuk tes. Return list pesan terkirim."""
    if not hidup():
        return []
    now = now or time.time()
    d = _baca()
    if data is None:
        if now - d.get("coba", 0) < JEDA_COBA:
            return []
    d["coba"] = now
    semua = []
    cache = {}          # QC 96: indeks kas dicek tiap jam (bursa tutup di jam berbeda), satu unduhan per simbol
    for kode, ysym, nama, bsym, jenis in INST:
        try:
            if data is not None:
                tgl, O, H, L, C = data[kode]
            else:
                if ysym not in cache:
                    cache[ysym] = ambil(ysym, now) if ysym.endswith("=F") else ambil_kas(ysym, now)
                tgl, O, H, L, C = cache[ysym]
            if len(tgl) < 210:
                continue
            semua += proses(d, kode, jenis, nama, bsym, tgl, O, H, L, C)
        except Exception as ex:
            print("[WARN] cfd", kode, ex)
    _tulis(d)
    if semua:
        teks = "📊 <b>CFD HARIAN · Bybit TradFi</b>\n\n" + "\n\n".join(semua) + "\n\n🧪 " + UJI
        try:
            import telegram_notify as TG
            TG.send([teks])
        except Exception as ex:
            print("[WARN] cfd kirim", ex)
        return [teks]
    return []


def rapor():
    d = _baca()
    rows = ["📊 <b>CFD HARIAN · Bybit TradFi</b> (buku terpisah)"]
    t = d.get("tutup", [])
    if t:
        r = [x["R"] for x in t]
        g = sum(x for x in r if x > 0); k = -sum(x for x in r if x < 0)
        rows.append(f"Live: {len(r)} trade, WR {sum(1 for x in r if x > 0) / len(r) * 100:.0f}%, PF {g / k if k else 99:.2f}, "
                    f"total {sum(r):+.2f}R")
    else:
        rows.append("Live: belum ada trade selesai.")
    nm = {k: (n, b) for k, _, n, b, _ in INST}
    for k, p in d.get("buka", {}).items():
        n, b = nm.get(k, (k, k))
        if p.get("e") is None:
            rows.append(f"• {n} ({b}): sinyal BUY {p.get('tgl')}, masuk di open berikutnya")
        else:
            rows.append(f"• {n} ({b}){' DIP' if k.endswith('.DIP') else ' AKHIR BULAN' if k.endswith('.TOM') else ''} BUY jalan, "
                        f"SL {p['e'] - p['sl']:+.2f} poin dari harga masuk")
    rows.append("Aturan: Emas dan Perak breakout 20 hari + SL berjalan 3 ATR. 8 indeks: DIP (RSI2 di bawah 5, jual RSI2 di atas 70) "
                "dan AKHIR BULAN (beli hari kerja terakhir, tahan 3 hari), keduanya hanya saat indeks di atas SMA200.")
    rows.append(UJI)
    return "\n".join(rows)
