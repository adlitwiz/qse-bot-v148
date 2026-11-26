"""QSE v150 QC 150 - KOIN ANDALAN (permintaan user 26 Nov 2026: koin yang bagus di backtest dan bagus bulan ini).
Riset riset/upgrade/run_v269_andalan.py (hasil_v269_andalan.txt). Ukuran yang TERBUKTI: PF koin dari semua sinyal siaran yang sudah selesai
(minimal 20 sinyal) >= 1.5. Di dalam sinyal ELIT: PF 3.29 / 3.09 / 3.61 (uji, 12 bulan, 6 bulan) lawan ELIT biasa 2.82 / 2.25 / 2.63,
WR 50 / 50 / 44%. Lot ELIT di koin andalan x1.25: saldo 64843 / 769 / 310 / 263 lawan QC 148 55379 / 719 / 292 / 255, DD naik 0-2 poin.
Yang TIDAK terbukti dan hanya ditampilkan sebagai info: bulan ini untung (PF di dalam ELIT turun ke 1.43 di 6 bulan) dan menang beruntun
3 kali (koin PF >= 2 yang baru menang 3 kali beruntun: uji PF 0.44, 12 bulan 0.70). Koin yang sedang menang beruntun sering berbalik.
Profil koin: data/profil_andalan.json (backtest Jul 2022 sampai Okt 2026, aturan keluar QC 127, biaya ikut)."""
import json
import os
import time

DIR = os.path.dirname(os.path.abspath(__file__))
PF_MIN, N_MIN = 1.5, 20
LOT_ANDALAN = float(os.environ.get("QSE_LOT_ANDALAN", "1.25"))
_P = {}


def profil():
    if not _P:
        try:
            with open(os.path.join(DIR, "data", "profil_andalan.json")) as f:
                _P.update(json.load(f))
        except Exception as _ex:
            __import__("config").diam("qse_andalan.py:profil", _ex)
    return _P


def andalan(sym):
    p = profil().get(sym)
    return bool(p and p["n"] >= N_MIN and p["pf"] >= PF_MIN)


def bulan_ini(sym, now=None):
    """Hasil sinyal robot (semua jalur) koin ini yang selesai 30 hari terakhir: (n, menang, total R, menang beruntun terakhir)."""
    now = now or time.time()
    rs = []
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            for c in ST.lihat(k).get("closed", []):
                if c.get("sym") == sym and c.get("R") is not None and now - float(c.get("selesai") or 0) <= 30 * 86400:
                    rs.append((float(c.get("selesai") or 0), float(c["R"])))
    except Exception as _ex:
        __import__("config").diam("qse_andalan.py:bulan", _ex)
    rs.sort()
    ws = 0
    for _, r in reversed(rs):
        if r > 0:
            ws += 1
        else:
            break
    return len(rs), sum(1 for _, r in rs if r > 0), round(sum(r for _, r in rs), 2), ws


def teks_bulan(sym, now=None):
    n, m, tot, ws = bulan_ini(sym, now)
    if not n:
        return "bulan ini belum ada sinyal selesai"
    return f"bulan ini {n} sinyal, {m} menang, {tot:+.2f}R" + (f", menang beruntun {ws}" if ws >= 2 else "")


def baris(sym, now=None):
    """Satu baris untuk kartu sinyal. '' kalau bukan koin andalan atau saklar QSE_ANDALAN=0."""
    if os.environ.get("QSE_ANDALAN", "1") == "0" or not andalan(sym):
        return ""
    p = profil()[sym]
    return (f"🏆 <b>KOIN ANDALAN</b>: backtest 2022-2026 {p['n']} sinyal, menang {p['wr']:.0f}%, PF {p['pf']:.2f}. {teks_bulan(sym, now)}. "
            f"Sinyal ELIT di koin andalan lot x{LOT_ANDALAN:g} (uji PF 3.29 lawan 2.82).")


def daftar(maks=30):
    a = [(k, v) for k, v in profil().items() if v["n"] >= N_MIN and v["pf"] >= PF_MIN]
    return sorted(a, key=lambda z: (-z[1]["pf"], -z[1]["n"]))[:maks]


