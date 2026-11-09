"""QSE v150 CUACA PASAR (9 Nov 2026). Label tiga cuaca di kartu sinyal: 📈 FOLLOW THE TREND, ↩️ RETRACEMENT, ↔️ SIDEWAYS.
Jenis cuaca ditentukan oleh teknik (bukan ramalan): teknik tren = Follow The Trend, teknik pantulan di dalam tren = Retracement,
teknik pantulan batas rentang = Sideways. Kondisi koin sekarang dibaca dari efisiensi arah (ER) 20 candle 4J:
ER >= 0.35 tren, ER <= 0.20 mendatar. Baris juga menampilkan kelas koin dan rekam jejak teknik itu di koin itu (profil_koin)."""

JENIS = {
    "msb_hpz": "TREND", "smc_choch": "TREND", "ema_short": "TREND", "mcginley": "TREND", "ichimoku": "TREND", "sektor": "TREND",
    "donchian": "TREND", "8lengan": "TREND",
    "gzh": "RETRACE", "GZH": "RETRACE", "orderblock": "RETRACE", "fib": "RETRACE", "jatuh": "RETRACE",
    "snr_vol": "SIDEWAYS", "rsi_vol": "SIDEWAYS", "lalat": "SIDEWAYS", "sniper": "SIDEWAYS", "bb_squeeze": "SIDEWAYS",
}
NAMA = {"TREND": "📈 FOLLOW THE TREND", "RETRACE": "↩️ RETRACEMENT", "SIDEWAYS": "↔️ SIDEWAYS"}
KELUAR = {"TREND": "keluar ikut tren (SL berjalan)", "RETRACE": "TP pendek di pantulan, SL ke entry cepat",
          "SIDEWAYS": "TP di tengah rentang"}


def er(c, n=20):
    """Efisiensi arah: |gerak bersih| / jumlah gerak. 1 = lurus, 0 = bolak-balik."""
    if c is None or len(c) < n + 1:
        return None
    x = c[-n - 1:]
    tot = sum(abs(x[i] - x[i - 1]) for i in range(1, len(x)))
    return abs(x[-1] - x[0]) / tot if tot else 0.0


def kondisi(sym):
    try:
        import qse_strat as ST
        df = ST._k4(sym, 60)
        e = er(df["close"].values.astype(float)[:-1])
    except Exception:
        e = None
    if e is None:
        return None, ""
    return e, ("tren" if e >= 0.35 else "mendatar" if e <= 0.20 else "campur")


def jenis(k):
    return JENIS.get(str(k), "TREND")


def kelas_koin(sym, k, arah):
    """('A'|'B'|'C'|'SAMPAH', profil dict) dari rekam jejak koin x teknik x arah."""
    try:
        import qse_otak as O
        pr = O.profil(sym, k, arah)
    except Exception:
        return "", None
    if not pr or not pr.get("n") and not pr.get("gabungan"):
        return "", pr
    wr, pf = pr.get("wr", 0), pr.get("pf", 0)
    if pf < 1.0:
        kl = "SAMPAH"
    elif wr > 70:
        kl = "A"
    elif wr >= 62:
        kl = "B"
    else:
        kl = "C"
    return kl, pr


def baris(k, it):
    j = jenis(k)
    e, kd = kondisi(it["sym"])
    kl, pr = kelas_koin(it["sym"], k, it["arah"])
    t = f"🌦 Cuaca: <b>{NAMA[j]}</b> ({KELUAR[j]})"
    if e is not None:
        t += f"  ·  koin sekarang {kd} (ER {e:.2f})"
    try:
        import qse_overmind as OM
        ka = OM.label_kelas_a(it["sym"], k, it["arah"])
        if ka:
            t += f"\n{ka}"
    except Exception:
        pass
    if pr:
        src = f"gabungan {pr['gabungan']} sinyal semua koin" if pr.get("gabungan") else f"{pr['n']} sinyal koin ini"
        t += f"\n🏅 Kelas koin {kl or '-'}  ·  rekam jejak teknik ini: WR {pr['wr']:.0f}%, PF {pr['pf']:.2f} ({src})"
    return t
