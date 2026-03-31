"""Step 2C — Video-level aggregation.

Semantic dedup (Jaccard), rank by specificity + quote quality, keep max 12 claims.
Porting of src/pipeline/video-aggregator.ts.
"""

from media_advisor.models.claims import Claim, Theme, VideoAnalysis
from media_advisor.pipeline.specificity import specificity_score

_SYNONYMS: dict[str, str] = {
    "injuries": "infortunio",
    "injury": "infortunio",
    "infortuni": "infortunio",
    "performance": "prestazione",
    "tactics": "tattica",
    "market": "mercato",
    "motivation": "motivazione",
    "finance": "finanza",
    "rivalry": "rivalità",
    "standings": "classifica",
    "refereeing": "arbitraggio",
    "nazionalita": "nazionalità",
    "nationality": "nazionalità",
    "comunicazione": "comunicazione",
    "communication": "comunicazione",
    "lealta": "lealtà",
    "loyalty": "lealtà",
    "management": "dirigenza",
}

_NON_ITALIAN_CHARS = str.maketrans(
    {"ț": "t", "ţ": "t", "ș": "s", "ş": "s", "ă": "a", "â": "a", "î": "i", "ő": "o", "ű": "u"}
)

_GENERIC_TOPICS: set[str] = {
    "calciatore", "giocatore", "squadra", "club", "legame", "calcio",
    "sport", "discussione", "analisi", "video", "tema", "argomento",
}


def _normalize_theme(raw: str) -> str:
    sanitized = raw.translate(_NON_ITALIAN_CHARS).lower().strip()
    return _SYNONYMS.get(sanitized, sanitized)


def _similarity(a: str, b: str) -> float:
    ta = {w for w in a.lower().split() if len(w) > 2}
    tb = {w for w in b.lower().split() if len(w) > 2}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


def _quote_quality(claim: Claim) -> float:
    q = claim.evidence_quotes[0] if claim.evidence_quotes else None
    if not q:
        return 0.0
    score = q.confidence
    length = len(q.quote_text)
    if length > 20:
        score += 0.2
    if length > 50:
        score += 0.2
    return score


def aggregate_video_claims(
    claims: list[Claim],
    themes: list[Theme],
    video_id: str,
    summary_short: str,
    similarity_threshold: float = 0.40,
    max_claims: int = 12,
) -> VideoAnalysis:
    # Drop trivial claims (intensity 0 = too vague)
    substantive = [c for c in claims if c.intensity > 0]

    kept: list[Claim] = []
    used: set[int] = set()

    for i in range(len(substantive)):
        if i in used or len(kept) >= max_claims:
            continue
        best_idx = i
        for j in range(i + 1, len(substantive)):
            if j in used:
                continue
            sim = _similarity(substantive[i].claim_text, substantive[j].claim_text)
            if sim >= similarity_threshold:
                si = specificity_score(substantive[i]) + _quote_quality(substantive[i])
                sj = specificity_score(substantive[j]) + _quote_quality(substantive[j])
                if sj > si:
                    best_idx = j
                used.add(j)
        if best_idx not in used:
            kept.append(substantive[best_idx])
            used.add(best_idx)

    kept.sort(key=lambda c: specificity_score(c) + _quote_quality(c), reverse=True)
    final_claims = kept[:max_claims]

    # Deduplicate and normalize themes, drop generic ones
    theme_map: dict[str, float] = {}
    for t in themes:
        key = _normalize_theme(t.theme)
        theme_map[key] = theme_map.get(key, 0.0) + t.weight

    meaningful = [
        Theme(theme=k, weight=w)
        for k, w in theme_map.items()
        if k not in _GENERIC_TOPICS
    ]
    meaningful.sort(key=lambda t: t.weight, reverse=True)
    top_themes = meaningful[:10]

    total_weight = sum(t.weight for t in top_themes) or 1.0
    norm_themes = [
        Theme(theme=t.theme, weight=round(t.weight / total_weight * 100))
        for t in top_themes
    ]

    return VideoAnalysis(
        video_id=video_id,
        themes=norm_themes,
        claims=final_claims,
        summary_short=summary_short[:1200],
    )
