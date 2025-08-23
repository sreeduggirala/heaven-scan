import os, base64, struct, asyncio
from typing import Any, Dict, List, Tuple, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
import aiohttp
from telethon.errors import ChannelPrivateError

from dexscreener import fetch_pairs_for_mint, pick_heaven_pair, format_pair_markdown
from telegram import send_markdown, get_client

HEAVEN_PROGRAM_ID = "HKZCA4EJ2e16P9n2afZHXm9ZvZkPcFAp9ZpA9E48Kyma"
# From IDL.events[].discriminator for CreateStandardLiquidityPoolEvent:
CSLPE_DISC = bytes([189, 56, 131, 144, 75, 63, 249, 148])  # \xBD8\x83\x90K?\xF9\x94

_session: Optional[aiohttp.ClientSession] = None
_seen: set[str] = set()
_seen_lock = asyncio.Lock()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _session
    _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    await get_client()
    try:
        yield
    finally:
        if _session and not _session.closed:
            await _session.close()

app = FastAPI(lifespan=lifespan)

@app.get("/healthz")
async def healthz():
    return {"ok": True, "program": HEAVEN_PROGRAM_ID}

# ---------- helpers to read logs from Helius ----------
def _iter_log_batches(payload: Dict[str, Any]) -> List[List[str]]:
    """
    Works for both Helius Enhanced and Raw webhooks.
    Returns a list of `logMessages` arrays (one per tx).
    """
    out: List[List[str]] = []

    # Case A: raw webhook -> { "transactions": [ { "transaction": {...}, "meta": {...} }, ... ] }
    txs = payload.get("transactions")
    if isinstance(txs, list):
        for t in txs:
            meta = t.get("meta") or t.get("transaction", {}).get("meta") or {}
            logs = meta.get("logMessages")
            if isinstance(logs, list) and logs:
                out.append(logs)

    # Case B: enhanced/custom -> array of notes with tx/meta/logs in different places
    notes = payload if isinstance(payload, list) else payload.get("data")
    if isinstance(notes, list):
        for n in notes:
            # enhanced: note.transaction.meta.logMessages
            tx = n.get("transaction") or n.get("tx") or {}
            meta = tx.get("meta") or {}
            logs = meta.get("logMessages")
            if isinstance(logs, list) and logs:
                out.append(logs)
            # logs sometimes appear directly
            elif isinstance(n.get("logs"), list) and n["logs"]:
                out.append(n["logs"])

    return out


# base58 without dependency
_ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def _bs58(b: bytes) -> str:
    pad = len(b) - len(b.lstrip(b'\0'))
    num = int.from_bytes(b, "big")
    out = bytearray()
    while num > 0:
        num, rem = divmod(num, 58)
        out.append(_ALPHABET[rem])
    out.extend(_ALPHABET[0] for _ in range(pad))
    out.reverse()
    return out.decode("ascii") if out else "1" * (pad or 1)

def _event_blobs_from_logs(logs: List[str]) -> List[bytes]:
    blobs: List[bytes] = []
    prefix = "Program log: EVENT:"
    for line in logs:
        if prefix in line:
            try:
                b64 = line.split(prefix, 1)[1].strip()
                blobs.append(base64.b64decode(b64))
            except Exception:
                continue
    return blobs

def _decode_create_standard_pool(blob: bytes) -> Optional[Tuple[str, str]]:
    """
    blob = 8(discriminator) + 4*32(pubkeys) + 2(u16) + 8(u64) + 8(u64)
    returns (mint, pool_id)
    """
    # discriminator check
    if len(blob) < 8 or blob[:8] != CSLPE_DISC:
        return None
    off = 8
    pool_id = _bs58(blob[off:off+32]); off += 32
    _payer  = _bs58(blob[off:off+32]); off += 32
    _creator= _bs58(blob[off:off+32]); off += 32
    mint    = _bs58(blob[off:off+32]); off += 32
    if len(blob) < off + 2 + 8 + 8:
        return None
    # u16 + two u64s (we don’t use them here)
    _cfg, = struct.unpack_from("<H", blob, off); off += 2
    _tok, = struct.unpack_from("<Q", blob, off); off += 8
    _wsl, = struct.unpack_from("<Q", blob, off); off += 8
    return mint, pool_id

# ---------- pipeline ----------
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

    msg = "🆕 Heaven Launch\n\n" + format_pair_markdown(dp)
    try:
        await send_markdown(msg)
    except ChannelPrivateError:
        print("ChannelPrivateError: bot cannot post to TG_CHANNEL.")

@app.post("/webhooks")
async def helius_webhook(req: Request):
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    batches = _iter_log_batches(payload)
    if not batches:
        return {"ok": True, "processed": 0}

    found = []
    seen = set()
    for logs in batches:
        for blob in _event_blobs_from_logs(logs):
            parsed = _decode_create_standard_pool(blob)
            if parsed:
                mint, pool_id = parsed
                key = f"{mint}:{pool_id}"
                if key not in seen:
                    seen.add(key)
                    found.append(parsed)

    for mint, pool_id in found:
        asyncio.create_task(_process_mint(mint, pool_id))

    return {"ok": True, "processed": len(found)}

