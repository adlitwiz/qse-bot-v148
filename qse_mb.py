"""QSE v150 - Mushroom Body asli lalat (FlyWire FAFB v783, belahan kanan) untuk otak lalat bionik.
Sirkuit dari data pemilik (OTAK LALAT.zip): 344 PN (indera bau), 2597 Kenyon cell, 1 APL (GABA penekan), 48 MBON (keluaran),
DAN PAM (hadiah) dan PPL1 (hukuman). File mb_sirkuit.npz (60 KB): 10.7 ribu sambungan PN->KC, 9.5 ribu KC->MBON, APL->KC.
Cara kerja, sama dengan lalat asli:
  1. Ciri pasar (token: koin, arah, jarak level, RSI, volume, BTC, tren) = bau. Tiap token menyalakan 3 PN tetap.
  2. PN menyalakan Kenyon cell lewat sinapsis asli. APL menekan, hanya 5% KC terkuat yang aktif (kode jarang).
  3. KC aktif menyalakan MBON lewat sinapsis asli. MBON di kompartemen PPL1 mendorong mendekat (makan),
     MBON di kompartemen PAM mendorong menghindar. Valensi = dorongan mendekat dikurangi dorongan menghindar.
  4. Belajar: TP = DAN PAM aktif, sinapsis KC aktif -> MBON penghindar melemah, jadi pola itu makin disukai.
     SL = DAN PPL1 aktif, sinapsis KC aktif -> MBON pendekat melemah, jadi pola itu dijauhi. Sinapsis pulih pelan ke awal.
Bobot hidup disimpan di STATE_DIR/lalat_mb.npy (9.5 ribu angka)."""
import hashlib
import os
import numpy as np
from config import STATE_DIR

_DIR = os.path.dirname(os.path.abspath(__file__))
F_SIRKUIT = os.path.join(_DIR, "mb_sirkuit.npz")
F_BOBOT = os.path.join(STATE_DIR, "lalat_mb.npy")
PN_PER_TOKEN = 3
KC_AKTIF = 0.05          # APL: hanya 5% Kenyon cell terkuat yang menyala


