"""QSE v150 OVERMIND (9 Nov 2026, QC 57, uji jalan-maju riset/upgrade/hasil_v164_overmind.txt). Dewan hakim di atas agen Gurita,
Lalat Abdul, Jalur v150, Sektor, dan GZH pantulan. Jalan sendiri tiap hari 00:05 WIB di VPS.
Uji pakai hasil asli 8 jalur v150 2021-2026, hasil trade baru dianggap diketahui 2 hari sesudah sinyal (tanpa intip masa depan):
1. KELAS A KOIN. Usulan awal jendela 14 hari GAGAL: Kelas A 14 hari 2025-2026 rata -0.019R (PF 0.93) vs lainnya +0.072R,
   jendela 30 hari juga lebih jelek. Jendela 365 hari LULUS di dua periode: 2023-2024 +0.086R PF 1.33 vs +0.053R PF 1.20,
   2025-2026 +0.100R PF 1.37 vs +0.059R PF 1.22. DIPASANG: tiap malam Kelas A = koin x teknik x arah dengan sinyal selesai
   365 hari terakhir minimal 3 dan WR >= 70%. Koin yang naik ke Kelas A dan yang dibuang dilaporkan. Kartu menampilkan label Kelas A.
2. DEWAN AGEN (8 jalur sebagai agen). Jalur yang 20 trade terakhirnya minus: 2023-2024 rata -0.029R vs normal +0.167R,
   2025-2026 +0.038R vs +0.154R. Bobot 0.5x untuk jalur minus menaikkan R per unit risiko di dua periode
   (+0.0615 -> +0.0934 dan +0.0711 -> +0.0846). DIPASANG: kartu jalur yang sedang minus turun ke KELAS RINGAN sampai 20 trade
   terakhirnya kembali positif. Pemimpin WR tidak lebih bagus dari jalur normal, jadi tidak diberi tambahan.
   Lalat, gurita, sektor, GZH: rapor saja (catatan live belum cukup untuk diuji).
3. COMBO GENETIK GAGAL: pasangan jalur WR >= 75% (n >= 15, 90 hari) yang dipromosikan tiap bulan, bulan berikutnya
   2023-2024 rata -0.083R PF 0.68, 2025-2026 -0.103R PF 0.67 (lebih jelek dari semua pasangan). Calon hanya dilaporkan, tidak live.
4. Ringkasan di atas menu Otak Gurita dan Info. Matikan aksi kelas: QSE_OVERMIND_LOT=0."""
import json
import os
import time
from itertools import combinations

from config import STATE_DIR

F = os.path.join(STATE_DIR, "overmind.json")
N_RAPOR = 20


