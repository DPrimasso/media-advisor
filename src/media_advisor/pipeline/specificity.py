"""Step 2D — Anti-fuffa filter.

Scores claims by specificity and discards overly vague ones.
Porting of src/pipeline/specificity-filter.ts.
"""

import re

from media_advisor.models.claims import Claim

_VAGUE = re.compile(
    r"\b(importante|merita|meritano|crescita|buon|bene|male|bella|bello"
    r"|interessante|interessanti|particolare|particolari)\b",
    re.IGNORECASE,
)
_ACTION = re.compile(
    r"\b(pressare|pressing|costruire|rotazione|modulo|formazione"
    r"|5-3-2|4-3-3|scavare|gestione|allenare)\b",
    re.IGNORECASE,
)


def specificity_score(claim: Claim) -> int:
    txt = claim.claim_text
    score = 0

    if re.search(r"\d+", txt):
        score += 2
    if _ACTION.search(txt):
        score += 2
    if claim.target_entity and len(claim.target_entity) > 2:
        score += 1
    if _VAGUE.search(txt) and not _ACTION.search(txt) and not re.search(r"\d+", txt):
        score -= 2

    word_count = len([w for w in txt.split() if w])
    if 8 <= word_count <= 25:
        score += 1
    if word_count < 5:
        score -= 1

    return score


def filter_by_specificity(claims: list[Claim], min_score: int = -1) -> list[Claim]:
    return [c for c in claims if specificity_score(c) >= min_score]
