import re
from typing import List, Optional, Tuple


def split_payee_desc_block(block: str) -> Tuple[str, str]:
    """Split a block containing payee and description using weighted votes.

    Each heuristic returns a token boundary index and is assigned a weight.
    Boundaries accumulate votes and the highest scoring split wins.  Some
    heuristics may abstain by returning ``None``.
    """
    block = (
        block.replace("\r", " ")
        .replace("\n", " ")
        .replace(" ,", ",")
        .strip()
    )
    block = re.sub(r",(?=[A-Za-z])", ", ", block)
    if not block:
        return "", ""

    STOPWORDS = {
        "MERCHANT",
        "OFFICE",
        "SUPPLIES",
        "EXPENSE",
        "FEE",
        "FEES",
        "PAYMENT",
        "RE",
        "RE:",
        "TOTAL",
        "REIMBURSEMENT",
        "REIMBURSE",
        "PERFORMANCE",
        "CONTRACT",
        "RENTAL",
        "PROGRAM",
        "TRAINING",
        "PER",
        "DIEM",
        "INVOICE",
        "PROFESSIONAL",
        "TUITION",
    }

    KNOWN_PREFIXES = [
        "ALAMEDA COUNTY FIRE DEPARTMENT",
        "BAY AREA NEWS GROUP",
        "DIEGO TRUCK REPAIR",
        "L.N. CURTIS & SONS",
        "J & O'S COMMERCIAL TIRE CENTER",
        "MUNICIPAL POOLING AUTHORITY",
        "KAISER FOUNDATION HEALTH PLAN",
        "EAST BAY REGIONAL COMMUNICATIONS SYSTEM",
        "CONTRA COSTA HEALTH SERVICES",
        "GHIRARDELLI ASSOCIATES",
        "FLOCK SAFETY",
        "PERS",
    ]

    SUFFIXES = {
        "LLP",
        "LLC",
        "INC",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LTD",
        "ASSOCIATES",
        "SUPPLY",
        "SERVICE",
        "SERVICES",
        "MANAGEMENT",
        "ELECTRIC",
    }
    MONTHS = {
        "JAN",
        "JANUARY",
        "FEB",
        "FEBRUARY",
        "MAR",
        "MARCH",
        "APR",
        "APRIL",
        "MAY",
        "JUN",
        "JUNE",
        "JUL",
        "JULY",
        "AUG",
        "AUGUST",
        "SEP",
        "SEPT",
        "SEPTEMBER",
        "OCT",
        "OCTOBER",
        "NOV",
        "NOVEMBER",
        "DEC",
        "DECEMBER",
    }
    PREFIX_SET = {p.upper() for p in KNOWN_PREFIXES}

    tokens = block.split()
    if not tokens:
        return "", ""

    i = 0
    letters: List[str] = []
    while i < len(tokens):
        tok = tokens[i]
        stripped = tok.rstrip(".,")
        if len(stripped) == 1 and stripped.isalpha():
            letters.append(stripped.upper())
            i += 1
        else:
            break
    if len(letters) > 1:
        joined = "".join(letters)
        if joined in PREFIX_SET:
            tokens = [joined] + tokens[i:]

    if len(tokens) == 1:
        return tokens[0], ""

    scores = [0] * (len(tokens))  # index == boundary after tokens[i-1]

    def vote(idx: int, weight: int) -> None:
        if 1 <= idx < len(tokens):
            scores[idx] += weight

    def h_known_prefix(toks: List[str], text: str) -> Optional[int]:
        upper_toks = [t.upper().rstrip(".,") for t in toks]
        for prefix in KNOWN_PREFIXES:
            parts = prefix.split()
            if upper_toks[: len(parts)] == parts:
                return len(parts)
        return None

    def h_fd_number(toks: List[str], text: str) -> Optional[int]:
        for i in range(len(toks) - 1):
            if toks[i].upper() == "FD" and toks[i + 1].isdigit():
                return i
        return None

    def h_middle_initial(toks: List[str], text: str) -> Optional[int]:
        if len(toks) >= 3:
            first, middle, last = toks[0], toks[1], toks[2]
            if (
                re.fullmatch(r"[A-Za-z]+", first.rstrip(".,"))
                and re.fullmatch(r"[A-Za-z]\.?", middle.rstrip(","))
                and re.fullmatch(r"[A-Za-z]+", last.rstrip(".,"))
            ):
                return 3
        return None

    def h_comma_pair(toks: List[str], text: str) -> Optional[int]:
        if len(toks) >= 2 and toks[0].endswith(",") and toks[1].rstrip(".,").isalpha():
            if not (toks[0].rstrip(",").isupper() and toks[1].isupper()):
                return 2
        return None

    def h_last_first(toks: List[str], text: str) -> Optional[int]:
        if len(toks) >= 2 and toks[0].endswith(",") and toks[1].rstrip(".,").isalpha():
            first_tok = toks[0].rstrip(",")
            if first_tok.isupper() and toks[1].isupper():
                if (
                    len(toks) >= 3
                    and toks[2].isalpha()
                    and toks[2].isupper()
                    and len(toks[2]) <= 3
                ):
                    return 3
                return 2
        return None

    def h_year(toks: List[str], text: str) -> Optional[int]:
        for i in range(1, len(toks)):
            if re.fullmatch(r"\d{4}", toks[i]):
                if any(t.rstrip(".,").upper() in SUFFIXES for t in toks[:i]):
                    continue
                if i == len(toks) - 1:
                    continue
                return i
        return None

    def h_stopword(toks: List[str], text: str) -> Optional[int]:
        for i in range(1, len(toks)):
            tok = toks[i]
            if tok.strip(",").upper() in STOPWORDS:
                if tok.endswith(","):
                    continue
                if i + 1 < len(toks) and toks[i + 1].rstrip(".,").upper() in SUFFIXES:
                    continue
                return i
        return None

    def h_date_or_month(toks: List[str], text: str) -> Optional[int]:
        for i in range(1, len(toks)):
            tok = toks[i].rstrip(",.")
            if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", tok):
                return i
            if tok.upper() in MONTHS:
                return i
        return None

    def h_alphanum(toks: List[str], text: str) -> Optional[int]:
        for i in range(1, len(toks)):
            tok = toks[i].rstrip(",.")
            if tok.startswith("#"):
                continue
            if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok):
                return i
        return None

    def h_hash_follow(toks: List[str], text: str) -> Optional[int]:
        for i in range(1, len(toks) - 1):
            if toks[i].startswith("#") and toks[i + 1].isalpha():
                return i + 2
        return None

    def h_two_title(toks: List[str], text: str) -> Optional[int]:
        if len(toks) >= 2 and toks[0].istitle() and toks[1].istitle():
            return 2
        return None

    def h_column_alignment(toks: List[str], text: str) -> Optional[int]:
        pos = 0
        for i, tok in enumerate(toks):
            pos += len(tok) + 1
            if pos >= 45:
                return i + 1
        return None

    def h_last_comma(toks: List[str], text: str) -> Optional[int]:
        last = None
        for i, tok in enumerate(toks):
            if tok.endswith(','):
                last = i + 1
        return last

    def h_city_of(toks: List[str], text: str) -> Optional[int]:
        if len(toks) >= 3 and toks[0].upper() == "CITY" and toks[1].upper() == "OF":
            if len(toks) >= 4 and toks[2].upper() == "SAN":
                return 4
            return 3
        return None

    def h_double_space(toks: List[str], text: str) -> Optional[int]:
        m = re.search(r"\s{2,}", text)
        if m:
            return len(text[: m.start()].split())
        return None

    def h_suffix(toks: List[str], text: str) -> Optional[int]:
        for i in range(len(toks) - 1, -1, -1):
            if toks[i].rstrip(".,").upper() in SUFFIXES:
                return i + 1
        return None

    def h_default(toks: List[str], text: str) -> Optional[int]:
        return 1

    heuristics = [
        ("known_prefix", 5, h_known_prefix),
        ("fd_number", 4, h_fd_number),
        ("middle_initial", 4, h_middle_initial),
        ("comma_pair", 4, h_comma_pair),
        ("last_first", 6, h_last_first),
        ("year", 4, h_year),
        ("date_or_month", 4, h_date_or_month),
        ("alphanum", 5, h_alphanum),
        ("hash_follow", 6, h_hash_follow),
        ("two_title", 3, h_two_title),
        ("stopword", 4, h_stopword),
        ("column_alignment", 2, h_column_alignment),
        ("last_comma", 2, h_last_comma),
        ("city_of", 5, h_city_of),
        ("double_space", 1, h_double_space),
        ("suffix", 5, h_suffix),
        ("default", 1, h_default),
    ]

    for _name, weight, func in heuristics:
        idx = func(tokens, block)
        if idx is not None:
            vote(idx, weight)

    best_idx = max(range(1, len(tokens)), key=lambda i: (scores[i], -i))
    suffix_pos = None
    for i, tok in enumerate(tokens):
        if tok.rstrip(".,").upper() in SUFFIXES:
            suffix_pos = i
    if suffix_pos is not None and best_idx > suffix_pos + 1:
        if not tokens[suffix_pos + 1].startswith("#"):
            best_idx = suffix_pos + 1

    payee = " ".join(tokens[:best_idx]).rstrip(",")
    desc = " ".join(tokens[best_idx:])

    payee = payee.strip()
    if "," in payee:
        parts = [p.strip() for p in payee.split(",")]
        if len(parts) == 2 and parts[0].istitle() and parts[1].istitle():
            payee = " ".join(parts).upper()
    desc = desc.strip()
    if not desc and len(tokens) > 3:
        payee = " ".join(tokens[:3]).strip().rstrip(",")
        desc = " ".join(tokens[3:]).strip()
    if re.fullmatch(r"\d{4}", desc):
        payee = f"{payee} {desc}".strip().rstrip(",")
        desc = ""

    payee_tokens = tokens[:best_idx]
    desc_tokens = tokens[best_idx:]
    repair_needed = not desc_tokens
    for i in range(1, len(payee_tokens)):
        tok = payee_tokens[i]
        stripped = tok.rstrip(",.")
        if stripped.upper() in STOPWORDS:
            if tok.endswith(','):
                continue
            if i + 1 < len(payee_tokens) and payee_tokens[i + 1].rstrip(".,").upper() in SUFFIXES:
                continue
            repair_needed = True
            break
        if (
            stripped.upper() in MONTHS
            or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", stripped)
            or (re.search(r"\d", stripped) and not stripped.startswith("#"))
        ):
            repair_needed = True
            break

    if repair_needed:
        for i in range(1, len(tokens)):
            tok = tokens[i]
            stripped = tok.rstrip(",.")
            if stripped.upper() in STOPWORDS:
                if tok.endswith(','):
                    continue
                if i + 1 < len(tokens) and tokens[i + 1].rstrip(".,").upper() in SUFFIXES:
                    continue
                payee = " ".join(tokens[:i]).strip().rstrip(",")
                desc = " ".join(tokens[i:]).strip()
                break
            if (
                stripped.upper() in MONTHS
                or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", stripped)
                or (re.search(r"\d", stripped) and not stripped.startswith("#"))
            ):
                payee = " ".join(tokens[:i]).strip().rstrip(",")
                desc = " ".join(tokens[i:]).strip()
                break

    return payee, desc
