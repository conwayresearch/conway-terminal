"""
market_analysis.py
-------------------
Conway's volume/gamma EV analysis layer.

Scores a mixed universe of onchain memecoin markets and equities/options on a
single comparable EV scale by combining:

  - 24h volume z-score          (abnormal activity vs. trailing baseline)
  - gamma pressure               (dealer short-gamma proxy / convexity)
  - orderflow imbalance          (pulled from orderflow_engine.py)
  - narrative velocity           (pulled from orderflow_engine.py)

All volume, open interest, and gamma figures below are singular snapshots for demo purposes.
No live exchange, DEX, or options market-maker feed is queried.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import List, Dict, Optional

from orderflow_engine import run_polling_cycle, OrderflowScore

random.seed(2027)

WEIGHTS = {
    "volume_z": 0.30,
    "gamma_pressure": 0.30,
    "orderflow_imbalance": 0.25,
    "narrative_velocity": 0.15,
}


@dataclass
class MarketData:
    ticker: str
    asset_class: str          # "memecoin" or "equity_options"
    volume_24h: float         # USD notional
    volume_baseline_30d_avg: float
    volume_baseline_30d_std: float
    open_interest: float      # USD notional (0 for pure spot memecoins)
    dealer_gamma_notional: float  # signed; negative = dealers short gamma (fuel for squeezes)
    liquidity_depth: float    # USD, top-of-book depth proxy


@dataclass
class EVResult:
    ticker: str
    asset_class: str
    volume_z: float
    gamma_pressure: float
    orderflow_imbalance: float
    narrative_velocity: float
    ev_score: float
    tier: str


# ---------------------------------------------------------------------------
# Synthetic market universe
# ---------------------------------------------------------------------------

def _generate_memecoin_markets() -> List[MarketData]:
    tickers = ["$WOJAK", "$FROGE", "$PONKE", "$BONKZ", "$MOOLA", "$RUGDOG"]
    markets = []
    for t in tickers:
        baseline = random.uniform(180_000, 2_400_000)
        std = baseline * random.uniform(0.15, 0.45)
        # occasional volume spike to create separation in the ranking
        spike_multiplier = random.choice([1.0, 1.0, 1.2, 1.8, 3.4])
        volume_24h = max(20_000, random.gauss(baseline, std) * spike_multiplier)
        # memecoins have no options gamma; use a synthetic "LP/derivatives pressure"
        # proxy instead, representing perp funding + concentrated LP range risk
        synthetic_gamma = -abs(random.gauss(0, baseline * 0.18)) * spike_multiplier
        markets.append(
            MarketData(
                ticker=t,
                asset_class="memecoin",
                volume_24h=round(volume_24h, 2),
                volume_baseline_30d_avg=round(baseline, 2),
                volume_baseline_30d_std=round(std, 2),
                open_interest=round(baseline * random.uniform(0.05, 0.25), 2),
                dealer_gamma_notional=round(synthetic_gamma, 2),
                liquidity_depth=round(baseline * random.uniform(0.02, 0.08), 2),
            )
        )
    return markets


def _generate_equity_markets() -> List[MarketData]:
    tickers = ["NVDA", "TSLA", "SMCI", "COIN"]
    markets = []
    for t in tickers:
        baseline = random.uniform(4_500_000_000, 22_000_000_000)
        std = baseline * random.uniform(0.10, 0.30)
        spike_multiplier = random.choice([1.0, 1.0, 1.15, 1.5, 2.1])
        volume_24h = max(500_000_000, random.gauss(baseline, std) * spike_multiplier)
        oi = baseline * random.uniform(0.3, 0.9)
        # dealer gamma: negative = short gamma (dealers buy rallies/sell dips -> amplifies moves)
        dealer_gamma = random.gauss(0, oi * 0.22) * spike_multiplier
        markets.append(
            MarketData(
                ticker=t,
                asset_class="equity_options",
                volume_24h=round(volume_24h, 2),
                volume_baseline_30d_avg=round(baseline, 2),
                volume_baseline_30d_std=round(std, 2),
                open_interest=round(oi, 2),
                dealer_gamma_notional=round(dealer_gamma, 2),
                liquidity_depth=round(baseline * random.uniform(0.01, 0.03), 2),
            )
        )
    return markets


def build_universe() -> List[MarketData]:
    return _generate_memecoin_markets() + _generate_equity_markets()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _volume_zscore(market: MarketData) -> float:
    std = market.volume_baseline_30d_std or 1e-9
    z = (market.volume_24h - market.volume_baseline_30d_avg) / std
    return z


def _normalize_z(z: float, cap: float = 3.5) -> float:
    """Squash a z-score into 0-1 using a hard cap at +/- `cap` std devs."""
    clipped = max(-cap, min(cap, z))
    return (clipped + cap) / (2 * cap)


def _gamma_pressure(market: MarketData) -> float:
    """
    Negative dealer gamma relative to open interest/baseline volume implies
    dealers must chase price (buy rallies, sell selloffs), amplifying moves.
    We normalize the magnitude of *negative* gamma into a 0-1 pressure score;
    positive (long) dealer gamma dampens moves and scores near 0.
    """
    denom = market.open_interest if market.open_interest > 0 else market.volume_baseline_30d_avg
    denom = denom or 1e-9
    ratio = market.dealer_gamma_notional / denom  # negative = short gamma
    if ratio >= 0:
        return max(0.0, 0.15 - ratio)  # long gamma still gets a small floor score
    pressure = min(1.0, abs(ratio) / 0.6)
    return pressure


def score_market(
    market: MarketData,
    orderflow_lookup: Dict[str, OrderflowScore],
) -> EVResult:
    z = _volume_zscore(market)
    volume_z_norm = _normalize_z(z)
    gamma_pressure = _gamma_pressure(market)

    flow = orderflow_lookup.get(market.ticker)
    orderflow_imbalance = flow.orderflow_imbalance if flow else 0.35  # neutral prior if unseen this cycle
    narrative_velocity = flow.narrative_velocity if flow else 0.10

    ev_score = (
        WEIGHTS["volume_z"] * volume_z_norm
        + WEIGHTS["gamma_pressure"] * gamma_pressure
        + WEIGHTS["orderflow_imbalance"] * orderflow_imbalance
        + WEIGHTS["narrative_velocity"] * narrative_velocity
    )

    if ev_score >= 0.70:
        tier = "HIGH CONVICTION"
    elif ev_score >= 0.45:
        tier = "WATCHLIST"
    else:
        tier = "NOISE"

    return EVResult(
        ticker=market.ticker,
        asset_class=market.asset_class,
        volume_z=round(z, 2),
        gamma_pressure=round(gamma_pressure, 3),
        orderflow_imbalance=round(orderflow_imbalance, 3),
        narrative_velocity=round(narrative_velocity, 3),
        ev_score=round(ev_score, 4),
        tier=tier,
    )


def rank_universe() -> List[EVResult]:
    markets = build_universe()
    orderflow_scores = run_polling_cycle()
    orderflow_lookup = {o.ticker: o for o in orderflow_scores}

    results = [score_market(m, orderflow_lookup) for m in markets]
    return sorted(results, key=lambda r: r.ev_score, reverse=True)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(results: List[EVResult]) -> None:
    print("=" * 92)
    print("CONWAY — VOLUME / GAMMA EV RANKING".center(92))
    print("=" * 92)
    header = (
        f"{'RANK':<5}{'TICKER':<9}{'CLASS':<15}{'VOL_Z':>8}{'GAMMA':>9}"
        f"{'FLOW':>8}{'VELOC':>8}{'EV':>9}   TIER"
    )
    print(header)
    print("-" * 92)
    for i, r in enumerate(results, start=1):
        print(
            f"{i:<5}{r.ticker:<9}{r.asset_class:<15}{r.volume_z:>8.2f}{r.gamma_pressure:>9.3f}"
            f"{r.orderflow_imbalance:>8.3f}{r.narrative_velocity:>8.3f}{r.ev_score:>9.3f}   {r.tier}"
        )
    print("-" * 92)

    high_conviction = [r for r in results if r.tier == "HIGH CONVICTION"]
    watchlist = [r for r in results if r.tier == "WATCHLIST"]
    print(
        f"high conviction: {len(high_conviction)}   "
        f"watchlist: {len(watchlist)}   "
        f"mean EV: {statistics.mean(r.ev_score for r in results):.3f}"
    )
    if high_conviction:
        top = high_conviction[0]
        print(f"top pick this cycle: {top.ticker} ({top.asset_class}) — EV {top.ev_score:.3f}")
    print("=" * 92)


if __name__ == "__main__":
    ranked = rank_universe()
    _print_report(ranked)
