# Security and operating boundaries

This is a research and alert program, NOT an execution bot. It has no Binance trading
keys and no exchange order, leverage-change, transfer or withdrawal calls. Never add
such keys to this repository just to make a data request work.

Use only the GitHub repository secrets `TELEGRAM_BOT2_TOKEN` and
`TELEGRAM_BOT2_CHAT_ID`. GitHub's built-in token writes small JSON state files on the
separate `btc-bot2-v12-state` branch. No personal access token or pickle is needed.
Keep the repository private: account equity, plan details and reports are not secrets
masked by the program and can appear in artifacts/state readable to repository users.

Do not post tokens in logs, screenshots, URLs or chat. Telegram and provider exceptions
are sanitized. An ambiguous send can leave an active lock: review Telegram and actual
orders before confirming flat. Exactly-once delivery is not guaranteed by the network.

Only whitelisted model/runtime/account JSON paths are written remotely. Provider
archive paths are validated; ZIP members are read in memory, not extracted by their
untrusted names. Size bounds and publisher checksums are enforced. No synthetic data
are a runtime fallback when real data fail.

GitHub state workflows share a concurrency group. State conflicts fail rather than
silently creating another entry. Changes to code/config invalidate model approval.
The included dependency/action versions were checked during this build, not promised
safe forever. Re-test updates before deployment. The license does not certify profit.

Self-hosted runners should be private, dedicated and restricted to trusted workflows.
Never run untrusted pull-request code on a machine with repository secrets or account
access. Follow GitHub and provider access policies. No access restriction bypass is
provided or recommended.

The bot cannot place a protective stop for you, verify a fill, know true equity, or
verify your Binance liquidation price. A risk-defined plan is not a loss guarantee.
Avoid other BTC positions/working orders that invalidate the single-position model.
