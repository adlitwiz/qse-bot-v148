"""QSE v148 - PENJAGA BERITA. Tidak mengubah vonis teknikal, hanya menahan atau memperingatkan.
  1. Kalender ekonomi: berita besar USD berdampak tinggi (CPI, FOMC, NFP, PCE, dan sejenisnya), ditambah jadwal resmi
     FOMC, CPI, NFP, ECB, BoJ, BoC sampai Desember 2027 sebagai cadangan, dan kalender 7 hari semua jenis berita
     (bank sentral, earnings saham besar, token unlock) dengan tanda dampak hasil uji (27 Okt 2026)
  2. Pengumuman Bybit: koin yang diumumkan delisting dikeluarkan dari sinyal
  3. Detektor guncangan: BTC bergerak jauh di luar kebiasaan dalam 1 sampai 3 jam
Semua sumber gagal dengan aman: kalau tidak bisa diambil, bot tetap jalan tanpa penjaga itu."""
import datetime as dt
import json
import os
import re
import time
import numpy as np
import requests
from config import STATE_DIR, BYBIT_URL

CACHE = os.path.join(STATE_DIR, "berita.json")
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
JAM = 3600 * 1000
WIB = dt.timezone(dt.timedelta(hours=7))
SEBELUM, SESUDAH = 2 * JAM, 1 * JAM          # jendela jeda berita


def _load():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(c):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CACHE + ".tmp", "w") as f:
        json.dump(c, f)
    os.replace(CACHE + ".tmp", CACHE)


def jam_wib(ms):
    return dt.datetime.fromtimestamp(ms / 1000, WIB).strftime("%d/%m %H:%M WIB")


# ---------------- 1. kalender ekonomi ----------------
# Jadwal resmi bulan-bulan depan (diambil 27 Okt 2026 dari federalreserve.gov, bls.gov, ecb.europa.eu, boj.or.jp,
# bankofcanada.ca), jam UTC. Dipakai cadangan kalau ForexFactory gagal (hanya memuat minggu ini) dan untuk jadwal bulanan.
# Uji gerak BTC 2021 - Okt 2026 di jam rilis dibanding jam yang sama minggu biasa (riset/berita/reaksi_btc.py, candle 1 jam):
#   FOMC 2.6x (1 jam) 2.5x (4 jam), CPI 2.4x 1.5x, NFP 1.7x 1.0x, PCE 1.35x 1.05x, GDP 0.8x 0.6x,
#   ECB 1.2x 0.9x, BoJ 1.0x 0.8x, earnings big tech 1.3-1.7x di jam pertama lalu tidak konsisten.
# Sinyal jalur yang entry 3 jam sebelum sampai 1 jam sesudah berita (aturan keluar sekarang): FOMC 97 trade PF 3.50 lawan 1.83,
# ECB 9 PF 3.09, BoJ 15 PF 2.98, earnings 84 PF 2.91. Tidak lebih jelek, jadi sinyal jalur tidak ditahan berita.
# CPI hanya 9 trade (PF 0.04), terlalu sedikit untuk aturan. Siaga CPI/FOMC untuk posisi jalan tetap (qse_saya.siaga_berita).
JADWAL = {
    "FOMC": ("USD", "FOMC Statement", ["2026-10-28 18:00", "2026-12-09 19:00", "2027-01-27 19:00", "2027-03-17 18:00",
                                       "2027-04-28 18:00", "2027-06-09 18:00", "2027-07-28 18:00", "2027-09-15 18:00",
                                       "2027-10-27 18:00", "2027-12-08 19:00"]),
    "CPI": ("USD", "CPI m/m", ["2026-11-10 13:30", "2026-12-10 13:30", "2027-01-13 13:30", "2027-02-11 13:30", "2027-03-10 13:30",
                               "2027-04-13 12:30", "2027-05-12 12:30", "2027-06-10 12:30", "2027-07-14 12:30", "2027-08-11 12:30",
                               "2027-09-14 12:30", "2027-10-14 12:30", "2027-11-10 13:30", "2027-12-10 13:30"]),
    "NFP": ("USD", "Non-Farm Employment Change", ["2026-11-06 13:30", "2026-12-04 13:30", "2027-01-08 13:30", "2027-02-05 13:30",
                                                  "2027-03-05 13:30", "2027-04-02 12:30", "2027-05-07 12:30", "2027-06-04 12:30",
                                                  "2027-07-02 12:30", "2027-08-06 12:30", "2027-09-03 12:30", "2027-10-08 12:30",
                                                  "2027-11-05 12:30", "2027-12-03 13:30"]),
    "ECB": ("EUR", "Main Refinancing Rate", ["2026-10-29 13:15", "2026-12-17 13:15", "2027-02-04 13:15", "2027-03-18 13:15",
                                             "2027-04-29 12:15", "2027-06-10 12:15", "2027-07-22 12:15", "2027-09-09 12:15",
                                             "2027-10-28 12:15", "2027-12-16 13:15"]),
    "BOJ": ("JPY", "BOJ Policy Rate", ["2026-10-30 03:00", "2026-12-18 03:00", "2027-01-22 03:00", "2027-03-18 03:00",
                                       "2027-04-28 03:00", "2027-06-11 03:00", "2027-07-22 03:00", "2027-09-22 03:00",
                                       "2027-10-29 03:00", "2027-12-17 03:00"]),
    "BOC": ("CAD", "Overnight Rate", ["2026-10-28 13:45", "2026-12-09 14:45", "2027-01-27 14:45", "2027-03-03 14:45",
                                      "2027-04-28 13:45", "2027-06-02 13:45", "2027-07-21 13:45", "2027-09-08 13:45",
                                      "2027-10-27 13:45", "2027-12-08 14:45"]),
}
KELUARGA = {"FOMC": ("FOMC", "FEDERAL FUNDS"), "CPI": ("CPI",), "NFP": ("NON-FARM",)}
# saham yang dipantau di kalender mingguan (info, dampak kecil ke BTC)
PANTAU_EARN = ("MSFT", "GOOGL", "AMZN", "AAPL", "META", "NVDA", "TSLA", "COIN", "MSTR", "HOOD", "XOM", "CVX")
NASDAQ_EARN = "https://api.nasdaq.com/api/calendar/earnings"


