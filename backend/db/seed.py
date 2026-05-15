"""
Seed the stocks table with ~150 S&P 500 large-cap Tier-1 symbols.

Run from the backend/ directory:
    python -m db.seed

Or from the repo root via the helper script:
    python scripts/seed_stocks.py
"""

import asyncio
import sys
from pathlib import Path

# Allow running directly as a module from backend/ or repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

# fmt: off
TIER1_STOCKS: list[tuple[str, str, str]] = [
    # (symbol, name, sector)
    ("AAPL",  "Apple Inc.",                              "Technology"),
    ("MSFT",  "Microsoft Corporation",                   "Technology"),
    ("NVDA",  "NVIDIA Corporation",                      "Technology"),
    ("GOOGL", "Alphabet Inc.",                           "Communication Services"),
    ("AMZN",  "Amazon.com Inc.",                         "Consumer Discretionary"),
    ("META",  "Meta Platforms Inc.",                     "Communication Services"),
    ("BRK-B", "Berkshire Hathaway Inc.",                 "Financials"),
    ("LLY",   "Eli Lilly and Company",                   "Health Care"),
    ("AVGO",  "Broadcom Inc.",                           "Technology"),
    ("TSLA",  "Tesla Inc.",                              "Consumer Discretionary"),
    ("JPM",   "JPMorgan Chase & Co.",                    "Financials"),
    ("V",     "Visa Inc.",                               "Financials"),
    ("UNH",   "UnitedHealth Group Inc.",                 "Health Care"),
    ("XOM",   "Exxon Mobil Corporation",                 "Energy"),
    ("MA",    "Mastercard Inc.",                         "Financials"),
    ("JNJ",   "Johnson & Johnson",                       "Health Care"),
    ("PG",    "Procter & Gamble Co.",                    "Consumer Staples"),
    ("ORCL",  "Oracle Corporation",                      "Technology"),
    ("COST",  "Costco Wholesale Corporation",            "Consumer Staples"),
    ("HD",    "The Home Depot Inc.",                     "Consumer Discretionary"),
    ("MRK",   "Merck & Co. Inc.",                        "Health Care"),
    ("ABBV",  "AbbVie Inc.",                             "Health Care"),
    ("CVX",   "Chevron Corporation",                     "Energy"),
    ("BAC",   "Bank of America Corporation",             "Financials"),
    ("KO",    "The Coca-Cola Company",                   "Consumer Staples"),
    ("PEP",   "PepsiCo Inc.",                            "Consumer Staples"),
    ("NFLX",  "Netflix Inc.",                            "Communication Services"),
    ("TMO",   "Thermo Fisher Scientific Inc.",           "Health Care"),
    ("CRM",   "Salesforce Inc.",                         "Technology"),
    ("ADBE",  "Adobe Inc.",                              "Technology"),
    ("AMD",   "Advanced Micro Devices Inc.",             "Technology"),
    ("ACN",   "Accenture plc",                           "Technology"),
    ("MCD",   "McDonald's Corporation",                  "Consumer Discretionary"),
    ("WMT",   "Walmart Inc.",                            "Consumer Staples"),
    ("CSCO",  "Cisco Systems Inc.",                      "Technology"),
    ("ABT",   "Abbott Laboratories",                     "Health Care"),
    ("DHR",   "Danaher Corporation",                     "Health Care"),
    ("LIN",   "Linde plc",                               "Materials"),
    ("NKE",   "NIKE Inc.",                               "Consumer Discretionary"),
    ("TXN",   "Texas Instruments Inc.",                  "Technology"),
    ("INTU",  "Intuit Inc.",                             "Technology"),
    ("PM",    "Philip Morris International Inc.",        "Consumer Staples"),
    ("NEE",   "NextEra Energy Inc.",                     "Utilities"),
    ("IBM",   "International Business Machines Corp.",   "Technology"),
    ("RTX",   "RTX Corporation",                         "Industrials"),
    ("QCOM",  "QUALCOMM Inc.",                           "Technology"),
    ("CAT",   "Caterpillar Inc.",                        "Industrials"),
    ("SPGI",  "S&P Global Inc.",                         "Financials"),
    ("AMGN",  "Amgen Inc.",                              "Health Care"),
    ("HON",   "Honeywell International Inc.",            "Industrials"),
    ("GE",    "GE Aerospace",                            "Industrials"),
    ("AMAT",  "Applied Materials Inc.",                  "Technology"),
    ("LOW",   "Lowe's Companies Inc.",                   "Consumer Discretionary"),
    ("ISRG",  "Intuitive Surgical Inc.",                 "Health Care"),
    ("PLD",   "Prologis Inc.",                           "Real Estate"),
    ("GS",    "The Goldman Sachs Group Inc.",            "Financials"),
    ("ELV",   "Elevance Health Inc.",                    "Health Care"),
    ("BKNG",  "Booking Holdings Inc.",                   "Consumer Discretionary"),
    ("AXP",   "American Express Company",                "Financials"),
    ("DE",    "Deere & Company",                         "Industrials"),
    ("LRCX",  "Lam Research Corporation",                "Technology"),
    ("KLAC",  "KLA Corporation",                         "Technology"),
    ("MDLZ",  "Mondelez International Inc.",             "Consumer Staples"),
    ("ADI",   "Analog Devices Inc.",                     "Technology"),
    ("SYK",   "Stryker Corporation",                     "Health Care"),
    ("GILD",  "Gilead Sciences Inc.",                    "Health Care"),
    ("REGN",  "Regeneron Pharmaceuticals Inc.",          "Health Care"),
    ("BLK",   "BlackRock Inc.",                          "Financials"),
    ("VRTX",  "Vertex Pharmaceuticals Inc.",             "Health Care"),
    ("PANW",  "Palo Alto Networks Inc.",                 "Technology"),
    ("SNPS",  "Synopsys Inc.",                           "Technology"),
    ("CDNS",  "Cadence Design Systems Inc.",             "Technology"),
    ("CME",   "CME Group Inc.",                          "Financials"),
    ("TJX",   "The TJX Companies Inc.",                  "Consumer Discretionary"),
    ("MU",    "Micron Technology Inc.",                  "Technology"),
    ("PGR",   "Progressive Corporation",                 "Financials"),
    ("MMC",   "Marsh & McLennan Companies Inc.",         "Financials"),
    ("EOG",   "EOG Resources Inc.",                      "Energy"),
    ("MCO",   "Moody's Corporation",                     "Financials"),
    ("WM",    "Waste Management Inc.",                   "Industrials"),
    ("SO",    "The Southern Company",                    "Utilities"),
    ("HCA",   "HCA Healthcare Inc.",                     "Health Care"),
    ("USB",   "U.S. Bancorp",                            "Financials"),
    ("CI",    "The Cigna Group",                         "Health Care"),
    ("APH",   "Amphenol Corporation",                    "Technology"),
    ("DUK",   "Duke Energy Corporation",                 "Utilities"),
    ("NOC",   "Northrop Grumman Corporation",            "Industrials"),
    ("EMR",   "Emerson Electric Co.",                    "Industrials"),
    ("INTC",  "Intel Corporation",                       "Technology"),
    ("ITW",   "Illinois Tool Works Inc.",                "Industrials"),
    ("GD",    "General Dynamics Corporation",            "Industrials"),
    ("SHW",   "The Sherwin-Williams Company",            "Materials"),
    ("ADP",   "Automatic Data Processing Inc.",          "Technology"),
    ("PH",    "Parker Hannifin Corporation",             "Industrials"),
    ("ECL",   "Ecolab Inc.",                             "Materials"),
    ("PNC",   "The PNC Financial Services Group Inc.",   "Financials"),
    ("CL",    "Colgate-Palmolive Company",               "Consumer Staples"),
    ("WELL",  "Welltower Inc.",                          "Real Estate"),
    ("FCX",   "Freeport-McMoRan Inc.",                   "Materials"),
    ("TT",    "Trane Technologies plc",                  "Industrials"),
    ("BSX",   "Boston Scientific Corporation",           "Health Care"),
    ("MSI",   "Motorola Solutions Inc.",                 "Technology"),
    ("AON",   "Aon plc",                                 "Financials"),
    ("CTAS",  "Cintas Corporation",                      "Industrials"),
    ("NXPI",  "NXP Semiconductors NV",                   "Technology"),
    ("EW",    "Edwards Lifesciences Corporation",        "Health Care"),
    ("NSC",   "Norfolk Southern Corporation",            "Industrials"),
    ("AFL",   "Aflac Inc.",                              "Financials"),
    ("FDX",   "FedEx Corporation",                       "Industrials"),
    ("PCAR",  "PACCAR Inc.",                             "Industrials"),
    ("ORLY",  "O'Reilly Automotive Inc.",                "Consumer Discretionary"),
    ("MPC",   "Marathon Petroleum Corporation",          "Energy"),
    ("VLO",   "Valero Energy Corporation",               "Energy"),
    ("PSA",   "Public Storage",                          "Real Estate"),
    ("CARR",  "Carrier Global Corporation",              "Industrials"),
    ("TEL",   "TE Connectivity Ltd.",                    "Technology"),
    ("MNST",  "Monster Beverage Corporation",            "Consumer Staples"),
    ("COF",   "Capital One Financial Corporation",       "Financials"),
    ("TDG",   "TransDigm Group Inc.",                    "Industrials"),
    ("FTNT",  "Fortinet Inc.",                           "Technology"),
    ("KMB",   "Kimberly-Clark Corporation",              "Consumer Staples"),
    ("ROP",   "Roper Technologies Inc.",                 "Industrials"),
    ("HLT",   "Hilton Worldwide Holdings Inc.",          "Consumer Discretionary"),
    ("PAYX",  "Paychex Inc.",                            "Industrials"),
    ("OXY",   "Occidental Petroleum Corporation",        "Energy"),
    ("FAST",  "Fastenal Company",                        "Industrials"),
    ("GWW",   "W.W. Grainger Inc.",                      "Industrials"),
    ("BDX",   "Becton Dickinson and Company",            "Health Care"),
    ("ODFL",  "Old Dominion Freight Line Inc.",          "Industrials"),
    ("ROST",  "Ross Stores Inc.",                        "Consumer Discretionary"),
    ("IR",    "Ingersoll Rand Inc.",                     "Industrials"),
    ("D",     "Dominion Energy Inc.",                    "Utilities"),
    ("CTVA",  "Corteva Inc.",                            "Materials"),
    ("IQV",   "IQVIA Holdings Inc.",                     "Health Care"),
    ("KDP",   "Keurig Dr Pepper Inc.",                   "Consumer Staples"),
    ("MCHP",  "Microchip Technology Inc.",               "Technology"),
    ("A",     "Agilent Technologies Inc.",               "Health Care"),
    ("EA",    "Electronic Arts Inc.",                    "Communication Services"),
    ("VRSK",  "Verisk Analytics Inc.",                   "Industrials"),
    ("OTIS",  "Otis Worldwide Corporation",              "Industrials"),
    ("CMG",   "Chipotle Mexican Grill Inc.",             "Consumer Discretionary"),
    ("DXCM",  "DexCom Inc.",                             "Health Care"),
    ("KEYS",  "Keysight Technologies Inc.",              "Technology"),
    ("ZTS",   "Zoetis Inc.",                             "Health Care"),
    ("LHX",   "L3Harris Technologies Inc.",              "Industrials"),
    ("YUM",   "Yum! Brands Inc.",                        "Consumer Discretionary"),
    ("ON",    "ON Semiconductor Corporation",            "Technology"),
]
# fmt: on


async def seed() -> None:
    from sqlalchemy.dialects.postgresql import insert

    from db.models import Stock
    from db.session import async_session_factory

    async with async_session_factory() as session:
        for symbol, name, sector in TIER1_STOCKS:
            stmt = (
                insert(Stock)
                .values(symbol=symbol, name=name, sector=sector, tier="T1", is_active=True)
                .on_conflict_do_update(
                    index_elements=["symbol"],
                    set_={"name": name, "sector": sector, "tier": "T1", "is_active": True},
                )
            )
            await session.execute(stmt)
        await session.commit()
    print(f"Seeded {len(TIER1_STOCKS)} Tier-1 stocks.")


if __name__ == "__main__":
    asyncio.run(seed())