def _baca():
    try:
        with open(F) as f:
            return json.load(f)
    except Exception:
        return {}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(F + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(F + ".tmp", F)


def _hasil_agen():
    """dict agen -> list (waktu selesai, R, sym, arah, jalur)."""
    out = {}
    try:
        import qse_lalat as LT
        out["🪰 Lalat Abdul"] = [(x.get("selesai", 0), x["R"], x["sym"], x["arah"], "lalat") for x in LT.state().get("riwayat", [])
                                 if x.get("R") is not None]
    except Exception as ex:
        print("[WARN] overmind lalat", ex)
    try:
        import qse_gurita as GR
        out["🐙 Gurita"] = [(p.get("selesai", p.get("t", 0)), p["R"], p["sym"], p["arah"], p.get("jalur", "gurita"))
                           for p in GR._baca().get("pick", []) if p.get("R") is not None]
    except Exception as ex:
        print("[WARN] overmind gurita", ex)
    try:
        import qse_otak as O
        out["🧠 Jalur v150"] = [(float(c.get("selesai") or c["t"]), float(c["R"]), c.get("sym"), c.get("arah"), c.get("jalur"))
                               for c in O._ledger()]
    except Exception as ex:
        print("[WARN] overmind jalur", ex)
    try:
        import qse_sektor as SK
        out["🧩 Sektor"] = [(c.get("selesai", 0), c["R"], c.get("sym"), c.get("arah"), "sektor") for c in SK.lihat().get("closed", [])
                           if c.get("R") is not None]
    except Exception as ex:
        print("[WARN] overmind sektor", ex)
    try:
        import qse_gzh2 as GZ
        out["🟡 GZH pantulan"] = [(c.get("selesai", 0), c["R"], c["sym"], c.get("arah", "LONG"), "gzh2") for c in GZ._baca().get("closed", [])]
    except Exception:
        pass
    try:
        import qse_whip as WP          # v170 QC 65: mesin news Whip-Fade
        tutup = WP._baca().get("closed", [])
        if tutup:
            out["⚡ Whip-Fade news"] = [(c.get("selesai", 0), c["R"], c["sym"], "LONG", "whip") for c in tutup]
    except Exception:
        pass
    return out


def rapor_agen(hasil=None):
    hasil = hasil or _hasil_agen()
    rows = []
    for nm, xs in hasil.items():
        xs = sorted(xs)[-N_RAPOR:]
        if not xs:
            rows.append(dict(agen=nm, n=0, wr=0.0, tot=0.0))
            continue
        r = [x[1] for x in xs]
        rows.append(dict(agen=nm, n=len(r), wr=sum(1 for v in r if v > 0) / len(r) * 100, tot=sum(r)))
    ada = [x for x in rows if x["n"] >= 5]
    pem = max(ada, key=lambda x: (x["wr"], x["tot"]))["agen"] if ada else None
    for x in rows:
        x["lot"] = 1.0 if (x["agen"] == pem or x["n"] < 5 or x["tot"] >= 0) else 0.5
        x["pemimpin"] = x["agen"] == pem
    return rows


def kali_lot(agen):
    """Pengali lot dari dewan. 1.0 kecuali QSE_OVERMIND_LOT=1 dan agen sedang minus."""
    if os.environ.get("QSE_OVERMIND_LOT", "0") != "1":
        return 1.0
    for x in _baca().get("rapor", []):
        if agen in x["agen"]:
            return x["lot"]
    return 1.0


def evolusi_koin(hari=14):
    """Koin x jalur x arah yang status profilnya berubah karena catatan live 14 hari terakhir."""
    naik, turun = [], []
    try:
        import qse_otak as O
        led = O._ledger()
        batas = time.time() - hari * 86400
        baru = {(c.get("sym"), c.get("jalur"), c.get("arah")) for c in led if float(c.get("selesai") or c["t"]) >= batas}
        lama = [c for c in led if float(c.get("selesai") or c["t"]) < batas]
        for s, j, a in sorted(baru):
            if not s:
                continue
            kini = O.profil(s, j, a, live=led)
            dulu = O.profil(s, j, a, live=lama)
            if kini.get("lulus") and not dulu.get("lulus"):
                naik.append(f"{s.replace('USDT', '')} {j} {a} (PF {kini['pf']:.2f})")
            elif dulu.get("lulus") and not kini.get("lulus"):
                turun.append(f"{s.replace('USDT', '')} {j} {a} (PF {kini['pf']:.2f})")
    except Exception as ex:
        print("[WARN] overmind evolusi", ex)
    return naik, turun


def calon_combo(hasil=None, hari=90, n_min=15, wr_min=75.0):
    hasil = hasil or _hasil_agen()
    xs = sorted(x for v in hasil.values() for x in v if x[0] >= time.time() - hari * 86400)
    grup = {}
    for i, a in enumerate(xs):
        for b in xs[i + 1:]:
            if b[0] - a[0] > 8 * 3600:
                break
            if a[2] == b[2] and a[3] == b[3] and a[4] != b[4]:
                k = tuple(sorted((str(a[4]), str(b[4])))) + (a[3],)
                grup.setdefault(k, []).append((a[1] + b[1]) / 2)
    out = []
    for k, r in grup.items():
        if len(r) >= n_min:
            wr = sum(1 for v in r if v > 0) / len(r) * 100
            if wr >= wr_min:
                out.append(dict(nama=f"{k[0]} + {k[1]} {k[2]}", n=len(r), wr=round(wr, 1), ex=round(sum(r) / len(r), 3)))
    return sorted(out, key=lambda x: -x["wr"])[:5]


def _seri(now=None):
    """Semua hasil jalur: list (sym, jalur, arah, t detik sinyal, R). Riwayat profil_koin.json + catatan live sesudahnya."""
    import qse_otak as O
    d = O._profil_data()
    rows = [(k.split("|")[0], k.split("|")[1], k.split("|")[2], t / 1000, float(r)) for k, v in d.get("sinyal", {}).items() for t, r in v]
    try:
        import qse_strat as ST
        for c in O._ledger():
            tt = float(c.get("selesai") or c["t"])
            if tt * 1000 > d.get("akhir_ms", 0) and c.get("sym"):
                rows.append((c["sym"], c.get("jalur"), c.get("arah"), float(c["t"]), float(ST.r_hasil(c))))
    except Exception as ex:
        print("[WARN] overmind seri live", ex)
    return rows


def kelas_a(rows=None, now=None, hari=365, n_min=4, wr_min=0.68, pf_min=1.6):
    """Set 'SYM|jalur|ARAH' Kelas A: sinyal yang hasilnya sudah diketahui (2 hari) dalam 365 hari terakhir.
    v172 QC 70 (permintaan user): syarat n >= 4, WR >= 68%, PF >= 1.6 (dulu n >= 3, WR >= 70%). Sumber: riwayat profil_koin.json
    2023-2026 ditambah catatan live, bukan log live saja. Uji jalan maju (run_v172_qc70.py): Kelas A syarat baru 2025 +0.161R
    (bukan +0.163R), 2026 +0.018R PF 1.07 (bukan -0.030R). Syarat lama 2026 -0.001R. Pembeda kecil, jadi tetap hanya label."""
    now = now or time.time()
    rows = _seri() if rows is None else rows
    g = {}
    for s_, j, a, t, r in rows:
        if now - hari * 86400 <= t + 2 * 86400 < now:
            g.setdefault(f"{s_}|{j}|{a}", []).append(r)
    def _pf(v):
        u, r_ = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
        return u / r_ if r_ > 0 else (99.0 if u > 0 else 0.0)
    return {k for k, v in g.items() if len(v) >= n_min and sum(1 for x in v if x > 0) / len(v) >= wr_min and _pf(v) >= pf_min}


_KA = {"t": 0.0, "s": set()}


def kelas_a_aktif():
    """Daftar Kelas A yang dipakai: hasil evolusi tersimpan, atau dihitung langsung dari riwayat (cache 1 jam) kalau yang tersimpan kosong.
    Ini memperbaiki tampilan '0 kombinasi' saat file evolusi kosong atau dibuat versi lama."""
    s = set(_baca().get("kelas_a") or [])
    if s:
        return s
    if time.time() - _KA["t"] > 3600:
        try:
            _KA.update(t=time.time(), s=kelas_a())
        except Exception as ex:
            print("[WARN] overmind kelas A", ex)
            _KA["t"] = time.time()
    return _KA["s"]


def jalur_minus(rows=None, now=None):
    """Jalur yang 20 trade terakhir (hasil sudah diketahui) totalnya negatif dan bukan pemimpin WR."""
    now = now or time.time()
    rows = _seri() if rows is None else rows
    per = {}
    for s_, j, a, t, r in sorted(rows, key=lambda x: x[3]):
        if t + 2 * 86400 < now:
            per.setdefault(j, []).append(r)
    last = {j: v[-20:] for j, v in per.items() if len(v) >= 20}
    if not last:
        return {}, None
    wr = {j: sum(1 for x in v if x > 0) / len(v) for j, v in last.items()}
    pem = max(wr, key=wr.get)
    info = {j: dict(wr=round(wr[j] * 100, 1), tot=round(sum(v), 2), minus=bool(sum(v) < 0 and j != pem)) for j, v in last.items()}
    return info, pem


def kelas_jalur(jalur):
    """(True, alasan) kalau dewan menurunkan jalur ini ke KELAS RINGAN malam tadi."""
    if os.environ.get("QSE_OVERMIND_LOT", "1") != "1":
        return False, ""
    j = str(jalur).replace("saran ", "")
    x = (_baca().get("jalur") or {}).get(j)
    if x and x.get("minus"):
        return True, f"🧬 Dewan Overmind: jalur ini 20 trade terakhir {x['tot']:+.1f}R (WR {x['wr']:.0f}%), turun ke kelas ringan sampai positif lagi"
    return False, ""


def label_kelas_a(sym, jalur, arah):
    k = f"{sym}|{jalur}|{arah}"
    return "🏅 KELAS A (365 hari: minimal 4 sinyal, WR 68%+, PF 1.6+)" if k in kelas_a_aktif() else ""


def evolusi():
    lama = _baca()
    hasil = _hasil_agen()
    rap = rapor_agen(hasil)
    rows = _seri()
    ka = kelas_a(rows)
    ka_lama = set(lama.get("kelas_a") or [])
    nm = lambda k: f"{k.split('|')[0].replace('USDT', '')} {k.split('|')[1]} {k.split('|')[2]}"
    naik = [nm(k) for k in sorted(ka - ka_lama)] if ka_lama else []
    turun = [nm(k) for k in sorted(ka_lama - ka)]
    jl, pem = jalur_minus(rows)
    cb = calon_combo(hasil)
    d = dict(t=time.time(), tanggal=time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600)), rapor=rap,
             naik=naik[:10], n_naik=len(naik), turun=turun[:10], n_turun=len(turun), kelas_a=sorted(ka), combo=cb,
             jalur=jl, pemimpin_jalur=pem)
    _tulis(d)
    return d


