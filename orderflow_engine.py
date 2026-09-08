"""
orderflow_engine.py
--------------------
Conway's orderflow ingestion layer.

Simulates parsing three live feeds:
  1. Twitter/X — tracked trader accounts + FOMO-prone wallet-linked accounts
  2. Telegram — memecoin call channels and alpha groups
  3. Equity/options tape — orderflow imbalance for tracked stock tickers

Each source is normalized into a Signal, clustered by ticker, and scored into
a composite OrderflowScore that feeds market_analysis.py's EV ranking.

All input data below is synthetic (fixed-seed) placeholder data standing in for
a real streaming ingestion pipeline (e.g. Twitter API v2 filtered stream,
Telegram MTProto client, and a broker/tape data feed).
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Dict

random.seed(1729)


# ---------------------------------------------------------------------------
# Source taxonomy
# ---------------------------------------------------------------------------

class SourceType(Enum):
    TWITTER_TRACKED_TRADER = "twitter_tracked_trader"
    TWITTER_FOMO_WALLET = "twitter_fomo_wallet"
    TELEGRAM_CALL_CHANNEL = "telegram_call_channel"
    EQUITY_ORDERFLOW = "equity_orderflow"


@dataclass
class TrackedAccount:
    handle: str
    source_type: SourceType
    followers: int
    historical_hit_rate: float  # 0-1, backtested win rate of this account's prior calls
    weight: float = field(init=False)

    def __post_init__(self) -> None:
        # Weight rewards accuracy far more than reach; a small accurate account
        # outweighs a large noisy one.
        reach_component = min(self.followers / 250_000, 1.0)
        self.weight = round(0.75 * self.historical_hit_rate + 0.25 * reach_component, 4)


@dataclass
class Signal:
    ticker: str
    source: TrackedAccount
    timestamp: datetime
    sentiment: float          # -1 (bearish) to +1 (bullish)
    mention_count: int        # mentions in this polling interval
    is_new_mention: bool      # first time this account has mentioned this ticker in 24h


@dataclass
class OrderflowScore:
    ticker: str
    orderflow_imbalance: float   # 0-1, net buy pressure across tracked sources
    narrative_velocity: float    # 0-1, rate of change of mention volume
    distinct_sources: int
    top_contributors: List[str]


# ---------------------------------------------------------------------------
# Synthetic tracked universe
# ---------------------------------------------------------------------------

TRACKED_ACCOUNTS: List[TrackedAccount] = [
    TrackedAccount("@basedcaller",     SourceType.TWITTER_TRACKED_TRADER, 184_000, 0.61),
    TrackedAccount("@onchain_owl",     SourceType.TWITTER_TRACKED_TRADER, 92_500,  0.68),
    TrackedAccount("@wagmi_wendell",   SourceType.TWITTER_FOMO_WALLET,    31_200,  0.34),
    TrackedAccount("@solsniper_dex",   SourceType.TWITTER_TRACKED_TRADER, 61_800,  0.57),
    TrackedAccount("@degen_dana",      SourceType.TWITTER_FOMO_WALLET,    18_900,  0.29),
    TrackedAccount("@pumpwatch_ai",    SourceType.TWITTER_TRACKED_TRADER, 47_300,  0.55),
    TrackedAccount("tg://alpha_calls_vip",   SourceType.TELEGRAM_CALL_CHANNEL, 24_500, 0.41),
    TrackedAccount("tg://gemhunters_sol",    SourceType.TELEGRAM_CALL_CHANNEL, 41_100, 0.38),
    TrackedAccount("tg://insider_flow",      SourceType.TELEGRAM_CALL_CHANNEL, 12_700, 0.52),
    TrackedAccount("flow://opra_tape_scanner", SourceType.EQUITY_ORDERFLOW, 0, 0.63),
]

MEMECOIN_TICKERS = ["$WOJAK", "$FROGE", "$PONKE", "$BONKZ", "$MOOLA", "$RUGDOG"]
STOCK_TICKERS = ["NVDA", "TSLA", "SMCI", "COIN"]


def _generate_signals(now: datetime) -> List[Signal]:
    """Synthesize a burst of raw signals across all sources for this polling cycle."""
    signals: List[Signal] = []

    for account in TRACKED_ACCOUNTS:
        universe = STOCK_TICKERS if account.source_type == SourceType.EQUITY_ORDERFLOW else MEMECOIN_TICKERS
        n_mentions_this_cycle = random.randint(0, 4)
        for _ in range(n_mentions_this_cycle):
            ticker = random.choice(universe)
            signals.append(
                Signal(
                    ticker=ticker,
                    source=account,
                    timestamp=now - timedelta(minutes=random.randint(0, 45)),
                    sentiment=round(random.uniform(-0.3, 1.0), 2),
                    mention_count=random.randint(1, 9),
                    is_new_mention=random.random() < 0.4,
                )
            )
    return signals


def cluster_by_ticker(signals: List[Signal]) -> Dict[str, List[Signal]]:
    clusters: Dict[str, List[Signal]] = {}
    for s in signals:
        clusters.setdefault(s.ticker, []).append(s)
    return clusters


def score_orderflow(clusters: Dict[str, List[Signal]]) -> List[OrderflowScore]:
    """Turn raw clustered signals into a per-ticker OrderflowScore."""
    scores: List[OrderflowScore] = []

    for ticker, sigs in clusters.items():
        weighted_sentiment = sum(s.sentiment * s.source.weight for s in sigs)
        total_weight = sum(s.source.weight for s in sigs) or 1e-9
        imbalance_raw = weighted_sentiment / total_weight  # roughly -1..1

        # Map to 0-1, then boost with new-mention ratio (fresh flow > stale re-shares)
        new_mention_ratio = sum(1 for s in sigs if s.is_new_mention) / len(sigs)
        orderflow_imbalance = max(0.0, min(1.0, (imbalance_raw + 1) / 2 * (0.7 + 0.3 * new_mention_ratio)))

        total_mentions = sum(s.mention_count for s in sigs)
        distinct_sources = len({s.source.handle for s in sigs})
        # Velocity: mentions per distinct source, log-compressed and normalized against
        # a reference ceiling of 12 mentions/source observed historically at viral peak.
        raw_velocity = total_mentions / max(distinct_sources, 1)
        narrative_velocity = max(0.0, min(1.0, raw_velocity / 12))

        top_contributors = sorted(
            {s.source.handle for s in sigs},
            key=lambda h: next(s.source.weight for s in sigs if s.source.handle == h),
            reverse=True,
        )[:3]

        scores.append(
            OrderflowScore(
                ticker=ticker,
                orderflow_imbalance=round(orderflow_imbalance, 4),
                narrative_velocity=round(narrative_velocity, 4),
                distinct_sources=distinct_sources,
                top_contributors=top_contributors,
            )
        )

    return sorted(scores, key=lambda o: o.orderflow_imbalance, reverse=True)


def run_polling_cycle() -> List[OrderflowScore]:
    now = datetime.now(timezone.utc)
    signals = _generate_signals(now)
    clusters = cluster_by_ticker(signals)
    return score_orderflow(clusters)


def _print_report(scores: List[OrderflowScore]) -> None:
    print("=" * 78)
    print("CONWAY — ORDERFLOW SIGNAL FEED".center(78))
    print(f"cycle time (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}".center(78))
    print("=" * 78)
    header = f"{'TICKER':<8}{'IMBALANCE':>12}{'VELOCITY':>12}{'SOURCES':>10}   TOP CONTRIBUTORS"
    print(header)
    print("-" * 78)
    for s in scores:
        contributors = ", ".join(s.top_contributors)
        print(f"{s.ticker:<8}{s.orderflow_imbalance:>12.3f}{s.narrative_velocity:>12.3f}{s.distinct_sources:>10}   {contributors}")
    print("-" * 78)
    if scores:
        avg_imbalance = statistics.mean(s.orderflow_imbalance for s in scores)
        print(f"mean imbalance this cycle: {avg_imbalance:.3f}   tickers seen: {len(scores)}")
    print("=" * 78)


if __name__ == "__main__":
    report = run_polling_cycle()
    _print_report(report)
