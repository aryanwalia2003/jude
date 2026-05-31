"""Deterministic context ranking with audit trails.

Scores symbols based on multiple deterministic factors and logs decisions.
No randomness, no LLM — pure algorithmic ranking with transparent reasoning.
"""

import math
import sqlite3
from dataclasses import dataclass, field

from . import db, metrics

WEIGHT_TEXT_RELEVANCE = 2.0
WEIGHT_CALL_FREQUENCY = 1.5
WEIGHT_RECENCY = 0.8
WEIGHT_NAME_MATCH = 0.5
WEIGHT_CODE_HUB = 0.3

WEIGHT_IMPACT_COUNT = 2.0
WEIGHT_MODULE_SPREAD = 1.0


@dataclass
class RankingFactor:
    """Single scoring factor contribution."""
    name: str
    value: float
    weight: float
    contribution: float  # value * weight


@dataclass
class RankingAudit:
    """Transparent audit trail for ranking decision."""
    name: str
    kind: str
    file_path: str
    rank_position: int
    composite_score: float
    factors: list[RankingFactor] = field(default_factory=list)

    @property
    def explanation(self) -> str:
        """Human-readable explanation of ranking."""
        if not self.factors:
            return f"{self.name}: no factors evaluated"
        lines = [f"{self.name} (rank #{self.rank_position}, score={self.composite_score:.3f})"]
        for f in self.factors:
            lines.append(f"  {f.name}: {f.value:.2f} * {f.weight:.2f} = {f.contribution:.3f}")
        return "\n".join(lines)


def deterministic_score(
    conn: sqlite3.Connection,
    symbol_name: str,
    query: str,
    bm25_score: float,
    caller_count: int,
    last_indexed_at: int,
    max_time: int,
) -> tuple[float, list[RankingFactor]]:
    """Compute deterministic ranking score with factors."""
    factors: list[RankingFactor] = []
    total_score = 0.0

    # Factor 1: Text relevance (BM25)
    bm25_normalized = max(0, -bm25_score) / max(1, max_time)
    f1_contrib = bm25_normalized * WEIGHT_TEXT_RELEVANCE
    factors.append(RankingFactor("text_relevance", bm25_normalized, WEIGHT_TEXT_RELEVANCE, f1_contrib))
    total_score += f1_contrib

    # Factor 2: Call frequency (hub score)
    hub_score = math.log1p(caller_count)
    f2_contrib = hub_score * WEIGHT_CALL_FREQUENCY
    factors.append(RankingFactor("call_frequency", hub_score, WEIGHT_CALL_FREQUENCY, f2_contrib))
    total_score += f2_contrib

    # Factor 3: Recency
    recency_score = (last_indexed_at / max(1, max_time)) if max_time > 0 else 0.0
    f3_contrib = recency_score * WEIGHT_RECENCY
    factors.append(RankingFactor("recency", recency_score, WEIGHT_RECENCY, f3_contrib))
    total_score += f3_contrib

    # Factor 4: Name match
    query_words = {w.lower() for w in query.split() if w}
    name_words = set(symbol_name.lower().split("_"))
    overlap = len(query_words & name_words)
    name_bonus = min(overlap, 3) * 0.5
    f4_contrib = name_bonus * WEIGHT_NAME_MATCH
    factors.append(RankingFactor("name_match", name_bonus, WEIGHT_NAME_MATCH, f4_contrib))
    total_score += f4_contrib

    # Factor 5: Code hub score
    fan_in_score = _compute_fan_in_score(conn, symbol_name)
    if fan_in_score is not None:
        f5_contrib = fan_in_score * WEIGHT_CODE_HUB
        factors.append(RankingFactor("code_hub_score", fan_in_score, WEIGHT_CODE_HUB, f5_contrib))
        total_score += f5_contrib

    return total_score, factors


def _compute_fan_in_score(conn: sqlite3.Connection, symbol_name: str) -> float | None:
    """Compute fan-in score for a symbol, or None if unavailable."""
    try:
        all_metrics = metrics.symbol_metrics(conn)
        for m in all_metrics:
            if m.name == symbol_name:
                return math.log1p(m.fan_in) / 3.0
        return None
    except Exception:
        return None


def rank_search_results(
    conn: sqlite3.Connection,
    results: list[dict],
    query: str,
    limit: int = 20,
) -> tuple[list[dict], list[RankingAudit]]:
    """Rank search results with deterministic scoring and audit trail.

    Returns: (ranked_results, audit_trail)
    """
    if not results:
        return [], []

    max_time = max((r["last_indexed_at"] for r in results), default=1) or 1
    scored_results = []

    for row in results:
        score, factors = deterministic_score(
            conn=conn,
            symbol_name=row["name"],
            query=query,
            bm25_score=row["bm25_score"],
            caller_count=row["caller_count"],
            last_indexed_at=row["last_indexed_at"],
            max_time=max_time,
        )
        scored_results.append((row, score, factors))

    # Sort by score (descending), then by symbol name (deterministic tie-breaking)
    scored_results.sort(key=lambda x: (-x[1], x[0]["name"]))

    audit_trail = []
    final_results = []
    for rank, (row, score, factors) in enumerate(scored_results[:limit], start=1):
        final_results.append({**row, "composite_score": score})
        audit_trail.append(RankingAudit(
            name=row["name"],
            kind=row["kind"],
            file_path=row["file_path"],
            rank_position=rank,
            composite_score=score,
            factors=factors,
        ))

    return final_results, audit_trail


def context_impact_score(
    conn: sqlite3.Connection,
    symbol_name: str,
    impact_symbols: list[str],
) -> tuple[float, list[RankingFactor]]:
    """Score the impact/blast radius of a symbol change.

    Considers: number of transitive callers, clustering, module coupling.
    """
    factors: list[RankingFactor] = []
    total_score = 0.0

    # Factor 1: Direct impact count
    impact_count = len(impact_symbols)
    impact_normalized = math.log1p(impact_count)
    f1_contrib = impact_normalized * WEIGHT_IMPACT_COUNT
    factors.append(RankingFactor("impact_count", impact_normalized, WEIGHT_IMPACT_COUNT, f1_contrib))
    total_score += f1_contrib

    # Factor 2: Clustering
    cluster_score = _compute_module_spread(conn, impact_symbols)
    if cluster_score is not None:
        f2_contrib = cluster_score * WEIGHT_MODULE_SPREAD
        factors.append(RankingFactor("module_spread", cluster_score, WEIGHT_MODULE_SPREAD, f2_contrib))
        total_score += f2_contrib

    return total_score, factors


def _compute_module_spread(conn: sqlite3.Connection, impact_symbols: list[str]) -> float | None:
    """Compute how many unique modules are affected, or None if unavailable."""
    if not impact_symbols:
        return None
    try:
        all_metrics = metrics.symbol_metrics(conn)
        modules_affected = set()
        for sym in impact_symbols:
            for m in all_metrics:
                if m.name == sym:
                    modules_affected.add(m.module)
                    break
        return math.log1p(len(modules_affected))
    except Exception:
        return None
