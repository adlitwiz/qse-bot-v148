"""QSE v148 - BATAS POSISI DAN RISIKO, per orang di grup (Rifqi dan Adli punya batas sendiri dari entry masing-masing).

NETRAL (27 Okt 2026, permintaan user): aturan dikunci ke hasil uji terbaik. Semua angka dalam R dan persen modal di risiko
standar 0.25% per trade (1R = 0.25% modal), jadi berlaku untuk modal berapa pun.
PROFIL DOLAR (28 Okt 2026, permintaan user): tiap orang boleh mengisi modal, risiko, dan leverage lewat /modal 155 1 5
(modal $155, risiko 1% per trade, leverage 5x). Kalau sudah diisi, kartu sinyal menampilkan ukuran posisi dalam dolar:
posisi = modal x risiko% / jarak SL%, margin = posisi / leverage. Persen modal di semua pesan memakai risiko orang itu.
Orang yang belum mengisi tetap memakai tampilan netral 0.25%. Bawaan pemilik: modal 155, risiko 1%, leverage 5x.
File modal.json lama tidak dibaca lagi.

Aturan tetap:
- maksimal 5 posisi berisiko per orang (order menunggu, atau posisi yang SL-nya masih di sisi rugi)
- posisi aman (SL sudah di entry atau di sisi untung) tidak makan slot berisiko, maksimal 2 posisi aman tambahan
- rugi kalau semua SL kena maksimal 5R = 1.25% modal. Posisi aman tidak menambah risiko
- rem harian -3R = -0.75% modal
- jam ke-8 belum kena TP 20%: rugi 0.5R atau lebih tutup, kalau belum SL naik ke -0.5R (qse_saya.aturan_jam8)
- batas waktu 36 jam: posisi yang belum kena TP 20% sejak terisi ditutup market
- 3 rugi beruntun (urut waktu tutup): jeda entry baru 24 jam (qse_saya.jeda_info)
  Uji jam ke-8 + jeda (riset/porto/pf_final.py): +392R PF 1.75 DD 17R, SL penuh 4.3%, SL penuh beruntun 5, kerugian beruntun
  terbesar -7.1R. Tanpa keduanya +393R PF 1.63 DD 34R, SL penuh 19.4%, SL penuh beruntun 10, kerugian beruntun -10.8R.

Batas 5 posisi per orang (27 Okt 2026). Simulasi 2021-2026 sinyal mode seimbang, satu orang ambil urut prioritas sampai
5 posisi, TP sebagian 20% di +0.5R lalu SL ke entry: 1.2 trade per hari, menang 69%, PF 1.36, total +282R, drawdown 25R.
Batas 3: PF 1.30, batas 8: PF 1.42 dengan drawdown 42R.

PERPUTARAN MODAL (27 Okt 2026, permintaan user: trade selesai maks 2 hari supaya modal cepat berputar).
Simulasi ulang dengan populasi sinyal seperti bot live (SL maks 10%, pump 30%, mutu buang, aturan Senin), satu orang,
2021-2026 candle 1 jam (riset/porto/pf_waktu3.py):
  sekarang (slot lepas saat keluar)             0.95/hari WR 70.6 PF 1.52 +314R DD 28 rugi penuh 29% selesai<=48j 62%
  + batas waktu 36 jam saja                     1.02/hari WR 65.2 PF 1.58 +319R DD 26
  + slot aman saja (maks 2 aman)                1.12/hari WR 71.4 PF 1.57 +393R DD 36
  + batas 36 jam + slot aman maks 2 (DIPAKAI)   1.18/hari WR 65.4 PF 1.63 +393R DD 31 rugi penuh 19% selesai<=48j 77%
  batas 48 jam + slot aman maks 2               1.16/hari WR 67.3 PF 1.58 +384R DD 36
  aman maks 1 / maks 3 (48 jam)                 +340R DD 34 / +389R DD 45
Tiap tahun 2021-2026 lebih untung dari cara lama (+58 +83 +68 +82 +43 +60R lawan +47 +77 +39 +73 +26 +52R).
Slot berisiko terkunci rata-rata 17 jam (maks 36 jam) lawan 60 jam. Catatan jujur: per trade, posisi yang ditutup di jam 36
rata-rata -0.25R, kalau ditahan -0.13R. Untungnya datang dari slot yang dipakai sinyal baru. WR turun karena 1 dari 5 trade
ditutup waktu dengan rugi kecil. Varian SL ke entry di jam 36 untuk yang sedang untung: +407R tapi WR 62%, tidak dipakai.
Filter SL maks 9% tidak konsisten (SL 9-10% PF 0.81 lalu 1.26), batas 10% tetap."""
import json
import os
import time

