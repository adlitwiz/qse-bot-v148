"""QSE v148 - aturan 90 pola, DIHASILKAN OTOMATIS dari QSE_v148_DASBOR.txt (jangan edit manual)."""

NM = ['Fib Golden Pocket', 'Fib Golden Zone', 'Golden Pocket Volume', 'Fib 0.5', 'Fib 0.382', 'Fib 0.786', 'Fib 0% Breakout', 'Fib Ext 1.272', 'Order Block SMC', 'Break of Structure', 'Change of Character', 'Fair Value Gap', 'Liquidity Sweep', 'Pantul SnR', 'Tembus SnR', 'Breakout Triangle', 'Double Top Bottom', 'Inside Bar Break', 'Candle Engulfing', 'Pin Bar Rejection', 'Morning Evening Star', 'Three Soldiers Crows', 'Pullback EMA20', 'VWAP Volume', 'SuperTrend Flip', 'Donchian Break', 'Infleksi Kalkulus', 'Hurst Z-score', 'Fractal7 Break', 'Fractal7 Pullback', 'GZ Extension', 'Retest Extension', 'Pantul Trendline', 'Tembus Trendline', 'Tembus Awan Ichimoku', 'Ichimoku TK Cross', 'MACD Cross', 'MACD Divergensi', 'RSI Divergensi', 'RSI Balik Jenuh', 'Angka Psikologi', 'False Breakout', 'Breakaway Gap', 'Runaway Gap', 'Exhaustion Gap', 'Bollinger Squeeze', 'Bollinger Reversal', 'ADX DMI Cross', 'OBV Divergensi', 'Head and Shoulders', 'Triple Top Horn', 'Pola Lanjutan', 'Pullback EMA50', 'Pullback EMA200', 'Pullback BB Mid', 'Pantul Kijun', 'Pantul Tenkan', 'Pantul SuperTrend', 'Fib 0.236', 'RSI 50 Reclaim', 'MACD Zero Cross', 'Volume Spike Balik', 'Outside Bar Balik', 'Isi Gap', 'Tembus Angka Bulat', 'Range Expansion', 'Tembus Kijun', 'Pullback Donchian Mid', 'Three Bar Reversal', 'OBV Breakout', 'ADX Awal Tren', 'Tembus Golden Pocket', 'Elliott Dorongan', 'Wedge Break', 'Rectangle Break', 'Dow Konfirmasi', 'Retest Zona Flip', 'Konfluensi Zona Trendline', 'Hidden Divergence', 'Balik Kuat', 'Pullback Stoch RSI', 'Retest Struktur', 'Retest Supply Demand', 'Broadening Break', 'Triangle Balik', 'RSI Trendline Break', 'Ribbon 5-8-13', 'Pullback EMA100', 'Golden Death Cross', 'Rebound EMA8-15']
NRA = ['sentuh Golden Pocket', 'masuk Golden Zone', 'GP dan delta volume', 'uji Fib 0.5', 'pullback Fib 0.382', 'koreksi Fib 0.786', 'tembus Fib 0%', 'uji Ext 1.272', 'balik ke Order Block', 'struktur jebol searah tren', 'struktur berbalik', 'isi Fair Value Gap', 'sweep likuiditas', 'memantul dari SnR', 'tembus SnR', 'breakout Triangle', 'tembus neckline', 'tembus range Inside Bar', 'Engulfing searah tren', 'Pin Bar menolak GP', 'Morning Evening Star', 'Soldiers atau Crows', 'pullback ke EMA20', 'uji VWAP', 'SuperTrend ganti warna', 'tembus Donchian 20', 'titik infleksi d2', 'Hurst dan Z-score', 'break fractal 7', 'pullback fractal 7', 'masuk GZ Extension', 'retest Ext 1.272', 'sentuh trendline lalu memantul', 'trendline TEMBUS lalu retest', 'tembus awan Ichimoku', 'Tenkan potong Kijun', 'MACD potong sinyal', 'MACD tidak ikut', 'RSI tidak ikut', 'RSI keluar jenuh', 'memantul angka bulat', 'tembus lalu GAGAL', 'gap besar bervolume', 'gap tengah tren', 'gap habis tenaga', 'pita menyempit lalu meledak', 'sentuh pita luar', 'DI potong ADX naik', 'OBV tidak ikut', 'kepala bahu selesai', 'tiga puncak sejajar', 'Flag Wedge jebol', 'pullback ke EMA50', 'pullback ke EMA200', 'pullback ke tengah pita', 'memantul dari Kijun', 'memantul dari Tenkan', 'memantul dari SuperTrend', 'pullback dangkal Fib 0.236', 'RSI merebut garis 50', 'MACD melewati nol', 'volume meledak lalu balik', 'outside bar menelan arah', 'harga menutup gap', 'menembus angka bulat', 'rentang melebar lalu jebol', 'menembus Kijun', 'pullback ke tengah Donchian', 'tiga bar lalu berbalik', 'OBV cetak ekstrem baru', 'ADX menembus 20', 'menembus Golden Pocket', 'gelombang dorongan Elliott', 'wedge jebol searah', 'rectangle jebol tepi', 'struktur Dow terkonfirmasi', 'zona tembus lalu diuji ulang', 'zona dan trendline bertemu plus candle tolak', 'harga higher low tapi RSI lower low', 'gagal buat low baru lalu trendline jebol candle besar', 'Stoch RSI balik dari jenuh searah tren', 'uji ulang high lama yang jadi support', 'kembali ke zona dasar sebelum dorongan', 'segitiga melebar lalu jebol', 'segitiga jebol berlawanan bentuknya', 'garis tren RSI jebol', 'EMA 5 8 13 baru berurutan', 'pullback ke EMA100', 'EMA50 potong EMA200', 'memantul di antara EMA8 dan EMA15']
BRK = [False, False, False, False, False, False, True, False, False, True, True, False, False, False, True, True, True, True, False, False, False, False, False, False, False, True, False, False, True, False, False, False, False, True, True, False, False, False, False, False, False, False, True, False, False, True, False, True, False, True, True, True, False, False, False, False, False, False, False, False, False, False, False, False, True, True, True, False, False, True, False, True, False, True, True, True, False, False, False, True, False, False, False, True, True, False, False, False, False, False]
FAM = [1, 1, 1, 1, 1, 1, 2, 0, 0, 2, 2, 0, 1, 1, 2, 2, 2, 2, 0, 1, 1, 0, 0, 0, 0, 2, 1, 1, 2, 1, 0, 0, 1, 2, 2, 0, 0, 1, 1, 1, 1, 1, 2, 2, 1, 2, 1, 2, 1, 1, 1, 2, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 1, 2, 2, 2, 0, 1, 2, 0, 2, 0, 2, 2, 0, 1, 1, 1, 2, 1, 1, 1, 2, 2, 1, 0, 0, 0, 0]

