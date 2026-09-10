# Binance access, GitHub runners, and HTTP 451

## This version does not make a restricted API available

The user's previous GitHub runner returned HTTP 451 from the Binance Futures live
API. Changing Python or adding a retry cannot guarantee that access becomes permitted.
This release does not provide a VPN, proxy, alternate domain or disguised venue.

It separates two tasks:

| Task | Provider | Requires live Futures API? |
|---|---|---|
| Historical research | Official data.binance.vision USD-M archives | No |
| Current conditional plan | Official fapi.binance.com public endpoints | Yes |

`Bot2 - Check Data` tests both independently. `HISTORY_ONLY` means archive research
may run; it does NOT mean live alerts are ready. It exits successfully to allow the
archive workflow, with `can_scan_live: false` explicitly recorded. In section `live`
mode alone a failed test exits nonzero. A sample test says nothing about every archive.

When live access is unavailable, the bot sends at most a daily data-status notice
(or a manually requested status) and withholds trade plans. It never inserts Coinbase
spot prices into a Binance perpetual strategy.

## Optional authorized self-hosted runner

Use this only on a computer/server and account legitimately permitted to access the
Binance Futures public API and to use the service. This guide makes no determination
about eligibility or jurisdiction. Do not use it to evade a denial.

GitHub lets a private repository route jobs to a self-hosted runner you administer:
https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow

1. In the private repository open Settings -> Actions -> Runners -> New self-hosted
   runner. Follow GitHub's platform-specific registration instructions on that page.
   Do not put its registration token in a code file or share it in chat.
2. Give it a custom label `btc-data` and keep its service online when scans should run.
   The machine must support Python 3.13, Bash, internet access and the pinned packages.
   This repository does not install or register a runner remotely for you.
3. Settings -> Secrets and variables -> Actions -> **Variables** -> New repository
   variable. Name: `BOT2_LIVE_RUNNER`. Value:

```
["self-hosted", "btc-data"]
```

4. Run Check Data -> section `live`. Run a manual PAPER scan only after research,
   then use STRICT only when the statistical and account gates allow it.

Without this variable the scan/check workflows use `ubuntu-latest`. Historical
research continues on the hosted runner by default. There is no automatic failover
between places, providers or symbols. A self-hosted machine being offline simply
queues/fails the job; it is not a real-time execution service.

The same project also runs locally (`START_HERE.md` lists the commands). Local
research/state and GitHub state are separate; they are not silently synchronized.

## Other failures

- HTTP 429: bounded retry honoring Retry-After; no aggressive scraping loop.
- HTTP 403/451: explicit access denial; no host substitution.
- HTTP 404 for a monthly archive: not published or unsupported series; do not fill it
  with another market. Use an actually available completed date range and retest.
- SHA256 failure: downloaded blob is discarded and research stops; do not skip hashes.
- Missing funding or mark-price path: net perpetual/position evidence is not approved.
- Quote/filter changes: review actual Binance output and update assumptions transparently.

Data references:
https://github.com/binance/binance-public-data
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information

A new provider, different contract or material execution change requires a new,
matching backtest. It cannot inherit an old model's approval.
