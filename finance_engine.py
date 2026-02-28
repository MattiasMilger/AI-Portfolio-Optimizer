"""
finance_engine.py — Market data (yfinance) and Gemini AI integration
for AI Portfolio Optimizer (wizard-based, session-only, no persistence).
"""

import json
import os
import re
from typing import Optional

import yfinance as yf
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
_GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# Simple in-process caches to avoid redundant network calls in a single session
_fx_cache: dict[str, float] = {}
_name_cache: dict[str, str] = {}


def set_api_key(key: str) -> None:
    """Update the in-process API key (call after saving a new key to .env)."""
    global _GEMINI_API_KEY
    _GEMINI_API_KEY = key.strip()


def validate_api_key(key: str) -> tuple[bool, str]:
    """
    Test whether `key` is a working Gemini API key.
    Returns (True, "") on success or (False, error_message) on failure.
    """
    key = key.strip()
    if not key:
        return False, "API key is empty."
    try:
        client = genai.Client(api_key=key)
        # A lightweight call — just list models to confirm auth works.
        models = list(client.models.list())
        if not models:
            return False, "Key accepted but no models were returned — check your project settings."
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _client() -> genai.Client:
    """Return a configured Gemini client."""
    return genai.Client(api_key=_GEMINI_API_KEY)


def _fmt_num(value: float) -> str:
    """Format a number cleanly: integer if whole, otherwise strip trailing zeros."""
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0")


# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------

def get_fx_rate(from_currency: str, to_currency: str) -> float:
    """
    Return how many `to_currency` units equal one `from_currency` unit.
    Uses yfinance FX tickers (e.g. 'USDSEK=X').
    Falls back to a cached value, then 1.0 if completely unavailable.
    """
    if from_currency == to_currency:
        return 1.0

    key = f"{from_currency}{to_currency}"
    symbol = f"{key}=X"

    try:
        hist = yf.Ticker(symbol).history(period="2d")
        if not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            _fx_cache[key] = rate
            return rate
    except Exception:
        pass

    # Fallback: try inverse and invert
    inv_key = f"{to_currency}{from_currency}"
    inv_symbol = f"{inv_key}=X"
    try:
        hist = yf.Ticker(inv_symbol).history(period="2d")
        if not hist.empty:
            inv_rate = float(hist["Close"].iloc[-1])
            if inv_rate != 0:
                rate = 1.0 / inv_rate
                _fx_cache[key] = rate
                return rate
    except Exception:
        pass

    return _fx_cache.get(key, 1.0)


