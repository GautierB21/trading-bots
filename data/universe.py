"""Master investment universe: US, European, and Asian stocks + ETFs.

Categorized ticker lists for strategy configuration. Symbols use the
yfinance suffix convention for non-US exchanges (e.g. ".L" London,
".PA" Paris, ".DE" Xetra, ".T" Tokyo, ".HK" Hong Kong, ".NS" NSE India,
".KS" Korea, ".TW" Taiwan, ".AX" Australia, ".SS"/".SZ" China A-shares).
"""

US_LARGE_CAP = [
    # S&P 100 - biggest US companies
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "JNJ",
    "WMT", "PG", "MA", "UNH", "HD", "DIS", "NFLX", "ADBE", "CRM", "INTC",
    "VZ", "T", "PFE", "ABBV", "MRK", "KO", "PEP", "BAC", "CMCSA", "XOM",
    "CVX", "CSCO", "ORCL", "ACN", "LIN", "TMO", "MCD", "ABT", "NKE", "UPS",
    "IBM", "QCOM", "MDT", "PM", "HON", "BA", "MMM", "CAT", "GE", "AMD",
    "AMGN", "GILD", "SBUX", "LMT", "BLK", "SCHW", "COP", "PLD", "MS", "GS",
    "SPGI", "DE", "RTX", "LOW", "AXP", "C", "BKNG", "UBER", "SYK", "ISRG",
    "TJX", "PGR", "EL", "MDLZ", "ADP", "ZTS", "CI", "CB", "BSX", "DHR",
    "EOG", "GM", "F", "MO", "DUK", "SO", "NEE", "SLB", "APD", "SHW",
    "BDX", "TGT", "FDX", "HUM", "REGN", "VRTX", "MRNA", "PYPL", "SQ", "NOW",
]

US_MID_CAP = [
    # S&P 400 - mid caps
    "AIZ", "ALGN", "ALLE", "AMCR", "ANSS", "AOS", "APA", "ARE", "ATO", "AVB",
    "AVY", "AWK", "AZO", "BALL", "BAX", "BBY", "BIO", "BKI", "BMRN", "BR",
    "BRO", "BXP", "CAG", "CAH", "CBOE", "CBRE", "CCK", "CDNS", "CE", "CFG",
    "CHD", "CHRW", "CHTR", "CINF", "CLX", "CMA", "CMC", "CMS", "CNP",
    "COO", "CPAY", "CPB", "CPRT", "CRL", "CSL", "CTAS", "CTLT", "CTVA",
    "DAL", "DD", "DECK", "DFS", "DG", "DGX", "DHI", "DOV", "DPZ", "DRE",
    "DRI", "DTE", "DVN", "EA", "EBAY", "ECL", "ED", "EFX",
    "EIX", "EMR", "ENPH", "EQT", "ES", "ESS", "ETR", "EVRG", "EW", "EXC",
    "EXPD", "EXR", "FANG", "FAST", "FCX", "FDS", "FE", "FFIV", "FIS", "FITB",
    "FMC", "FOXA", "FRT", "FSLR", "FTI", "FTNT", "GD", "GDDY", "GIS", "GL",
    "GLW", "GNRC", "GPC", "GPN", "GRMN", "GWW", "HAL", "HAS", "HBAN",
    "HCA", "HEI", "HES", "HIG", "HII", "HOLX", "HRL", "HSIC", "HST", "HSY",
    "HUBB", "ICE", "IEX", "IFF", "ILMN", "INCY", "IP", "IPG",
    "IQV", "IR", "IRM", "IT", "ITW", "IVZ", "J", "JBHT", "JKHY", "JNPR",
    "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMI", "KMX", "KR", "L", "LDOS",
    "LEN", "LH", "LHX", "LII", "LKQ", "LNC", "LNT", "LUV", "LVS", "LW",
    "LYB", "LYV", "MAA", "MANH", "MAR", "MAS", "MCHP", "MCK", "MCO", "MGM",
    "MHK", "MKC", "MKTX", "MLM", "MNST", "MOH", "MOS", "MPC", "MPW",
    "MRO", "MSI", "MTB", "MTCH", "MTD", "MU", "NDAQ", "NDSN",
    "NEM", "NI", "NOC", "NOV", "NRG", "NSC", "NTAP", "NTRS",
    "NUE", "NWL", "O", "OKE", "OMC", "ON", "OTIS", "OXY", "PARA", "PAYX",
    "PCAR", "PEG", "PENN", "PFG", "PH", "PHM",
    "PKI", "PNC", "PNR", "PPG", "PPL",
]