def rules_cLa(v):
    g = v.__getitem__
    a04 = g('a04')
    a05 = g('a05')
    aboveK = g('aboveK')
    adxV = g('adxV')
    atChB = g('atChB')
    atSup = g('atSup')
    atTlL = g('atTlL')
    avgRng = g('avgRng')
    bbM = g('bbM')
    bbRL = g('bbRL')
    blkL = g('blkL')
    bodyR = g('bodyR')
    bosL = g('bosL')
    brange = g('brange')
    brdL = g('brdL')
    brkGU = g('brkGU')
    cdlL = g('cdlL')
    cdvB = g('cdvB')
    cfTlL = g('cfTlL')
    choL = g('choL')
    close = g('close')
    contU = g('contU')
    d2 = g('d2')
    d3 = g('d3')
    dblB = g('dblB')
    dcM = g('dcM')
    dcU = g('dcU')
    diM = g('diM')
    diP = g('diP')
    divBM = g('divBM')
    divBR = g('divBR')
    dmiCU = g('dmiCU')
    dowUp = g('dowUp')
    e127 = g('e127')
    elwU = g('elwU')
    ema20 = g('ema20')
    ema200 = g('ema200')
    ema50 = g('ema50')
    engL = g('engL')
    exhGD = g('exhGD')
    fanFU = g('fanFU')
    fbL = g('fbL')
    fib0 = g('fib0')
    frBU = g('frBU')
    frD1 = g('frD1')
    frTU = g('frTU')
    fvFL = g('fvFL')
    gcL = g('gcL')
    gpTop = g('gpTop')
    hdvL = g('hdvL')
    hi10 = g('hi10')
    high = g('high')
    hrB = g('hrB')
    hsL = g('hsL')
    hurst = g('hurst')
    hurstT = g('hurstT')
    ibL = g('ibL')
    inEZ = g('inEZ')
    inGP = g('inGP')
    inGZ = g('inGZ')
    inflL = g('inflL')
    islB = g('islB')
    kBU = g('kBU')
    kijun = g('kijun')
    lastGD = g('lastGD')
    low = g('low')
    macdCU = g('macdCU')
    macdH = g('macdH')
    macdL = g('macdL')
    obL = g('obL')
    obvDL = g('obvDL')
    obvV = g('obvV')
    open = g('open')
    p100L = g('p100L')
    pLo20 = g('pLo20')
    ph1 = g('ph1')
    pinL = g('pinL')
    psyBL = g('psyBL')
    psyLv = g('psyLv')
    r236 = g('r236')
    r382 = g('r382')
    r500 = g('r500')
    r786 = g('r786')
    r815L = g('r815L')
    rbL = g('rbL')
    rectC = g('rectC')
    resV = g('resV')
    rsL = g('rsL')
    rsiRL = g('rsiRL')
    rsiV = g('rsiV')
    rtFlipL = g('rtFlipL')
    rtbL = g('rtbL')
    runGU = g('runGU')
    rv10 = g('rv10')
    rv11 = g('rv11')
    rv12 = g('rv12')
    rv13 = g('rv13')
    rvol = g('rvol')
    sdL = g('sdL')
    sol3 = g('sol3')
    sqBU = g('sqBU')
    srL = g('srL')
    stDir = g('stDir')
    stL = g('stL')
    stLine = g('stLine')
    supV = g('supV')
    swpL = g('swpL')
    tSt = g('tSt')
    tUp = g('tUp')
    tenkan = g('tenkan')
    tkU = g('tkU')
    tlBU = g('tlBU')
    trB = g('trB')
    triBL = g('triBL')
    triL = g('triL')
    upLeg = g('upLeg')
    vwapV = g('vwapV')
    wdgF = g('wdgF')
    zPr = g('zPr')
    zThr = g('zThr')
    sh, nz, na = v['sh'], v['nz'], v['na']
    ta_highest, ta_lowest, math_abs, math_avg = v['ta_highest'], v['ta_lowest'], v['math_abs'], v['math_avg']
    return [
        upLeg & inGP & cdlL,  # 0
        upLeg & inGZ & cdlL,  # 1
        upLeg & inGP & cdvB & rv11,  # 2
        upLeg & (math_abs(low - r500) <= a05) & cdlL,  # 3
        upLeg & (math_abs(low - r382) <= a05) & cdlL,  # 4
        upLeg & (math_abs(low - r786) <= a05) & cdlL,  # 5
        upLeg & (close > fib0) & (sh(close, 1) <= fib0) & rv12,  # 6
        upLeg & (math_abs(high - e127) <= a05) & cdlL,  # 7
        obL & rv10,  # 8
        bosL & rv11,  # 9
        choL & rv12,  # 10
        fvFL & tUp,  # 11
        swpL & rv12,  # 12
        atSup & cdlL & (close > supV),  # 13
        (close > resV) & (sh(close, 1) <= resV) & rv13,  # 14
        triL,  # 15
        dblB,  # 16
        ibL,  # 17
        engL & tUp,  # 18
        pinL & (atSup | inGP),  # 19
        stL & rv10,  # 20
        sol3 & tUp,  # 21
        tUp & (low <= ema20) & (close > ema20) & cdlL,  # 22
        cdvB & (low <= vwapV) & (close > vwapV),  # 23
        (stDir < 0) & (sh(stDir, 1) > 0) & (close > ema200),  # 24
        (close > dcU) & rv12,  # 25
        inflL & (d3 > 0) & cdlL,  # 26
        (hurst > hurstT) & (math_abs(tSt) > 2.01) & (zPr < -zThr * 0.6) & (d2 > 0),  # 27
        frBU & frTU & cdvB,  # 28
        frTU & ~na(frD1) & (low <= frD1 + a04) & cdlL,  # 29
        upLeg & inEZ & cdlL & rv11,  # 30
        upLeg & (close > e127) & (low <= e127 + a04) & cdlL,  # 31
        (atTlL | atChB) & cdlL,  # 32
        (tlBU | fanFU) & rv12,  # 33
        kBU & rv12,  # 34
        tkU & aboveK & (close > kijun),  # 35
        macdCU & (macdH > 0) & tUp,  # 36
        divBM & cdlL,  # 37
        divBR & cdlL,  # 38
        rsiRL & (atSup | inGP),  # 39
        psyBL,  # 40
        fbL,  # 41
        brkGU,  # 42
        runGU,  # 43
        exhGD | islB,  # 44
        sqBU,  # 45
        bbRL,  # 46
        dmiCU,  # 47
        obvDL & cdlL,  # 48
        hsL,  # 49
        trB | hrB,  # 50
        contU,  # 51
        tUp & (low <= ema50) & (close > ema50) & cdlL,  # 52
        (low <= ema200) & (close > ema200) & cdlL,  # 53
        tUp & (low <= bbM) & (close > bbM) & cdlL,  # 54
        (low <= kijun) & (close > kijun) & cdlL,  # 55
        aboveK & (low <= tenkan) & (close > tenkan) & cdlL,  # 56
        (stDir < 0) & (low <= stLine) & (close > stLine) & cdlL,  # 57
        upLeg & (math_abs(low - r236) <= a05) & cdlL,  # 58
        (rsiV > 50) & (sh(rsiV, 1) <= 50) & tUp,  # 59
        (macdL > 0) & (sh(macdL, 1) <= 0),  # 60
        (rvol >= 2.0) & (low <= pLo20) & cdlL,  # 61
        (high > sh(high, 1)) & (low < sh(low, 1)) & (close > open) & (bodyR > 0.5),  # 62
        ~na(lastGD) & (low <= lastGD) & (close > lastGD) & cdlL,  # 63
        (close > psyLv) & (sh(close, 1) <= psyLv) & rv12,  # 64
        (brange > avgRng * 1.5) & (close > hi10) & rv11,  # 65
        (close > kijun) & (sh(close, 1) <= kijun) & aboveK,  # 66
        tUp & (low <= dcM) & (close > dcM) & cdlL,  # 67
        (low < sh(low, 1)) & (sh(low, 1) < sh(low, 2)) & (close > sh(high, 1)),  # 68
        (obvV > sh(ta_highest(obvV, 20), 1)) & (close > sh(close, 1)),  # 69
        (adxV > 20) & (sh(adxV, 1) <= 20) & (diP > diM),  # 70
        upLeg & (close > gpTop) & (sh(close, 1) <= gpTop) & rv11,  # 71
        elwU,  # 72
        wdgF & (close > ph1) & (sh(close, 1) <= ph1) & rv11,  # 73
        rectC & (close > ph1) & (sh(close, 1) <= ph1) & rv12,  # 74
        dowUp & (close > ph1) & (sh(close, 1) <= ph1) & rv11,  # 75
        rtFlipL,  # 76
        cfTlL,  # 77
        hdvL,  # 78
        blkL,  # 79
        srL,  # 80
        rsL,  # 81
        sdL,  # 82
        brdL,  # 83
        triBL,  # 84
        rtbL,  # 85
        rbL,  # 86
        p100L,  # 87
        gcL,  # 88
        r815L,  # 89
    ]

