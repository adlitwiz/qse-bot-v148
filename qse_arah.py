"""QSE v148 - /arah KOIN: baca pasar sekarang di 7 TF, kondisi hari yang sama di tahun-tahun sebelumnya,
pola harga kembar di sejarah koin ini, dan riwayat pola robot (DASBOR) yang sedang aktif.
Semua dihitung dari candle yang sudah tutup, data diambil saat perintah diketik (real time)."""
import calendar
import time
import numpy as np
import bybit_fetch as B

TF = [("15", "15m", 15), ("30", "30m", 30), ("60", "1J", 60), ("120", "2J", 120), ("240", "4J", 240),
      ("D", "1D", 1440), ("W", "1W", 10080)]


def _tutup(sym, iv, menit, bars):
    df = B._raw(sym, iv, bars)
    now = int(time.time() * 1000)
    return df[df.index + menit * 60000 <= now]


def _ema(x, n):
    k, out = 2 / (n + 1), np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(c, n=14):
    d = np.diff(c)
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(d)):
        au, ad = (au * (n - 1) + up[i]) / n, (ad * (n - 1) + dn[i]) / n
    return 100 - 100 / (1 + au / ad) if ad > 0 else 100.0


def _baca_tf(sym):
    """Tren tiap TF: close vs EMA20 vs EMA50, RSI14, perubahan candle terakhir."""
    rows, skor = [], 0
    for iv, nama, menit in TF:
        try:
            df = _tutup(sym, iv, menit, 200)
            c = df["close"].values.astype(float)
            if len(c) < 60:
                rows.append(f"{nama}: data kurang")
                continue
            e20, e50 = _ema(c, 20), _ema(c, 50)
            if c[-1] > e20[-1] > e50[-1]:
                tr, s = "NAIK", 1
            elif c[-1] < e20[-1] < e50[-1]:
                tr, s = "TURUN", -1
            else:
                tr, s = "campur", 0
            skor += s
            r = _rsi(c)
            ket = " jenuh beli" if r >= 70 else " jenuh jual" if r <= 30 else ""
            rows.append(f"{nama}: {tr} | RSI {r:.0f}{ket} | candle terakhir {(c[-1] / c[-2] - 1) * 100:+.2f}%")
        except Exception as ex:
            rows.append(f"{nama}: gagal diambil ({str(ex)[:40]})")
    kes = ("mayoritas NAIK" if skor >= 3 else "mayoritas TURUN" if skor <= -3 else "campur, belum ada arah kompak")
    return rows, skor, kes


def _hari_sama(sym):
    """Tanggal yang sama di tahun-tahun sebelumnya: gerak 7 hari sebelum dan 7 hari sesudah tanggal itu."""
    df = _tutup(sym, "D", 1440, 2000)
    if len(df) < 400:
        return ["Data harian belum cukup untuk tahun sebelumnya."], []
    idx = df.index.values
    c = df["close"].values.astype(float)
    now = time.gmtime()
    rows, nxt = [], []
    for th in range(now.tm_year - 1, now.tm_year - 6, -1):
        try:
            t = calendar.timegm((th, now.tm_mon, now.tm_mday, 0, 0, 0)) * 1000
        except Exception:
            continue
        i = int(np.searchsorted(idx, t))
        if i >= len(idx) or abs(idx[i] - t) > 86400000 or i < 7 or i + 7 >= len(c):
            continue
        sebelum = (c[i] / c[i - 7] - 1) * 100
        sesudah = (c[i + 7] / c[i] - 1) * 100
        besok = (c[i + 1] / c[i] - 1) * 100
        nxt.append(sesudah)
        rows.append(f"{th}: 7 hari sebelumnya {sebelum:+.1f}% | besoknya {besok:+.1f}% | 7 hari sesudahnya {sesudah:+.1f}%")
    if not rows:
        rows.append("Koin ini belum ada di tanggal yang sama tahun lalu.")
    return rows, nxt