def get_current_price(ticker: str) -> Optional[float]:
    """
    Fetch the latest closing price for a ticker via yfinance.
    Returns None when the ticker cannot be resolved.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        info = t.info
        for field in ("currentPrice", "regularMarketPrice", "navPrice", "previousClose"):
            if info.get(field):
                return float(info[field])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Portfolio enrichment
# ---------------------------------------------------------------------------

def enrich_portfolio(portfolio: list[dict], base_currency: str) -> list[dict]:
    """
    Add live price data and P/L calculations (all amounts in base_currency)
    to each position dict.
    Each position dict should have: ticker, quantity, avg_buy_price, original_currency.
    """
    needed_pairs: set[tuple[str, str]] = set()
    for pos in portfolio:
        orig = pos["original_currency"].upper()
        base = base_currency.upper()
        if orig != base:
            needed_pairs.add((orig, base))

    fx_rates: dict[str, float] = {}
    for orig, base in needed_pairs:
        fx_rates[f"{orig}{base}"] = get_fx_rate(orig, base)

    enriched: list[dict] = []
    for pos in portfolio:
        ticker = pos["ticker"]
        orig_currency = pos["original_currency"].upper()
        base = base_currency.upper()
        quantity = pos["quantity"]
        avg_buy_price = pos["avg_buy_price"]

        t_obj = yf.Ticker(ticker)

        try:
            hist = t_obj.history(period="2d")
            current_price = float(hist["Close"].iloc[-1]) if not hist.empty else None
        except Exception:
            current_price = None
        fetch_ok = current_price is not None
        if not fetch_ok:
            current_price = avg_buy_price

        if ticker not in _name_cache:
            try:
                info = t_obj.info
                _name_cache[ticker] = (
                    info.get("shortName") or info.get("longName") or ticker
                )
            except Exception:
                _name_cache[ticker] = ticker
        company_name = _name_cache[ticker]

        fx_key = f"{orig_currency}{base}"
        fx_rate = fx_rates.get(fx_key, 1.0) if orig_currency != base else 1.0

        current_price_base = current_price * fx_rate
        avg_buy_price_base = avg_buy_price * fx_rate
        current_value_base = current_price_base * quantity
        cost_basis_base = avg_buy_price_base * quantity
        pl_abs = current_value_base - cost_basis_base
        pl_pct = (
            ((current_price - avg_buy_price) / avg_buy_price) * 100.0
            if avg_buy_price > 0
            else 0.0
        )

        enriched.append(
            {
                **pos,
                "company_name": company_name,
                "current_price": current_price,
                "current_price_base": current_price_base,
                "avg_buy_price_base": avg_buy_price_base,
                "current_value_base": current_value_base,
                "cost_basis_base": cost_basis_base,
                "pl_abs": pl_abs,
                "pl_pct": pl_pct,
                "fx_rate": fx_rate,
                "fetch_ok": fetch_ok,
            }
        )

    return enriched


# ---------------------------------------------------------------------------
# Gemini model discovery
# ---------------------------------------------------------------------------

def list_available_models() -> str:
    """Return a human-readable list of Gemini models available for this API key."""
    if not _GEMINI_API_KEY:
        return "  GEMINI_API_KEY not set."
    try:
        client = _client()
        models = [
            m for m in client.models.list()
            if m.supported_actions and "generateContent" in m.supported_actions
        ]
        if not models:
            return "No models supporting generateContent found for this API key."
        lines = ["Models available on your API key:\n"]
        for m in sorted(models, key=lambda x: x.name):
            lines.append(f"  • {m.name.replace('models/', '')}")
        return "\n".join(lines)
    except Exception as exc:
        return f"  Could not list models: {exc}"


# ---------------------------------------------------------------------------
# Portfolio image scanner
# ---------------------------------------------------------------------------

def scan_portfolio_image(
    image_path: str, model_name: str = "gemini-2.5-flash"
) -> tuple[list[dict], str]:
    """
    Send a portfolio screenshot to Gemini and extract positions as structured data.
    Returns (positions, raw_text). positions is a list of dicts with keys:
      ticker, quantity, avg_buy_price, original_currency
    On failure positions is [] and raw_text contains the error/explanation.
    """
    if not _GEMINI_API_KEY:
        return [], "  GEMINI_API_KEY not set."

    try:
        import PIL.Image
        img = PIL.Image.open(image_path)
    except Exception as exc:
        return [], f"  Could not open image: {exc}"

    prompt = (
        "Extract every stock / ETF / fund position visible in this portfolio screenshot. "
        "Return ONLY a valid JSON array — no markdown, no explanation. "
        "Each element must have exactly these keys:\n"
        '  "ticker"        : string  — the full yfinance ticker including exchange suffix (see rules below)\n'
        '  "quantity"      : number  — shares / units held\n'
        '  "avg_buy_price" : number  — average purchase price\n'
        '  "original_currency" : string  — 3-letter currency code (e.g. "USD", "SEK")\n'
        "Use null for any field you cannot determine with confidence.\n\n"
        "CRITICAL — ticker exchange suffix rules (yfinance format):\n"
        "First, identify the market/exchange from the screenshot context (currency, broker name, flag, country label).\n"
        "Then append the correct suffix:\n"
        "  Sweden (SEK, Nasdaq Stockholm) → .ST   e.g. LUG → LUG.ST, ERIC-B → ERIC-B.ST\n"
        "  Norway (NOK, Oslo Børs)        → .OL   e.g. EQNR → EQNR.OL\n"
        "  Denmark (DKK, Nasdaq CPH)      → .CO   e.g. NOVO-B → NOVO-B.CO\n"
        "  Finland (EUR, Nasdaq Helsinki) → .HE\n"
        "  Germany (XETRA)                → .DE   e.g. SAP → SAP.DE\n"
        "  UK (LSE, GBP)                  → .L    e.g. SHEL → SHEL.L\n"
        "  France (Euronext Paris)        → .PA\n"
        "  Netherlands (Euronext AMS)     → .AS\n"
        "  Canada (TSX)                   → .TO\n"
        "  Australia (ASX)                → .AX\n"
        "  Hong Kong (HKEX)               → .HK\n"
        "  Japan (TSE)                    → .T\n"
        "  USA (NYSE / Nasdaq)            → no suffix  e.g. AAPL, MSFT, TSLA\n"
        "If the screenshot mixes markets, infer per-position from its currency or any visible exchange label.\n"
        "If truly uncertain, use no suffix but prefer making an educated guess over returning a bare symbol."
    )

    _ALL_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-flash-latest",
    ]
    models_to_try = [model_name] + [m for m in _ALL_MODELS if m != model_name]

    client = _client()
    last_err = ""
    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=[prompt, img],
            )
            text = response.text.strip()

            fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence:
                text = fence.group(1).strip()

            positions = json.loads(text)
            if not isinstance(positions, list):
                return [], f"  Unexpected response (not a JSON array):\n{response.text}"

            # Normalise: rename "currency" key → "original_currency" if needed
            valid = []
            for p in positions:
                if not p.get("ticker"):
                    continue
                if "currency" in p and "original_currency" not in p:
                    p["original_currency"] = p.pop("currency")
                valid.append(p)
            return valid, response.text

        except json.JSONDecodeError as exc:
            return [], f"  Could not parse AI response as JSON ({exc}).\n\nRaw:\n{text}"
        except Exception as exc:
            last_err = str(exc)
            if "429" in last_err or "404" in last_err:
                continue
            return [], f"  Scan error: {exc}"

    return [], f"  Scan failed on all models. Last error: {last_err}"


# ---------------------------------------------------------------------------
# Optimizer AI recommendation (no DB, direct params)
# ---------------------------------------------------------------------------


def build_situation_report(
    enriched_portfolio: list[dict],
    industries: str,
    budget: float,
    base_currency: str,
    countries: str = "",
    asset_types: str = "",
    risk_profile: str = "Moderate",
) -> str:
    """Build the text situation report from enriched portfolio data."""
    if enriched_portfolio:
        holdings_lines = []
        for p in enriched_portfolio:
            stale = " [STALE — no live price]" if not p.get("fetch_ok") else ""
            company = p.get("company_name") or p["ticker"]
            holdings_lines.append(
                f"  • {company} ({p['ticker']})  "
                f"qty={_fmt_num(p['quantity'])}  "
                f"avg_cost={_fmt_num(p['avg_buy_price'])} {p['original_currency']}  "
                f"price={_fmt_num(p['current_price_base'])} {base_currency}  "
                f"value={p['current_value_base']:.2f} {base_currency}  "
                f"P/L={p['pl_pct']:+.2f}% ({p['pl_abs']:+.2f} {base_currency})"
                f"{stale}"
            )
        holdings_text = "\n".join(holdings_lines)
        total_value = sum(p["current_value_base"] for p in enriched_portfolio)
        total_pl = sum(p["pl_abs"] for p in enriched_portfolio)
        num_positions = len(enriched_portfolio)
    else:
        holdings_text = "  (No current holdings — fresh start)"
        total_value = 0.0
        total_pl = 0.0
        num_positions = 0

    budget_text = (
        f"  Additional cash budget: {budget:,.2f} {base_currency} (available for new purchases)"
        if budget > 0
        else f"  Additional cash budget: none (rebalance within existing holdings only)"
    )

    return f"""
