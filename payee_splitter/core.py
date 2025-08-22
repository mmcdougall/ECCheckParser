import re
from typing import List, Optional, Tuple
from .constants import STOPWORDS, SUFFIXES, MONTHS, PREFIX_SET
from .heuristics import HEURISTICS


def split_payee_desc_block(block: str) -> Tuple[str, str]:
    """Split a block containing payee and description using weighted votes.

    Each heuristic returns a token boundary index and is assigned a weight.
    Boundaries accumulate votes and the highest scoring split wins.  Some
    HEURISTICS may abstain by returning ``None``.
    """
    block = block.replace('\r', ' ').replace('\n', ' ').replace(' ,', ',').strip()
    block = re.sub(',(?=[A-Za-z])', ', ', block)
    if not block:
        return ('', '')
    tokens = block.split()
    if not tokens:
        return ('', '')
    i = 0
    letters: List[str] = []
    while i < len(tokens):
        tok = tokens[i]
        stripped = tok.rstrip('.,')
        if len(stripped) == 1 and stripped.isalpha():
            letters.append(stripped.upper())
            i += 1
        else:
            break
    if len(letters) > 1:
        joined = ''.join(letters)
        if joined in PREFIX_SET:
            tokens = [joined] + tokens[i:]
    if len(tokens) == 1:
        return (tokens[0], '')
    scores = [0] * len(tokens)

    def vote(idx: int, weight: int) -> None:
        if 1 <= idx < len(tokens):
            scores[idx] += weight
    for _name, weight, func in HEURISTICS:
        idx = func(tokens, block)
        if idx is not None:
            vote(idx, weight)
    best_idx = max(range(1, len(tokens)), key=lambda i: (scores[i], -i))
    suffix_pos = None
    for i, tok in enumerate(tokens):
        if tok.rstrip('.,').upper() in SUFFIXES:
            suffix_pos = i
    if suffix_pos is not None and best_idx > suffix_pos + 1:
        if not tokens[suffix_pos + 1].startswith('#'):
            best_idx = suffix_pos + 1
    payee = ' '.join(tokens[:best_idx]).rstrip(',')
    desc = ' '.join(tokens[best_idx:])
    payee = payee.strip()
    if ',' in payee:
        parts = [p.strip() for p in payee.split(',')]
        if len(parts) == 2 and parts[0].istitle() and parts[1].istitle():
            payee = ' '.join(parts).upper()
    desc = desc.strip()
    if not desc and len(tokens) > 3:
        payee = ' '.join(tokens[:3]).strip().rstrip(',')
        desc = ' '.join(tokens[3:]).strip()
    if re.fullmatch('\\d{4}', desc):
        payee = f'{payee} {desc}'.strip().rstrip(',')
        desc = ''
    payee_tokens = tokens[:best_idx]
    desc_tokens = tokens[best_idx:]
    repair_needed = not desc_tokens
    for i in range(1, len(payee_tokens)):
        tok = payee_tokens[i]
        stripped = tok.rstrip(',.')
        if stripped.upper() in STOPWORDS:
            if tok.endswith(','):
                continue
            if i + 1 < len(payee_tokens) and payee_tokens[i + 1].rstrip('.,').upper() in SUFFIXES:
                continue
            repair_needed = True
            break
        if stripped.upper() in MONTHS or re.fullmatch('\\d{1,2}/\\d{1,2}/\\d{2,4}', stripped) or (re.search('\\d', stripped) and (not stripped.startswith('#'))):
            repair_needed = True
            break
    if repair_needed:
        for i in range(1, len(tokens)):
            tok = tokens[i]
            stripped = tok.rstrip(',.')
            if stripped.upper() in STOPWORDS:
                if tok.endswith(','):
                    continue
                if i + 1 < len(tokens) and tokens[i + 1].rstrip('.,').upper() in SUFFIXES:
                    continue
                payee = ' '.join(tokens[:i]).strip().rstrip(',')
                desc = ' '.join(tokens[i:]).strip()
                break
            if stripped.upper() in MONTHS or re.fullmatch('\\d{1,2}/\\d{1,2}/\\d{2,4}', stripped) or (re.search('\\d', stripped) and (not stripped.startswith('#'))):
                payee = ' '.join(tokens[:i]).strip().rstrip(',')
                desc = ' '.join(tokens[i:]).strip()
                break
    return (payee, desc)
