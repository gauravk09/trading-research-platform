"""
commodity_map.py — Which MCX commodities have a liquid global benchmark contract.

MCX contracts are, for the metals and energy complex, price-takers: they are the
CME/LME reference price converted to INR (times a lot-size and a small
import-parity basis). So a signal can be researched on the deep global series
and executed on the shallow Indian one — but ONLY where the two are genuinely
the same underlying. This table is the whitelist for that claim.

`global_symbol` is a Yahoo continuous front-month futures symbol.
`global_venue`  is where the real price is discovered.
`spot_symbol`   is the cash/benchmark series in spot_commodities.py (None where
                no free official spot feed exists).
`fx_sensitive`  is True when the MCX leg carries USDINR risk the global leg does
                not (which is every USD-quoted benchmark — i.e. all of them).

Anything NOT in this table (MENTHAOIL, COTTONCANDY, CASTORSEED, most agri) is
India-domestic price discovery with no offshore twin. Do not model those from
global data.
"""

# mcx_symbol -> metadata. mcx_root is the Kite tradingsymbol prefix.
PAIRS = {
    "GOLD":        dict(mcx_root="GOLD",       global_symbol="GC=F",  global_venue="COMEX", spot_symbol="XAUUSD",
                        unit="10 g vs troy oz", lot=100,  fx_sensitive=True),
    "SILVER":      dict(mcx_root="SILVER",     global_symbol="SI=F",  global_venue="COMEX", spot_symbol="XAGUSD",
                        unit="1 kg vs troy oz", lot=30,   fx_sensitive=True),
    "CRUDEOIL":    dict(mcx_root="CRUDEOIL",   global_symbol="CL=F",  global_venue="NYMEX", spot_symbol="WTIUSD",
                        unit="1 bbl",           lot=100,  fx_sensitive=True),
    "NATURALGAS":  dict(mcx_root="NATURALGAS", global_symbol="NG=F",  global_venue="NYMEX", spot_symbol="NGUSD",
                        unit="1 mmBtu",         lot=1250, fx_sensitive=True),
    "COPPER":      dict(mcx_root="COPPER",     global_symbol="HG=F",  global_venue="COMEX", spot_symbol=None,   # LME cash only, no free feed
                        unit="1 kg vs lb",      lot=2500, fx_sensitive=True),
}

# MCX base metals whose real reference is the LME, which has no free daily feed.
# Listed so they are visibly excluded rather than silently forgotten.
LME_ONLY = ["ZINC", "ALUMINIUM", "LEAD", "NICKEL"]

# MCX contracts with no offshore twin — domestic supply/demand only.
DOMESTIC_ONLY = ["MENTHAOIL", "COTTONCANDY", "CASTORSEED", "CPO", "KAPAS"]

FX_SYMBOL = "INR=X"   # USDINR, needed to translate any USD benchmark to MCX terms


def global_symbols() -> list:
    """Every global series worth downloading, FX included."""
    return [p["global_symbol"] for p in PAIRS.values()] + [FX_SYMBOL]
