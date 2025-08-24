import os, base64, struct, asyncio
from typing import Any, Dict, List, Tuple, Optional
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request, HTTPException
from telethon.errors import ChannelPrivateError

from dexscreener import fetch_pairs_for_mint, pick_heaven_pair, format_pair_markdown
from telegram import send_markdown, get_client

# Heaven: CreateStandardLiquidityPoolEvent (8-byte Anchor discriminator)
CSLPE_DISC = bytes([189, 56, 131, 144, 75, 63, 249, 148])

# ───────────────── runtime state ─────────────────
_session: Optional[aiohttp.ClientSession] = None
_seen: set[str] = set()
_seen_lock = asyncio.Lock()

@asynccontextmanager
async def lifespan(app: FastAPI):
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

# ───────────────── helpers ─────────────────
def _iter_log_batches(payload: Dict[str, Any]) -> List[List[str]]:
    """
    Return a list of log arrays. Supports both Enhanced and Raw Helius shapes.
    Accepts:
      - {"transactions":[{"meta":{"logMessages":[...]}}]}
      - {"data":[{"transaction":{"meta":{"logMessages":[...]}}}]}
      - {"data":[{"logs":[...]}]}
      - or payload is already a list of notes
    """
    out: List[List[str]] = []

    def add(logs: Any):
        if isinstance(logs, list) and logs:
            out.append(logs)

    # raw
    for t in payload.get("transactions", []) or []:
        add((t.get("meta") or t.get("transaction", {}).get("meta") or {}).get("logMessages"))

    # enhanced/custom
    notes = payload if isinstance(payload, list) else (payload.get("data") or [])
    for n in notes:
        tx = n.get("transaction") or n.get("tx") or {}
        add((tx.get("meta") or {}).get("logMessages"))
        add(n.get("logs"))

    return out

# tiny base58 (keeps deps light)
_ALPH = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def _bs58(b: bytes) -> str:
    pad = len(b) - len(b.lstrip(b'\0'))
    n = int.from_bytes(b, "big")
    out = bytearray()
    while n:
        n, r = divmod(n, 58)
        out.append(_ALPH[r])
    out += _ALPH[:1] * pad
    out.reverse()
    return out.decode() or "1" * (pad or 1)

def _event_blobs_from_logs(logs: List[str]) -> List[bytes]:
    blobs: List[bytes] = []
    prefix = "Program log: EVENT:"
    for line in logs:
        if prefix in line:
            b64 = line.split(prefix, 1)[1].strip()
            try:
                blobs.append(base64.b64decode(b64))
            except Exception:
                pass
    return blobs

def _decode_create_standard_pool(blob: bytes) -> Optional[Tuple[str, str]]:
    """
    Layout:
      8  discriminator
      32 pool_id
      32 payer
      32 creator
      32 mint
      2  config_version (u16)
      8  initial_token_reserve (u64 LE)
      8  initial_virtual_wsol_reserve (u64 LE)
    Returns (mint, pool_id) or None.
    """
    if len(blob) < 8 + 32*4 + 2 + 8 + 8 or blob[:8] != CSLPE_DISC:
        return None
    off = 8
    pool_id = _bs58(blob[off:off+32]); off += 32
    off += 32  # payer skip
    off += 32  # creator skip
    mint = _bs58(blob[off:off+32]); off += 32
    # ensure remaining bytes exist; we don't need the values
    if len(blob) < off + 2 + 8 + 8:
        return None
    return mint, pool_id

# ───────────────── pipeline ─────────────────
async def _process_mint(mint: str, pool_id: str):
    global _session
    if _session is None:
        return
    key = f"{mint}:{pool_id}"
    async with _seen_lock:
        if key in _seen:
            return
        _seen.add(key)

    pairs = await fetch_pairs_for_mint(_session, "solana", mint)
    if not pairs:
        return
    dp = pick_heaven_pair(pairs)
    if not dp:
        return

    try:
        await send_markdown("🆕 Heaven Launch\n\n" + format_pair_markdown(dp))
    except ChannelPrivateError:
        print("ChannelPrivateError: bot cannot post to TG_CHANNEL.")

# ───────────────── webhook ─────────────────
@app.post("/webhooks")
async def helius_webhook(req: Request):
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    found: List[Tuple[str, str]] = []
    seen_local: set[str] = set()

    for logs in _iter_log_batches(payload):
        for blob in _event_blobs_from_logs(logs):
            parsed = _decode_create_standard_pool(blob)
            if not parsed:
                continue
            mint, pool = parsed
            k = f"{mint}:{pool}"
            if k not in seen_local:
                seen_local.add(k)
                found.append(parsed)

    for mint, pool in found:
        asyncio.create_task(_process_mint(mint, pool))

    return {"ok": True, "processed": len(found)}