def _kembar(sym, n=24, maju=6, k=20):
    """Pola kembar 4J: 24 candle terakhir dibandingkan dengan semua potongan di sejarah koin (korelasi gerak).
    Hasil: apa yang terjadi 6 candle (24 jam) sesudah potongan yang paling mirip, dibanding rata-rata biasa."""
    df = _tutup(sym, "240", 240, 3000)
    c = df["close"].values.astype(float)
    if len(c) < 400:
        return "Pola kembar: sejarah 4J belum cukup."
    r = np.diff(np.log(c))
    now = r[-n:]
    now = (now - now.mean()) / (now.std() + 1e-12)
    skor = []
    for i in range(n, len(r) - n - maju):          # potongan yang hasil 6 candle sesudahnya sudah diketahui
        w = r[i - n:i]
        sd = w.std()
        if sd <= 0:
            continue
        skor.append((float(np.dot((w - w.mean()) / sd, now) / n), i))
    skor.sort(reverse=True)
    pilih, pakai = [], []
    for s, i in skor:
        if s < 0.5 or len(pilih) >= k:
            break
        if all(abs(i - j) >= n for j in pakai):          # potongan tidak boleh tumpang tindih
            pilih.append(c[i + maju] / c[i] - 1)
            pakai.append(i)
    if len(pilih) < 5:
        return "Pola kembar 4J: belum ada pola yang cukup mirip (kurang dari 5)."
    pilih = np.array(pilih) * 100
    semua = (c[maju:] / c[:-maju] - 1) * 100
    naik, dasar = (pilih > 0).mean() * 100, (semua > 0).mean() * 100
    arah = "condong NAIK" if naik >= dasar + 10 else "condong TURUN" if naik <= dasar - 10 else "tidak beda dari biasa"
    return (f"Pola kembar 4J: {len(pilih)} pola mirip di sejarah koin ini. 24 jam sesudahnya naik {naik:.0f}% "
            f"(biasanya {dasar:.0f}%), median {np.median(pilih):+.2f}%. Kesimpulan: {arah}. "
            f"Uji di 25 koin: tebakan arah tepat 52%, jadi pakai sebagai info, bukan alasan entry.")


def _pola_robot(sym):
    """Pola DASBOR yang aktif sekarang dan riwayatnya di koin ini (dari scan 4J terakhir)."""
    import qse_saya as SY
    r = SY.hasil_robot(sym)
    if not r:
        return ["Koin ini belum ada di scan 4J terakhir."]
    rows = []
    for x in r["saran"][:3]:
        n = x["win"] + x["loss"]
        st = "EKSEKUSI" if x["eksekusi"] else "TAHAN"
        rows.append(f"{x['arah']} {x['pola']} ({st}, mutu {x['mutu']}): di sejarah koin ini {n} kali, "
                    f"{x['win']} TP dan {x['loss']} SL, WR {x['wr']:.0f}%, total {x['net_r']:+.1f}R"
                    + (", sampel kecil" if n < 12 else ""))
    if not rows:
        rows.append("Belum ada pola robot yang aktif di koin ini.")
    rows.append(f"Rapor robot koin ini {r['rapor']} | {r['trd']} trade | WR {r['wr']:.0f}% | PF {r['pf']:.2f}")
    return rows


def teks(args):
    sym = (args[0] if args else "BTC")
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    try:
        tf_rows, skor, kes = _baca_tf(sym)
    except Exception as ex:
        return f"{sym} gagal dibaca: {str(ex)[:100]}"
    blok = [f"<b>ARAH {sym}</b> (candle tutup, data saat ini)",
            "<b>Tren per TF</b>\n" + "\n".join(tf_rows) + f"\nKesimpulan 7 TF: {kes} (skor {skor:+d} dari ±7)"]
    try:
        hs, nxt = _hari_sama(sym)
        ring = ""
        if len(nxt) >= 2:
            ring = (f"\nRingkas: {sum(1 for x in nxt if x > 0)} dari {len(nxt)} tahun naik dalam 7 hari sesudahnya. "
                    f"Sampel kecil, pakai sebagai info saja.")
        blok.append("<b>Tanggal yang sama tahun-tahun sebelumnya</b>\n" + "\n".join(hs) + ring)
    except Exception as ex:
        blok.append(f"Tanggal yang sama tahun lalu gagal dihitung: {str(ex)[:60]}")
    try:
        blok.append(_kembar(sym))
    except Exception as ex:
        blok.append(f"Pola kembar gagal dihitung: {str(ex)[:60]}")
    blok.append("<b>Pola robot QSE sekarang di koin ini</b>\n" + "\n".join(_pola_robot(sym)))
    try:
        import qse_saya as SY
        blok.append(SY.baris_pasar())
    except Exception:
        pass
    return "\n\n".join(blok)


