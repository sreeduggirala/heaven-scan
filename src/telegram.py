# telegram.py
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError

load_dotenv()

TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
TG_CHANNEL = os.getenv("TG_CHANNEL")  # e.g. -1001234567890 (recommended)
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")  # MUST be set for bot-only mode

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN is required. Refusing to use user auth.")

_client: TelegramClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> TelegramClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = TelegramClient(
                    "heaven_watcher_session", TG_API_ID, TG_API_HASH
                )
                # Bot-only start (no phone prompt ever)
                await _client.start(bot_token=TG_BOT_TOKEN)
    return _client


async def send_markdown(msg: str) -> None:
    client = await get_client()
    try:
        await client.send_message(
            entity=TG_CHANNEL,
            message=msg,
            link_preview=False,
            parse_mode="md",
        )
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
        await client.send_message(
            entity=TG_CHANNEL, message=msg, link_preview=False, parse_mode="md"
        )
    except ChannelPrivateError:
        raise RuntimeError(
            "Bot cannot post to TG_CHANNEL. Make sure the bot is a member/admin of the channel "
            "and that TG_CHANNEL is the numeric -100… ID or a handle the bot can see."
        )
