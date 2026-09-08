# Conway <img src="https://i.ibb.co/kgtjtTtB/F8-D5-D96-C-E5-C7-4-CF6-8-DA2-831-EE987-E704.webp" alt="Chucho" width="50" />

**Conway** is an autonomous trading agent that hunts for asymmetric, short-horizon
expected value (EV) across onchain memecoin markets and equity/options orderflow.
It fuses two signal families into a single ranked opportunity set:

1. **Social/orderflow ingestion** (`orderflow_engine.py`) — parses a live feed of
   tweets, wallet activity, and Telegram channel chatter to detect early FOMO
   formation, smart-money wallet clustering, and narrative velocity around
   specific memecoin tickers, plus unusual options/equity orderflow for stocks.
2. **Volume/Gamma EV analysis** (`market_analysis.py`) — scores every candidate
   market on realized volume, dealer gamma exposure (GEX), and momentum decay to
   produce a single comparable EV score, so the agent can rank a Solana memecoin
   against a mega-cap options chain on the same scale.

Conway's job is not to predict direction with certainty — it's to systematically
find where **flow + volatility + convexity** line up, size positions
proportionally to conviction, and get out before the crowd does.

---

## Repository layout

```
conway/
├── README.md              this file
├── orderflow_engine.py     Twitter/Telegram/wallet orderflow ingestion + signal scoring
└── market_analysis.py      Volume & gamma EV analysis / market ranking
```

## Architecture

```
                     ┌──────────────────────────┐
                     │      Data Sources          │
                     │  Twitter/X firehose         │
                     │  Telegram channel scrapes   │
                     │  Onchain wallet activity     │
                     │  Equity/options tape          │
                     └────────────┬────────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │   orderflow_engine.py         │
                    │  - trader/wallet clustering     │
                    │  - FOMO velocity scoring          │
                    │  - narrative decay half-life        │
                    │  - stock orderflow imbalance          │
                    └─────────────┬──────────────────────┘
                                  │  ranked signal candidates
                    ┌─────────────▼──────────────────────┐
                    │   market_analysis.py                   │
                    │  - 24h volume z-score                     │
                    │  - dealer gamma exposure (GEX)              │
                    │  - EV composite scoring & ranking             │
                    └─────────────┬──────────────────────────────┘
                                  │  ranked EV table
                    ┌─────────────▼──────────────────────────────┐
                    │   Conway execution layer (not included)        │
                    │  - position sizing, risk limits, order routing    │
                    └────────────────────────────────────────────────┘
```

## Quickstart

```bash 
python market_analysis.py       # prints ranked EV table across memecoins + equities
python orderflow_engine.py      # prints live-style orderflow signal feed + composite scores
```
Both scripts are self-contained (standard library only) and run with Python 3.9+.


## Conway Wallets
```#core 0xC9C1bC03B05D99FAd47aA11567Af1f12C58aA69B ```

## How EV is scored

Conway's composite EV score blends four normalized (0–1) components per market:

| Component        | Weight | What it captures                                                |
|-------------------|--------|-------------------------------------------------------------------|
| Volume z-score     | 0.30   | How abnormal current volume is vs. the trailing baseline           |
| Gamma pressure      | 0.30   | Dealer short-gamma exposure — proxy for forced hedging/convexity   |
| Orderflow imbalance  | 0.25   | Net buy/sell pressure from tracked wallets, socials, and tape       |
| Narrative velocity    | 0.15   | Rate of change of mention volume across Twitter/Telegram             |

```
EV_score = 0.30·volume_z + 0.30·gamma_pressure + 0.25·orderflow_imbalance + 0.15·narrative_velocity
```

Markets are ranked descending by `EV_score`. The agent treats scores above `0.70`
as high-conviction, `0.45–0.70` as watchlist, and below `0.45` as noise.

## Data note

All market data in this repository (volumes, gamma exposure, wallet counts,
mention velocity) is **dated snapshot-taken volumetrics** for demo and architecture purposes. It is
not sourced from any live exchange, options market maker, or social platform.

## Disclaimer

Conway is a research/engineering agent. Nothing here is financial advice, and the
included data is entirely algorythmic. Memecoin markets and options gamma trading
carry substantial risk of loss, including total loss of principal. Anyone adapting
this code to trade real capital is responsible for their own risk management,
compliance, and due diligence.
