"""Normalization: analyst names and instruments, with conflict handling.

Pure functions wherever possible (data in, data out) per testability rules.
"""

from __future__ import annotations

import re

from final_trades.domain import AssetType, VerificationStatus

# Curated alias map: raw spellings observed in sources → canonical name.
# Extend only with evidence (source excerpt) — never guess identity.
ANALYST_ALIASES: dict[str, str] = {
    "josh brown": "Joshua Brown",
    "joshua brown": "Joshua Brown",
    "joe terranova": "Joseph M. Terranova",
    "joseph terranova": "Joseph M. Terranova",
    "joseph m. terranova": "Joseph M. Terranova",
    "steph link": "Stephanie Link",
    "stephanie link": "Stephanie Link",
    "steve weiss": "Stephen Weiss",
    "stephen weiss": "Stephen Weiss",
    "rob sechan": "Rob Sechan",
    "robert sechan": "Rob Sechan",
    "bill baruch": "Bill Baruch",
    "william baruch": "Bill Baruch",
    "dan nathan": "Dan Nathan",
    "daniel nathan": "Dan Nathan",
    "malcolm ethridge": "Malcolm Ethridge",
    "liz thomas": "Liz Thomas",
    "elizabeth thomas": "Liz Thomas",
    "jenny van leeuwen harrington": "Jenny Van Leeuwen Harrington",
    "kevin simpson": "Kevin Simpson",
    "shannon saccocia": "Shannon Saccocia",
    "michael batnick": "Michael Batnick",
    "mark tepper": "Mark Tepper",
    "steven weiss": "Stephen Weiss",
}

# Curated non-ticker instruments → (canonical symbol, asset type).
INSTRUMENT_PHRASE_MAP: dict[str, tuple[str, AssetType]] = {
    "US10Y": ("US10Y", AssetType.FIXED_INCOME),
    "BTC-USD": ("BTC-USD", AssetType.CRYPTO),
    "TELECOM": ("TELECOM", AssetType.OTHER),
}

# Symbols widely known as ETFs (evidence: appeared as ETFs in sources).
KNOWN_ETFS: frozenset[str] = frozenset(
    {
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "XLF",
        "XLE",
        "XLK",
        "XLI",
        "XLP",
        "XLU",
        "XLB",
        "XLRE",
        "XLV",
        "TLT",
        "HYG",
        "LQD",
        "GLD",
        "SLV",
        "USO",
        "SMH",
        "ARKK",
        "IYJ",
        "IYM",
        "UTWO",
        "GPIQ",
        "OIH",
        "IVE",
        "XAR",
        "INFL",
        "CWEN",
        "VTI",
        "VEA",
        "EEM",
        "KWEB",
        "IBIT",
        "ETHA",
        "SPMO",
        "JEPI",
    }
)

VALID_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-^]{0,11}$")
_WHITESPACE = re.compile(r"\s+")


def canonicalize_analyst(raw_name: str | None) -> str | None:
    """Normalize an analyst name to its canonical form.

    Returns None when no name is available (unattributed).
    """
    if not raw_name:
        return None
    cleaned = _WHITESPACE.sub(" ", raw_name.replace("\u2019", "'")).strip(" .,")
    cleaned = re.sub(r"\s+([,])", r"\1", cleaned)
    if not cleaned:
        return None
    alias = ANALYST_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    # Title-case words, preserve initials like "M." and particles like "Van"
    return cleaned


def normalize_instrument(ticker_raw: str) -> tuple[str, AssetType] | None:
    """Normalize a raw instrument token to (symbol, asset_type).

    Returns None when the token cannot be responsibly normalized (the caller
    records it as rejected with the raw value preserved in review notes).
    """
    token = ticker_raw.strip().upper()
    if token in INSTRUMENT_PHRASE_MAP:
        return INSTRUMENT_PHRASE_MAP[token]
    if VALID_SYMBOL.match(token):
        asset = AssetType.ETF if token in KNOWN_ETFS else AssetType.EQUITY
        return token, asset
    return None


def upgrade_verification(current: str, incoming: str, distinct_sources: int) -> str:
    """Verification lattice: unverified < verified < corroborated; unresolved sticks.

    distinct_sources = number of distinct source keys supporting the record
    AFTER the incoming evidence is added.
    """
    if current == VerificationStatus.UNRESOLVED or incoming == VerificationStatus.UNRESOLVED:
        return VerificationStatus.UNRESOLVED
    order: dict[str, int] = {
        VerificationStatus.UNVERIFIED: 0,
        VerificationStatus.VERIFIED: 1,
        VerificationStatus.CORROBORATED: 2,
    }
    best = current if order.get(current, 0) >= order.get(incoming, 0) else incoming
    if distinct_sources >= 2 and order.get(best, 0) >= 1:
        return VerificationStatus.CORROBORATED
    return best