def _ms(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def jadwal(dari_ms, sampai_ms, negara=None):
    """Kejadian jadwal resmi dalam rentang waktu. Return list dict(judul, negara, ts, kode)."""
    out = []
    for kode, (ng, judul, L) in JADWAL.items():
        if negara and ng != negara:
            continue
        out += [dict(judul=judul, negara=ng, ts=_ms(s), kode=kode) for s in L if dari_ms <= _ms(s) <= sampai_ms]
    return sorted(out, key=lambda e: e["ts"])


def _ambil_ff(c, now):
    """Semua berita berdampak tinggi minggu ini dari ForexFactory (semua negara). Disimpan 3 jam."""
    if now - c.get("kal_ts", 0) < 3 * JAM and "kal" in c and "kal_semua" in c:
        return
    if now - c.get("kal_gagal", 0) < 15 * 60000:
        return          # baru saja gagal: coba lagi 15 menit kemudian, jadwal resmi tetap dipakai
    try:
        r = requests.get(FF_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0 qse-bot"})
        semua = []
        for x in r.json():
            if x.get("impact") == "High":
                t = dt.datetime.fromisoformat(x["date"]).timestamp() * 1000
                semua.append(dict(judul=x.get("title", "berita"), negara=x.get("country", ""), ts=int(t),
                                  perkiraan=x.get("forecast") or "", sebelum=x.get("previous") or ""))
        semua.sort(key=lambda e: e["ts"])
        c["kal_semua"] = semua
        c["kal"] = [dict(judul=e["judul"], ts=e["ts"]) for e in semua if e["negara"] == "USD"]
        c["kal_ts"] = now
        _save(c)
    except Exception as ex:
        print("[WARN] kalender ekonomi:", ex)
        c["kal_gagal"] = now
        try:
            _save(c)
        except Exception:
            pass


def _sama(e, f):
    """Dua kejadian dianggap sama: jarak 3 jam dan satu keluarga (FOMC, CPI, NFP) atau judul sama."""
    if abs(e["ts"] - f["ts"]) > 3 * JAM:
        return False
    a, b = e["judul"].upper(), f["judul"].upper()
    if a == b:
        return True
    return any(any(k in a for k in ks) and any(k in b for k in ks) for ks in KELUARGA.values())


def kalender():
    """Berita besar USD (ForexFactory minggu ini) plus jadwal resmi FOMC, CPI, NFP yang belum ada di sana
    (cadangan kalau ForexFactory gagal, dan minggu-minggu berikutnya). Return list dict(judul, ts) urut waktu."""
    c = _load()
    now = int(time.time() * 1000)
    _ambil_ff(c, now)
    ff = list(c.get("kal", []))
    tambah = [dict(judul=j["judul"], ts=j["ts"]) for j in jadwal(now - 2 * 86400000, now + 40 * 86400000, "USD")
              if not any(_sama(j, f) for f in ff)]
    return sorted(ff + tambah, key=lambda e: e["ts"])


# ---------------- 1b. kalender mingguan (semua jenis berita, dengan dampak teruji) ----------------
NAMA_BERITA = (            # (negara, kata di judul ForexFactory, nama Indonesia)
    ("USD", ("FEDERAL FUNDS", "FOMC STATEMENT"), "FOMC: suku bunga AS"), ("USD", ("FOMC PRESS",), "FOMC: konferensi pers"),
    ("USD", ("CPI",), "CPI AS (inflasi)"), ("USD", ("NON-FARM", "UNEMPLOYMENT RATE", "AVERAGE HOURLY"), "NFP AS (data kerja)"),
    ("USD", ("PCE",), "PCE AS (inflasi)"), ("USD", ("GDP",), "GDP AS"),
    ("EUR", ("REFINANCING", "MONETARY POLICY", "ECB PRESS", "DEPOSIT"), "ECB: suku bunga Eropa"),
    ("JPY", ("BOJ", "MONETARY POLICY"), "BoJ: suku bunga Jepang"),
    ("CAD", ("OVERNIGHT", "BOC"), "BoC: suku bunga Kanada"),
    ("GBP", ("BANK RATE", "MPC", "BOE", "MONETARY POLICY"), "BoE: suku bunga Inggris"),
    ("AUD", ("CASH RATE", "RBA"), "RBA: suku bunga Australia"), ("NZD", ("CASH RATE", "RBNZ"), "RBNZ: suku bunga Selandia Baru"),
    ("CHF", ("SNB", "POLICY RATE"), "SNB: suku bunga Swiss"),
)


def nama_berita(judul, negara):
    u = (judul or "").upper()
    for ng, kata, nm in NAMA_BERITA:
        if negara == ng and any(k in u for k in kata):
            return nm + (" (konferensi pers)" if "PRESS" in u and "konferensi" not in nm else "")
    return f"{negara} {judul}".strip()


def dampak(judul, negara):
    """Tanda dampak ke BTC dari uji 2021-2026: 🔴 besar, 🟠 sedang, ⚪ kecil."""
    u = (judul or "").upper()
    if negara == "USD" and any(k in u for k in ("FOMC", "FEDERAL FUNDS", "CPI")):
        return "🔴"
    if negara == "USD" and "GDP" in u:
        return "⚪"
    if negara == "USD":
        return "🟠"
    return "⚪"


def _et(d):
    """Selisih jam New York ke UTC pada tanggal d: -4 saat musim panas AS (Minggu ke-2 Maret s.d. Minggu ke-1 November), -5 lainnya."""
    mar = dt.date(d.year, 3, 8)
    mulai = mar + dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.date(d.year, 11, 1)
    akhir = nov + dt.timedelta(days=(6 - nov.weekday()) % 7)
    return -4 if mulai <= d < akhir else -5


def earnings(now_ms=None, hari=7):
    """Jadwal laporan keuangan saham yang dipantau (Nasdaq, gratis). Disimpan 12 jam. Return list dict(sym, ts, sesi)."""
    c = _load()
    now_ms = now_ms or int(time.time() * 1000)
    if now_ms - c.get("earn_ts", 0) < 12 * JAM and "earn" in c:
        return [e for e in c["earn"] if now_ms - 6 * JAM <= e["ts"] <= now_ms + hari * 86400000]
    out = []
    try:
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
        for i in range(hari + 1):
            d = dt.datetime.fromtimestamp(now_ms / 1000 + i * 86400, dt.timezone(dt.timedelta(hours=-5))).date()
            if d.weekday() >= 5:
                continue
            r = requests.get(NASDAQ_EARN, params={"date": d.isoformat()}, headers=h, timeout=15)
            for x in ((r.json().get("data") or {}).get("rows") or []):
                s = (x.get("symbol") or "").upper()
                if s not in PANTAU_EARN:
                    continue
                w = x.get("time") or ""
                pre = "pre-market" in w
                jam = (7, 0) if pre else (16, 5)          # perkiraan: sebelum buka 07:00 ET, setelah tutup 16:05 ET
                ts = int(dt.datetime(d.year, d.month, d.day, *jam, tzinfo=dt.timezone(dt.timedelta(hours=_et(d)))).timestamp() * 1000)
                out.append(dict(sym=s, ts=ts, sesi="sebelum bursa buka" if pre else "setelah bursa tutup"))
            time.sleep(0.5)
        c["earn"], c["earn_ts"] = out, now_ms
        _save(c)
    except Exception as ex:
        print("[WARN] kalender earnings:", ex)
        out = c.get("earn", [])
    return [e for e in out if now_ms - 6 * JAM <= e["ts"] <= now_ms + hari * 86400000]


def kalender_semua(hari=7, now_ms=None):
    """Semua berita penting dalam `hari` ke depan: berita berdampak tinggi semua negara (ForexFactory), jadwal resmi bank
    sentral yang belum ada, earnings saham yang dipantau, dan token unlock >= 1% koin Bybit.
    Return list dict(ts, tanda, teks) urut waktu, kejadian di jam dan kelompok yang sama digabung."""
    c = _load()
    now_ms = now_ms or int(time.time() * 1000)
    _ambil_ff(c, now_ms)
    c = _load()
    sampai = now_ms + hari * 86400000
    ff = [e for e in c.get("kal_semua", []) if now_ms - JAM <= e["ts"] <= sampai]
    ev = list(ff) + [j for j in jadwal(now_ms - JAM, sampai) if not any(_sama(j, f) or
                     (j["negara"] == f["negara"] and abs(j["ts"] - f["ts"]) <= 3 * JAM) for f in ff)]
    grup = {}
    for e in ev:
        if e["negara"] != "USD" and nama_berita(e["judul"], e["negara"]).startswith(e["negara"] + " "):
            continue          # negara lain hanya keputusan bank sentral (data lain tidak relevan ke kripto)
        k = (e["ts"] // (15 * 60000), nama_berita(e["judul"], e["negara"]))          # rilis yang berdekatan 15 menit digabung
        g = grup.setdefault(k, dict(ts=e["ts"], tanda=dampak(e["judul"], e["negara"]), nama=k[1], angka=[]))
        if e.get("perkiraan") and e.get("sebelum") and len(g["angka"]) < 1:
            g["angka"].append(f"perkiraan {e['perkiraan']}, sebelumnya {e['sebelum']}")
        if dampak(e["judul"], e["negara"]) == "🔴":
            g["tanda"] = "🔴"
    out = [dict(ts=g["ts"], tanda=g["tanda"], teks=g["nama"] + (f" ({g['angka'][0]})" if g["angka"] else "")) for g in grup.values()]
    try:
        earn = {}
        for e in earnings(now_ms, hari):
            earn.setdefault((e["ts"], e["sesi"]), []).append(e["sym"])
        out += [dict(ts=ts, tanda="⚪", teks=f"Earnings {', '.join(sorted(s))} ({sesi})") for (ts, sesi), s in earn.items()]
    except Exception as ex:
        print("[WARN] earnings kalender", ex)
    try:
        import qse_unlock as UL
        out += [dict(ts=u["t"] * 1000, tanda="🔓", teks=f"Unlock {u['sym'].replace('USDT', '')} {u['pct']:.1f}% pasokan: "
                     f"LONG baru {u['sym'].replace('USDT', '')} ditahan sampai lewat unlock") for u in UL.kalender(hari)]
    except Exception as ex:
        print("[WARN] unlock kalender", ex)
    return sorted(out, key=lambda x: (x["ts"], x["teks"]))


HARI_ID = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
LEGENDA = ("<b>Arti tanda</b> (uji gerak BTC 2021-2026 di jam rilis dibanding jam yang sama minggu biasa)\n"
           "🔴 <b>besar</b>: FOMC 2.5x, CPI 2.4x. Robot kirim SIAGA 1 jam sebelum: posisi untung ditutup, yang rugi ditahan\n"
           "🟠 <b>sedang</b>: NFP 1.7x, PCE 1.35x hanya di jam pertama, lalu normal. Data AS lain yang berdampak tinggi juga 🟠\n"
           "⚪ <b>kecil</b>: ECB, BoJ, BoC, GDP, earnings. BTC tidak bergerak lebih dari biasa\n"
           "🔓 <b>token unlock</b> 1% pasokan atau lebih: 7 hari sebelumnya koin rata-rata -3% lawan BTC. LONG baru ditahan\n"
           "Sinyal jalur tetap jalan saat berita: uji 2021-2026, sinyal yang masuk dekat FOMC, ECB, BoJ, dan earnings tidak lebih jelek.")


def teks_kalender_minggu(now_ms=None, hari=7):
    """Pesan 📅 KALENDER BERITA: jadwal 7 hari ke depan, dikelompokkan per hari (jam WIB), dengan tanda dampak."""
    now_ms = now_ms or int(time.time() * 1000)
    ev = kalender_semua(hari, now_ms)
    rows = ["📅 <b>QSE v148 | KALENDER BERITA 7 HARI</b>",
            "Jam WIB. Diambil otomatis tiap minggu: ForexFactory, jadwal resmi bank sentral, Nasdaq (earnings), DefiLlama (unlock)."]
    if not ev:
        rows.append("\nTidak ada berita berdampak tinggi 7 hari ke depan.")
    hari_ini = None
    for e in ev:
        w = dt.datetime.fromtimestamp(e["ts"] / 1000, WIB)
        if w.date() != hari_ini:
            hari_ini = w.date()
            rows += ["", f"<b>{HARI_ID[w.weekday()]} {w.strftime('%d/%m')}</b>"]
        teks = f"<b>{e['teks']}</b>" if e["tanda"] in ("🔴", "🔓") else e["teks"]
        rows.append(f"• {w.strftime('%H:%M')} {e['tanda']} {teks}")
    return "\n".join(rows + ["", LEGENDA])


def jadwal_bulan(now_ms=None):
    """Baris jadwal resmi 1 bulan ke depan untuk laporan bulanan: FOMC, CPI, NFP, lalu ECB, BoJ, BoC."""
    now_ms = now_ms or int(time.time() * 1000)
    ev = jadwal(now_ms, now_ms + 31 * 86400000)
    if not ev:
        return ""
    nm = {"FOMC": "🔴 FOMC suku bunga AS", "CPI": "🔴 CPI AS", "NFP": "🟠 NFP AS", "ECB": "⚪ ECB", "BOJ": "⚪ BoJ (sekitar)",
          "BOC": "⚪ BoC"}
    return "📅 <b>JADWAL BERITA BESAR 1 BULAN</b> (jam WIB)\n" + "\n".join(
        f"• {HARI_ID[dt.datetime.fromtimestamp(e['ts'] / 1000, WIB).weekday()]} {jam_wib(e['ts'])}: {nm[e['kode']]}" for e in ev)


def jeda(now_ms=None):
    """Berita besar yang jendela jedanya sedang aktif (2 jam sebelum sampai 1 jam sesudah)."""
    now_ms = now_ms or int(time.time() * 1000)
    return next((e for e in kalender() if e["ts"] - SEBELUM <= now_ms <= e["ts"] + SESUDAH), None)


def hari_ini(now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    d = dt.datetime.fromtimestamp(now_ms / 1000, WIB).date()
    return [e for e in kalender() if dt.datetime.fromtimestamp(e["ts"] / 1000, WIB).date() == d]


def pengingat(now_ms=None):
    """Berita besar dalam 75 menit ke depan yang belum diingatkan. Tiap berita hanya sekali."""
    now_ms = now_ms or int(time.time() * 1000)
    c = _load()
    sudah = set(c.get("ingat", []))
    out = [e for e in kalender() if 0 < e["ts"] - now_ms <= 75 * 60000 and f"{e['ts']}{e['judul']}" not in sudah]
    if out:
        c["ingat"] = (list(sudah) + [f"{e['ts']}{e['judul']}" for e in out])[-200:]
        _save(c)
    return out


# ---------------- 1c. pengingat bertahap dan perubahan jadwal (otomatis, tidak dadakan) ----------------
# 🔴 FOMC dan CPI: H-24 dan H-6 (H-1 sudah ada: pengingat 75 menit dan SIAGA CPI/FOMC untuk posisi jalan). 🟠 dan ⚪ hanya H-1.
TAHAP = {"🔴": (24 * JAM, 6 * JAM)}
JENDELA_TAHAP = 40 * 60000           # pengingat dikirim sampai 40 menit setelah waktunya, supaya bot yang mati sebentar tetap mengirim
LIPAT = (("FOMC", "FOMC 2.6x"), ("FEDERAL FUNDS", "FOMC 2.6x"), ("CPI", "CPI 2.4x"))          # gerak BTC di jam rilis, uji 2021-2026
UTC = dt.timezone.utc


def _jam_utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, UTC).strftime("%d/%m %H:%M UTC")


def _hitung_mundur(sisa_ms):
    m = max(0, int(sisa_ms / 60000))
    return f"{m // 60} jam {m % 60} menit lagi" if m >= 60 else f"{m} menit lagi"


def _angka(e):
    """Perkiraan dan nilai sebelumnya dari ForexFactory kalau ada. Return teks atau ''."""
    for x in _load().get("kal_semua", []):
        if x.get("negara") == "USD" and x["ts"] == e["ts"] and x["judul"] == e["judul"] and x.get("perkiraan") and x.get("sebelum"):
            return f"Perkiraan {x['perkiraan']}, sebelumnya {x['sebelum']}"
    return ""


def _sumber(e):
    """Nama sumber tanggal: ForexFactory (nfs.faireconomy.media) dan atau jadwal resmi (federalreserve.gov, bls.gov)."""
    c = _load()
    s = []
    if any(f["ts"] == e["ts"] and f["judul"] == e["judul"] for f in c.get("kal", [])):
        s.append("ForexFactory")
    j = [x for x in jadwal(e["ts"] - 3 * JAM, e["ts"] + 3 * JAM, "USD") if _sama(x, e)]
    if j:
        s.append({"FOMC": "federalreserve.gov", "CPI": "bls.gov", "NFP": "bls.gov"}.get(j[0]["kode"], "jadwal resmi"))
    return " + ".join(s) if s else "belum terverifikasi"


def teks_tahap(e, jam, now_ms=None, posisi=None):
    """Pesan pengingat H-jam. Waktu WIB dan UTC, hitung mundur, angka, sumber, posisi terbuka. Tanpa tebakan arah harga."""
    now_ms = now_ms or int(time.time() * 1000)
    w = dt.datetime.fromtimestamp(e["ts"] / 1000, WIB)
    nm = nama_berita(e["judul"], "USD")
    u = e["judul"].upper()
    lipat = next((t for k, t in LIPAT if k in u), "")
    c = _load()
    diambil = c.get("kal_ts")
    rows = [f"📅 <b>PENGINGAT BERITA H-{jam} JAM</b>",
            f"{dampak(e['judul'], 'USD')} <b>{nm}</b>",
            f"Mulai: {HARI_ID[w.weekday()]} {w.strftime('%d/%m %H:%M')} WIB ({_jam_utc(e['ts'])}), {_hitung_mundur(e['ts'] - now_ms)}"]
    ang = _angka(e)
    if ang:
        rows.append(ang)
    rows.append("Sumber: " + _sumber(e) + (f", data diambil {dt.datetime.fromtimestamp(diambil / 1000, WIB).strftime('%H:%M')} WIB" if diambil else ""))
    rows.append("Gerak BTC biasanya lebih besar sekitar rilis" + (f" ({lipat} di jam pertama, uji 2021-2026)" if lipat else "")
                + ". Ini jadwal, bukan tebakan arah.")
    if posisi:
        rows.append("Posisi jalan sekarang:")
        rows += list(posisi)
        rows.append("SL di Bybit tetap melindungi. Robot kirim SIAGA 1 jam sebelum rilis.")
    else:
        rows.append("Tidak ada posisi jalan.")
    return "\n".join(rows)


def tahap_jatuh_tempo(now_ms=None):
    """Pengingat bertahap yang waktunya sudah tiba dan belum dikirim. Tiap (berita, tahap) hanya sekali. Return list dict(e, jam)."""
    now_ms = now_ms or int(time.time() * 1000)
    c = _load()
    sudah = set(c.get("tahap", []))
    out = []
    for e in kalender():
        sisa = e["ts"] - now_ms
        for h in TAHAP.get(dampak(e["judul"], "USD"), ()):
            kunci = f"{e['ts']}|{e['judul']}|H{h // JAM}"
            if h - JENDELA_TAHAP < sisa <= h and kunci not in sudah:
                out.append(dict(e=e, jam=h // JAM, kunci=kunci))
    if out:
        c["tahap"] = (list(sudah) + [x["kunci"] for x in out])[-300:]
        _save(c)
    return out


def cek_ubah(now_ms=None):
    """Deteksi jadwal berubah: berita 🔴 atau 🟠 berikutnya (per jenis) pindah waktu. Harus terlihat dua kali berturut-turut,
    selisih 20 menit atau lebih, supaya data sumber yang goyah tidak memicu pesan. Return list dict(nama, lama, baru)."""
    now_ms = now_ms or int(time.time() * 1000)
    c = _load()
    snap, tunda = c.get("snap", {}), c.get("snap_tunda", {})
    nxt = {}
    for e in kalender():
        if e["ts"] > now_ms and dampak(e["judul"], "USD") in ("🔴", "🟠"):
            nxt.setdefault(nama_berita(e["judul"], "USD"), e)
    out = []
    for k, e in nxt.items():
        lama = snap.get(k)
        if lama is None or lama <= now_ms or lama == e["ts"]:
            snap[k] = e["ts"]
            tunda.pop(k, None)
            continue
        t = tunda.get(k)
        if t and t["ts"] == e["ts"]:
            if now_ms - t["t"] >= 20 * 60000:
                if abs(e["ts"] - lama) <= 14 * 86400000:
                    out.append(dict(nama=k, lama=lama, baru=e["ts"], e=e))
                snap[k] = e["ts"]
                tunda.pop(k, None)
        else:
            tunda[k] = dict(ts=e["ts"], t=now_ms)
    c["snap"], c["snap_tunda"] = snap, tunda
    _save(c)
    return out


def pesan_agenda(posisi_fn=None, now_ms=None):
    """Semua pesan agenda yang jatuh tempo sekarang (perubahan jadwal dan pengingat bertahap). Dipanggil tiap menit oleh listener."""
    now_ms = now_ms or int(time.time() * 1000)
    out = []
    for u in cek_ubah(now_ms):
        out.append(f"🔄 <b>JADWAL BERITA BERUBAH</b>\n{dampak(u['e']['judul'], 'USD')} {u['nama']}\n"
                   f"Sebelumnya: {jam_wib(u['lama'])} ({_jam_utc(u['lama'])})\n"
                   f"Sekarang: {jam_wib(u['baru'])} ({_jam_utc(u['baru'])})\n"
                   f"Sumber: {_sumber(u['e'])}. Pengingat otomatis ikut jadwal baru.")
    due = tahap_jatuh_tempo(now_ms)
    pos = None
    if due and posisi_fn:
        try:
            pos = posisi_fn()
        except Exception as ex:
            print("[WARN] posisi pengingat berita", ex)
    for x in due:
        out.append(teks_tahap(x["e"], x["jam"], now_ms, pos))
    return out


# ---------------- 2. pengumuman Bybit ----------------
def delisting():
    """Simbol yang diumumkan delisting oleh Bybit dalam 45 hari terakhir."""
    c = _load()
    now = int(time.time() * 1000)
    if now - c.get("del_ts", 0) < 3 * JAM and "del" in c:
        return set(c["del"])
    try:
        r = requests.get(BYBIT_URL + "/v5/announcements/index",
                         params={"locale": "en-US", "type": "delistings", "limit": 50}, timeout=15)
        syms = set()
        for it in r.json().get("result", {}).get("list", []):
            ts = int(it.get("dateTimestamp") or it.get("publishTime") or now)
            if now - ts > 45 * 86400000:
                continue
            teks = f"{it.get('title', '')} {it.get('description', '')}".upper()
            syms |= set(re.findall(r"\b([A-Z0-9]{2,20}USDT)\b", teks))
        c["del"], c["del_ts"] = sorted(syms), now
        _save(c)
    except Exception as ex:
        print("[WARN] pengumuman Bybit:", ex)
    return set(c.get("del", []))


# ---------------- 3. detektor guncangan ----------------
def guncang(btc1h):
    """BTC 1 jam: candle terakhir lebih dari 2,5 ATR atau gerak 3 jam lebih dari 3,5 ATR."""
    try:
        h, l, c = (btc1h[k].values.astype(float) for k in ("high", "low", "close"))
        if len(c) < 30:
            return None
        tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        a = tr[-15:-1].mean()
        rng, g3 = h[-1] - l[-1], c[-1] - c[-4]
        if a > 0 and (rng > 2.5 * a or abs(g3) > 3.5 * a):
            pct = float((c[-1] / c[-4] - 1) * 100)
            return dict(arah="naik" if pct > 0 else "turun", pct=pct, x=float(max(rng, abs(g3)) / a))
    except Exception as ex:
        print("[WARN] detektor guncangan:", ex)
    return None
