# Update guide - BTC Bot 2 v1.2

## A. Replace the BTC repository files

Use the existing **BTC Bot 2** repository and Telegram bot. Do not touch the separate
stock bot. Upload the extracted files rather than the ZIP. The root should contain
`main.py`, `config.yaml`, `btc_quant/`, `tests_v12/`, `scripts/` and `.github/`.

Replace all existing workflows with the supplied same-named files. Add the new
`bot2_account.yml`. Do not leave another hourly BTC workflow running in parallel.
The old `btc-bot2-state` branch may remain, but this version does not use its spot
approvals. New state is on `btc-bot2-v12-state`.

### When Actions shows no workflows

Create these paths with GitHub **Add file -> Create new file**:

```
.github/workflows/bot2_scan.yml
.github/workflows/bot2_research.yml
.github/workflows/bot2_check_data.yml
.github/workflows/bot2_setup.yml
.github/workflows/bot2_account.yml
.github/workflows/tests.yml
```

Copy each corresponding file from `WORKFLOW_COPIES/<filename>.txt` into the GitHub
editor and commit to the default branch (`main` in most repositories). The dot in
`.github` matters. Do not put the ZIP or another project folder above these paths.

`Install_Workflows.ps1` restores the correct workflow paths **locally** if your ZIP
extractor omitted the dot directory; it does not upload or commit anything remotely.

## B. Secrets and permissions

Settings -> Secrets and variables -> Actions:

```
TELEGRAM_BOT2_TOKEN
TELEGRAM_BOT2_CHAT_ID
```

Keep the existing values. Never put a token into source code, screenshots, browser
URLs, issues or logs. Do not supply a Binance trading key: none is needed or supported.

The research, scan and account workflows request `contents: write` for JSON state.
If repository/organization policy denies it, ask the administrator to allow those
workflows to persist the state branch. Do not add a personal access token just to
work around a clear policy restriction.

## C. Run in this order

**1. Bot2 - Offline Tests**

Runs software tests with network access blocked in the test fixtures. A pass is NOT
a real-market backtest.

**2. Bot2 - Telegram Setup** (only needed to verify connection)

When a Chat ID secret already exists, the script tests it instead of rediscovering
private chats. For a new bot, send `/start` to it first. If there are zero or multiple
private updates, discovery deliberately refuses to choose a recipient arbitrarily.

**3. Bot2 - Hourly Signals -> Run workflow -> mode: demo, dry_run: false**

Expect a message labeled `DEMO - SYNTHETIC, NOT LIVE` with Entry/SL/TP/quantity/leverage.
The demo does not change active-plan locks or claim a backtest result.

**4. Bot2 - Check Data -> section: both**

- `READY`: the sample archive and live test both worked in that run.
- `HISTORY_ONLY`: research can proceed, but live alerts cannot use that runner.
- `NOT_READY`: inspect `provider_check.json` or `failure.json`.

Sample availability does not verify all months of history. Each archive is checked
again during research. On HTTP 451 read `docs/BINANCE_DATA_ACCESS.md`.

**5. Bot2 - Research Backtest -> download: true**

This downloads official monthly Binance USD-M trade candles, BTC mark-price candles,
and BTC funding events. ETH/SOL candles provide context. Downloads and raw checksum
files are cached. No live API access is required for this archive-only stage.

Results are in Actions -> the run -> Summary / Artifacts. Read `BACKTEST_REPORT.md`.
`NO_VALIDATED_80_PERCENT_EDGE` is an honest negative result. Do not rewrite the report
or keep adjusting parameters on the same holdout until it turns green.

**6. Bot2 - Hourly Signals -> mode: status**

Shows the selected candidate, observed results, and blocks. It does not place a trade.
Use **Run workflow**, not **Re-run jobs**, to change mode or other inputs.

**7. Optional manual paper mode**

`mode: paper`, `dry_run: false` uses real Binance observations when accessible but
explicitly labels any plan UNVALIDATED. It cannot be enabled by the hourly schedule.
No setup, stale timing, high cost, excessive stop distance or bad data can still
legitimately result in no plan.

**8. Confirm account input, then strict mode**

Only after the statistical gate passes, use **Bot2 - Account Settings**:

```
equity_usdt: 500 (or your ACTUAL current equity allocated to this bot)
flat_confirmed: true ONLY after checking Binance has no BTC position or pending order
```

Default planned risk is 2%, capped at 50 USDT and subject to margin. At 500 USDT,
that is at most 10 USDT, not an instruction to risk 50 every time. Isolated leverage
is chosen within 1-3x and initial margin plus cost reserve stays within 60% of equity.

Strict needs current equity confirmation (within 24 hours), fresh Binance data,
matching exchange filters, matching code/config and an approved direction. It will
not automatically promote an unvalidated model.

## D. How to use a plan

A plan is conditional. Do not place it before `Activate ONLY at`. At activation,
check that the setup is still valid, the quote is between SL and TP, and the exchange
accepts the stated quantity and price steps. Cancel an unfilled order at expiry.
Set exchange-side SL/TP after a real fill; never wait for GitHub to protect a position.

The displayed liquidation price is deliberately `NOT VERIFIED`. The JSON margin
stress price is NOT the exchange liquidation price. Verify Binance Mark Price,
liquidation distance, isolated mode, fee tier and whether auto-add-margin is enabled.
The model assumes no added margin, no other BTC positions and no pyramiding.

A strict plan reserves an active lock before delivery. After your position is closed
or an order is cancelled/expired, confirm current equity and flat status again in
Account Settings. The bot does not infer your actual fill from a candle touch.

## E. Troubleshooting

| Status | What to do |
|---|---|
| Old version / KeyError | Replace config and ALL Python modules together; run new workflow from default branch. |
| Wrong venue/model schema | Old Coinbase state is not reusable. Run the Binance v1.2 research. |
| HTTP 451 | Use only a provider-authorized environment; archive research is independent. No bypass is supplied. |
| Missing bars | Small gaps remain NaN and reset models. Large gaps fail. Held-gap outcomes are retained and block approval. |
| Exchange rules changed | Inspect live `rules` in Check Data, update `research_rules`, and rerun research; these are not perpetual fixed constants. |
| Evidence stale | Keep the old ledger, move the end to a newly completed month, rerun and document that this is repeated testing. |
| No qualifying setup | Nothing passed now. Do not loosen criteria merely to force an alert. |
| Account confirmation expired | Update actual equity while flat; do not confirm flat while a position/order remains open. |
| Delivery unconfirmed | Check Telegram and exchange before clearing the reserved lock; do not blindly rerun. |

## F. Local commands

```
python -m pip install -r requirements-dev.txt
python -m pytest tests_v12 -q
python main.py scan --manual --mode demo --dry-run
python main.py check-data --section archive
python main.py research --download
python main.py scan --manual --mode status --dry-run
python main.py account --equity 500 --flat-confirmed
python main.py scan --manual --mode paper --dry-run
```

For Telegram outside GitHub, provide the two Telegram secrets as environment variables
without committing them. Local state stays in `state/`; GitHub uses its state branch.
The local guide does not assume that your physical location or account is permitted
to access Binance Futures. Check applicable access and account restrictions yourself.