def jalankan(now=None):
    """Tiap menit dari listener. Sekali sehari antara 00:05 dan 00:20 WIB. Return pesan atau ''."""
    now = now or time.time()
    if not _baca():          # pertama kali jalan sesudah deploy: isi dewan dan Kelas A tanpa menunggu 00:05
        try:
            evolusi()
        except Exception as ex:
            print("[WARN] overmind awal", ex)
    w = time.gmtime(now + 7 * 3600)
    hari = time.strftime("%Y-%m-%d", w)
    if not (w.tm_hour == 0 and 5 <= w.tm_min <= 20) or _baca().get("tanggal") == hari:
        return ""
    d = evolusi()
    return "🧬 <b>QSE v150 | EVOLUSI HARIAN OVERMIND</b>\n\n" + ringkas(d)


def ringkas(d=None):
    d = d or _baca()
    if not d:
        return "🧬 Overmind belum jalan. Evolusi pertama 00:05 WIB."
    rows = [f"🧬 <b>OVERMIND</b> · evaluasi {d.get('tanggal', '-')}"]
    for x in d.get("rapor", []):
        if not x["n"]:
            rows.append(f"• {x['agen']}: belum ada trade live yang selesai (pencatat sudah tersambung, terisi begitu ada posisi tutup)")
            continue
        rows.append(f"{'👑' if x['pemimpin'] else '•'} {x['agen']}: {x['n']} trade terakhir, WR {x['wr']:.0f}%, {x['tot']:+.2f}R"
                    + (f", lot dewan {x['lot']:g}x" if x["lot"] != 1 else ""))
    jl = d.get("jalur") or {}
    if jl:
        rows.append("🧠 Jalur v150 (20 trade terakhir): " + ", ".join(
            f"{'👑 ' if j == d.get('pemimpin_jalur') else ''}{j} WR {x['wr']:.0f}% {x['tot']:+.1f}R{' 🟨 RINGAN' if x['minus'] else ''}"
            for j, x in sorted(jl.items(), key=lambda kv: -kv[1]["wr"])))
    rows.append(f"🏅 Kelas A (365 hari, minimal 4 sinyal, WR 68%+, PF 1.6+): {len(d.get('kelas_a') or kelas_a_aktif())} kombinasi koin x teknik x arah "
                "(dari riwayat 2025-2026 dan catatan live)")
    rows.append("⬆️ Naik ke Kelas A tadi malam: " + (", ".join(d.get("naik") or []) or "belum ada")
                + (f" (+{d['n_naik'] - 10} lagi)" if d.get("n_naik", 0) > 10 else ""))
    rows.append("⬇️ Dibuang dari Kelas A: " + (", ".join(d.get("turun") or []) or "belum ada")
                + (f" (+{d['n_turun'] - 10} lagi)" if d.get("n_turun", 0) > 10 else ""))
    if d.get("combo"):
        rows.append("🧪 Calon combo baru (tidak live, uji combo genetik PF 0.67): "
                    + "; ".join(f"{c['nama']} WR {c['wr']:.0f}% n {c['n']}" for c in d["combo"]))
    return "\n".join(rows)
