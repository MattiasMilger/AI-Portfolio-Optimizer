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


def _client() -> genai.Client:
    """Return a configured Gemini client."""
    return genai.Client(api_key=_GEMINI_API_KEY)


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
    if enriched_portfolio:
        holdings_lines = []
        for p in enriched_portfolio:
            stale = " [STALE — no live price]" if not p.get("fetch_ok") else ""
            company = p.get("company_name") or p["ticker"]
            holdings_lines.append(
                f"  • {company} ({p['ticker']})  "
                f"qty={p['quantity']:.4f}  "
                f"avg_cost={p['avg_buy_price']:.4f} {p['original_currency']}  "
                f"price={p['current_price_base']:.4f} {base_currency}  "
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

    situation_report = f"""
PORTFOLIO SNAPSHOT
==================
Risk Profile      : {risk_profile}
Target Industries : {industries or 'No preference'}
Target Countries  : {countries or 'No preference'}
Base Currency     : {base_currency}

CURRENT HOLDINGS ({num_positions} position(s)):
{holdings_text}

SUMMARY:
  Total Portfolio Value : {total_value:,.2f} {base_currency}
  Total Unrealised P/L  : {total_pl:+,.2f} {base_currency}

BUDGET:
{budget_text}
""".strip()

    new_stocks_section = (
        "Also suggest 2-3 NEW stocks or ETFs not currently held that fit the target industries "
        "and can be purchased within the stated budget, each with ticker and one-line rationale.\n"
        if rec_new_stocks and num_positions > 0
        else (
            "The portfolio is empty — suggest 3-5 starter positions that fit the target industries "
            "and can be purchased within the stated budget, each with ticker and one-line rationale.\n"
            if num_positions == 0
            else ""
        )
    )

    countries_clause = (
        f"Prefer stocks listed or headquartered in: {countries}. "
        if countries else ""
    )
    system_instruction = (
        "You are a financial analyst. "
        f"The investor's risk profile is {risk_profile}. "
        f"{countries_clause}"
        "Use ONLY the signals SELL, BUY, and HOLD — never 'add', 'reduce', or any other word. "
        "Be balanced: default to HOLD unless there is a concrete, specific reason to act. "
        "If you recommend a SELL, you must pair it with a BUY for the proceeds. "
        f"{new_stocks_section}"
        "End your response with exactly this block. "
        "Order: all SELLs first, then all BUYs, then all HOLDs. "
        "Each SELL and BUY line must end with ' — ' followed by a one-line reason. "
        "HOLD lines have no reason. "
        "Use the full company name exactly as in the holdings data.\n\n"
        "MY RECOMMENDATION\n"
        "-----------------\n"
        "Sell X share(s) of Full Company Name (TICKER) — reason\n"
        "Buy X share(s) of Full Company Name (TICKER) — reason\n"
        "Hold Full Company Name (TICKER)\n\n"
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