def rules_cSa(v):
    g = v.__getitem__
    a04 = g('a04')
    a05 = g('a05')
    adxV = g('adxV')
    atChT = g('atChT')
    atRes = g('atRes')
    atTlS = g('atTlS')
    avgRng = g('avgRng')
    bbM = g('bbM')
    bbRS = g('bbRS')
    belowK = g('belowK')
    blkS = g('blkS')
    bodyR = g('bodyR')
    bosS = g('bosS')
    brange = g('brange')
    brdS = g('brdS')
    brkGD = g('brkGD')
    cdlS = g('cdlS')
    cdvS = g('cdvS')
    cfTlS = g('cfTlS')
    choS = g('choS')
    close = g('close')
    contD = g('contD')
    cro3 = g('cro3')
    d2 = g('d2')
    d3 = g('d3')
    dblT = g('dblT')
    dcL = g('dcL')
    dcM = g('dcM')
    diM = g('diM')
    diP = g('diP')
    divSM = g('divSM')
    divSR = g('divSR')
    dmiCD = g('dmiCD')
    dowDn = g('dowDn')
    e127 = g('e127')
    elwD = g('elwD')
    ema20 = g('ema20')
    ema200 = g('ema200')
    ema50 = g('ema50')
    engS = g('engS')
    exhGU = g('exhGU')
    fanFD = g('fanFD')
    fbS = g('fbS')
    fib0 = g('fib0')
    frBD = g('frBD')
    frTD = g('frTD')
    frU1 = g('frU1')
    fvFS = g('fvFS')
    gcS = g('gcS')
    gpBot = g('gpBot')
    hdvS = g('hdvS')
    high = g('high')
    hound = g('hound')
    hrT = g('hrT')
    hsS = g('hsS')
    hurst = g('hurst')
    hurstT = g('hurstT')
    ibS = g('ibS')
    inEZ = g('inEZ')
    inGP = g('inGP')
    inGZ = g('inGZ')
    inflS = g('inflS')
    islT = g('islT')
    kBD = g('kBD')
    kijun = g('kijun')
    lastGU = g('lastGU')
    lo10 = g('lo10')
    low = g('low')
    macdCD = g('macdCD')
    macdH = g('macdH')
    macdL = g('macdL')
    obS = g('obS')
    obvDS = g('obvDS')
    obvV = g('obvV')
    open = g('open')
    p100S = g('p100S')
    pHi20 = g('pHi20')
    pinS = g('pinS')
    pl1 = g('pl1')
    psyBS = g('psyBS')
    psyLv = g('psyLv')
    r236 = g('r236')
    r382 = g('r382')
    r500 = g('r500')
    r786 = g('r786')
    r815S = g('r815S')
    rbS = g('rbS')
    rectC = g('rectC')
    resV = g('resV')
    rsS = g('rsS')
    rsiRS = g('rsiRS')
    rsiV = g('rsiV')
    rtFlipS = g('rtFlipS')
    rtbS = g('rtbS')
    runGD = g('runGD')
    rv10 = g('rv10')
    rv11 = g('rv11')
    rv12 = g('rv12')
    rv13 = g('rv13')
    rvol = g('rvol')
    sdS = g('sdS')
    sqBD = g('sqBD')
    srS = g('srS')
    stDir = g('stDir')
    stLine = g('stLine')
    stS = g('stS')
    supV = g('supV')
    swpS = g('swpS')
    tDn = g('tDn')
    tSt = g('tSt')
    tenkan = g('tenkan')
    tkD = g('tkD')
    tlBD = g('tlBD')
    trT = g('trT')
    triBS = g('triBS')
    triS = g('triS')
    upLeg = g('upLeg')
    vwapV = g('vwapV')
    wdgR = g('wdgR')
    zPr = g('zPr')
    zThr = g('zThr')
    sh, nz, na = v['sh'], v['nz'], v['na']
    ta_highest, ta_lowest, math_abs, math_avg = v['ta_highest'], v['ta_lowest'], v['math_abs'], v['math_avg']
    return [
        ~upLeg & inGP & cdlS,  # 0
        ~upLeg & inGZ & cdlS,  # 1
        ~upLeg & inGP & cdvS & rv11,  # 2
        ~upLeg & (math_abs(high - r500) <= a05) & cdlS,  # 3
        ~upLeg & (math_abs(high - r382) <= a05) & cdlS,  # 4
        ~upLeg & (math_abs(high - r786) <= a05) & cdlS,  # 5
        ~upLeg & (close < fib0) & (sh(close, 1) >= fib0) & rv12,  # 6
        ~upLeg & (math_abs(low - e127) <= a05) & cdlS,  # 7
        obS & rv10,  # 8
        bosS & rv11,  # 9
        choS & rv12,  # 10
        fvFS & tDn,  # 11
        swpS & rv12,  # 12
        atRes & cdlS & (close < resV),  # 13
        (close < supV) & (sh(close, 1) >= supV) & rv13,  # 14
        triS,  # 15
        dblT,  # 16
        ibS,  # 17
        engS & tDn,  # 18
        pinS & (atRes | inGP),  # 19
        stS & rv10,  # 20
        cro3 & tDn,  # 21
        tDn & (high >= ema20) & (close < ema20) & cdlS,  # 22
        cdvS & (high >= vwapV) & (close < vwapV),  # 23
        (stDir > 0) & (sh(stDir, 1) < 0) & (close < ema200),  # 24
        (close < dcL) & rv12,  # 25
        inflS & (d3 < 0) & cdlS,  # 26
        (hurst > hurstT) & (math_abs(tSt) > 2.01) & (zPr > zThr * 0.6) & (d2 < 0),  # 27
        frBD & frTD & cdvS,  # 28
        frTD & ~na(frU1) & (high >= frU1 - a04) & cdlS,  # 29
        ~upLeg & inEZ & cdlS & rv11,  # 30
        ~upLeg & (close < e127) & (high >= e127 - a04) & cdlS,  # 31
        (atTlS | atChT) & cdlS,  # 32
        (tlBD | fanFD) & rv12,  # 33
        kBD & rv12,  # 34
        tkD & belowK & (close < kijun),  # 35
        macdCD & (macdH < 0) & tDn,  # 36
        divSM & cdlS,  # 37
        divSR & cdlS,  # 38
        rsiRS & (atRes | inGP),  # 39
        psyBS,  # 40
        fbS,  # 41
        brkGD,  # 42
        runGD,  # 43
        exhGU | islT,  # 44
        sqBD,  # 45
        bbRS,  # 46
        dmiCD,  # 47
        obvDS & cdlS,  # 48
        hsS | hound,  # 49
        trT | hrT,  # 50
        contD,  # 51
        tDn & (high >= ema50) & (close < ema50) & cdlS,  # 52
        (high >= ema200) & (close < ema200) & cdlS,  # 53
        tDn & (high >= bbM) & (close < bbM) & cdlS,  # 54
        (high >= kijun) & (close < kijun) & cdlS,  # 55
        belowK & (high >= tenkan) & (close < tenkan) & cdlS,  # 56
        (stDir > 0) & (high >= stLine) & (close < stLine) & cdlS,  # 57
        ~upLeg & (math_abs(high - r236) <= a05) & cdlS,  # 58
        (rsiV < 50) & (sh(rsiV, 1) >= 50) & tDn,  # 59
        (macdL < 0) & (sh(macdL, 1) >= 0),  # 60
        (rvol >= 2.0) & (high >= pHi20) & cdlS,  # 61
        (high > sh(high, 1)) & (low < sh(low, 1)) & (close < open) & (bodyR > 0.5),  # 62
        ~na(lastGU) & (high >= lastGU) & (close < lastGU) & cdlS,  # 63
        (close < psyLv) & (sh(close, 1) >= psyLv) & rv12,  # 64
        (brange > avgRng * 1.5) & (close < lo10) & rv11,  # 65
        (close < kijun) & (sh(close, 1) >= kijun) & belowK,  # 66
        tDn & (high >= dcM) & (close < dcM) & cdlS,  # 67
        (high > sh(high, 1)) & (sh(high, 1) > sh(high, 2)) & (close < sh(low, 1)),  # 68
        (obvV < sh(ta_lowest(obvV, 20), 1)) & (close < sh(close, 1)),  # 69
        (adxV > 20) & (sh(adxV, 1) <= 20) & (diM > diP),  # 70
        ~upLeg & (close < gpBot) & (sh(close, 1) >= gpBot) & rv11,  # 71
        elwD,  # 72
        wdgR & (close < pl1) & (sh(close, 1) >= pl1) & rv11,  # 73
        rectC & (close < pl1) & (sh(close, 1) >= pl1) & rv12,  # 74
        dowDn & (close < pl1) & (sh(close, 1) >= pl1) & rv11,  # 75
        rtFlipS,  # 76
        cfTlS,  # 77
        hdvS,  # 78
        blkS,  # 79
        srS,  # 80
        rsS,  # 81
        sdS,  # 82
        brdS,  # 83
        triBS,  # 84
        rtbS,  # 85
        rbS,  # 86
        p100S,  # 87
        gcS,  # 88
        r815S,  # 89
    ]