def teks(now=None):
    """/andalan: daftar koin andalan dengan hasil bulan ini."""
    d = daftar()
    if not d:
        return "🏆 <b>KOIN ANDALAN</b>\nProfil koin belum terbaca."
    rows = []
    for i, (s, p) in enumerate(d):
        rows.append(f"{i + 1}. {s.replace('USDT', '')}: PF {p['pf']:.2f}, menang {p['wr']:.0f}%, {p['n']} sinyal · {teks_bulan(s, now)}")
    return (f"🏆 <b>KOIN ANDALAN</b> (PF koin >= {PF_MIN:g}, minimal {N_MIN} sinyal, backtest Jul 2022 sampai Okt 2026): "
            f"{len(daftar(999))} koin\n" + "\n".join(rows)
            + "\n\nSinyal 💎 ELIT di koin ini lot x1.25 (uji PF 3.29, 12 bulan 3.09, 6 bulan 3.61). Hasil bulan ini hanya info: "
              "uji menunjukkan koin yang baru menang beruntun 3 kali justru sering berbalik (PF 0.44 di uji).")


# ---------- QC 151 PASANGAN WANGI: koin + teknik + arah yang terbukti sering profit ----------
# Riset riset/upgrade/run_v270_pasangan_wangi.py (hasil_v270_pasangan_wangi.txt). Jalan maju tanpa melihat masa depan.
#   Pasangan yang SELALU profit (WR 100%) tidak bertahan: 12 bulan dan 6 bulan menang 0%. Pasangan WR >= 70-80% juga rontok di uji.
#   Yang bertahan: riwayat pasangan minimal 5 sinyal selesai dan menang >= 60%.
#     semua sinyal  : PF 1.61 / 1.90 / 1.81 / 2.13, WR 42 / 46 / 45 / 44%.
#     di dalam ELIT : PF 12.85 / 5.95 / 3.55 / 5.39, WR 78 / 70 / 58 / 54% (ELIT biasa WR 61 / 47 / 44 / 43%).
#   Lot ELIT pasangan wangi x1.5 (di atas QC 150): saldo 73783 / 805 / 326 / 276 lawan 64843 / 769 / 310 / 263, DD 17 / 33 / 33 / 19%.
# Profil: data/profil_pasangan.json (backtest sampai Okt 2026) ditambah hasil buku jalur robot yang selesai sesudahnya.
WANGI_N, WANGI_WR = 5, 0.6
LOT_WANGI = float(os.environ.get("QSE_LOT_WANGI", "1.5"))
_PP = {}


def profil_pasangan():
    if not _PP:
        try:
            with open(os.path.join(DIR, "data", "profil_pasangan.json")) as f:
                _PP.update(json.load(f))
        except Exception as _ex:
            __import__("config").diam("qse_andalan.py:pasangan", _ex)
    return _PP


def pasangan(sym, k, arah):
    """(n, menang) riwayat pasangan: backtest + buku jalur robot yang selesai sesudah backtest."""
    kk = f"{sym}|{k}|{'L' if arah == 'LONG' else 'S'}"
    p = profil_pasangan().get(kk) or {}
    n, m, t0 = p.get("n", 0), p.get("m", 0), p.get("t", 0) / 1000
    try:
        import qse_strat as ST
        for c in ST.lihat(k).get("closed", []):
            if c.get("sym") == sym and c.get("arah") == arah and c.get("R") is not None and float(c.get("selesai") or 0) > t0:
                n += 1; m += float(c["R"]) > 0
    except Exception as _ex:
        __import__("config").diam("qse_andalan.py:pasangan_live", _ex)
    return n, m


def wangi(sym, k, arah):
    n, m = pasangan(sym, k, arah)
    return n >= WANGI_N and m / n >= WANGI_WR, n, m


def baris_wangi(sym, k, arah):
    if os.environ.get("QSE_ANDALAN", "1") == "0":
        return ""
    ya, n, m = wangi(sym, k, arah)
    if not ya:
        return ""
    return (f"🌹 <b>PASANGAN WANGI</b>: {sym.replace('USDT', '')} + teknik ini {arah}, riwayat {n} sinyal menang {m} ({m / n * 100:.0f}%). "
            f"Sinyal ELIT di pasangan wangi lot x{LOT_WANGI:g} (uji menang 70%, 12 bulan 58%, 6 bulan 54%).")
