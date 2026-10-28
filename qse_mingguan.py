"""QSE v148 - LAPORAN MINGGUAN: hasil live lawan hasil uji 2021-2026.
Dikirim listener Senin 06:20 WIB dan bisa dipanggil kapan saja dengan /mingguan.
Tiga bagian:
1. ROBOT: sinyal jalur terbukti yang selesai 7 hari terakhir (catatan robot sendiri, aturan jalur murni, sudah biaya 0.15% harga),
   dibanding rata-rata per trade jalur itu di uji (qse_catat.EXP_UJI).
2. TIAP ORANG: trade yang dicatat bot dengan aturan keluar final (TP 20% di +0.5R, jam ke-8, jeda). R dikurangi biaya 0.15% harga
   seperti di uji, lalu dibanding uji portofolio satu orang: WR 60%, PF 1.75, rata +0.17R, SL penuh 4.3%
   (riset/porto/hasil_pf_final.txt, baris jam 8 SL -0.5R + jeda 3 kalah 24 jam).
3. HARGA ISI: harga entry kamu lawan harga sinyal robot, dalam R dan persen harga.
Satu minggu itu sampel kecil. Penilaian 'di bawah uji' atau 'sesuai uji' baru keluar setelah 100 trade."""
import calendar
import html
import time

HARI = 7
MIN_NILAI = 100
UJI = dict(wr=60.2, pf=1.75, rata=0.17, slp=4.3)
ATURAN_BARU = calendar.timegm((2026, 10, 27, 0, 0, 0)) * 1000         # TP 20% dan jam ke-8 mulai dipakai, trade lama aturan lain
JENDELA_SINYAL = 36 * 3600                                            # isi dihitung milik sinyal kalau terjadi dalam 36 jam sesudahnya


def _stat(rs):
    n = len(rs)
    if not n:
        return dict(n=0, wr=0.0, pf=0.0, net=0.0, avg=0.0, tanpa_rugi=False)
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    return dict(n=n, wr=sum(r > 0 for r in rs) / n * 100, pf=(pos / neg if neg > 0 else 0.0), net=sum(rs), avg=sum(rs) / n,
                tanpa_rugi=neg <= 0 < pos)


def _fmt(s):
    if not s["n"]:
        return "belum ada trade selesai"
    pf = "PF tanpa rugi" if s["tanpa_rugi"] else f"PF {s['pf']:.2f}"
    return f"{s['n']} trade, WR {s['wr']:.0f}%, {pf}, rata {s['avg']:+.2f}R, total {s['net']:+.1f}R"


def _nilai(s, pembanding, selisih=0.10):
    """Penilaian jujur: di bawah MIN_NILAI trade tidak dinilai."""
    if s["n"] < MIN_NILAI:
        return f"Belum bisa dinilai ({s['n']} dari {MIN_NILAI} trade)"
    if pembanding is None:
        return ""
    return f"Di bawah uji ({pembanding:+.2f}R)" if s["avg"] < pembanding - selisih else f"Sesuai uji ({pembanding:+.2f}R)"


def _tgl(t):
    g = time.gmtime(t + 7 * 3600)
    return f"{g.tm_mday}/{g.tm_mon}"


# ---------------- 1. robot ----------------
def bagian_robot(now, hari=HARI):
    import qse_catat as CT
    data = CT._tutup_terbukti()                                       # (kunci jalur, nama, item) hanya yang punya R
    if not data:
        return ["", "🤖 <b>ROBOT</b>: belum ada sinyal selesai di catatan."]
    batas = now - hari * 86400
    mg = [(k, n, c) for k, n, c in data if c.get("selesai", 0) >= batas]
    rows = ["", "🤖 <b>ROBOT, semua sinyal jalur terbukti</b> (aturan jalur murni, sudah biaya)"]
    s7 = _stat([float(c["R"]) for _, _, c in mg])
    sa = _stat([float(c["R"]) for _, _, c in data])
    # pembanding: rata-rata uji tiap jalur dibobot jumlah trade jalur itu
    def exp_campur(x):
        w = [CT.EXP_UJI[k] for k, _, _ in x if CT.EXP_UJI.get(k) is not None]
        return sum(w) / len(w) if w else None
    rows.append(f"• 7 hari: {_fmt(s7)}")
    rows.append(f"• Tercatat: {_fmt(sa)}. {_nilai(sa, exp_campur(data))}")
    grup = {}
    for k, n, c in mg:
        grup.setdefault((k, n), []).append(float(c["R"]))
    besar = [(sum(v), k, n, len(v)) for (k, n), v in grup.items() if len(v) >= 3]
    if besar:
        besar.sort(reverse=True)
        pilih = besar[:2] + [b for b in besar[-2:] if b not in besar[:2] and b[0] < 0]
        rows.append("• Jalur minggu ini (minimal 3 trade): " + ", ".join(f"{n} {t:+.1f}R ({m} trade)" for t, _, n, m in pilih))
    return rows


# ---------------- 3. harga isi lawan sinyal ----------------
def _sinyal_robot():
    """Semua sinyal robot (terbuka dan selesai) dari tiap jalur: list dict(sym, arah, entry, t, risk)."""
    srcs = []
    try:
        import qse_strat as ST
        srcs += [ST.lihat(k) for k in ST.STRAT]
    except Exception as ex:
        print("[WARN] mingguan strat", ex)
    for modul in ("qse_ichimoku", "qse_ob"):
        try:
            srcs.append(__import__(modul).lihat())
        except Exception as ex:
            print("[WARN] mingguan", modul, ex)
    out = []
    for d in srcs:
        for it in list((d.get("open") or {}).values()) + list(d.get("closed") or []):
            try:
                e, t = float(it["entry"]), float(it["t"])
                r = float(it.get("risk") or abs(e - float(it.get("sl0") or it["sl"])))
                if e > 0 and r > 0:
                    out.append(dict(sym=it["sym"], arah=it["arah"], entry=e, t=t, risk=r))
            except Exception:
                continue
    return out


