"""QSE v150 - PETA KOMANDO BTC.
Arah BTC di 1J, 4J, 1D dari McGinley Dynamic (close di atas garis yang menanjak = naik), volume objektif
(volume candle naik lawan turun 6 candle 4J terakhir), order flow (letak close di range x volume, 24 candle 1J),
struktur smart money (puncak dan lembah 4J terakhir), support resistance terdekat, dan zona likuiditas
(puncak atau lembah 7 hari yang belum tersapu, puncak kembar lebih kuat).
Kesimpulan FOKUS LONG, FOKUS SHORT, atau TAHAN dipakai untuk URUTAN dan LABEL sinyal, bukan penghalang:
uji 2021-2026 (riset/upgrade/hasil_g8.txt) sinyal lawan arah BTC rata-rata tetap untung +0.10 sampai +0.17R,
membuang semuanya menurunkan total profit NILAI 8+ dari +314R ke +215R."""
import time
import numpy as np

_CACHE = {"t": 0, "v": None}


def _ema(x, n):
    a = 2.0 / (n + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def _mcginley(c, n, k=0.6):
    md = np.empty(len(c))
    md[0] = c[0]
    for i in range(1, len(c)):
        md[i] = md[i - 1] + (c[i] - md[i - 1]) / max(k * n * (c[i] / md[i - 1]) ** 4, 1.0)
    return md


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.empty(len(tr))
    out[0] = tr[0]
    for i in range(1, len(tr)):
        out[i] = out[i - 1] + (tr[i] - out[i - 1]) / n
    return out


def keadaan(c, n):
    """+1 naik, -1 turun, 0 sideways (McGinley n, sama dengan riset v150 trend_state)."""
    if len(c) < n + 5:
        return 0
    md = _mcginley(c, n)
    e = _ema(c, 50 if n >= 30 else 20)
    if c[-1] > md[-1] and md[-1] > md[-2] and c[-1] > e[-1]:
        return 1
    if c[-1] < md[-1] and md[-1] < md[-2] and c[-1] < e[-1]:
        return -1
    return 0


def vol_objektif(o, c, v, n=6):
    """(volume naik - volume turun) / volume total, n candle terakhir. +1 = semua volume di candle naik."""
    o, c, v = o[-n:], c[-n:], v[-n:]
    up = v[c > o].sum()
    dn = v[c < o].sum()
    return float((up - dn) / max(v.sum(), 1e-12))


def order_flow(o, h, l, c, v, n=24):
    """Aliran order dari candle: volume x letak close di range. +1 beli agresif, -1 jual agresif."""
    o, h, l, c, v = o[-n:], h[-n:], l[-n:], c[-n:], v[-n:]
    r = np.where(h > l, h - l, np.nan)
    d = np.nan_to_num(v * ((c - l) - (h - c)) / r)
    return float(d.sum() / max(v.sum(), 1e-12))


def pivot(h, l, k=3):
    """Indeks puncak dan lembah (k candle kiri kanan lebih rendah/tinggi)."""
    ph, pl = [], []
    for i in range(k, len(h) - k):
        if h[i] == h[i - k:i + k + 1].max() and h[i] > h[i - k:i].max():          # puncak datar tidak dihitung dua kali
            ph.append(i)
        if l[i] == l[i - k:i + k + 1].min() and l[i] < l[i - k:i].min():
            pl.append(i)
    return ph, pl


def snr(h, l, c, k=3, lb=150):
    """Support terdekat di bawah harga dan resistance terdekat di atas dari pivot candle (lb candle terakhir)."""
    h, l = h[-lb:], l[-lb:]
    px = c[-1]
    ph, pl = pivot(h, l, k)
    lv = [h[i] for i in ph] + [l[i] for i in pl]
    sup = max([x for x in lv if x < px], default=None)
    res = min([x for x in lv if x > px], default=None)
    return sup, res


def struktur(h, l, k=3):
    """Struktur smart money dari 2 puncak dan 2 lembah terakhir: HH+HL naik, LH+LL turun, selain itu campur."""
    ph, pl = pivot(h, l, k)
    if len(ph) < 2 or len(pl) < 2:
        return 0, "belum jelas"
    hh = h[ph[-1]] > h[ph[-2]]
    hl = l[pl[-1]] > l[pl[-2]]
    if hh and hl:
        return 1, "HH + HL (naik)"
    if not hh and not hl:
        return -1, "LH + LL (turun)"
    return 0, ("HH + LL (melebar)" if hh else "LH + HL (menyempit)")


def likuiditas(h, l, c, jam=168, k=3, tol=0.0015):
    """Zona likuiditas 1J: puncak di atas harga dan lembah di bawah harga dalam `jam` terakhir yang belum tersapu
    (belum ada harga yang melewatinya sesudah terbentuk). Puncak/lembah kembar (selisih <= tol) ditandai lebih kuat.
    Return (atas, bawah): daftar (harga, kembar) terdekat dulu."""
    h, l = h[-jam:], l[-jam:]
    px = c[-1]
    ph, pl = pivot(h, l, k)
    atas, bawah = [], []
    for i in ph:
        if h[i] > px and h[i + 1:].max(initial=-np.inf) <= h[i]:
            kembar = any(j != i and abs(h[j] / h[i] - 1) <= tol for j in ph)
            atas.append((float(h[i]), kembar))
    for i in pl:
        if l[i] < px and l[i + 1:].min(initial=np.inf) >= l[i]:
            kembar = any(j != i and abs(l[j] / l[i] - 1) <= tol for j in pl)
            bawah.append((float(l[i]), kembar))
    atas.sort(key=lambda z: z[0])
    bawah.sort(key=lambda z: -z[0])
    return atas[:3], bawah[:3]


def hitung(d1, d4, dD):
    """d1, d4, dD: DataFrame candle tutup (open high low close volume) 1J, 4J, 1D. Return dict peta BTC."""
    g = lambda df, k: df[k].values.astype(float)
    c1, c4, cD = g(d1, "close"), g(d4, "close"), g(dD, "close")
    s1, s4, sD = keadaan(c1, 34), keadaan(c4, 34), keadaan(cD, 14)
    vo = vol_objektif(g(d4, "open"), c4, g(d4, "volume"))
    fl = order_flow(g(d1, "open"), g(d1, "high"), g(d1, "low"), c1, g(d1, "volume"))
    st, st_t = struktur(g(d4, "high"), g(d4, "low"))
    sup4, res4 = snr(g(d4, "high"), g(d4, "low"), c4)
    supD, resD = snr(g(dD, "high"), g(dD, "low"), cD, k=2, lb=90)
    atas, bawah = likuiditas(g(d1, "high"), g(d1, "low"), c1)
    skor = s1 + s4 + 2 * sD + (1 if vo > 0.2 else -1 if vo < -0.2 else 0) + (1 if fl > 0.1 else -1 if fl < -0.1 else 0) + st
    fokus = "LONG" if skor >= 3 else "SHORT" if skor <= -3 else "TAHAN"
    a4 = _atr(g(d4, "high"), g(d4, "low"), c4)[-1]
    return dict(px=float(c1[-1]), s1=s1, s4=s4, sD=sD, vol=vo, flow=fl, struktur=st, struktur_t=st_t, sup4=sup4, res4=res4,
                supD=supD, resD=resD, liq_atas=atas, liq_bawah=bawah, skor=int(skor), fokus=fokus, atr4=float(a4))


def peta(maks_umur=300):
    """Peta BTC dari Bybit, disimpan 5 menit."""
    now = time.time()
    if _CACHE["v"] is not None and now - _CACHE["t"] < maks_umur:
        return _CACHE["v"]
    import bybit_fetch as B
    ms = int(now * 1000)
    d1 = B._raw("BTCUSDT", "60", 400)
    d1 = d1[d1.index + 3600000 <= ms]
    d4 = B._raw("BTCUSDT", "240", 300)
    d4 = d4[d4.index + 14400000 <= ms]
    dD = B._raw("BTCUSDT", "D", 200)
    dD = dD[dD.index + 86400000 <= ms]
    v = hitung(d1, d4, dD)
    try:
        v["px"] = float(B.get_tickers()["BTCUSDT"]["last"]) or v["px"]
    except Exception:
        pass
    _CACHE.update(t=now, v=v)
    return v


_IK = {1: "🟢 naik", -1: "🔴 turun", 0: "⚪ sideways"}


def _f(x):
    return "-" if x is None else f"{x:,.0f}"


def teks(p=None, singkat=False):
    p = p or peta()
    fk = {"LONG": "🟢 <b>FOKUS LONG</b>", "SHORT": "🔴 <b>FOKUS SHORT</b>", "TAHAN": "⏸ <b>TAHAN, DUA ARAH SELEKTIF</b>"}[p["fokus"]]
    if singkat:
        return (f"🧭 Peta BTC {p['px']:,.0f}  ·  {fk} (skor {p['skor']:+d})  ·  1J {_IK[p['s1']]} · 4J {_IK[p['s4']]} · 1D {_IK[p['sD']]}  ·  "
                f"support {_f(p['sup4'])} / resistance {_f(p['res4'])}. Peta kondisi, bukan ramalan harga")
    la = ", ".join(f"{x:,.0f}{' (kembar)' if k else ''}" for x, k in p["liq_atas"]) or "-"
    lb = ", ".join(f"{x:,.0f}{' (kembar)' if k else ''}" for x, k in p["liq_bawah"]) or "-"
    vol = "beli dominan" if p["vol"] > 0.2 else "jual dominan" if p["vol"] < -0.2 else "seimbang"
    fl = "beli agresif" if p["flow"] > 0.1 else "jual agresif" if p["flow"] < -0.1 else "netral"
    target = None
    if p["fokus"] == "LONG" and p["liq_atas"]:
        target = f"sapuan ke atas {p['liq_atas'][0][0]:,.0f}"
    elif p["fokus"] == "SHORT" and p["liq_bawah"]:
        target = f"sapuan ke bawah {p['liq_bawah'][0][0]:,.0f}"
    return "\n".join([
        f"🧭 <b>PETA KOMANDO BTC</b>  ·  harga {p['px']:,.0f}",
        f"• Tren McGinley: 1J {_IK[p['s1']]}, 4J {_IK[p['s4']]}, 1D {_IK[p['sD']]}",
        f"• Volume 6 candle 4J: {vol} ({p['vol']:+.2f})  ·  order flow 24 jam: {fl} ({p['flow']:+.2f})",
        f"• Struktur 4J: {p['struktur_t']}",
        f"• Support 4J {_f(p['sup4'])}, resistance 4J {_f(p['res4'])}  ·  harian S {_f(p['supD'])} / R {_f(p['resD'])}",
        f"• Likuiditas di atas (stop short): {la}",
        f"• Likuiditas di bawah (stop long): {lb}",
        f"👉 {fk} (skor {p['skor']:+d} dari -8 sampai +8)" + (f". Target sapuan berikutnya: {target}" if target else ""),
        "Ini peta kondisi, bukan ramalan harga BTC: uji 2019-2026 tebakan arah BTC 24 jam dari FOKUS benar 44-53% (lempar koin). "
        "Gunanya untuk sinyal altcoin: searah FOKUS rata +0.10R per sinyal, lawan FOKUS +0.02R (riset/v150/hasil_fokus_btc.txt). "
        "Menahan semua sinyal lawan FOKUS menurunkan profit 2025-2026, jadi tetap dikirim dengan tanda.",
    ])


def label_sinyal(arah):
    """Baris pendek untuk kartu sinyal: searah atau lawan komando BTC."""
    try:
        p = peta()
    except Exception:
        return ""
    if p["fokus"] == "TAHAN":
        return f"🧭 Komando BTC: TAHAN (skor {p['skor']:+d}), pilih sinyal NILAI tertinggi saja"
    if p["fokus"] == arah:
        return f"🧭 Searah komando BTC (FOKUS {p['fokus']}, skor {p['skor']:+d})"
    return (f"↔️ Lawan komando BTC (FOKUS {p['fokus']}, skor {p['skor']:+d}): boleh, tapi uji 2021-2026 rata hanya +0.02R per sinyal "
            f"lawan +0.10R kalau searah. Pilih yang searah kalau slot terbatas")


TF_TEKS = ("⏱ <b>Sinyal TF 4J</b> (candle 4 jam tutup) · konfirmasi akurasi tinggi · gaya swing cepat: TP 20% biasanya kena dalam "
           "beberapa jam, posisi belum aman maks 30 jam")


# Skor keyakinan dari tingkat NILAI (riset/upgrade/hasil_g20.txt, sinyal lolos profil koin, 2023-2026):
# tanpa label rata +0.086R PF 1.32, NILAI 8 +0.091R PF 1.35, NILAI 9 +0.135R PF 1.57, NILAI 10 +0.240R PF 2.19 (WR 66%).
# PF profil koin yang lebih tinggi (2, 3, ke atas) TIDAK memberi hasil lebih baik, jadi tidak menaikkan skor.
SKOR = ((8, 90, "NILAI 10", "+0.24R", "2.19", "66%"), (5, 75, "NILAI 9", "+0.14R", "1.57", "65%"),
        (3, 60, "NILAI 8", "+0.09R", "1.35", "60%"), (-99, 55, "tanpa label", "+0.09R", "1.32", "60%"))


def _cari_it(sym, arah):
    """Sinyal jalur terbaru untuk koin dan arah ini dari catatan jalur (berisi profil koin)."""
    best = None
    sumber = []
    try:
        import qse_strat as ST
        sumber += [(k, ST.lihat(k)["open"].values()) for k in ST.STRAT]
    except Exception:
        pass
    for mod, k in (("qse_ichimoku", "ichimoku"), ("qse_ob", "orderblock")):
        try:
            sumber.append((k, __import__(mod).lihat()["open"].values()))
        except Exception:
            pass
    for k, items in sumber:
        for it in items:
            if it.get("sym") == sym and it.get("arah") == arah and (best is None or it.get("t", 0) > best[1].get("t", 0)):
                best = (k, it)
    return best


def baris_skor(nilai, sym=None, arah=None, kunci_it=None):
    """Baris skor keyakinan, label prioritas, kategori masuk, dan rekam jejak koin."""
    rows = []
    for batas, skor, nm, rr, pf, wr in SKOR:
        if nilai >= batas:
            break
    if nilai >= 8:
        rows.append("🏆 <b>SINYAL PRIORITAS UTAMA</b> (NILAI 10: uji 2023-2026 PF 2.19, WR 66%, rata +0.24R per sinyal)")
    rows.append(f"💯 <b>Skor keyakinan {skor}/100</b> ({nm}: uji 2023-2026 PF {pf}, WR {wr}, rata {rr} per sinyal)")
    rows.append("🎯 Kategori: <b>IKUTI ARUS, masuk MARKET sekarang</b>. Uji 2021-2026: menunggu koreksi atau pantulan membuang sinyal "
                "terbaik yang langsung lari (hasil_g15, g16, g17)")
    if kunci_it:
        k, it = kunci_it
        pr = it.get("profil")
        if pr:
            rows.append(f"🧪 Rekam jejak {sym} {k} {arah}: 2024-2026 {pr['n24']} sinyal, WR {pr['wr24']:.0f}%, PF {pr['pf24']:.2f} "
                        f"(sejak 2021: {pr['n']} sinyal, PF {pr['pf']:.2f}). Lulus gerbang profil koin.")
    return rows


def baris_kartu(m, pr=None):
    """Baris tambahan kartu sinyal: asal TF, skor, kategori, rekam jejak koin, support/resistance 4J, komando BTC."""
    import re
    x = re.search(r"<b>\d+\. ([A-Z0-9]+USDT) (LONG|SHORT)</b>", m or "")
    rows = [TF_TEKS]
    if not x:
        return rows
    sym, arah = x.group(1), x.group(2)
    try:
        rows += baris_skor(int(pr[0]) if pr else 0, sym, arah, _cari_it(sym, arah))
    except Exception as ex:
        print("[WARN] skor kartu", ex)
    try:
        import bybit_fetch as B
        import telegram_notify as TG
        ms = int(time.time() * 1000)
        d4 = B._raw(sym, "240", 160)
        d4 = d4[d4.index + 14400000 <= ms]
        h, l, c = (d4[k].values.astype(float) for k in ("high", "low", "close"))
        sup, res = snr(h, l, c)
        if time.time() - _CACHE.get("tick_t", 0) > 3600:
            try:
                _CACHE.update(tick=B.get_symbols(), tick_t=time.time())
            except Exception:
                pass
        t = (_CACHE.get("tick") or {}).get(sym, 1e-8)
        f = lambda v: "-" if v is None else TG.fp(v, t)
        rows.append(f"🧱 <b>Support 4J {f(sup)}</b> · <b>Resistance 4J {f(res)}</b> (pivot 3 candle, 150 candle terakhir)")
    except Exception as ex:
        print("[WARN] snr kartu", ex)
    lb = label_sinyal(arah)
    if lb:
        rows.append(lb)
    return rows


def kartu_ringkas(m, pr=None, nama=""):
    """v150: kartu sinyal ringkas dan rapi dari kartu jalur lengkap. Urutan: judul, label, blok salin, bukti, BTC, level, cara masuk,
    alasan, aturan keluar, lot. Gagal mengurai = None (pengirim memakai kartu lengkap)."""
    import re
    x = re.search(r"<b>\d+\. ([A-Z0-9]+USDT) (LONG|SHORT)</b>\s*·\s*([^\n]+)", m or "")
    pre = re.search(r"<pre>.*?</pre>", m or "", re.S)
    if not x or not pre:
        return None
    sym, arah, jalur_nm = x.group(1), x.group(2), re.sub(r"<[^>]+>", "", x.group(3)).strip()
    nilai = int(pr[0]) if pr else 0
    for batas, skor, nm, rr, pf, wr in SKOR:
        if nilai >= batas:
            break
    baris = m.split("\n")
    ambil = lambda awal: [b for b in baris if b.startswith(awal)]
    L = arah == "LONG"
    rows = [f"{'🟢' if L else '🔴'} <b>{sym} {arah}</b>  ·  {jalur_nm}"]
    if nilai >= 8:
        rows.append("🏆 <b>SINYAL PRIORITAS UTAMA</b>")
    rows.append(f"💯 Skor <b>{skor}/100</b>  ·  {nm}  ·  uji 2023-2026 PF {pf}, WR {wr}")
    rows.append("━━━━━━━━━━━━━━━━━━")
    rows.append(pre.group(0))
    rows += ambil("🎯 Entry valid")
    rows.append("━━━━━━━━━━━━━━━━━━")
    ki = _cari_it(sym, arah)
    pr_k = (ki[1].get("profil") if ki else None) or {}
    if pr_k:
        rows.append(f"📊 Koin ini di jalur ini: 2024-2026 {pr_k['n24']} sinyal, WR {pr_k['wr24']:.0f}%, PF {pr_k['pf24']:.2f} "
                    f"(sejak listing {pr_k['n']} sinyal, PF {pr_k['pf']:.2f})")
    try:
        p = peta()
        arah_btc = {1: "naik", -1: "turun", 0: "datar"}
        cocok = ("searah, lebih bagus" if p["fokus"] == arah else ("netral" if p["fokus"] == "TAHAN" else "lawan arah, hasil uji hampir impas"))
        rows.append(f"🧭 BTC fokus <b>{p['fokus']}</b> ({cocok})  ·  1J {arah_btc[p['s1']]}, 4J {arah_btc[p['s4']]}, 1D {arah_btc[p['sD']]}")
    except Exception:
        pass
    try:
        import bybit_fetch as B
        import telegram_notify as TG
        ms = int(time.time() * 1000)
        d4 = B._raw(sym, "240", 160)
        d4 = d4[d4.index + 14400000 <= ms]
        sup, res = snr(*(d4[k].values.astype(float) for k in ("high", "low", "close")))
        if time.time() - _CACHE.get("tick_t", 0) > 3600:
            try:
                _CACHE.update(tick=B.get_symbols(), tick_t=time.time())
            except Exception:
                pass
        t = (_CACHE.get("tick") or {}).get(sym, 1e-8)
        px = float(d4["close"].values[-1])
        f = lambda v: "-" if v is None else f"{TG.fp(v, t)} ({(v / px - 1) * 100:+.1f}%)"
        rows.append(f"🧱 Support 4J <b>{f(sup)}</b>  ·  Resistance 4J <b>{f(res)}</b>")
        # v150: info ringkas pasar (info saja: efisiensi tren, funding, dan derivatif BTC sudah diuji dan tidak memilah, hasil_v150.txt)
        c = d4["close"].values.astype(float)[-21:]
        ef = abs(c[-1] - c[0]) / max(np.abs(np.diff(c)).sum(), 1e-12)
        try:
            fr = float(B.get_tickers().get(sym, {}).get("funding") or 0) * 100
            fr_t = f"funding {fr:+.4f}%"
        except Exception:
            fr_t = "funding -"
        rows.append(f"📐 TF pemicu 4J  ·  efisiensi tren 20 candle {ef:.2f} ({'lurus' if ef >= 0.3 else 'berombak' if ef < 0.15 else 'sedang'})  ·  {fr_t}")
    except Exception as ex:
        print("[WARN] snr ringkas", ex)
    try:
        import qse_saya as SY
        import qse_modal as MD
        sl_ = []
        for u in SY.daftar_pengguna():
            st = MD.status(u)
            sl_.append(f"{SY.nama_pengguna(u)} {st['n_posisi']}/{st['maks']}")
        if sl_:
            rows.append("🎰 Slot posisi jalan: " + "  ·  ".join(sl_))
    except Exception as ex:
        print("[WARN] slot ringkas", ex)
    rows.append("⏱ TF 4J  ·  <b>ikuti arus, masuk MARKET sekarang</b> (uji: menunggu koreksi lebih jelek)")
    label = []
    for kata in ("COMBO RAJA", "COMBO FIX PROFIT", "COMBO EMAS", "MUTU TINGGI", "PULLBACK", "VOLUME PASAR TINGGI", "BTC.D TURUN"):
        if kata in m:
            label.append(kata.title())
    g = re.search(r"COMBO (\d+)</b>: juga ([^.]+?) searah", m)
    if g:
        label.append(f"combo dengan {g.group(2)}")
    kenapa = []
    if "💡 <b>Kenapa</b>" in baris:
        for b in baris[baris.index("💡 <b>Kenapa</b>") + 1:]:
            if not b.startswith("• ") or b.startswith("• Bukti"):
                break
            kenapa.append(b[2:].split(":")[0])
    if kenapa or label:
        rows.append("💡 " + "  ·  ".join(kenapa + label))
    try:
        import qse_saya as SY
        lv = level_dari_kartu(m)
        it_ = ki[1] if ki else {}
        trail = None if lv["tp"] else (it_.get("trail_atr", 3.0) / it_.get("sl_atr", 2.0) * abs(lv["entry"] - lv["sl"]) if lv["entry"] and lv["sl"] else None)
        rows.append(SY.cara_pasang(sym, arah, lv["entry"], lv["sl"], it_.get("tick"), tp=lv["tp"], trail=trail, ringkas=True))
    except Exception as ex:
        print("[WARN] langkah ringkas", ex)
    for awal in ("⛔", "🛡 <b>Rem", "🔓", "📅", "↔️ Lawan", "💼", "🟦", "🟨"):
        rows += [b for b in baris if b.startswith(awal) and b not in rows]
    return "\n".join(rows)


def caption_sinyal(rk, maks=1000):
    """Potong kartu ringkas jadi caption gambar (maks karakter terlihat). Baris yang dibuang dulu: alasan, cara, TF, bukti koin."""
    import telegram_notify as TG
    rows = rk.split("\n")
    for awal in ("💡", "⏱", "🎰", "📐", "📲", "📊", "🧱", "━━"):
        if TG.panjang_terlihat("\n".join(rows)) <= maks:
            break
        rows = [r for r in rows if not r.startswith(awal)]
    t = "\n".join(rows)
    return t if TG.panjang_terlihat(t) <= maks else None


def cara_dari_kartu(rk):
    """Langkah lengkap pasang di Bybit untuk satu kartu (gelembung kedua di bawah gambar)."""
    import re
    import qse_saya as SY
    x = re.search(r"<b>([A-Z0-9]+USDT) (LONG|SHORT)</b>", rk or "")
    if not x:
        return None
    sym, arah = x.groups()
    lv = level_dari_kartu(rk)
    ki = _cari_it(sym, arah)
    it_ = ki[1] if ki else {}
    trail = None if lv["tp"] else it_.get("trail_atr", 3.0) / it_.get("sl_atr", 2.0) * abs(lv["entry"] - lv["sl"])
    return f"<b>{sym} {arah}</b>\n" + SY.cara_pasang(sym, arah, lv["entry"], lv["sl"], it_.get("tick"), tp=lv["tp"], trail=trail)


def level_dari_kartu(rk):
    """Harga entry, SL, TP sebagian, TP dari blok salin."""
    import re
    g = lambda pola: (lambda x: float(x.group(1).replace(",", "")) if x else None)(re.search(pola, rk))
    return dict(entry=g(r"Entry\s+([\d.,]+)"), sl=g(r"\nSL\s+([\d.,]+)"), tps=g(r"(?:Sebagian|TPawal)\s+([\d.,]+)"), tp=g(r"\nTP\s+([\d.,]+)"),
                sup=g(r"Support 4J <b>([\d.,]+)"), res=g(r"Resistance 4J <b>([\d.,]+)"))
