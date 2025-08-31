import re
from typing import List, Optional

from .constants import KNOWN_PREFIXES, SUFFIXES, STOPWORDS, MONTHS

def h_known_prefix(toks: List[str], text: str) -> Optional[int]:
    """Split after matching known payee prefix."""
    upper_toks = [t.upper().rstrip('.,') for t in toks]
    for prefix in KNOWN_PREFIXES:
        parts = prefix.split()
        if upper_toks[:len(parts)] == parts:
            return len(parts)
    return None

def h_last_first(toks: List[str], text: str) -> Optional[int]:
    """Split uppercase 'LAST, FIRST' patterns."""
    if len(toks) >= 2 and toks[0].endswith(',') and toks[1].rstrip('.,').isalpha():
        first_tok = toks[0].rstrip(',')
        if first_tok.isupper() and toks[1].isupper():
            if len(toks) >= 3 and toks[2].isalpha() and toks[2].isupper() and (len(toks[2]) <= 3):
                return 3
            return 2
    return None

def h_stopword(toks: List[str], text: str) -> Optional[int]:
    """Stop at stopwords unless suffix follows."""
    for i in range(1, len(toks)):
        tok = toks[i]
        if tok.strip(',').upper() in STOPWORDS:
            if tok.endswith(','):
                continue
            if i + 1 < len(toks):
                next_tok = toks[i + 1].rstrip('.,')
                if next_tok.upper() in SUFFIXES:
                    continue
                if next_tok.isupper() and len(next_tok) <= 4:
                    continue
            return i
    return None

def h_date_or_month(toks: List[str], text: str) -> Optional[int]:
    """Break at dates or month names."""
    for i in range(1, len(toks)):
        tok = toks[i].rstrip(',.')
        if re.fullmatch('\\d{1,2}/\\d{1,2}/\\d{2,4}', tok):
            return i
        if tok.upper() in MONTHS:
            return i
    return None

def h_hash_follow(toks: List[str], text: str) -> Optional[int]:
    """Break after word following '#number'."""
    for i in range(1, len(toks) - 1):
        if toks[i].startswith('#') and toks[i + 1].isalpha():
            return i + 2
    return None

def h_two_title(toks: List[str], text: str) -> Optional[int]:
    """Split two consecutive Title-case words."""
    if len(toks) >= 2 and toks[0].istitle() and toks[1].istitle():
        return 2
    return None

def h_city_of(toks: List[str], text: str) -> Optional[int]:
    """Handle 'City of' names with suffix skip."""
    if len(toks) >= 3 and toks[0].upper() == 'CITY' and toks[1].upper() == 'OF':
        idx = 3
        if len(toks) >= 4 and toks[2].upper() == 'SAN':
            idx = 4
        while idx < len(toks):
            tok = toks[idx].rstrip('.,')
            if tok.upper() in SUFFIXES:
                idx += 1
                continue
            if tok.upper() in STOPWORDS and idx + 1 < len(toks) and toks[idx + 1].rstrip('.,').upper() in SUFFIXES:
                idx += 2
                continue
            break
        return idx
    return None

def h_close_paren(toks: List[str], text: str) -> Optional[int]:
    """Split after token closing parenthesis."""
    for i in range(len(toks) - 1):
        if toks[i].endswith(')'):
            next_tok = toks[i + 1].rstrip('.,')
            if next_tok.upper() not in SUFFIXES:
                return i + 1
    return None

def h_suffix(toks: List[str], text: str) -> Optional[int]:
    """Split after trailing suffix tokens."""
    for i in range(len(toks) - 1, -1, -1):
        if toks[i].rstrip('.,').upper() in SUFFIXES:
            return i + 1
    return None

HEURISTICS = [
    ('known_prefix', 8, h_known_prefix),
    ('last_first', 6, h_last_first),
    ('date_or_month', 4, h_date_or_month),
    ('hash_follow', 6, h_hash_follow),
    ('two_title', 3, h_two_title),
    ('close_paren', 7, h_close_paren),
    ('stopword', 6, h_stopword),
    ('city_of', 5, h_city_of),
    ('suffix', 5, h_suffix),
]