def rules_lvL(v):
    g = v.__getitem__
    bbL = g('bbL')
    bbM = g('bbM')
    bbU = g('bbU')
    chBot = g('chBot')
    dcM = g('dcM')
    dcU = g('dcU')
    dmT = g('dmT')
    e127 = g('e127')
    ema100 = g('ema100')
    ema15 = g('ema15')
    ema20 = g('ema20')
    ema200 = g('ema200')
    ema50 = g('ema50')
    ema8 = g('ema8')
    ezBot = g('ezBot')
    ezTop = g('ezTop')
    fib0 = g('fib0')
    flipU = g('flipU')
    frD1 = g('frD1')
    frU1 = g('frU1')
    fvUB = g('fvUB')
    gpBot = g('gpBot')
    gpTop = g('gpTop')
    gzBot = g('gzBot')
    gzTop = g('gzTop')
    hi10 = g('hi10')
    high = g('high')
    kijun = g('kijun')
    kumoT = g('kumoT')
    lastGD = g('lastGD')
    lastGU = g('lastGU')
    lo10 = g('lo10')
    low = g('low')
    lrN = g('lrN')
    neckU = g('neckU')
    obBT = g('obBT')
    ph1 = g('ph1')
    ph2 = g('ph2')
    psyLv = g('psyLv')
    r236 = g('r236')
    r382 = g('r382')
    r500 = g('r500')
    r786 = g('r786')
    resV = g('resV')
    stLine = g('stLine')
    supV = g('supV')
    tenkan = g('tenkan')
    tlHv = g('tlHv')
    tlLv = g('tlLv')
    vwapV = g('vwapV')
    sh, nz, na = v['sh'], v['nz'], v['na']
    ta_highest, ta_lowest, math_abs, math_avg = v['ta_highest'], v['ta_lowest'], v['math_abs'], v['math_avg']
    return [
        math_avg(gpTop, gpBot),  # 0
        math_avg(gzTop, gzBot),  # 1
        math_avg(gpTop, gpBot),  # 2
        r500,  # 3
        r382,  # 4
        r786,  # 5
        fib0,  # 6
        e127,  # 7
        obBT,  # 8
        ph1,  # 9
        ph1,  # 10
        fvUB,  # 11
        lo10,  # 12
        supV,  # 13
        resV,  # 14
        ph1,  # 15
        ph1,  # 16
        sh(high, 1),  # 17
        ema20,  # 18
        math_avg(gpTop, gpBot),  # 19
        ema20,  # 20
        ema20,  # 21
        ema20,  # 22
        vwapV,  # 23
        stLine,  # 24
        dcU,  # 25
        lrN,  # 26
        lrN,  # 27
        frU1,  # 28
        frD1,  # 29
        math_avg(ezTop, ezBot),  # 30
        e127,  # 31
        nz(chBot, tlLv),  # 32
        tlHv,  # 33
        kumoT,  # 34
        kijun,  # 35
        ema20,  # 36
        lo10,  # 37
        lo10,  # 38
        supV,  # 39
        psyLv,  # 40
        lo10,  # 41
        lastGU,  # 42
        lastGU,  # 43
        lastGU,  # 44
        bbU,  # 45
        bbL,  # 46
        ema20,  # 47
        lo10,  # 48
        neckU,  # 49
        neckU,  # 50
        ph1,  # 51
        ema50,  # 52
        ema200,  # 53
        bbM,  # 54
        kijun,  # 55
        tenkan,  # 56
        stLine,  # 57
        r236,  # 58
        ema20,  # 59
        ema20,  # 60
        lo10,  # 61
        sh(low, 1),  # 62
        nz(lastGD, ema20),  # 63
        psyLv,  # 64
        hi10,  # 65
        kijun,  # 66
        dcM,  # 67
        sh(high, 1),  # 68
        ema20,  # 69
        ema20,  # 70
        gpTop,  # 71
        nz(ph1, ema20),  # 72
        nz(ph1, ema20),  # 73
        nz(ph1, ema20),  # 74
        nz(ph1, ema20),  # 75
        nz(flipU, supV),  # 76
        nz(tlLv, supV),  # 77
        ema20,  # 78
        high,  # 79
        ema20,  # 80
        nz(ph2, ema20),  # 81
        nz(dmT, ema20),  # 82
        nz(ph1, ema20),  # 83
        nz(ph1, ema20),  # 84
        ema20,  # 85
        ema8,  # 86
        ema100,  # 87
        ema50,  # 88
        ema15,  # 89
    ]

