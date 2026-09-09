# Research review and design decisions

Reviewed 2026-09-09. Scope: original studies, author/university records, publisher abstracts and accessible article text, plus official statistical/API documentation. This is an annotated review, not an independent replication or an exhaustive meta-analysis. Publication results belong to their authors and must not be reported as this bot's backtest.

## 1. BTC-ETH leadership: an empirical question, not a permanent rule

Sifat, Mohamad and Mohamed Shariff (2019), *Lead-lag relationship between Bitcoin and Ethereum: Evidence from hourly and daily data*, Research in International Business and Finance 50, 306-321. DOI 10.1016/j.ribaf.2019.06.012.

The authors used several time-series/dependence tests on hourly and daily observations from 2017-2018. Results were mixed and largely bidirectional; identifying price discovery did not translate into an easy intraday advantage. **Design implication:** ETH is a candidate, not a declared leader. Forecasts must improve a BTC-only baseline and survive costs and later observations.

Primary university record: https://research.monash.edu/en/publications/lead-lag-relationship-between-bitcoin-and-ethereum-evidence-from-
Author institution record: https://irep.iium.edu.my/73405/

## 2. Cryptocurrency pairs can underperform ordinary benchmarks

Fil and Kristoufek (2020), *Pairs Trading in Cryptocurrency Markets*, IEEE Access 8, 172644-172651. DOI 10.1109/ACCESS.2020.3024619.

This study compares distance/cointegration approaches across 26 cryptocurrencies at daily, hourly and five-minute frequencies. Its broad finding is benchmark underperformance with substantial sensitivity to costs, execution windows and parameters, despite some favorable higher-frequency cases. **Design implication:** do not infer that a strong price correlation or stationary spread is profitable. Compare alternatives after friction and retain simple benchmarks. Do not transplant a five-minute result into this delayed hourly bot.

Publisher: https://ieeexplore.ieee.org/document/9200323/

## 3. Positive evidence for richer dependence models

Tadi and Witzany (2025), *Copula-based trading of cointegrated cryptocurrency Pairs*, Financial Innovation 11, article 40. DOI 10.1186/s40854-024-00702-7. An earlier preprint appeared in 2023.

The study combines cointegration selection with copula-based dependence signals. The published article distinguishes its more favorable level-based copula approach from other tested methods suffering substantial transaction costs. **Design implication:** pair selection and signal construction are separate problems. Our simple residual-z implementation is a baseline for comparison, not a replication of the authors' copula model or its reported performance.

Publisher, full text: https://link.springer.com/article/10.1186/s40854-024-00702-7
Earlier version: https://arxiv.org/abs/2305.06961

## 4. Contrary evidence even with hourly copulas

Pindza and Mba (2026), *Adaptive copula-based pairs trading with market overlay: An enhanced framework for cryptocurrency markets*, Quantitative Finance and Economics 10(2), 378-404. DOI 10.3934/QFE.2026016.

On hourly USDT perpetual observations, the authors report that market-neutral copula strategies had negative net returns after their modeled trading costs, while an overlay relaxing neutrality tracked buy-and-hold more closely. **Design implication:** profitability may come from directional market exposure rather than a pair-specific advantage. Record both legs, funding and a passive benchmark; do not call every two-asset strategy arbitrage.

Publisher: https://www.aimspress.com/article/doi/10.3934/QFE.2026016

## 5. Hourly Bitcoin forecasting: decisions matter as much as prediction

Bysik and Slepaczuk (2026), *Machine Learning-Based Bitcoin Trading Under Transaction Costs: Evidence From Walk-Forward Forecasting*, arXiv:2606.00060v1. Working paper, not treated as settled consensus.

The paper uses hourly BTC data and sequential out-of-sample folds. Naive direction-only model strategies fail after modeled costs; filters requiring a sufficiently large forecast reduce trading and improve selected configurations. The authors do not establish statistically robust benchmark dominance and note uneven regime performance. **Design implication:** a forecast's sign is insufficient. Our ridge model requires a magnitude exceeding a cost/uncertainty hurdle and improvement over BTC-only features. This code does not implement or claim to replicate their XGBoost/LSTM/iTransformer experiments.

Author paper, full HTML: https://arxiv.org/html/2606.00060v1

## 6. Original pairs-trading baseline is not crypto proof

Gatev, Goetzmann and Rouwenhorst, NBER Working Paper 7032 (1999), subsequently published in Review of Financial Studies (2006), *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*.

Historical normalized-price matching in equities supplies an important baseline concept. Its market, frequency, period and execution differ from perpetual cryptocurrency trading. **Design implication:** separate formation from subsequent trading, account for microstructure and compare to simple alternatives, rather than assuming a published equity premium transfers to BTC on 1h.

Primary working paper record: https://www.nber.org/papers/w7032

## 7. Crypto momentum is not a blanket hourly buy rule

Liu and Tsyvinski, *Risks and Returns of Cryptocurrency*, NBER Working Paper 24877 (2018), later journal version.

The study reports cryptocurrency-specific momentum and attention effects. It does not validate this project's exact hourly divergence, volume or stop rules. **Design implication:** include a momentum/breakout alternative to mean reversion, but test its actual horizon and costs rather than treating a broad factor result as an intraday edge.

Primary record: https://www.nber.org/papers/w24877

## 8. Trying more backtests can manufacture an apparent winner

Bailey, Borwein, Lopez de Prado and Zhu, *The Probability of Backtest Overfitting*.

The paper develops the problem of choosing strategies after many historical trials. It motivates recording the number of experiments and protecting evaluation data. **Design implication:** fixed 20-candidate baseline, one validation selection, no holdout-driven replacement, code/config fingerprints, preservation of failed studies. Our code does NOT implement the paper's PBO estimator, and a held-out test alone does not erase all selection bias.

Author-hosted paper: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf

## 9. Wilson intervals and dependence caveats

NIST Dataplot documentation discusses Wilson/Agresti-Coull proportion intervals and one-sided bounds. An observed rate is not a lower confidence limit. Serially dependent and changing financial outcomes additionally violate simple independent-trial assumptions. **Design implication:** combine Wilson with a four-calendar-week circular block bootstrap, minimum sample/time coverage and economic checks. This combination is an engineering admission rule, not a calibrated next-trade probability or a theorem covering arbitrary future regimes.

NIST: https://www.itl.nist.gov/div898/software/dataplot/refman2/auxillar/agrecoul.htm

## 10. Cointegration implementation assumptions

Statsmodels documents that `coint` tests the null of no cointegration, assumes I(1) inputs and has lag-selection behavior that must be specified. **Design implication:** explicitly fix constant/lag parameters, use past formation windows, reject missing observations and record p-values as diagnostics. A small p-value is not a percentage chance of a winning trade.

Official reference: https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html

## Operational primary sources

Binance official archive specification and checksum policy:
https://github.com/binance/binance-public-data

Binance USD-M market-data API:
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History

Telegram bot creation and Bot API:
https://core.telegram.org/bots/features
https://core.telegram.org/bots/api

GitHub Actions scheduling, default-branch behavior and delays:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub Actions secrets:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

Official action repositories (major versions checked at build time):
https://github.com/actions/checkout
https://github.com/actions/setup-python
https://github.com/actions/cache
https://github.com/actions/upload-artifact

## Findings that are NOT established by this review

No reviewed source establishes that this bot, a named BTC companion, or the exact 1h entries/exits in this repository wins >90% in future trading. No paper's equity curve has been reused as our own. Full real-data replication remains the job of the included workflow, followed by independent forward observation. Headlines, analyst opinions and social-media enthusiasm are not labels of empirical trading success.