try:
    from config import STATE_DIR
except Exception:                                  # pragma: no cover
    STATE_DIR = os.path.expanduser("~/qse_state")

PROFIL_FILE = os.path.join(STATE_DIR, "profil.json")
PROFIL_PEMILIK = dict(modal=155.0, risiko=1.0, lev=5)        # bawaan pemilik catatan, ubah dengan /modal
RISIKO_MAKS_PROFIL = 5.0                                      # persen modal per trade, batas atas yang diterima /modal
RISK_PCT = 0.25          # persen modal per 1R (saran risiko per trade, lot 1x)
MAKS_POSISI = 5          # posisi berisiko per orang
MAKS_AMAN = 2            # posisi aman tambahan (SL sudah di entry atau untung)
RISIKO_BUKA = 5.0        # R, rugi kalau semua SL kena
REM_HARIAN = 3.0         # R
WAKTU_JAM = 36.0         # batas waktu posisi yang belum kena TP 20%
JAM = 3600 * 1000


def _kunci(uid=None):
    """Kunci profil: uid pengirim (atau pemilik catatan kalau tidak ada pengirim aktif)."""
    try:
        import qse_saya as SY
        u = SY.uid_aktif() if uid is None else uid
        pem = str(SY._peng().get("pemilik") or "")
        u = str(u) if u not in (None, "") else pem
        return u, pem
    except Exception:
        return ("" if uid is None else str(uid)), ""


