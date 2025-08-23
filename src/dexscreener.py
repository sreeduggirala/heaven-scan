import aiohttp
from typing import Any, Dict, List, Optional

DEXS_BASE = "https://api.dexscreener.com"


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


def _to_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


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

        liq = raw.get("liquidity") or {}
        self.liq_usd = _to_float(liq.get("usd"))

        vol = raw.get("volume") or {}
        self.vol_m5 = _to_float(vol.get("m5"))
        self.vol_h1 = _to_float(vol.get("h1"))
        self.vol_h6 = _to_float(vol.get("h6"))
        self.vol_h24 = _to_float(vol.get("h24"))

    @property
    def market_cap_float(self) -> float:
        return _to_float(self.market_cap)


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
    urls = [
        f"{DEXS_BASE}/token-pairs/v1/{chain_id}/{mint}",
        f"{DEXS_BASE}/latest/dex/tokens/{chain_id}/{mint}",
        f"{DEXS_BASE}/latest/dex/search?q={mint}",
    ]
    last_err = None
    for i, url in enumerate(urls):
        try:
            data = await _get_json(session, url)
            if isinstance(data, list):
                pairs_raw = data
            elif isinstance(data, dict) and "pairs" in data:
                pairs_raw = data.get("pairs") or []
            else:
                pairs_raw = []

            filtered = [
                p
                for p in pairs_raw
                if (p.get("baseToken") or {}).get("address") == mint
            ]
            if not filtered and i >= 1:
                filtered = [
                    p
                    for p in pairs_raw
                    if mint in ((p.get("baseToken") or {}).get("address") or "")
                ]
            if filtered:
                return [DexPair(p) for p in filtered]
        except Exception as e:
            last_err = e
            continue
    if last_err:
        pass
    return []


def pick_heaven_pair(pairs: List[DexPair]) -> Optional[DexPair]:
    """Return the Heaven DEX pair only; otherwise None."""
    for p in pairs:
        if p.dex_id == "heaven":
            return p
    return None


def format_pair_markdown(pair: DexPair, *, explorer: str = "solscan") -> str:
    name, symbol, mint, url = pair.name, pair.symbol, pair.mint, pair.url
    price, mc, pc = pair.price_usd, pair.market_cap, pair.pc

    explorer_url = (
        f"https://solscan.io/token/{mint}"
        if explorer == "solscan"
        else f"https://solana.fm/address/{mint}"
    )
    scan_url = f"https://rugcheck.xyz/tokens/{mint}"
    display_mint = f"`{mint}`"

    header = (
        f"{name} | {symbol} | {display_mint}\n"
        f"[Explorer]({explorer_url}) | [Chart]({url}) | [Scan]({scan_url})"
    )

    body = [
        f"Price: ${price}",
        f"5m: {_pct(pc.get('m5')):+.2f}%, 1h: {_pct(pc.get('h1')):+.2f}%, 6h: {_pct(pc.get('h6')):+.2f}%, 24h: {_pct(pc.get('h24')):+.2f}%",
        f"Market Cap: {_fmt_money(mc)}",
        f"Volume (24h): {_fmt_money(pair.vol_h24)}",
        f"Liquidity: {_fmt_money(pair.liq_usd)}",
    ]
    return header + "\n\n" + "\n".join(body)
