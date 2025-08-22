import re
from typing import List, Optional

from .constants import KNOWN_PREFIXES, SUFFIXES, STOPWORDS, MONTHS

def h_known_prefix(toks: List[str], text: str) -> Optional[int]:
    upper_toks = [t.upper().rstrip('.,') for t in toks]
    for prefix in KNOWN_PREFIXES:
        parts = prefix.split()
        if upper_toks[:len(parts)] == parts:
            return len(parts)
    return None

def h_fd_number(toks: List[str], text: str) -> Optional[int]:
    for i in range(len(toks) - 1):
        if toks[i].upper() == 'FD' and toks[i + 1].isdigit():
            return i
    return None

def h_middle_initial(toks: List[str], text: str) -> Optional[int]:
    if len(toks) >= 3:
        first, middle, last = (toks[0], toks[1], toks[2])
        if re.fullmatch('[A-Za-z]+', first.rstrip('.,')) and re.fullmatch('[A-Za-z]\\.?', middle.rstrip(',')) and re.fullmatch('[A-Za-z]+', last.rstrip('.,')):
            return 3
    return None

def h_comma_pair(toks: List[str], text: str) -> Optional[int]:
    if len(toks) >= 2 and toks[0].endswith(',') and toks[1].rstrip('.,').isalpha():
        if not (toks[0].rstrip(',').isupper() and toks[1].isupper()):
            return 2
    return None

def h_last_first(toks: List[str], text: str) -> Optional[int]:
    if len(toks) >= 2 and toks[0].endswith(',') and toks[1].rstrip('.,').isalpha():
        first_tok = toks[0].rstrip(',')
        if first_tok.isupper() and toks[1].isupper():
            if len(toks) >= 3 and toks[2].isalpha() and toks[2].isupper() and (len(toks[2]) <= 3):
                return 3
            return 2
    return None

def h_year(toks: List[str], text: str) -> Optional[int]:
    for i in range(1, len(toks)):
        if re.fullmatch('\\d{4}', toks[i]):
            if any((t.rstrip('.,').upper() in SUFFIXES for t in toks[:i])):
                continue
            if i == len(toks) - 1:
                continue
            return i
    return None

def h_stopword(toks: List[str], text: str) -> Optional[int]:
    for i in range(1, len(toks)):
        tok = toks[i]
        if tok.strip(',').upper() in STOPWORDS:
            if tok.endswith(','):
                continue
            if i + 1 < len(toks) and toks[i + 1].rstrip('.,').upper() in SUFFIXES:
                continue
            return i
    return None

def h_date_or_month(toks: List[str], text: str) -> Optional[int]:
    for i in range(1, len(toks)):
        tok = toks[i].rstrip(',.')
        if re.fullmatch('\\d{1,2}/\\d{1,2}/\\d{2,4}', tok):
            return i
        if tok.upper() in MONTHS:
            return i
    return None

def h_alphanum(toks: List[str], text: str) -> Optional[int]:
    for i in range(1, len(toks)):
        tok = toks[i].rstrip(',.')
        if tok.startswith('#'):
            continue
        if re.search('[A-Za-z]', tok) and re.search('\\d', tok):
            return i
    return None

def h_hash_follow(toks: List[str], text: str) -> Optional[int]:
    for i in range(1, len(toks) - 1):
        if toks[i].startswith('#') and toks[i + 1].isalpha():
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
    if len(toks) >= 3 and toks[0].upper() == 'CITY' and (toks[1].upper() == 'OF'):
        if len(toks) >= 4 and toks[2].upper() == 'SAN':
            return 4
        return 3
    return None

def h_double_space(toks: List[str], text: str) -> Optional[int]:
    m = re.search('\\s{2,}', text)
    if m:
        return len(text[:m.start()].split())
    return None

def h_suffix(toks: List[str], text: str) -> Optional[int]:
    for i in range(len(toks) - 1, -1, -1):
        if toks[i].rstrip('.,').upper() in SUFFIXES:
            return i + 1
    return None

def h_default(toks: List[str], text: str) -> Optional[int]:
    return 1

HEURISTICS = [('known_prefix', 5, h_known_prefix), ('fd_number', 4, h_fd_number), ('middle_initial', 4, h_middle_initial), ('comma_pair', 4, h_comma_pair), ('last_first', 6, h_last_first), ('year', 4, h_year), ('date_or_month', 4, h_date_or_month), ('alphanum', 5, h_alphanum), ('hash_follow', 6, h_hash_follow), ('two_title', 3, h_two_title), ('stopword', 4, h_stopword), ('column_alignment', 2, h_column_alignment), ('last_comma', 2, h_last_comma), ('city_of', 5, h_city_of), ('double_space', 1, h_double_space), ('suffix', 5, h_suffix), ('default', 1, h_default)]
