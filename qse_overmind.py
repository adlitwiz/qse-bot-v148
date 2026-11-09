"""QSE v150 OVERMIND (9 Nov 2026, permintaan user). Dewan hakim di atas agen Gurita, Lalat Abdul, Jalur v150, Sektor, dan GZH pantulan.
Berjalan sendiri tiap hari 00:05 WIB di VPS (dipanggil listener tiap menit, kerja sekali sehari).
1. Rapor agen: 20 trade selesai terakhir tiap agen (WR, total R). Agen dengan WR tertinggi jadi PEMIMPIN.
   Bobot lot: pemimpin 1x, agen dengan 20 trade terakhir minus 0.5x sampai kembali positif. Bobot hanya dipakai kartu kalau env
   QSE_OVERMIND_LOT=1, karena pengalokasian dinamis ini belum bisa diuji mundur (catatan live agen baru beberapa minggu).
2. Evolusi koin 14 hari: koin x jalur x arah yang 14 hari terakhir live-nya naik kelas (PF rekam jejak gabungan backtest + live >= 1.3)
   atau turun kelas dicatat. profil_koin.json sendiri sudah otomatis menggabungkan catatan live (qse_otak.profil), jadi tidak ditimpa.
3. Calon combo baru: pasangan jalur yang menunjuk koin dan arah sama dalam 8 jam dan menang >= 75% dengan minimal 15 kejadian
   (90 hari) dicatat sebagai CALON. Tidak langsung live: uji v161 menunjukkan memilih dari sampel kecil (koin x teknik WR >= 68%)
   jatuh ke WR 63% dan -0.04R di data berikutnya. Calon naik live hanya lewat uji data lokal di riset.
4. Ringkasan tampil di atas menu Otak Gurita dan Info."""
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
        out["🟡 GZH pantulan"] = [(c.get("selesai", 0), c["R"], c["sym"], "LONG", "gzh2") for c in GZ._baca().get("closed", [])]
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


def evolusi():
    hasil = _hasil_agen()
    rap = rapor_agen(hasil)
    naik, turun = evolusi_koin()
    cb = calon_combo(hasil)
    d = dict(t=time.time(), tanggal=time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600)), rapor=rap,
             naik=naik[:10], turun=turun[:10], combo=cb)
    _tulis(d)
    return d


def jalankan(now=None):
    """Tiap menit dari listener. Sekali sehari antara 00:05 dan 00:20 WIB. Return pesan atau ''."""
    now = now or time.time()
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
        rows.append(f"{'👑' if x['pemimpin'] else '•'} {x['agen']}: {x['n']} trade terakhir, WR {x['wr']:.0f}%, {x['tot']:+.2f}R"
                    + (f", lot dewan {x['lot']:g}x" if x["lot"] != 1 else ""))
    rows.append("⬆️ Naik kelas tadi malam: " + (", ".join(d.get("naik") or []) or "belum ada"))
    rows.append("⬇️ Dibuang tadi malam: " + (", ".join(d.get("turun") or []) or "belum ada"))
    if d.get("combo"):
        rows.append("🧪 Calon combo baru (belum live, perlu uji data lokal): "
                    + "; ".join(f"{c['nama']} WR {c['wr']:.0f}% n {c['n']}" for c in d["combo"]))
    if os.environ.get("QSE_OVERMIND_LOT", "0") != "1":
        rows.append("Bobot lot dewan: info saja (nyalakan dengan QSE_OVERMIND_LOT=1).")
    return "\n".join(rows)