PORTFOLIO SNAPSHOT
==================
Risk Profile      : {risk_profile}
Target Industries : {industries or 'No preference'}
Target Countries  : {countries or 'No preference'}
Asset Types       : {asset_types or 'No preference'}
Base Currency     : {base_currency}

CURRENT HOLDINGS ({num_positions} position(s)):
{holdings_text}

SUMMARY:
  Total Portfolio Value : {total_value:,.2f} {base_currency}
  Total Unrealised P/L  : {total_pl:+,.2f} {base_currency}

BUDGET:
{budget_text}
""".strip()

_ALL_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-flash-latest",
]

AVAILABLE_MODELS = _ALL_MODELS


def get_optimizer_recommendation(
    enriched_portfolio: list[dict],
    industries: str,
    budget: float,
    base_currency: str,
    countries: str = "",
    asset_types: str = "",
    risk_profile: str = "Moderate",
    rec_new_stocks: bool = False,
    preferred_model: str = "gemini-2.5-flash",
) -> str:
    """
    Build a portfolio situation report and send it to Gemini for analysis.
    Returns the model's response text (or an error string).

    Parameters
    ----------
    enriched_portfolio : output of enrich_portfolio()
    industries         : user-supplied target industries string
    budget             : additional cash budget available for new positions
    base_currency      : 3-letter code, e.g. "SEK"
    risk_profile       : "Conservative", "Moderate", or "Aggressive"
    rec_new_stocks     : if True, ask the model to suggest new tickers too
    preferred_model    : Gemini model name to try first
    """
    if not _GEMINI_API_KEY:
        return (
            "  GEMINI_API_KEY not found.\n\n"
            "Create a .env file in the project folder with:\n"
            "    GEMINI_API_KEY=your_key_here\n\n"
            "Get a free key at https://aistudio.google.com/app/apikey"
        )

    # --- Build situation report -------------------------------------------
    num_positions = len(enriched_portfolio)
    situation_report = build_situation_report(
        enriched_portfolio=enriched_portfolio,
        industries=industries,
        budget=budget,
        base_currency=base_currency,
        countries=countries,
        asset_types=asset_types,
        risk_profile=risk_profile,
    )

    asset_types_clause = (
        f"Preferred asset types are: {asset_types}. Respect this when choosing what to buy or suggest — "
        "only recommend other asset types if no suitable match exists. "
        if asset_types else ""
    )
    new_stocks_section = (
        f"Also suggest 2-3 NEW assets not currently held that fit the target industries{' and preferred asset types' if asset_types else ''}. "
        "Each suggestion must include a specific whole number of shares that can be purchased within the stated budget, "
        "plus a ticker and one-line rationale.\n"
        if rec_new_stocks and num_positions > 0
        else (
            f"The portfolio is empty — suggest 3-5 starter assets that fit the target industries{' and preferred asset types' if asset_types else ''}. "
            "Each suggestion must include a specific whole number of shares that can be purchased within the stated budget, "
            "plus a ticker and one-line rationale.\n"
            if num_positions == 0
            else ""
        )
    )

    countries_clause = (
        f"Prefer assets listed or headquartered in: {countries}. "
        if countries else ""
    )
    system_instruction = (
        "You are a financial analyst. "
        f"The investor's risk profile is {risk_profile}. "
        f"{countries_clause}"
        f"{asset_types_clause}"
        "Use ONLY the signals SELL, BUY, and HOLD — never 'add', 'reduce', or any other word. "
        "Be balanced: default to HOLD unless there is a concrete, specific reason to act. "
        "If you recommend a SELL, use the proceeds for a BUY of a DIFFERENT security — "
        "never sell a position only to rebuy the same ticker. "
        "For every SELL and BUY you must state a specific whole number of shares — "
        "calculate it from the prices and budget in the report. "
        "Never use vague language like 'some', 'a portion', 'a few', or a range. "
        "The total cost of all BUYs must not exceed the sum of all SELL proceeds plus the additional cash budget. "
        "Choose quantities so that cash in (sells + budget) equals cash out (buys) as closely as possible. "
        f"{new_stocks_section}"
        "End your response with exactly this block (in this order): "
        "all SELLs first, then all BUYs, then all HOLDs, then the CASH FLOW SUMMARY, then the rationale paragraph. "
        "Each SELL line must include the price per share, total proceeds, and end with ' — reason'. "
        "Each BUY line must include the price per share, total cost, and end with ' — reason'. "
        "Every position not being sold must appear as a HOLD line — never list a ticker without the Hold keyword. "
        "HOLD lines have no price or reason. "
        "Use the full company name exactly as in the holdings data. "
        "After all SELL/BUY/HOLD lines, add a CASH FLOW SUMMARY block showing: "
        "sell proceeds, additional budget, total available cash, total buy cost, and net remaining cash. "
        "Net remaining cash must be >= 0 (you must never overspend). "
        f"All monetary values must be in {base_currency}.\n\n"
        "MY RECOMMENDATION\n"
        "-----------------\n"
        f"Sell 3 share(s) of Full Company Name (TICKER) @ 150.00 {base_currency}/share = 450.00 {base_currency} proceeds — reason\n"
        f"Buy 5 share(s) of Full Company Name (TICKER) @ 90.00 {base_currency}/share = 450.00 {base_currency} cost — reason\n"
        "Hold Full Company Name (TICKER)\n\n"
        "CASH FLOW SUMMARY\n"
        "-----------------\n"
        f"Sell proceeds    : +450.00 {base_currency}\n"
        f"Additional budget: +0.00 {base_currency}\n"
        f"Total available  : +450.00 {base_currency}\n"
        f"Total buy cost   :  -450.00 {base_currency}\n"
        f"Net remaining    :    0.00 {base_currency}\n\n"
        "[One concise paragraph: overall strategic rationale and key risk]\n\n"
        "No introductions, no disclaimers, no fluff. "
        "Target industries are a soft preference. "
        f"All prices in {base_currency}."
    )

    models_to_try = [preferred_model] + [m for m in _ALL_MODELS if m != preferred_model]
    errors: list[str] = []

    client = _client()
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=situation_report,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                ),
            )
            note = (
                f"\n\n---\n_Fallback model used: {model_name}_"
                if model_name != models_to_try[0]
                else ""
            )
            return response.text + note
        except Exception as exc:
            err = str(exc)
            errors.append(f"{model_name}: {err}")
            if "429" in err or "404" in err:
                continue
            return f"  Gemini API error: {exc}"

    lines = ["  All models failed. Per-model errors:\n"]
    for entry in errors:
        model_part, _, err_part = entry.partition(": ")
        code = "429" if "429" in err_part else ("404" if "404" in err_part else "ERR")
        lines.append(f"  [{code}]  {model_part}")

    all_errors_text = " ".join(errors)
    delay_match = re.search(r"retry.*?(\d+)\s*s", all_errors_text, re.IGNORECASE)
    if delay_match:
        lines.append(f"\nRetry in ~{delay_match.group(1)} seconds.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Follow-up chat about a recommendation
# ---------------------------------------------------------------------------

def chat_about_recommendation(
    situation_report: str,
    initial_recommendation: str,
    chat_history: list[dict],
    user_message: str,
    preferred_model: str = "gemini-2.5-flash",
) -> str:
    """
    Continue a conversation about the portfolio recommendation.

    chat_history: list of {"role": "user"|"model", "text": "..."} (past exchanges)
    Returns the model's reply text (or an error string).
    """
    if not _GEMINI_API_KEY:
        return "GEMINI_API_KEY not set."

    system_instruction = (
        "You are a financial analyst who just provided a portfolio recommendation. "
        "The investor may disagree with specific parts or want targeted adjustments. "
        "Be concise and specific — give exact share quantities and prices when suggesting changes. "
        "Do not restart the full analysis. Focus only on what is being asked. "
        "You have access to the original portfolio snapshot and your previous recommendation."
    )

    # Build the multi-turn conversation as a list of Content objects.
    # Seed with the original analysis exchange so the model has full context.
    contents: list = [
        types.Content(role="user",  parts=[types.Part(text=situation_report)]),
        types.Content(role="model", parts=[types.Part(text=initial_recommendation)]),
    ]
    for msg in chat_history:
        contents.append(
            types.Content(role=msg["role"], parts=[types.Part(text=msg["text"])])
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    models_to_try = [preferred_model] + [m for m in _ALL_MODELS if m != preferred_model]
    client = _client()

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                ),
            )
            return response.text
        except Exception as exc:
            err = str(exc)
            if "429" in err or "404" in err:
                continue
            return f"Error: {exc}"

    return "All models failed. Please try again later."
