# Security and operational boundaries

Use a NEW private repository and a NEW Telegram bot for Bot 2. Set only TELEGRAM_BOT2_TOKEN and TELEGRAM_BOT2_CHAT_ID as repository Actions secrets. Never paste a token into config.yaml, Python code, a commit, an issue, browser URL or screenshot. If exposed, revoke it in BotFather and replace the secret; deleting a committed file does not erase history.

No exchange trading key, withdrawal permission or broker API is required or supported. All exchange requests are public market-data reads. The only writes are Telegram messages and three whitelisted JSON files in your own repository's btc-bot2-state branch. The built-in GITHUB_TOKEN needs contents: write for research/scan persistence. Setup, diagnostics and tests request contents: read. Checkout disables persisted git credentials. No personal access token is needed.

Dependencies are directly version-pinned, but transitive dependencies are not a fully hashed supply-chain lock. GitHub Actions use verified current major tags, not immutable commit SHAs. Review official releases and pin SHAs to your organization's policy for stronger supply-chain hardening. Dependence on external service behavior is not a security audit.

Messages and artifacts intentionally contain model/trading research, but not secrets. A private repository is not a vault from collaborators with read access. Do not publish your account position or identity in logs. Locally ignored state/, data/, output/, .env, venv and caches must not be committed.

The Telegram helper will not guess between multiple private chats or remove a webhook. If the Chat ID is already configured, it tests sending directly. Use a bot dedicated to this project. This is a push-notification bot, not an interactive service that responds continuously to Telegram commands.

403/451 exchange responses stop safely. No proxy, location spoofing, unauthorized data access or cross-venue substitution is supplied. Use only services and environments you are authorized to access. An archive passing checksums proves file integrity against the publisher's checksum, not that the publisher's historical data are economically correct.

The model uses JSON only; no downloaded pickle/model deserialization. Corrupt state is not silently reset. Workflow concurrency reduces duplicate updates; network failures can still produce uncertain delivery. Do not repeat an actual order based only on a repeated Telegram message.

No automatic orders, position reconciliation, liquidation protection or real-time stop management. Native stops in the backtest are hypothetical; actual account execution must be independently managed. If a research model is replaced while its alert-position is unresolved, code may halt monitoring rather than silently use incompatible parameters. Check the real position before any state reset.
