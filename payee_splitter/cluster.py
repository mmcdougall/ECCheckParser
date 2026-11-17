from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Tuple, TYPE_CHECKING

from register_format import AMOUNT_RE, SOURCE_RE, split_row_header

from .core import _tidy_text

if TYPE_CHECKING:
    from check_register.models import PositionedWord


def _squeeze_letters(tokens: List[PositionedWord]) -> List[PositionedWord]:
    """Merge runs of single letters into a single token.

    Some payees such as ``P E R S`` have their letters extracted as separate
    PDF words.  These individual tokens confuse the column split logic because
    the gaps between letters can exceed the gap to the description column.  We
    merge adjacent single-letter tokens when their x-distance is tiny to
    reconstruct the original word.
    """

    if not tokens:
        return tokens

    squeezed: List[PositionedWord] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if len(t.text) == 1 and t.text.isalpha():
            letters = [t.text]
            x_last = t.x0
            j = i + 1
            while (
                j < len(tokens)
                and len(tokens[j].text) == 1
                and tokens[j].text.isalpha()
                and 0 <= tokens[j].x0 - x_last <= 6
            ):
                letters.append(tokens[j].text)
                x_last = tokens[j].x0
                j += 1
            if len(letters) > 1:
                squeezed.append(replace(t, text="".join(letters)))
                i = j
                continue
        squeezed.append(t)
        i += 1
    return squeezed


def _collect_tokens_after_source(
    line_words: List[List[PositionedWord]],
) -> Optional[List[PositionedWord]]:
    """Gather the row payload using the shared metadata boundary."""
    if not line_words or not line_words[0]:
        return None
    first = line_words[0]
    text = " ".join(word.text for word in first)
    source = SOURCE_RE.search(text)
    if source:
        start = len(text[:source.end()].split())
    else:
        fields = split_row_header(text)
        if fields is None:
            return None
        start = len(first) - len(fields[4].split())
    tokens = []
    amount_found = False
    for line in [first[start:], *line_words[1:]]:
        payload = line if amount_found else _drop_trailing_amount(line)
        amount_found = amount_found or len(payload) < len(line)
        tokens.extend(payload)
    return tokens or None


def _drop_trailing_amount(tokens: List[PositionedWord]) -> List[PositionedWord]:
    """Remove a trailing amount token, if present.

    Amounts follow the description and use a wide preceding gap that could be
    mistaken for the column split.  Trimming that token ensures threshold
    detection only sees payee and description words.
    """

    if tokens and AMOUNT_RE.fullmatch(tokens[-1].text):
        tokens = tokens[:-1]
        if tokens and tokens[-1].text == "$":
            tokens = tokens[:-1]
    return tokens


def _determine_column_threshold(tokens: List[PositionedWord]) -> Optional[float]:
    """Find the x boundary separating payee and description tokens.

    The algorithm enumerates all potential splits, computing the sum of squared
    distances to each side's mean x position.  The split with the minimal cost
    acts as a 1D k-means clustering and yields the threshold.  ``None`` is
    returned when the search lacks enough distinct positions.
    """

    xs = sorted(t.x0 for t in tokens)
    if len(xs) < 2:
        return None

    best_cost = float("inf")
    best_thresh: Optional[float] = None
    for i in range(1, len(xs)):
        left = xs[:i]
        right = xs[i:]
        mean_l = sum(left) / len(left)
        mean_r = sum(right) / len(right)
        cost = sum((x - mean_l) ** 2 for x in left) + sum((x - mean_r) ** 2 for x in right)
        if cost < best_cost:
            best_cost = cost
            best_thresh = (xs[i - 1] + xs[i]) / 2.0

    return best_thresh


def infer_description_column_x0(
    rows: List[List[List[PositionedWord]]],
) -> Optional[float]:
    """Return the left edge of the most frequent column alignment.

    Starts within one PDF point share an alignment. Its left edge includes
    descriptions whose placement differs slightly between rows.
    """
    positions = []
    for line_words in rows:
        tokens = _collect_tokens_after_source(line_words)
        if tokens:
            positions.extend(token.x0 for token in tokens[1:])

    alignments: List[List[float]] = []
    for position in sorted(positions):
        if not alignments or position - alignments[-1][0] >= 1:
            alignments.append([])
        alignments[-1].append(position)
    column = max(alignments, key=lambda values: (len(values), values[0]), default=[])
    return column[0] if len(column) >= 3 else None


def split_payee_desc_by_x(
    line_words: List[List[PositionedWord]],
    description_x0: Optional[float] = None,
) -> Optional[Tuple[str, str]]:
    """Split payee/description using x-coordinate clustering.

    The parser provides ``line_words`` which captures each PDF word and its
    starting ``x`` position.  Typical check register entries show the payee and
    description separated into two vertical columns.  By clustering ``x``
    coordinates we can infer the boundary between the two columns and avoid
    relying on brittle text heuristics.

    Parameters
    ----------
    line_words:
        Tokenised words for each line with their ``x0`` coordinates.

    Returns
    -------
    tuple of (payee, description) or ``None`` if the data doesn't resemble the
    expected pattern.
    """

    tokens = _collect_tokens_after_source(line_words)
    if not tokens:
        return None

    tokens = _squeeze_letters(tokens)

    if description_x0 is None:
        threshold = _determine_column_threshold(tokens)
        if threshold is None:
            return None
        payee_tokens = [t.text for t in tokens if t.x0 <= threshold]
        desc_tokens = [t.text for t in tokens if t.x0 > threshold]
    else:
        payee_tokens = [t.text for t in tokens if t.x0 < description_x0 - 0.01]
        desc_tokens = [t.text for t in tokens if t.x0 >= description_x0 - 0.01]

    payee = _tidy_text(" ".join(payee_tokens).rstrip(',').strip())
    desc = _tidy_text(" ".join(desc_tokens).strip())

    if not payee and not desc:
        return None

    return payee, desc
