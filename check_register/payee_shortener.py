import re

SUFFIXES_TO_DROP = [
    ", INC",
    ", INC.",
    ", LLC",
    ", LLC.",
    ", CO",
    ", CO.",
    ", CORP",
    ", CORP.",
    ", LTD",
    ", LTD.",
    ", LP",
    ", LP.",
    ", LLP",
    ", LLP.",
]

PAREN_PATTERNS = [
    r"\([^)]*formerly[^)]*\)",
    r"\([^)]*dba [^)]*\)",
]

WORD_CONTRACTIONS = {
    "ENTERPRISES": "ENT",
    "ENGINEERING": "ENG",
    "SERVICES": "SVCS",
    "MANAGEMENT": "MGMT",
    "ASSOCIATION": "ASSOC",
}


def shorten_payee(name: str) -> str:
    """Return a shortened payee name."""
    out = name

    for pat in PAREN_PATTERNS:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)

    out = out.strip()

    changed = True
    while changed:
        changed = False
        upper = out.upper()
        for suffix in SUFFIXES_TO_DROP:
            if upper.endswith(suffix):
                out = out[: -len(suffix)]
                out = out.rstrip()
                upper = out.upper()
                changed = True
    words_pat = re.compile(
        r"\b(" + "|".join(map(re.escape, WORD_CONTRACTIONS.keys())) + r")\b",
        re.IGNORECASE,
    )
    out = words_pat.sub(lambda m: WORD_CONTRACTIONS[m.group(0).upper()], out)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"[.,;:-]+$", "", out)
    return out.strip()
