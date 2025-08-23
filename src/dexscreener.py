import aiohttp
import asyncio
from typing import Any, Dict, List, Optional

DEXS_BASE = "https://api.dexscreener.com"


class DexPair:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.dex_id = (raw.get("dexId") or "").lower()
        self.url = raw.get("url") or ""
        self.price_usd = str(raw.get("priceUsd") or "?")
        self.market_cap = raw.get("marketCap") or raw.get("fdv")
        self.pc = raw.get("priceChange") or {}
        bt = raw.get("baseToken") or {}
        self.symbol = bt.get("symbol") or "UNKNOWN"
        self.name = bt.get("name") or self.symbol
        self.mint = bt.get("address") or ""


def _pct(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _fmt_money(x) -> str:
    if x is None:
        return "?"
    try:
        n = float(x)
    except Exception:
        return "?"
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.2f}K"
    return f"${n:,.0f}"


async def _get_json(session: aiohttp.ClientSession, url: str) -> Any:
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=12),
        headers={"Accept": "application/json", "User-Agent": "dexscreener-client/1.0"},
    ) as r:
        txt = await r.text()
        if r.status != 200:
            raise aiohttp.ClientResponseError(
                r.request_info, r.history, status=r.status, message=txt
            )
        try:
            return await r.json()
        except Exception:
            # DEXS sometimes returns text (e.g., Cloudflare block); surface it
            raise aiohttp.ClientResponseError(
                r.request_info,
                r.history,
                status=r.status,
                message=f"Non-JSON: {txt[:256]}",
            )


async def fetch_pairs_for_mint(
    session: aiohttp.ClientSession, chain_id: str, mint: str
) -> List[DexPair]:
    mint = mint.strip()
    # Strategy 1: primary pairs endpoint
    urls = [
        f"{DEXS_BASE}/token-pairs/v1/{chain_id}/{mint}",
        # Strategy 2: tokens endpoint (returns {"pairs":[...]})
        f"{DEXS_BASE}/latest/dex/tokens/{chain_id}/{mint}",
        # Strategy 3: search endpoint (returns {"pairs":[...]})
        f"{DEXS_BASE}/latest/dex/search?q={mint}",
    ]
    last_err = None
    for i, url in enumerate(urls):
        try:
            data = await _get_json(session, url)

            # Normalize into a list of pair dicts
            if isinstance(data, list):  # v1 /token-pairs
                pairs_raw = data
            elif isinstance(data, dict) and "pairs" in data:
                pairs_raw = data.get("pairs") or []
            else:
                pairs_raw = []

            # Filter to baseToken.address == mint (avoid pairs where the mint is quote)
            filtered = [
                p
                for p in pairs_raw
                if (p.get("baseToken") or {}).get("address") == mint
            ]

            # If Strategy 2/3 and we got no exact matches, accept any pair mentioning this mint as base
            if not filtered and i >= 1:
                # occasionally the address field is mismatched in early seconds; fallback to contains check
                filtered = [
                    p
                    for p in pairs_raw
                    if mint in ((p.get("baseToken") or {}).get("address") or "")
                ]

            if filtered:
                return [DexPair(p) for p in filtered]

        except Exception as e:
            last_err = e
            # try next strategy
            continue

    # If we got here, nothing matched
    if last_err:
        # Optional: print the last error for debugging
        # print(f"DEXS error: {last_err}")
        pass
    return []


def pick_heaven_pair(pairs: List[DexPair]) -> Optional[DexPair]:
    if not pairs:
        return None
    for p in pairs:
        if p.dex_id == "heaven":
            return p
    return pairs[0]


def format_pair_markdown(pair: DexPair, *, explorer: str = "solscan") -> str:
    name, symbol, mint, url = pair.name, pair.symbol, pair.mint, pair.url
    price, mc, pc = pair.price_usd, pair.market_cap, pair.pc

    # links must use the raw mint (no backticks)
    explorer_url = (
        f"https://solscan.io/token/{mint}"
        if explorer == "solscan"
        else f"https://solana.fm/address/{mint}"
    )
    scan_url = f"https://rugcheck.xyz/tokens/{mint}"

    # display mint wrapped in backticks for Telegram markdown
    display_mint = f"`{mint}`"

    header = (
        f"{name} | {symbol} | {display_mint}\n"
        f"[Explorer]({explorer_url}) | [Chart]({url}) | [Scan]({scan_url})"
    )

    body = [
        f"Price: ${price}",
        f"5m: {_pct(pc.get('m5')):+.2f}%, 1h: {_pct(pc.get('h1')):+.2f}%, 6h: {_pct(pc.get('h6')):+.2f}%, 24h: {_pct(pc.get('h24')):+.2f}%",
        f"Market Cap: {_fmt_money(mc)}",
    ]
    return header + "\n\n" + "\n".join(body)


# quick manual test
if __name__ == "__main__":

    async def _t():
        test_mint = "6MqCLbQi7L39RN7ETqHAxhmQYzYtyAqiDL6xcZg9S777"  # your example
        async with aiohttp.ClientSession() as s:
            pairs = await fetch_pairs_for_mint(s, "solana", test_mint)
            if not pairs:
                print(f"No pairs found for mint: {test_mint}")
                return
            dp = pick_heaven_pair(pairs)
            print(format_pair_markdown(dp))

    asyncio.run(_t())
