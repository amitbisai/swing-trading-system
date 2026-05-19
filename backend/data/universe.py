"""
T2 screening universe — the pool of US-listed stocks screened nightly.

The seed list covers ~250 mid-cap stocks across all major sectors in the
$300 M – $15 B market-cap range.  The market-cap filter in t2_screener.py
runs *after* OHLCV download, so stocks that have drifted outside the range
are automatically dropped without needing to update this list.

Stocks already in T1 (S&P 500) are deduplicated in scanner.py before the
OHLCV fetch, so there is no harm in some overlap here.
"""

from __future__ import annotations

# fmt: off
SEED_UNIVERSE: list[str] = [
    # ── Technology & Cloud Software ───────────────────────────────────────────
    "DDOG", "NET", "ZS", "CRWD", "FTNT", "OKTA", "PLTR", "PATH",
    "AI", "ASAN", "MNDY", "BILL", "HUBS", "ZI", "GTLB", "IOT",
    "S",    "PCOR", "BRZE", "JAMF", "FROG", "NCNO", "GWRE", "MANH",
    "PEGA", "EPAM", "CDNS", "SNPS", "ANSS", "MDB",  "DOMO", "TWLO",
    "ZM",   "DOCN", "ESTC", "ALRM", "APPF", "BOX",  "SMAR", "COUP",
    "ALTR", "CWAN", "TOST", "APPN", "NEWR", "PDCE", "VERX", "TASK",

    # ── Semiconductors (mid-cap) ──────────────────────────────────────────────
    "MRVL", "MPWR", "SWKS", "QRVO", "CRUS", "WOLF", "AMBA", "ACLS",
    "ONTO", "POWI", "RMBS", "SITM", "LSCC", "DIOD", "FORM", "HIMX",
    "SMTC", "AEHR", "CCMP", "INDI", "OLED", "VICR", "AXTI", "COHU",

    # ── Fintech & Crypto ──────────────────────────────────────────────────────
    "COIN", "SOFI", "AFRM", "UPST", "HOOD", "LPLA", "VIRT", "MKTX",
    "PIPR", "SEIC", "MSTR", "MARA", "RIOT", "CLSK", "HUT",  "CIFR",
    "BTBT", "WULF", "IREN",

    # ── Healthcare / MedTech ──────────────────────────────────────────────────
    "VEEV", "DOCS", "EXAS", "NVCR", "IONS", "ALKS", "NTRA", "TMDX",
    "TWST", "ACAD", "INSM", "KRYS", "ARWR", "FOLD", "RARE", "LEGN",
    "INVA", "RXDX", "MDXG", "RDVT", "HCAT", "CERT", "GMED", "IRTC",
    "AXNX", "NARI", "RGEN", "BRKR", "ITGR", "MMSI", "STER",

    # ── Biotech ───────────────────────────────────────────────────────────────
    "SRPT", "BEAM", "EDIT", "CRSP", "FATE", "DNLI", "ARVN", "KYMR",
    "PRAX", "PTGX", "RCUS", "IMGO", "NTLA", "ALLO", "KURA", "VKTX",
    "COGT", "NUVL", "JANX", "IMVT", "LNTH", "CORT", "ACVA",

    # ── Consumer Discretionary ────────────────────────────────────────────────
    "ONON", "DECK", "CROX", "SKX",  "BOOT", "SHAK", "JACK", "CAKE",
    "TXRH", "BLMN", "EAT",  "DNUT", "WEN",  "OXM",  "GIII", "XPOF",
    "MODG", "YETI", "PRKS", "PLNT", "WING", "LOCO",

    # ── Consumer Growth / Platform ────────────────────────────────────────────
    "DASH", "DKNG", "RBLX", "ROKU", "PINS", "SNAP", "TTD",  "MGNI",
    "ZETA", "APPS", "SSTK", "BRLT", "MAPS", "EVGO", "LYFT",

    # ── Industrials & Defense ─────────────────────────────────────────────────
    "AXON", "HEI",  "ESAB", "KTOS", "MOOG", "CAE",  "SAIC", "LDOS",
    "TGH",  "AER",  "TDG",  "AVAV", "RKLB", "SPIR", "LUNR", "ACHR",

    # ── Electric Vehicles & Clean Energy ──────────────────────────────────────
    "RIVN", "LCID", "XPEV", "NIO",  "CHPT", "BLNK", "PTRA", "EVGO",
    "STEM", "FLUX", "BE",   "PLUG", "FCEL", "ARRY",

    # ── Energy (oil & gas mid-cap) ────────────────────────────────────────────
    "RRC",  "CTRA", "AR",   "SM",   "MTDR", "CHRD", "WHD",  "KOS",
    "VTLE", "TRGP", "ENLC", "CIVI", "NOG",  "ESTE", "MGY",

    # ── Materials ─────────────────────────────────────────────────────────────
    "MP",   "AMR",  "HL",   "PAAS", "CDE",  "SSRM", "EXK",  "ARCH",
    "METC", "HCC",  "SILV", "GATO", "MAG",

    # ── Real Estate (growth REITs & industrial) ───────────────────────────────
    "IIPR", "COLD", "REXR", "CUBE", "STAG", "ADC",  "TRNO", "EPRT",
    "ROIC", "ILDA",

    # ── Communication / Media / Ad-tech ──────────────────────────────────────
    "LBRDK", "NWSA", "FOXA", "SSTK", "ZETA", "MGNI", "TTD",
]
# fmt: on

# Deduplicate while preserving order
_seen: set[str] = set()
_deduped: list[str] = []
for _s in SEED_UNIVERSE:
    if _s not in _seen:
        _seen.add(_s)
        _deduped.append(_s)
SEED_UNIVERSE = _deduped
del _seen, _deduped, _s


def get_universe(exclude: set[str] | None = None) -> list[str]:
    """
    Return the screening universe, optionally excluding known symbols
    (e.g. T1 stocks that are already analysed).
    """
    if not exclude:
        return list(SEED_UNIVERSE)
    return [s for s in SEED_UNIVERSE if s not in exclude]