class Otak:
    def __init__(self, path=F_SIRKUIT):
        z = np.load(path)
        self.pk_p, self.pk_k, self.pk_w = z["pk_p"].astype(np.int64), z["pk_k"].astype(np.int64), z["pk_w"].astype(np.float64)
        self.km_k, self.km_m = z["km_k"].astype(np.int64), z["km_m"].astype(np.int64)
        self.w0 = z["km_w"].astype(np.float64)
        self.apl = z["apl_w"].astype(np.float64); self.apl = self.apl / max(self.apl.mean(), 1e-9)
        self.kel = z["kel"].astype(np.int64)
        self.n_pn, self.n_kc, self.n_m = len(z["pn_id"]), len(z["kc_id"]), len(z["mbon_id"])
        self.w = self.w0.copy()
        self.e_app = self.kel[self.km_m] == -1          # sinapsis ke MBON pendekat (kompartemen PPL1)
        self.e_avo = self.kel[self.km_m] == 1           # sinapsis ke MBON penghindar (kompartemen PAM)
        self._pn = {}

    # ---------- indera ----------
    def pn_token(self, tok):
        if tok not in self._pn:
            h = hashlib.blake2b(f"pn|{tok}".encode(), digest_size=16).digest()
            out, i = [], 0
            while len(out) < PN_PER_TOKEN:
                x = int.from_bytes(h[i:i + 2], "big") % self.n_pn
                if x not in out:
                    out.append(x)
                i = (i + 2) % 14
                if i == 0:
                    h = hashlib.blake2b(h, digest_size=16).digest()
            self._pn[tok] = np.array(out)
        return self._pn[tok]

    def kc(self, tokens):
        """Kenyon cell aktif untuk satu pola (sesudah tekanan APL). Return indeks KC."""
        act = np.zeros(self.n_pn)
        for t in tokens:
            act[self.pn_token(t)] = 1.0
        drive = np.bincount(self.pk_k, weights=self.pk_w * act[self.pk_p], minlength=self.n_kc)
        if drive.max() <= 0:
            return np.array([], np.int64)
        drive = drive - 0.5 * self.apl * drive[drive > 0].mean()
        k = max(1, int(self.n_kc * KC_AKTIF))
        idx = np.argpartition(-drive, k)[:k]
        return idx[drive[idx] > 0]

    # ---------- keputusan ----------
    def valensi(self, tokens, aktif=None):
        """Dorongan mendekat dikurangi menghindar, relatif ke sinapsis awal. 0 = netral, positif = disukai."""
        aktif = self.kc(tokens) if aktif is None else aktif
        if not len(aktif):
            return 0.0
        on = np.zeros(self.n_kc, bool); on[aktif] = True
        e = on[self.km_k]
        a = self.w[e & self.e_app].sum() / max(self.w0[e & self.e_app].sum(), 1e-9)
        v = self.w[e & self.e_avo].sum() / max(self.w0[e & self.e_avo].sum(), 1e-9)
        return float(a - v)

    # ---------- belajar ----------
    def belajar(self, tokens, R, eta, pulih=0.0):
        """Dopamin: R > 0 = PAM menekan sinapsis KC aktif ke MBON penghindar. R < 0 = PPL1 menekan ke MBON pendekat."""
        if pulih:
            self.w += pulih * (self.w0 - self.w)
        if not eta or abs(R) < 0.05:
            return
        on = np.zeros(self.n_kc, bool); on[self.kc(tokens)] = True
        e = on[self.km_k] & (self.e_avo if R > 0 else self.e_app)
        self.w[e] *= (1.0 - eta * min(abs(R), 1.5))

    # ---------- simpan ----------
    def muat(self, path=F_BOBOT):
        try:
            w = np.load(path)
            if w.shape == self.w0.shape:
                self.w = w.astype(np.float64)
        except Exception:
            pass
        return self

    def simpan(self, path=F_BOBOT):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.save(path + ".tmp.npy", self.w.astype(np.float32))
        os.replace(path + ".tmp.npy", path)

    def ringkas(self):
        r = self.w / np.maximum(self.w0, 1e-9)
        return dict(pn=self.n_pn, kc=self.n_kc, mbon=self.n_m, sinapsis=len(self.w0),
                    app_rata=float(r[self.e_app].mean()), avo_rata=float(r[self.e_avo].mean()),
                    melemah=int((r < 0.9).sum()))


# ---------- otak MB kedua: menilai sinyal jalur v150 (permintaan 5 Nov 18:08) ----------
# Masa kecil: menonton 1952 sinyal jalur 2023-2024 (mb_jalur.npy). Uji 2025-2026 (riset/upgrade/run_v159_tim.py bagian B):
# valensi > 0 n 556 rata +0.210R, valensi < 0 n 1822 rata +0.085R. Lot 0.5x/0.1x dari valensi: +73.7R lawan lot rata 0.25x +67.8R.
F_JALUR = os.path.join(STATE_DIR, "lalat_mb_jalur.npy")
_J = [None]


def otak_jalur():
    if _J[0] is None:
        try:
            o = Otak()
            o.muat(F_JALUR if os.path.exists(F_JALUR) else os.path.join(_DIR, "mb_jalur.npy"))
            _J[0] = o
        except Exception as ex:
            print("[WARN] otak MB jalur", ex)
            _J[0] = False
    return _J[0] or None


def token_jalur(jalur, sym, arah):
    return (f"jalur:{jalur}", f"koin:{sym}", f"arah:{arah}", f"spesialis:{sym}:{arah}")


def lot_jalur(jalur, sym, arah):
    """Return (pengali lot, valensi). Valensi > 0 = lot x2 (0.25x -> 0.5x), < 0 = lot x0.4 (0.25x -> 0.1x)."""
    o = otak_jalur()
    if not o or os.environ.get("QSE_MB_LOT", "1") == "0":
        return 1.0, 0.0
    v = o.valensi(token_jalur(jalur, sym, arah))
    return (2.0 if v > 0 else 0.4 if v < 0 else 1.0), v


def belajar_jalur(jalur, sym, arah, R, eta=0.002):
    o = otak_jalur()
    if o:
        o.belajar(token_jalur(jalur, sym, arah), R, eta)
        try:
            o.simpan(F_JALUR)
        except Exception as ex:
            print("[WARN] simpan MB jalur", ex)