def _baca_profil():
    try:
        with open(PROFIL_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _simpan_profil(d):
    os.makedirs(os.path.dirname(PROFIL_FILE) or ".", exist_ok=True)
    with open(PROFIL_FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PROFIL_FILE + ".tmp", PROFIL_FILE)


def profil(uid=None):
    """Profil dolar satu orang: dict(modal, risiko, lev) atau None kalau belum mengisi (tampilan netral).
    Pemilik catatan punya bawaan PROFIL_PEMILIK sampai dia mengubahnya."""
    u, pem = _kunci(uid)
    p = _baca_profil().get(u)
    if p is None and u == pem:
        p = dict(PROFIL_PEMILIK)
    if not p or not p.get("modal") or p["modal"] <= 0:
        return None
    return dict(modal=float(p["modal"]), risiko=float(p.get("risiko") or 1.0), lev=int(p.get("lev") or 5))


def risk_pct(uid=None):
    """Persen modal per 1R untuk orang ini: risiko profilnya, atau 0.25% netral."""
    p = profil(uid)
    return p["risiko"] if p else RISK_PCT


def _usd(x):
    return f"${x:,.2f}" if abs(x) < 10 else f"${x:,.1f}"


def pmodal(R, uid=None):
    """R ke persen modal di risiko orang itu (netral 0.25% kalau belum mengisi profil)."""
    return R * risk_pct(uid)


def teks_pmodal(R, uid=None):
    """' (+0.13% modal)' untuk ditempel setelah angka R. Tambah dolar kalau profil sudah diisi."""
    p = profil(uid)
    if not p:
        return f" ({R * RISK_PCT:+.2f}% modal)"
    usd = R * p["modal"] * p["risiko"] / 100
    return f" ({R * p['risiko']:+.2f}% modal, {_usd_s(usd)})"


def _usd_s(usd):
    """'+$1.55' atau '-$1.55'. Nol tanpa tanda."""
    if abs(usd) < 0.005:
        return _usd(0.0)
    return ("+" if usd > 0 else "-") + _usd(abs(usd))


def usd_r(R, uid=None):
    """' (+$1.55)' untuk ditempel setelah persen modal. Kosong kalau orang itu belum mengisi profil."""
    p = profil(uid)
    if not p:
        return ""
    return f" ({_usd_s(R * p['modal'] * p['risiko'] / 100)})"


def teks_r(R, uid=None):
    """'+0.90R = +0.90% modal (+$1.40)'. Tanpa dolar kalau profil belum diisi (netral 0.25% per R)."""
    return f"{R:+.2f}R = {pmodal(R, uid):+.2f}% modal{usd_r(R, uid)}"


def atur_profil(uid, modal=None, risiko=None, lev=None):
    """Simpan profil. Return (profil, pesan_error)."""
    if modal is not None and not (1 <= modal <= 100_000_000):
        return None, "Modal harus antara 1 dan 100000000 dolar. Contoh: /modal 155"
    if risiko is not None and not (0.05 <= risiko <= RISIKO_MAKS_PROFIL):
        return None, f"Risiko per trade harus antara 0.05 dan {RISIKO_MAKS_PROFIL:g} persen modal. Contoh: /modal risiko 1"
    if lev is not None and not (1 <= lev <= 100):
        return None, "Leverage harus antara 1 dan 100. Contoh: /modal lev 5"
    u, _ = _kunci(uid)
    d = _baca_profil()
    lama = profil(uid) or dict(PROFIL_PEMILIK, modal=0.0)
    baru = dict(modal=modal if modal is not None else lama["modal"],
                risiko=risiko if risiko is not None else lama["risiko"],
                lev=int(lev) if lev is not None else lama["lev"])
    if baru["modal"] <= 0:
        return None, "Isi modal dulu. Contoh: /modal 155"
    d[u] = baru
    _simpan_profil(d)
    return baru, ""


def waktu_jam():
    return WAKTU_JAM


def lihat():
    """Aturan tetap (dulu dari /modal). Dipertahankan untuk kode lama yang membaca kunci ini."""
    return dict(modal=0.0, risk=RISK_PCT, rem=REM_HARIAN, posisi=MAKS_POSISI, risiko_buka=RISIKO_BUKA, aman=MAKS_AMAN,
                waktu=WAKTU_JAM)


def teks_aturan():
    """Satu baris aturan otomatis, dipakai di pesan sinyal."""
    return (f"⏳ <b>Aturan otomatis</b>: jam ke-8 belum kena TP 20%, SL naik ke -0.5R. {WAKTU_JAM:g} jam belum kena, tutup. "
            f"3 rugi beruntun, jeda entry 24 jam. Posisi yang SL-nya sudah di entry tidak makan slot (maks {MAKS_AMAN})")


FORMAT_MODAL = ("Format: /modal 155 (modal dolar), /modal 155 1 5 (modal, risiko persen per trade, leverage), "
                "/modal risiko 0.5, /modal lev 10")


def _num(s):
    s = str(s).upper().replace("$", "").replace(",", ".").strip()
    if s.endswith(("X", "%")):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _proses_args(args):
    """/modal 155, /modal 155 1 5, /modal risiko 0.5, /modal lev 10. Return teks balasan."""
    toks = [str(a).upper() for a in args]
    kv = {}
    bebas = []
    i = 0
    while i < len(toks):
        k = {"MODAL": "modal", "RISIKO": "risiko", "RISK": "risiko", "LEV": "lev", "LEVERAGE": "lev"}.get(toks[i])
        if k and i + 1 < len(toks):
            v = _num(toks[i + 1])
            if v is None:
                return f"Angka tidak dikenali: {toks[i + 1]}. {FORMAT_MODAL}"
            kv[k] = v
            i += 2
            continue
        v = _num(toks[i])
        if v is None:
            return f"Tidak dikenali: {toks[i]}. {FORMAT_MODAL}"
        bebas.append(v)
        i += 1
    for k in ("modal", "risiko", "lev"):
        if k not in kv and bebas:
            kv[k] = bebas.pop(0)
    if bebas:
        return f"Terlalu banyak angka. {FORMAT_MODAL}"
    baru, err = atur_profil(None, kv.get("modal"), kv.get("risiko"), kv.get("lev"))
    if err:
        return err
    nilai = baru["modal"] * baru["risiko"] / 100 / 0.03
    return (f"✅ Profil tersimpan: modal {_usd(baru['modal'])}, risiko {baru['risiko']:g}% per trade "
            f"(1R = {_usd(baru['modal'] * baru['risiko'] / 100)}), leverage {baru['lev']}x.\n"
            f"Contoh SL 3% dari entry: posisi {_usd(nilai)}, margin {_usd(nilai / baru['lev'])}, "
            f"rugi kalau SL kena {_usd(baru['modal'] * baru['risiko'] / 100)}. Kartu sinyal berikutnya memakai angka ini.")


def baris_profil(uid=None):
    p = profil(uid)
    if not p:
        return "👤 Modal belum diisi. Kirim /modal 155 supaya ukuran posisi tampil dalam dolar"
    return (f"👤 <b>Profil kamu</b>: modal {_usd(p['modal'])}, risiko {p['risiko']:g}% per trade "
            f"(1R = {_usd(p['modal'] * p['risiko'] / 100)}), leverage {p['lev']}x. Ubah: /modal 200 1 5")


def perintah(args=None):
    """/modal: kondisi kamu sekarang. /modal 155 1 5 mengisi modal, risiko, dan leverage kamu (dolar)."""
    if args:
        return _proses_args(args)
    st = status()
    rp = risk_pct(st.get("uid"))
    rows = ["<b>Batas posisi dan risiko</b> (aturan sama untuk semua orang, dihitung dari entry masing-masing)",
            baris_profil(st.get("uid")),
            f"1R = risiko {rp:g}% modal per trade (lot 1x). Maksimal {MAKS_POSISI} posisi berisiko + {MAKS_AMAN} posisi aman. "
            f"Rugi kalau semua SL kena maksimal {RISIKO_BUKA:g}R = {pmodal(RISIKO_BUKA, st.get('uid')):.2f}% modal. "
            f"Rem harian -{REM_HARIAN:g}R = -{pmodal(REM_HARIAN, st.get('uid')):.2f}% modal",
            f"🛡 <b>Jam ke-8</b>: belum kena TP 20%, SL naik ke -0.5R. Sudah rugi lebih dari itu, tutup market",
            f"⏳ <b>Batas waktu {WAKTU_JAM:g} jam</b>: posisi yang belum kena TP 20% sejak terisi, tutup market. "
            f"Posisi aman (SL sudah di entry) tidak makan slot berisiko",
            "⏸️ <b>Jeda</b>: 3 trade rugi berturut-turut, berhenti entry baru 24 jam",
            "",
            "<b>Kondisi kamu sekarang</b>",
            f"Hasil hari ini {st['hari_ini']:+.2f}R{teks_pmodal(st['hari_ini'], st.get('uid'))} | posisi berisiko {st['n_posisi']}/{st['maks']} | "
            f"aman {st['n_aman']}/{st['maks_aman']} | kalau semua SL kena rugi {st['risiko']:.2f}R = {st['risiko_pct']:.2f}% modal",
            *[_baris_daftar(x) for x in st["daftar"]],
            ("⛔ " + st["alasan"]) if st["rem"] else f"✅ Boleh entry, sisa slot {st['sisa']}"]
    return "\n".join(rows)


def _baris_daftar(x):
    if x["status"] == "MENUNGGU":
        return f"• {x['sym']} {x['arah']}: order menunggu terisi, SL {x['pct']:.1f}% dari entry (dihitung slot berisiko)"
    if x["aman"]:
        return f"• {x['sym']} {x['arah']}: SL di entry atau untung, aman (risiko 0, tidak makan slot berisiko)"
    t = f"• {x['sym']} {x['arah']}: SL {x['pct']:.1f}% dari entry"
    if x["sisa_jam"] is not None:
        t += (f"  ·  ⏰ <b>lewat batas waktu ({x['lewat_jam']:.0f} jam), tutup market</b>" if x["sisa_jam"] <= 0
              else f"  ·  ⏰ sisa {x['sisa_jam']:.0f} jam (batas {x['batas']})")
    return t


def status(uid=None):
    """Rem harian, batas posisi, dan risiko terbuka dari trade SATU orang (/entry). uid None = pengirim perintah,
    atau pemilik kalau dipanggil tugas otomatis. Trade orang lain di grup tidak ikut dihitung.
    Slot: maks MAKS_POSISI posisi berisiko (order menunggu atau SL masih di sisi rugi) dan maks MAKS_POSISI + MAKS_AMAN
    total. Posisi yang SL-nya sudah di entry atau di sisi untung tidak dihitung slot berisiko dan tidak menambah risiko."""
    import qse_saya as SY
    u = uid if uid is not None else SY.uid_aktif()
    data = SY._baca(SY._path_uid(u))
    now = int(time.time() * 1000)
    awal = (now + 7 * 3600000) // 86400000 * 86400000 - 7 * 3600000
    hari = sum(c["result_r"] for c in data["closed"] if c.get("why") in ("SL", "BE", "TP2", "TUTUP")
               and c.get("closed_ts", 0) >= awal)
    hari += sum(SY._real(it) for it in data["open"].values() if it["status"] in ("TERISI", "TP1"))
    buka = [it for it in data["open"].values() if it.get("status") in ("TERISI", "TP1", "MENUNGGU")]
    risiko, daftar, lewat = 0.0, [], []
    n_risk = n_aman = 0
    for it in buka:
        L = it["arah"] == "LONG"
        sl = it["entry"] if (it["status"] == "TP1" and not it.get("sl_manual")) else it["sl"]
        rugi_sisi = (sl < it["entry"]) if L else (sl > it["entry"])           # SL masih di sisi rugi
        r_it = SY._sisa(it) * abs(it["entry"] - sl) / SY._risk0(it) if rugi_sisi else 0.0
        risiko += r_it
        aman = it["status"] != "MENUNGGU" and r_it == 0.0
        if aman:
            n_aman += 1
        else:
            n_risk += 1
        x = dict(sym=it["sym"], arah=it["arah"], status=it["status"], aman=aman, sisa_jam=None, lewat_jam=0.0, batas="",
                 pct=abs(it["entry"] - sl) / it["entry"] * 100 if it["entry"] else 0.0)
        try:
            bw = SY.batas_waktu(it)
            if bw and not SY.sudah_aman(it):
                x["sisa_jam"] = (bw - now) / JAM
                x["lewat_jam"] = (now - (it.get("fill_ts") or it.get("created_ts") or now)) / JAM
                x["batas"] = SY._jam_wib(bw)
                if x["sisa_jam"] <= 0:
                    lewat.append(x)
        except Exception as ex:
            print("[WARN] batas waktu", ex)
        daftar.append(x)
    maks_total = MAKS_POSISI + MAKS_AMAN
    try:
        jd = SY.jeda_info(data["closed"], now)
    except Exception as ex:
        print("[WARN] jeda", ex)
        jd = dict(aktif=False, sampai=None, beruntun=0)
    alasan = ""
    if hari <= -REM_HARIAN:
        alasan = f"REM HARIAN: hasil hari ini {hari:+.2f}R ({pmodal(hari, u):+.2f}% modal), sebaiknya berhenti trading sampai besok"
    elif jd["aktif"]:
        dh = SY.teks_dihitung(jd)
        alasan = (f"JEDA: {jd['beruntun']} rugi beruntun" + (f" ({dh}, hanya catatan kamu)" if dh else "")
                  + f", entry baru lagi {SY._jam_wib(jd['sampai'])}")
    elif n_risk >= MAKS_POSISI:
        alasan = (f"BATAS POSISI: sudah {n_risk} posisi berisiko atau order terbuka (maks {MAKS_POSISI} per orang). "
                  f"Posisi yang SL-nya sudah di entry tidak dihitung")
    elif len(buka) >= maks_total:
        alasan = f"BATAS TOTAL: sudah {len(buka)} posisi (maks {MAKS_POSISI} berisiko + {MAKS_AMAN} aman)"
    elif risiko >= RISIKO_BUKA:
        alasan = f"BATAS RISIKO: kalau semua SL kena rugi {risiko:.1f}R = {pmodal(risiko, u):.2f}% modal (maks {RISIKO_BUKA:g}R)"
    return dict(hari_ini=hari, n_posisi=n_risk, n_aman=n_aman, n_total=len(buka), maks=MAKS_POSISI, maks_aman=MAKS_AMAN,
                sisa=max(0, min(MAKS_POSISI - n_risk, maks_total - len(buka))),
                risiko=risiko, risiko_pct=pmodal(risiko, u), risiko_maks=RISIKO_BUKA, daftar=daftar, lewat=lewat, uid=u,
                rem=bool(alasan), alasan=alasan, jeda=jd)


def status_semua():
    """[(nama, status)] untuk tiap orang yang punya catatan trade."""
    import qse_saya as SY
    out = []
    for u in SY.daftar_pengguna():
        try:
            out.append((SY.nama_pengguna(u), status(u)))
        except Exception as ex:
            print("[WARN] status modal", u, ex)
    return out


def _teks_risiko(st):
    """Rugi kalau semua SL kena saat ini dibanding batasnya, dalam R dan persen modal."""
    if not st.get("n_total", st["n_posisi"]):
        return ""
    if st["risiko"] <= 0:
        return "SL semua sudah di entry atau untung, rugi 0R"
    u = st.get("uid")
    p = profil(u)
    usd = (lambda R: f" ({_usd(R * p['modal'] * p['risiko'] / 100)})") if p else (lambda R: "")
    return (f"kalau semua SL kena rugi {st['risiko']:.1f}R = {st['risiko_pct']:.2f}% modal{usd(st['risiko'])}, batas "
            f"{st['risiko_maks']:g}R = {pmodal(st['risiko_maks'], u):.2f}%{usd(st['risiko_maks'])}")


def baris_slot():
    """Slot posisi per orang untuk pesan sinyal. Contoh: 👤 Rifqi 2/5 posisi berisiko + 1 aman, sisa slot 3  ·  kalau semua
    SL kena rugi 2.0R = 0.50% modal, batas 5R = 1.25%. Posisi yang lewat batas waktu ditulis tebal. Baris terakhir aturan."""
    import html
    rows = []
    for nm, st in status_semua():
        nm = html.escape(str(nm))
        rk = _teks_risiko(st)
        aman = f" + {st['n_aman']} aman" if st.get("n_aman") else ""
        if st["rem"]:
            why = st["alasan"].split(":")[0].lower()
            if st["alasan"].startswith("JEDA"):
                why = f"jeda {st['jeda']['beruntun']} rugi beruntun sampai {st['alasan'].split('entry baru lagi ')[-1]}"
                try:
                    import qse_saya as SY_j
                    dh = SY_j.teks_dihitung(st["jeda"])
                    why += f" (dihitung: {html.escape(dh)})" if dh else ""
                except Exception:
                    pass
            rows.append(f"⛔ <b>{nm} {st['n_posisi']}/{st['maks']} posisi berisiko{aman}: {why}, jangan entry baru dulu</b>"
                        + (f"  ·  {rk}" if rk else ""))
        else:
            rows.append(f"👤 <b>{nm} {st['n_posisi']}/{st['maks']} posisi berisiko</b>{aman}, sisa slot {st['sisa']}"
                        + (f"  ·  {rk}" if rk else ""))
        for x in st.get("lewat", []):
            rows.append(f"⏳ <b>{nm}: {x['sym']} {x['arah']} lewat batas waktu ({x['lewat_jam']:.0f} jam belum kena TP 20%). "
                        f"Tutup market, lalu /tutup {x['sym'].replace('USDT', '')}</b>")
    if rows:
        rows.append(teks_aturan())
    return rows


def _baris_lot_netral(sl_pct, kali, lev):
    risiko = RISK_PCT * kali
    nilai = risiko / sl_pct * 100
    teks = f"💼 Ukuran: <b>nilai posisi {nilai:.1f}% modal</b> (risiko {risiko:g}% modal, SL {sl_pct:.1f}% dari entry)"
    if lev:
        teks += f", margin {nilai / lev:.2f}% modal di {lev}x"
    return teks


def _baris_lot_dolar(nama, p, sl_pct, kali, lev):
    """Satu orang yang sudah isi modal: posisi, margin, dan rugi kalau SL kena, dalam dolar.
    posisi = modal x risiko% x lot / jarak SL%, margin = posisi / leverage."""
    risiko = p["risiko"] * kali
    rugi = p["modal"] * risiko / 100
    posisi = rugi / (sl_pct / 100)
    lv = int(lev) if lev else p["lev"]
    margin = posisi / lv
    teks = (f"💼 <b>{nama}: posisi {_usd(posisi)}</b>, margin {_usd(margin)} di {lv}x, rugi kalau SL kena {_usd(rugi)} "
            f"({risiko:g}% modal, SL {sl_pct:.1f}% dari entry)")
    if margin > p["modal"]:
        teks += f". ⚠️ Margin melebihi modal {_usd(p['modal'])}, kecilkan risiko atau naikkan leverage"
    return teks


def baris_lot(entry, sl, kali=1.0, lev=None):
    """Ukuran posisi. Orang yang sudah isi /modal dapat angka dolar (posisi, margin, rugi kalau SL kena), sisanya tampilan
    netral dalam persen modal. Dipanggil oleh pengirim perintah: hanya barisnya. Dipanggil robot (pesan grup): satu baris
    per orang. Contoh SL 4%, risiko 1%, modal 155: rugi 1.55, posisi 38.8."""
    if entry <= 0 or abs(entry - sl) <= 0:
        return ""
    sl_pct = abs(entry - sl) / entry * 100
    try:
        import html
        import qse_saya as SY
        aktif = SY.uid_aktif()
        orang = [aktif] if aktif is not None else SY.daftar_pengguna()
        baris, netral = [], False
        for u in orang:
            p = profil(u)
            if p:
                baris.append(_baris_lot_dolar(html.escape(str(SY.nama_pengguna(u))), p, sl_pct, kali, lev))
            else:
                netral = True
        if netral or not baris:
            baris.append(_baris_lot_netral(sl_pct, kali, lev))
        return "\n".join(baris)
    except Exception:
        return _baris_lot_netral(sl_pct, kali, lev)
