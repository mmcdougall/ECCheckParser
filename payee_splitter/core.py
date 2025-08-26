"""Core payee/description splitting logic.

Heavy heuristics live in :mod:`heuristics`, leaving this module to focus on
tokenisation, voting and a bit of post-processing.  Keeping the heuristics
separate makes the core easier for humans to read.
"""

import re
from typing import List, Tuple

from .constants import PREFIX_SET
from .heuristics import HEURISTICS


def _normalize_block(block: str) -> Tuple[str, List[str]]:
    """Return a normalised block along with whitespace-split tokens."""

    block = (
        block.replace("\r", " ")
        .replace("\n", " ")
        .replace(" ,", ",")
        .strip()
    )
    block = re.sub(",(?=[A-Za-z])", ", ", block)
    tokens = block.split()
    return block, tokens


def _merge_letter_prefixes(tokens: List[str]) -> List[str]:
    """Merge recognised single-letter prefixes such as ``A B C`` -> ``ABC``."""

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
    return tokens


def _apply_heuristics(tokens: List[str], block: str) -> int:
    """Return the payee/description boundary index based on heuristic votes."""

    scores = [0] * len(tokens)

    def vote(idx: int, weight: int) -> None:
        if 1 <= idx < len(tokens):
            scores[idx] += weight

    for _name, weight, func in HEURISTICS:
        idx = func(tokens, block)
        if idx is not None:
            vote(idx, weight)

    return max(range(1, len(tokens)), key=lambda i: (scores[i], -i))


def split_payee_desc_block(block: str) -> Tuple[str, str]:
    """Split a block containing payee and description using weighted votes."""

    block, tokens = _normalize_block(block)
    if not tokens:
        return ("", "")

    tokens = _merge_letter_prefixes(tokens)
    if len(tokens) == 1:
        return (tokens[0], "")

    best_idx = _apply_heuristics(tokens, block)

    payee = " ".join(tokens[:best_idx]).rstrip(",").strip()
    desc = " ".join(tokens[best_idx:]).strip()

    # Convert "LAST, FIRST" into a nicer upper-case form.
    if "," in payee:
        parts = [p.strip() for p in payee.split(",")]
        if len(parts) == 2 and parts[0].istitle() and parts[1].istitle():
            payee = " ".join(parts).upper()

    return (payee, desc)