def _ringkas_tf(sym):
    rows, skor, kes = _baca_tf(sym)
    arah = [x.split(":")[0] + " " + x.split(":")[1].split("|")[0].strip() for x in rows if ":" in x]
    return f"{sym}: {kes} (skor {skor:+d}) | " + ", ".join(arah)


def harian():
    """Laporan otomatis tiap pagi (21 Okt 2026): hanya yang teruji dan bisa dipakai. Rencana hari ini, sinyal valid,
    posisi kamu, berita besar, BTC (info), spot DCA. Arah 7 TF, pola kembar, tanggal sama, dan siklus dihapus:
    uji arah BTC 24 jam dari indikator 48-52% (sama dengan acak), pola kembar 52%."""
    import time as _t
    import qse_saya as SY
    import qse_strat as ST
    import qse_porto as PO
    blok = []
    hari_ = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"][_t.gmtime(_t.time() + 7 * 3600).tm_wday]
    hh = PO.hari()
    rencana = {"senin": "hanya sinyal COMBO EMAS, COMBO FIX, atau COMBO 3+ yang dikirim (sinyal Senin lain PF 0.89). "
                        "Jadwal DCA BTC spot Rp100.000 hari ini.",
               "akhir_pekan": "sinyal tetap dikirim dengan lot setengah (uji 2021-2026 akhir pekan PF sekitar 0.9)."}.get(
        hh, "hari terbaik, sinyal normal dengan lot penuh (uji Selasa-Jumat PF 1.32-1.50).")
    blok.append(f"📅 <b>{hari_.upper()}</b>: {rencana}")
    try:
        sv = SY.sinyal_jalur(jam=True)
        blok.append("🎯 <b>SINYAL VALID SEKARANG</b> (urut prioritas)\n" + (sv if sv else
                    "Belum ada. Sinyal baru dikirim tiap candle 4J tutup: 03, 07, 11, 15, 19, 23 WIB."))
    except Exception as ex:
        print("[WARN] harian sinyal", ex)
    try:
        pos = [v for v in SY.lihat()["open"].values() if v["status"] in ("TERISI", "TP1", "MENUNGGU")]
        if pos:
            rows = ["👤 <b>POSISI KAMU</b>"]
            for v in pos[:8]:
                px = SY.harga_live(v["sym"]) or 0
                fl = SY.floating(v, px) if px else None
                rows.append(f"{'🟢' if v['arah'] == 'LONG' else '🔴'} {v['sym']} {v['arah']} "
                            + (f"{fl['r']:+.2f}R" if fl else SY.NM_ST.get(v["status"], v["status"]))
                            + (", ikut aturan jalur, tahan sampai SL atau TP" if v.get("ikut") else ""))
            blok.append("\n".join(rows))
    except Exception as ex:
        print("[WARN] harian posisi", ex)
    try:
        import qse_berita as BR
        ev = BR.hari_ini()
        blok.append("📰 <b>BERITA BESAR USD HARI INI</b>\n" + ("\n".join(
            f"• {e['judul']} jam {BR.jam_wib(e['ts'])[6:]}: sinyal baru ditahan 2 jam sebelum sampai 1 jam sesudah"
            + (". CPI/FOMC: robot kirim SIAGA sekitar 1 jam sebelum (tutup yang untung, tahan yang rugi)"
               if any(x in e["judul"].upper() for x in ("CPI", "FOMC", "FED", "INTEREST RATE")) else "")
            for e in ev[:5]) if ev else "Tidak ada."))
    except Exception:
        pass
    try:
        blok.append("₿ <b>BTC</b> (info, tidak dipakai menyaring sinyal)\n" + ST.btc_ema50_teks())
    except Exception:
        pass
    blok.append("Detail satu koin: /cek KOIN  ·  sinyal valid kapan saja: /sinyal4j  ·  hasil live: /jalur")
    return "\n\n".join(blok)