def rules_lvS(v):
    g = v.__getitem__
    bbL = g('bbL')
    bbM = g('bbM')
    bbU = g('bbU')
    chTop = g('chTop')
    dcL = g('dcL')
    dcM = g('dcM')
    e127 = g('e127')
    ema100 = g('ema100')
    ema15 = g('ema15')
    ema20 = g('ema20')
    ema200 = g('ema200')
    ema50 = g('ema50')
    ema8 = g('ema8')
    ezBot = g('ezBot')
    ezTop = g('ezTop')
    fib0 = g('fib0')
    flipD = g('flipD')
    frD1 = g('frD1')
    frU1 = g('frU1')
    fvDT = g('fvDT')
    gpBot = g('gpBot')
    gpTop = g('gpTop')
    gzBot = g('gzBot')
    gzTop = g('gzTop')
    hi10 = g('hi10')
    high = g('high')
    kijun = g('kijun')
    kumoB = g('kumoB')
    lastGD = g('lastGD')
    lastGU = g('lastGU')
    lo10 = g('lo10')
    low = g('low')
    lrN = g('lrN')
    neckD = g('neckD')
    obSB = g('obSB')
    pl1 = g('pl1')
    pl2 = g('pl2')
    psyLv = g('psyLv')
    r236 = g('r236')
    r382 = g('r382')
    r500 = g('r500')
    r786 = g('r786')
    resV = g('resV')
    spB = g('spB')
    stLine = g('stLine')
    supV = g('supV')
    tenkan = g('tenkan')
    tlHv = g('tlHv')
    tlLv = g('tlLv')
    vwapV = g('vwapV')
    sh, nz, na = v['sh'], v['nz'], v['na']
    ta_highest, ta_lowest, math_abs, math_avg = v['ta_highest'], v['ta_lowest'], v['math_abs'], v['math_avg']
    return [
        math_avg(gpTop, gpBot),  # 0
        math_avg(gzTop, gzBot),  # 1
        math_avg(gpTop, gpBot),  # 2
        r500,  # 3
        r382,  # 4
        r786,  # 5
        fib0,  # 6
        e127,  # 7
        obSB,  # 8
        pl1,  # 9
        pl1,  # 10
        fvDT,  # 11
        hi10,  # 12
        resV,  # 13
        supV,  # 14
        pl1,  # 15
        pl1,  # 16
        sh(low, 1),  # 17
        ema20,  # 18
        math_avg(gpTop, gpBot),  # 19
        ema20,  # 20
        ema20,  # 21
        ema20,  # 22
        vwapV,  # 23
        stLine,  # 24
        dcL,  # 25
        lrN,  # 26
        lrN,  # 27
        frD1,  # 28
        frU1,  # 29
        math_avg(ezTop, ezBot),  # 30
        e127,  # 31
        nz(chTop, tlHv),  # 32
        tlLv,  # 33
        kumoB,  # 34
        kijun,  # 35
        ema20,  # 36
        hi10,  # 37
        hi10,  # 38
        resV,  # 39
        psyLv,  # 40
        hi10,  # 41
        lastGD,  # 42
        lastGD,  # 43
        lastGD,  # 44
        bbL,  # 45
        bbU,  # 46
        ema20,  # 47
        hi10,  # 48
        neckD,  # 49
        neckD,  # 50
        pl1,  # 51
        ema50,  # 52
        ema200,  # 53
        bbM,  # 54
        kijun,  # 55
        tenkan,  # 56
        stLine,  # 57
        r236,  # 58
        ema20,  # 59
        ema20,  # 60
        hi10,  # 61
        sh(high, 1),  # 62
        nz(lastGU, ema20),  # 63
        psyLv,  # 64
        lo10,  # 65
        kijun,  # 66
        dcM,  # 67
        sh(low, 1),  # 68
        ema20,  # 69
        ema20,  # 70
        gpBot,  # 71
        nz(pl1, ema20),  # 72
        nz(pl1, ema20),  # 73
        nz(pl1, ema20),  # 74
        nz(pl1, ema20),  # 75
        nz(flipD, resV),  # 76
        nz(tlHv, resV),  # 77
        ema20,  # 78
        low,  # 79
        ema20,  # 80
        nz(pl2, ema20),  # 81
        nz(spB, ema20),  # 82
        nz(pl1, ema20),  # 83
        nz(pl1, ema20),  # 84
        ema20,  # 85
        ema8,  # 86
        ema100,  # 87
        ema50,  # 88
        ema15,  # 89
    ]