def selisih_isi(trades, sinyal):
    """Untuk tiap trade yang diisi dalam JENDELA_SINYAL sesudah sinyal robot di koin dan arah sama: selisih harga isi lawan harga
    sinyal. Positif = isi lebih buruk (LONG lebih mahal, SHORT lebih murah). Return list dict(r, pct)."""
    hasil = []
    for c in trades:
        if not (c.get("ikut") or str(c.get("jalur", "manual")) != "manual"):
            continue
        ts = (c.get("fill_ts") or c.get("created_ts") or 0) / 1000
        if not ts:
            continue
        calon = [s for s in sinyal if s["sym"] == c.get("sym") and s["arah"] == c.get("arah")
                 and s["t"] - 900 <= ts <= s["t"] + JENDELA_SINYAL]
        if not calon:
            continue
        s = max(calon, key=lambda z: z["t"])
        arah = 1 if s["arah"] == "LONG" else -1
        sel = (float(c["entry"]) - s["entry"]) * arah
        hasil.append(dict(r=sel / s["risk"], pct=sel / s["entry"] * 100))
    return hasil


# ---------------- 2. tiap orang ----------------
def _r_bersih(c):
    """R trade dikurangi biaya 0.15% harga (sama dengan uji). Bot mencatat R sebelum biaya."""
    try:
        import qse_strat as ST
        r0 = float(c.get("risk0") or abs(float(c["entry"]) - float(c["sl"])))
        biaya = ST.BIAYA * float(c["entry"]) / r0 if r0 > 0 else 0.0
        return float(c["result_r"]) - (biaya if biaya < 1.0 else 0.0)
    except Exception:
        return float(c["result_r"])


def _trade_selesai(uid):
    import qse_saya as SY
    d = SY._baca(SY._path_uid(uid))
    return [c for c in d.get("closed", []) if c.get("why") in SY.SELESAI and c.get("result_r") is not None and c.get("closed_ts")]


def bagian_orang(now, hari=HARI):
    import qse_saya as SY
    try:
        import qse_modal as MD
    except Exception:
        MD = None
    daftar = SY.daftar_pengguna()
    banyak = len(daftar) > 1
    sinyal = _sinyal_robot()
    rows = []
    batas = (now - hari * 86400) * 1000
    for u in daftar:
        try:
            cl = _trade_selesai(u)
        except Exception as ex:
            print("[WARN] mingguan trade", u, ex)
            continue
        nama = html.escape(str(SY.nama_pengguna(u))) if banyak else "kamu"
        baru = [c for c in cl if (c.get("fill_ts") or c.get("created_ts") or 0) >= ATURAN_BARU]
        m7 = [c for c in baru if c["closed_ts"] >= batas]
        rows += ["", f"👤 <b>{nama.upper() if banyak else 'TRADE KAMU'}</b> (aturan keluar final: TP 20%, jam ke-8, jeda)"]
        if not baru:
            rows.append("• Belum ada trade selesai dengan aturan final (mulai 27 Okt 2026).")
            continue
        r7 = [_r_bersih(c) for c in m7]
        ra = [_r_bersih(c) for c in baru]
        s7, sa = _stat(r7), _stat(ra)
        usd = MD.teks_pmodal(s7["net"], u if u else None) if (MD and s7["n"]) else ""
        rows.append(f"• 7 hari: {_fmt(s7)} setelah biaya{usd}")
        if s7["n"]:
            slp = sum(1 for c in m7 if float(c["result_r"]) <= -0.9)
            rows.append(f"• SL penuh: {slp} dari {s7['n']} ({slp / s7['n'] * 100:.0f}%). Uji: {UJI['slp']:g}%")
        rows.append(f"• Sejak 27 Okt: {_fmt(sa)}. {_nilai(sa, UJI['rata'])}")
        rows.append(f"• Uji 2021-2026: WR {UJI['wr']:.0f}%, PF {UJI['pf']:.2f}, rata {UJI['rata']:+.2f}R per trade")
        sel = selisih_isi(m7, sinyal)
        if sel:
            rata = sum(x["r"] for x in sel) / len(sel)
            luar = sum(1 for x in sel if x["r"] > 0.5)
            pct = sum(x["pct"] for x in sel) / len(sel)
            rows.append(f"• Harga isi lawan sinyal robot ({len(sel)} dari {s7['n']} trade cocok): rata {abs(rata):.2f}R "
                        f"{'lebih buruk' if rata > 0 else 'lebih baik'} dari harga sinyal ({abs(pct):.2f}% harga), "
                        f"terburuk {max(x['r'] for x in sel):+.2f}R, {luar} di luar range 0.5R")
    return rows


def teks(now=None, hari=HARI):
    now = now or time.time()
    rows = [f"📅 <b>QSE v148 | LAPORAN MINGGUAN</b> ({_tgl(now - hari * 86400)} sampai {_tgl(now)})",
            "Hasil live lawan uji 2021-2026. Satu minggu itu sampel kecil, jangan ubah aturan dari satu minggu saja."]
    for fn in (bagian_robot, bagian_orang):
        try:
            rows += fn(now, hari)
        except Exception as ex:
            print("[WARN] mingguan", fn.__name__, ex)
            rows += ["", f"⚠️ Bagian {fn.__name__.replace('bagian_', '')} gagal dibuat: {html.escape(str(ex))[:80]}"]
    return "\n".join(rows)