INTERNATIONAL = [
    # Europe - Netherlands
    "ASML.AS", "ADYEN.AS", "HEIA.AS", "INGA.AS", "PHIA.AS",
    # Europe - France
    "MC.PA", "TTE.PA", "BN.PA", "OR.PA", "AI.PA", "SU.PA", "RMS.PA",
    "AIR.PA", "SAF.PA", "KER.PA", "EL.PA",
    # Europe - Germany
    "SAP.DE", "DTE.DE", "ALV.DE", "MUV2.DE", "SIE.DE", "BAYN.DE", "BMW.DE",
    "VOW3.DE", "ADS.DE", "DB1.DE", "IFX.DE", "HEI.DE",
    # Europe - UK
    "SHEL.L", "ULVR.L", "HSBA.L", "BP.L", "AZN.L", "GSK.L", "DGE.L", "RIO.L",
    "BARC.L", "LLOY.L", "PRU.L", "AV.L", "NG.L", "REL.L", "EXPN.L",
    # Europe - Switzerland
    "NOVN.SW", "ROG.SW", "NESN.SW", "ABBN.SW",
    # Europe - Italy
    "ENEL.MI", "ENI.MI", "UCG.MI", "ISP.MI",
    # Europe - Spain
    "SAN.MC", "IBE.MC", "BBVA.MC", "TEF.MC", "ITX.MC",
    # Europe - Nordics
    "NOKIA.HE", "SAMPO.HE", "NOVO-B.CO", "MAERSK-B.CO", "ERIC-B.ST", "VOLV-B.ST",

    # Asia - Japan (suffix .T for Tokyo)
    "7203.T", "6758.T", "6861.T", "9984.T", "9432.T", "9433.T",
    "8306.T", "8316.T", "8035.T", "8766.T", "4502.T", "4503.T",
    "4063.T", "6954.T", "7731.T", "6981.T", "7751.T", "7974.T",
    "8058.T", "6501.T", "6502.T", "7201.T", "7267.T", "9020.T",
    "9021.T", "9022.T", "1925.T", "8801.T", "8802.T", "2914.T",
    "2502.T", "2503.T", "2801.T", "2802.T", "2871.T", "3382.T",
    "8001.T", "8002.T", "8053.T", "3402.T", "3405.T", "3861.T",
    "5411.T", "5711.T", "5801.T", "5802.T", "4901.T", "5201.T",

    # Asia - Hong Kong (suffix .HK)
    "0700.HK", "9988.HK", "9999.HK", "9618.HK", "1810.HK",
    "0011.HK", "0005.HK", "1299.HK", "0388.HK", "0016.HK",
    "0012.HK", "0002.HK", "0003.HK", "0006.HK", "0066.HK",
    "0017.HK", "0019.HK", "0027.HK", "0101.HK", "0151.HK",
    "2382.HK", "6699.HK", "1024.HK",

    # China A shares via Shanghai/Shenzhen
    "600519.SS", "000858.SZ", "000333.SZ", "601318.SS", "600036.SS",
    "601166.SS", "600900.SS", "600887.SS", "002415.SZ", "000651.SZ",

    # India (suffix .NS for NSE)
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "KOTAKBANK.NS", "BAJFINANCE.NS", "SBIN.NS", "BHARTIARTL.NS",
    "ITC.NS", "WIPRO.NS", "AXISBANK.NS", "MARUTI.NS", "TATAMOTORS.NS",

    # South Korea (suffix .KS)
    "005930.KS", "000660.KS", "207940.KS", "051910.KS", "035420.KS",
    "068270.KS", "105560.KS", "028260.KS", "012330.KS", "055550.KS",
    "096770.KS", "017670.KS", "006400.KS", "032830.KS", "011200.KS",

    # Taiwan
    "2330.TW", "2317.TW", "2454.TW", "2308.TW", "2382.TW",

    # Australia (suffix .AX)
    "BHP.AX", "CBA.AX", "NAB.AX", "WBC.AX", "ANZ.AX",
    "CSL.AX", "WES.AX", "MQG.AX", "WOW.AX", "TLS.AX",
    "RIO.AX", "FMG.AX", "ALL.AX", "QBE.AX", "SUN.AX",
]

ETFS = [
    # US broad market
    "SPY", "IVV", "VOO", "QQQ", "VTI", "DIA", "IWM",
    # International
    "EFA", "VXUS", "IEFA", "IEMG", "VEU", "SCHF",
    # Europe
    "VGK", "IEUR", "EZU", "FEZ",
    # Asia Pacific
    "VPL", "AAXJ", "EWJ", "EWT", "EWY", "EWH", "INDY", "EPI",
    # Emerging Markets
    "VWO", "EEM", "SCHE", "FM",
    # Sector ETFs
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLY",
    "VGT", "VHT", "VNQ", "VAW", "VDC", "VOX", "VIS", "VPU",
    # Bond ETFs
    "AGG", "BND", "TLT", "IEF", "SHY", "LQD", "HYG", "MUB",
    # Smart beta / factor
    "QUAL", "SIZE", "MTUM", "VLUE", "USMV", "SPLV", "FNDX",
    # Commodity
    "GLD", "SLV", "IAU", "USO", "UNG", "DBA", "GSG",
]

# For pairs trading - pairs across different markets
PAIRS = [
    {"symbol_a": "XOM", "symbol_b": "CVX"},
    {"symbol_a": "KO", "symbol_b": "PEP"},
    {"symbol_a": "SHEL.L", "symbol_b": "BP.L"},          # European oil majors
    {"symbol_a": "BHP.AX", "symbol_b": "RIO.AX"},        # Australian miners
    {"symbol_a": "7203.T", "symbol_b": "7267.T"},        # Toyota vs Honda
    {"symbol_a": "005930.KS", "symbol_b": "000660.KS"},  # Samsung vs SK Hynix
    {"symbol_a": "RELIANCE.NS", "symbol_b": "TCS.NS"},   # Indian large caps
    {"symbol_a": "0700.HK", "symbol_b": "9988.HK"},      # Tencent vs Alibaba
    {"symbol_a": "ULVR.L", "symbol_b": "PG"},            # Unilever vs P&G
    {"symbol_a": "MC.PA", "symbol_b": "KER.PA"},         # LVMH vs Kering
    {"symbol_a": "ASML.AS", "symbol_b": "NVDA"},         # ASML vs Nvidia (semis)
    {"symbol_a": "SPY", "symbol_b": "QQQ"},              # S&P vs Nasdaq
]

ALL_US = sorted(set(US_LARGE_CAP + US_MID_CAP))
ALL = sorted(set(US_LARGE_CAP + US_MID_CAP + INTERNATIONAL + ETFS))
