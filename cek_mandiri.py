"""QSE v150 QC 142 - CEK MANDIRI dan PENJALAN TES.
1. muat_semua(): dipanggil listener saat hidup. Semua modul qse_*.py, config, telegram_notify, bybit_fetch dimuat. Return list (modul, error).
2. python3 cek_mandiri.py        : cek muat semua modul (cepat, tanpa jaringan).
   python3 cek_mandiri.py --semua: jalankan seluruh tes regresi riset/upgrade/uji_*.py dan riset/v150/uji_*.py, tiap tes di folder state
   sementara sendiri (state VPS tidak tersentuh). Keluar dengan kode 1 kalau ada yang gagal. Jalankan ini sebelum restart sesudah update."""
import glob
import importlib
import os
import subprocess
import sys
import tempfile
import time

DIR = os.path.dirname(os.path.abspath(__file__))
LEWATI = {"uji_fokus.py"}          # butuh file data riset besar yang tidak ikut repo


def muat_semua():
    gagal = []
    sys.path.insert(0, DIR)
    nama = ["config", "telegram_notify", "bybit_fetch"] + sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(DIR, "qse_*.py")))
    for m in nama:
        try:
            importlib.import_module(m)
        except Exception as ex:
            gagal.append((m, f"{type(ex).__name__}: {ex}"[:200]))
    return gagal


def tes_semua():
    tes = sorted(glob.glob(os.path.join(DIR, "riset", "upgrade", "uji_*.py")) + glob.glob(os.path.join(DIR, "riset", "v150", "uji_*.py")))
    tes = [t for t in tes if os.path.basename(t) not in LEWATI]
    gagal = []
    t0 = time.time()
    for t in tes:
        env = dict(os.environ, QSE_STATE_DIR=tempfile.mkdtemp(prefix="qse_uji_"))
        env.pop("TELEGRAM_BOT_TOKEN", None); env.pop("ANTHROPIC_API_KEY", None)
        try:
            r = subprocess.run([sys.executable, os.path.basename(t)], cwd=os.path.dirname(t), env=env, capture_output=True, text=True, timeout=600)
            ok = r.returncode == 0
            ekor = (r.stdout + r.stderr).strip().splitlines()[-3:]
        except subprocess.TimeoutExpired:
            ok, ekor = False, ["waktu habis 600 detik"]
        print(("LULUS " if ok else "GAGAL ") + os.path.relpath(t, DIR), flush=True)
        if not ok:
            gagal.append(t)
            print("   " + "\n   ".join(ekor), flush=True)
    print(f"\n{len(tes) - len(gagal)} dari {len(tes)} tes lulus dalam {time.time() - t0:.0f} detik.")
    return gagal


if __name__ == "__main__":
    os.environ.setdefault("QSE_STATE_DIR", tempfile.mkdtemp(prefix="qse_cek_"))
    g = muat_semua()
    for m, e in g:
        print(f"GAGAL MUAT {m}: {e}")
    print(f"muat modul: {'semua OK' if not g else str(len(g)) + ' gagal'}")
    if "--semua" in sys.argv:
        g = g or tes_semua()
    sys.exit(1 if g else 0)
