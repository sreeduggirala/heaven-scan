import os
import asyncio
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
import aiohttp
from telethon.errors import ChannelPrivateError

from dexscreener import (
    fetch_pairs_for_mint,
    pick_heaven_pair,
    format_pair_markdown,
)
from telegram import send_markdown, get_client

# ── Runtime state ──────────────────────────────────────────────────────
_session: Optional[aiohttp.ClientSession] = None
_seen: set[str] = set()
_seen_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown hooks."""
    global _session
    _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    await get_client()  # warm Telethon
    try:
        yield
    finally:
        if _session and not _session.closed:
            await _session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def _extract_mints_from_helius(payload: Dict[str, Any]) -> List[str]:
    """
    Adjust to match your actual Helius webhook payload.
    Should return a list of base token mint strings.
    """
    mints: List[str] = []
    notifications = payload if isinstance(payload, list) else [payload]
    for note in notifications:
        base_mint = note.get("base_mint")
        if base_mint:
            mints.append(base_mint)
    return [m for m in mints if m]


async def _process_mint(mint: str):
    global _session
    if _session is None:
        return

    # Idempotency (basic; use Redis for multi-process deployments)
    async with _seen_lock:
        if mint in _seen:
            return
        _seen.add(mint)

    pairs = await fetch_pairs_for_mint(_session, "solana", mint)
    if not pairs:
        return

    dp = pick_heaven_pair(pairs)
    if not dp:
        return

    msg = "🆕 Heaven Launch\n\n" + format_pair_markdown(dp)
    try:
        await send_markdown(msg)
    except ChannelPrivateError:
        print(
            "ChannelPrivateError: bot cannot post to TG_CHANNEL. Check permissions/ID."
        )


@app.post("/webhooks/helius")
async def helius_webhook(req: Request):
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    mints = _extract_mints_from_helius(payload)
    if not mints:
        return {"ok": True, "processed": 0}

    for mint in mints:
        asyncio.create_task(_process_mint(mint))

    return {"ok": True, "processed": len(mints)}
