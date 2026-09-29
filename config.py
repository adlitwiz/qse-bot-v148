"""QSE v148 Bot - semua pengaturan. Nilai engine = default input() Pine v148 (jangan diubah bila ingin sama dengan DASBOR)."""
import os


def _env(k, d, cast=str):
    v = os.environ.get(k)
    return d if v in (None, "") else cast(v)


# ===== DATA =====
BYBIT_URL = _env("BYBIT_URL", "https://api.bybit.com")
TV_BARS = _env("QSE_TV_BARS", 5000, int)          # jumlah bar chart TradingView (akun gratis 5000)
H1_BARS = _env("QSE_H1_BARS", 0, int)             # bar 1H untuk bias m60, 0 = penuh sepanjang chart 4H
H1_INTRABAR = _env("QSE_H1_INTRABAR", "first")    # nilai 1H yang dipakai per candle 4H: first / last
REQ_PER_SEC = _env("QSE_REQ_PER_SEC", 40, float)
FETCH_THREADS = _env("QSE_FETCH_THREADS", 8, int)
PROC_WORKERS = _env("QSE_WORKERS", 0, int)        # 0 = semua core CPU
TFS = [t for t in _env("QSE_TF", "240,60").replace(" ", "").split(",") if t in ("240", "60")]
SCAN_MIN_TURNOVER = _env("QSE_SCAN_MIN_TURNOVER", 500000, float)  # koin di bawah ini tidak dihitung, 0 = semua
MAX_MENIT = _env("QSE_MAX_MENIT", 45, float)                     # batas waktu satu run
ONLY_SYMBOLS = [s for s in _env("QSE_SYMBOLS", "").replace(" ", "").split(",") if s]
STATE_DIR = _env("QSE_STATE_DIR", os.path.expanduser("~/qse_state"))

# ===== ENGINE (persis input Pine v148) =====
P = dict(
    hardProven=True, minWRd=55.0, wrTop=75.0, pfTop=2.0, wrDrop=5.0, tierHard=False, grAbon=90.0,
    tierBon=60.0, pfDrop=0.2, needRg=True, slPerm=3, minKeep=12, doneB=2, coolTP=14, freeDir=False,
    lockB=24, provWaive=True, gzBon=10.0, retBon=8.0, provW=6.0, biasBon=6.0, useRegFit=True,
    trendPen=10.0, corrBon=8.0, minWinD=5, laxSmp=4, minSmp=12, minNetD=1.5, minPFd=1.5,
    banAfter=8, banNetR=-4.0, brkBars=40, allowAnti=False, antiMinR=8.0, biasHold=3, needCdl=True,
    antiMBar=3, antiMATR=0.9, needSlope=True, maxFar=3.5, mktTol=0.10, farPen=6.0, usePsy=True,
    psyTol=0.30, useGap=True, gapMin=0.30, usePat=True, patTol=0.50, useChan=True, useFan=True,
    useDow=True, useCRS=True, btcGate=True, useRW=True, useSuic=True, suicZ=2.5, useElw=True,
    memCap=8.0, memBon=20.0, rgBon=14.0, minHelp=4, vlExpB=60, r1MinN=5, tlPer=10, tlTol=0.35,
    scEvery=8, selEvery=4, kMode="Skor (lunak)", kMinSc=2, d1Thr=0.015, d2Thr=0.010, useTpX=True,
    priorK=8.0, tpReach=1.4, tp1Mul=0.8, tp1Rch=0.7, wickLb=10, wickMul=1.15, minRR=1.0,
    wGrA=58.0, eGrA=0.25, pGrA=1.60, wGrB=48.0, eGrB=0.10, pGrB=1.25, fibBon=4.0, minConf=4,
    needMTF=True, useLT=True, chaseA=1.5, atrLen=14, slBuf=0.45, slMinA=1.0, slMaxA=2.5,
    spikeX=2.5, statLen=100, zThr=2.0, hurstT=0.55, frLen=3, snrPer=20, swLen=30, msbPiv=7,
)

# ===== NOTIFIKASI =====
RAPOR_OK = tuple(_env("QSE_RAPOR", "A,B").split(","))   # rapor robot yang dikirim
SEND_EMPTY = _env("QSE_SEND_EMPTY", 1, int)              # kirim pesan walau tidak ada sinyal
MAX_SIGNALS = _env("QSE_MAX_SIGNALS", 12, int)           # batas sinyal per pesan, urut terbaik

# ===== FILTER PROFIT (lapisan tambahan, engine tetap sama dengan DASBOR) =====
FP = dict(
    on=_env("QSE_FIX_PROFIT", 1, int) == 1,
    min_turnover=_env("QSE_MIN_TURNOVER", 500000, float),  # USDT 24 jam, koin sepi slippage besar
    max_spread_pct=_env("QSE_MAX_SPREAD", 0.15, float),    # persen bid ask
    max_funding=_env("QSE_MAX_FUNDING", 0.001, float),     # 0.1 persen, crowded trade
    fee_pct=_env("QSE_FEE", 0.055, float),                 # taker fee Bybit per sisi, persen
    min_tp1_net_r=_env("QSE_MIN_TP1_R", 0.55, float),      # TP1 bersih setelah fee, dalam R
    skip_tunggu=_env("QSE_SKIP_TUNGGU", 1, int) == 1,      # order TUNGGU tidak dikirim
    max_same_dir=_env("QSE_MAX_SAME_DIR", 8, int),         # batas sinyal searah per run
    mute_after_sl=_env("QSE_MUTE_SL", 2, int),             # SL beruntun live per koin sebelum jeda
    mute_days=_env("QSE_MUTE_DAYS", 5, float),
    pat_min_trades=_env("QSE_PAT_MIN", 4, int),            # pola live dibuang bila rugi setelah n trade
    risk_usdt=_env("QSE_RISK_USDT", 0, float),             # isi untuk hitung lot, 0 = tidak tampil
    market_atr=_env("QSE_MARKET_ATR", 0.25, float),        # harga sejauh ini dari entry = MARKET
    limit_max_atr=_env("QSE_LIMIT_MAX_ATR", 2.5, float),   # batas keras gap LIMIT dalam ATR
    min_fill=_env("QSE_MIN_FILL", 60, float),              # peluang LIMIT tersentuh dalam limit_hours, persen
    limit_hours=_env("QSE_LIMIT_HOURS", 24, float),        # LIMIT belum terisi sesudah ini = dibatalkan
    kirim_stop=_env("QSE_KIRIM_STOP", 0, int) == 1,        # 1 = breakout yang belum tembus dikirim sebagai STOP
)
