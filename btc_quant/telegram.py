from __future__ import annotations
import os
import time
import requests

class TelegramError(RuntimeError):
    pass


def _call(method: str, payload: dict):
    token = os.environ.get("TELEGRAM_BOT2_TOKEN", "").strip()
    if not token: raise TelegramError("Missing TELEGRAM_BOT2_TOKEN in repository Actions secrets")
    # Never print URLs or request exceptions: Telegram URLs contain the token.
    for attempt in range(3):
        try:
            response = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=25)
        except requests.RequestException:
            raise TelegramError("TELEGRAM_NETWORK_ERROR; delivery is unconfirmed, not automatically retried") from None
        try: body = response.json()
        except ValueError: raise TelegramError(f"TELEGRAM_INVALID_RESPONSE HTTP {response.status_code}") from None
        if response.status_code == 429 and attempt < 2:
            time.sleep(min(int(body.get("parameters", {}).get("retry_after", 5)), 45)); continue
        if not response.ok or not body.get("ok"):
            raise TelegramError(f"TELEGRAM_HTTP_{response.status_code}; check token, Chat ID and /start with the NEW bot")
        return body["result"]
    raise TelegramError("TELEGRAM_RATE_LIMIT")


def send(text: str, chat_id: str | None = None) -> None:
    chat_id = chat_id or os.environ.get("TELEGRAM_BOT2_CHAT_ID", "").strip()
    if not chat_id: raise TelegramError("Missing TELEGRAM_BOT2_CHAT_ID; create it after starting Bot 2")
    # Plain text: no Markdown injection, no user-generated links, under Telegram length cap.
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > 3500:
            if current: chunks.append(current); current = ""
            chunks.append(line[:3500]); line = line[3500:]
        if len(current)+len(line) > 3500: chunks.append(current); current = ""
        current += line
    if current: chunks.append(current)
    for chunk in chunks:
        _call("sendMessage", {"chat_id": chat_id, "text": chunk, "link_preview_options": {"is_disabled": True}})


def setup_bot() -> None:
    _call("getMe", {})
    chat_id = os.environ.get("TELEGRAM_BOT2_CHAT_ID", "").strip()
    if chat_id:
        send("BTC QUANT BOT 2 - CONNECTION OK\nThis is the second bot. No order is placed.\nNext: run Bot2 - Check Data, then Bot2 - Research Backtest.", chat_id)
        print("Bot 2 token and configured Chat ID verified; no rediscovery required.")
        return
    updates = _call("getUpdates", {"limit": 100, "timeout": 0, "allowed_updates": ["message"]})
    chats = {str(u.get("message", {}).get("chat", {}).get("id")) for u in updates
             if u.get("message", {}).get("chat", {}).get("type") == "private"}
    if len(chats) != 1:
        raise TelegramError("CHAT_ID_NOT_CONFIGURED: send /start to the NEW dedicated bot and run setup again, or reuse your own private Chat ID from Bot 1 in TELEGRAM_BOT2_CHAT_ID. No chat ID is printed to public logs.")
    chat_id = next(iter(chats))
    send(f"BTC QUANT BOT 2\nYour private Chat ID is: {chat_id}\nSave it as GitHub Actions secret TELEGRAM_BOT2_CHAT_ID.\nDo not put the bot token in any file or screenshot.", chat_id)
    print("Private Chat ID sent to your Telegram. Set the secret, then rerun this workflow to verify.")
