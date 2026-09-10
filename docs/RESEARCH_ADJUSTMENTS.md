# Research-to-code review

Prepared 2026-09-10. This document separates source findings from implementation
choices. There is no imported 80% win rate and no claimed live-market replication.

## 1. User-uploaded thesis: gs631130444.pdf

Wattana Masanthia (2021), *An Analysis of Economic Factors and Bitcoin Price Affecting
Gold Bullion Price in Thailand*, Srinakharinwirot University. This is **not** the ACM
paper previously linked by the user.

### What the thesis actually studies

The dependent variable is Thai gold bullion price, not a BTCUSDT perpetual return.
The main analysis uses 60 monthly observations, January 2017-December 2021, and
multiple regression. Variables are GOLDSP, OIL, SET, EXC, INT, CPI, GDP, SHOCK and BTC.
The English abstract is on PDF page 6; the research scope is on PDF page 25.

The study discusses stationarity, multicollinearity, autocorrelation and
heteroskedasticity. Its reported Model 2, Table 17 on printed page 65 / PDF page 78,
contains first-differenced terms. The BTC coefficient is -0.000078 with p=0.3271.
GOLDSP and EXC are significant positive predictors in that model; SHOCK is negative
at the author's 10% significance level. R-squared is 0.984848.

Table 19 on printed page 69 / PDF page 82 compares two monthly samples and two daily
samples. The author does not find a statistically significant BTC term in those
specifications. The limitation/future-work discussion on printed page 73 / PDF page
86 warns that relationships from one period need not persist in another.

### What this does NOT establish

- It is not a backtest of hourly BTC entry/SL/TP or leverage.
- It does not establish that gold leads BTC or that BTC-gold is the best pair.
- A high regression R-squared is not a trade win rate.
- Failure to find a significant BTC coefficient in this conditional Thai-gold
  regression is not proof of independence of all BTC and gold markets at all horizons.
- Its monthly/daily parameter estimates are not transferred numerically to a 1h model.

### Implementation decision

Do not impose a gold signal. Retain a BTC-only baseline and require evidence that a
crypto companion improves the declared BTC-only trade expression. Relationship
models work with returns or separately tested log-price spreads rather than treating
raw trending prices as sufficient evidence. These are our adaptations, not a claim
that the thesis prescribes this trading engine. Gold is not downloaded or scored.

No full thesis is redistributed in the repository. The personal biography/address
page is not extracted into any artifact.

## 2. Lancaster (2025) - ResearchGate research proposal

Source: https://www.researchgate.net/publication/395400190_Performance_Analysis_of_a_BTC-USD_Trend-Following_Algorithm_A_Comprehensive_Quantitative_Study_2021-2025

Reported hourly BTC-USD study: Jan 2021-May 2025. Parameters include EMA27/125,
ADX90 >=14, ATR14 and percentage-risk sizing. Reported win rate is 30%, not 80%.
The listed profit factor equals 3.69/1.24, creating an audit question about whether
payoff ratio and aggregate profit factor were confused; position-size data are
needed before asserting an error. The full trade ledger was not reproduced here.

Implementation: retain the EMA/ADX/ATR idea as a **trend-pullback hypothesis**, use
causal confirmation, and simulate a fixed SL/TP bracket. Short-side symmetry,
pullback reclaim, limit entry, margins and companion filters are new assumptions,
not an exact replication of the proposal's trailing-stop system or results.

## 3. ACM article

Xiangyang Xu and Xinglei Xu, *Research on Quantitative Trading Model--Taking Bitcoin
and gold as examples*, DOI 10.1145/3603781.3603818.

URL: https://dl.acm.org/doi/fullHtml/10.1145/3603781.3603818

The full article was not available in the previous review. The newly uploaded thesis
is a different work and cannot fill that gap. No ACM strategy, coefficients or
performance numbers have been silently reconstructed.

## 4. Independent statistical and operational references

- NIST, binomial confidence intervals: https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm
- statsmodels cointegration API: https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html
- Binance official archives and SHA256 checksums: https://github.com/binance/binance-public-data
- Binance USD-M market data: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- Binance funding history: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
- Binance mark-price candles: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data
- Binance liquidation protocols: https://www.binance.com/en-AU/support/faq/detail/360033525271
- GitHub schedule limitations: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- GitHub authorized self-hosted runner routing: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow

These references define interfaces and methodological cautions. They do not certify
the profitability of this implementation. The 4-week block bootstrap, evidence
thresholds, risk caps and limited candidate set are explicitly chosen research policies.
