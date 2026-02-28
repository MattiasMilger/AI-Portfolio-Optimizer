# AI Portfolio Optimizer

A desktop application that walks you through a guided wizard to analyse your stock portfolio and generate personalised AI-powered investment recommendations using Google Gemini.

---

## What is this?

AI Portfolio Optimizer is a streamlined, session-based tool for retail investors who want a second opinion on their portfolio. You feed it your holdings — either by uploading a screenshot or entering them manually — set your preferences, and receive a structured recommendation from a large language model grounded in live market data.

Every session starts from scratch. There is no account, no login, and no cloud sync. Your portfolio data never leaves your machine except for the anonymised prompt sent to the Gemini API.

### What it does

- Scans a portfolio screenshot using Gemini's vision capability and automatically extracts your positions, including the correct exchange-suffixed tickers (e.g. `LUG.ST` for Swedish stocks)
- Fetches live prices and FX rates via yfinance to give the AI accurate, up-to-date values
- Converts all positions to a single base currency for a consolidated P&L view
- Generates a structured recommendation in the format **SELL → BUY → HOLD**, each with a one-line rationale
- Optionally suggests new stocks or ETFs to add, filtered by your target industries and countries
- Saves the AI output to a dated text file in `reports/`

---

## Requirements

### System
- **Python 3.11 or later** (3.13 recommended)
- Windows 10/11 (tested), macOS and Linux should work but are untested

### Python packages

```
customtkinter>=5.2.0
google-genai>=1.0.0
yfinance>=0.2.40
python-dotenv>=1.0.0
Pillow>=10.0.0
requests>=2.31.0
```

### API key
A free **Google Gemini API key** is required. Get one at:
[https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

---

## Setup

**1. Clone or download the repository**

```bash
git clone https://github.com/MattiasMilger/AI-Portfolio-Optimizer.git
cd "AI Portfolio Optimizer"
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Run the app**

```bash
python main.py
```

---

## How to use it

### API Key Setup (first run only)

The first time you launch the app — or any time no valid key is found — it opens the **API Key Setup** screen before anything else.

**Step 1 — Get your key**

Click **Open Google AI Studio ↗** to open [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) in your browser. Sign in with a Google account, create a new API key, and copy it.

**Step 2 — Paste and save**

Paste the key into the entry field (use the *Show* checkbox to reveal it if needed) and click **Test & Save Key**. The app contacts the Gemini API to confirm the key works, then writes it to a local `.env` file in the project folder.

> **Security notice:** your API key grants access to your Google AI quota and billing account.
> - Never share it publicly, commit it to a repository, or send it in messages.
> - It is stored only in the local `.env` file, which is listed in `.gitignore` and will never be committed to git.
> - Treat it like a password — if it is ever exposed, regenerate it immediately at [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).

Once saved you will not see this screen again unless you delete the `.env` file. You can also return to it at any time via the **Change API Key** button on the title screen.

If you prefer to set the key manually before launching, copy `.env.example` to `.env` and fill in your key — the wizard will be skipped automatically on startup.

---

### Wizard pages

The app is a linear wizard. Each step has a **← Back** button so you can revisit any earlier step.

| Step | Page | What you do |
|------|------|-------------|
| 0 | **API Key Setup** | First-run only — paste your Gemini key and click *Test & Save Key* |
| 1 | **Title** | Click *Optimize Portfolio* to begin |
| 2 | **Source** | Choose *Upload Image* (screenshot scan) or *Start from Scratch* (manual entry) |
| 3 | **Positions** | Review, edit, add, or delete the extracted/entered positions |
| 4 | **Suggest New Assets?** | Tick if you want the AI to recommend new assets (only shown when you have existing positions) |
| 5 | **Investment Preferences** | Enter target industries, target countries, and preferred asset types (all optional, all saveable as defaults) |
| 6 | **Risk Profile** | Choose Conservative, Moderate, or Aggressive |
| 7 | **Budget & Currency** | Set your base currency and any additional cash available for new purchases |
| 8 | **AI Model** | Pick the Gemini model to use |
| 9 | **Results** | The AI recommendation loads automatically. Use *Save*, *Rethink*, or *Restart* |

### Result page actions

| Button | What it does |
|--------|-------------|
| **💾 Save** | Saves the full AI output to `reports/YYYY-MM-DD.txt` (auto-increments if the file exists) |
| **🔄 Rethink** | Re-runs the same prompt for a fresh response |
| **↺ Restart** | Clears the session and returns to the title screen |

---

## Image scan tips

The scanner works best with clean, high-contrast screenshots from a brokerage app or trading platform. For best results:

- Make sure tickers, quantities, and average buy prices are all visible
- Include the currency or country context (flag, broker name, exchange label) so the AI can assign the correct exchange suffix
- Supported formats: PNG, JPG, JPEG, WEBP, BMP

### Supported exchange suffixes (auto-detected)

| Market | Suffix | Example |
|--------|--------|---------|
| Sweden (SEK, Nasdaq Stockholm) | `.ST` | `ERIC-B.ST` |
| Norway (NOK, Oslo Børs) | `.OL` | `EQNR.OL` |
| Denmark (DKK, Nasdaq CPH) | `.CO` | `NOVO-B.CO` |
| Finland (EUR, Nasdaq Helsinki) | `.HE` | |
| Germany (XETRA) | `.DE` | `SAP.DE` |
| UK (LSE, GBP) | `.L` | `SHEL.L` |
| France (Euronext Paris) | `.PA` | |
| Netherlands (Euronext AMS) | `.AS` | |
| Canada (TSX) | `.TO` | |
| Australia (ASX) | `.AX` | |
| Hong Kong (HKEX) | `.HK` | |
| Japan (TSE) | `.T` | |
| USA (NYSE / Nasdaq) | *(none)* | `AAPL`, `MSFT` |

---

## Technical overview

### Architecture

The app is split into two modules:

- **`main.py`** — all UI logic, the wizard page stack, and session state management
- **`finance_engine.py`** — all external calls: yfinance market data, FX rates, Gemini AI (vision and text)

There is no database. Everything is held in a `session` dict on the `App` instance and discarded when the app closes or the user clicks Restart. The only file written during normal use is `data/defaults.json` (saved industries/countries preferences) and the optional `reports/` output.

### Navigation model

All wizard pages are instantiated once at startup and stacked in the same grid cell. `tkraise()` brings the active page to the front. A `_current_page` string and `_history` list on the `App` object implement browser-style Back navigation without re-creating widgets.

### AI recommendation pipeline

1. `enrich_portfolio()` fetches live closing prices and FX rates from yfinance and converts all values to the chosen base currency
2. A structured situation report is assembled (holdings, P&L, budget, risk profile, preferences)
3. The report is sent to Gemini with a strict system instruction that enforces the SELL / BUY / HOLD format
4. The model tries `preferred_model` first, then falls back through a priority list if a 429 or 404 is returned

### Persistent state

The only data persisted between sessions is `data/defaults.json`, which stores the user's saved Target Industries, Target Countries, and Asset Types strings. Nothing else is written to disk unless the user explicitly clicks Save on the results page.

---

## Project structure

```
AI Portfolio Optimizer/
│
├── main.py                  # GUI — wizard pages and navigation
├── finance_engine.py        # Market data (yfinance) and Gemini AI calls
├── requirements.txt         # Python package dependencies
├── .env.example             # Template for the API key
├── .env                     # Your API key (not committed to git)
│
├── data/
│   └── defaults.json        # Saved industry/country/asset-type preferences (auto-created)
│
└── reports/
    └── YYYY-MM-DD.txt       # Saved AI recommendation outputs (auto-created)
```

### Key classes (`main.py`)

| Class | Role |
|-------|------|
| `App` | Root `CTk` window; owns session state and navigation stack |
| `WizardPage` | Base class for all pages; defines `on_show()` and `on_reset()` hooks |
| `ApiKeyPage` | First-run API key setup; validates key against Gemini and writes to `.env` |
| `TitlePage` | Landing screen |
| `SourcePage` | Upload image or start from scratch |
| `PositionsPage` | Editable position list with add/delete rows |
| `RecModePage` | Toggle for recommending new stocks |
| `IndustriesPage` | Target industries, countries, and asset types with persistent defaults |
| `RiskProfilePage` | Conservative / Moderate / Aggressive radio selection |
| `BudgetPage` | Base currency (freeform combobox) + cash budget |
| `ModelPage` | Gemini model picker |
| `ResultPage` | Runs analysis in a background thread; Save / Rethink / Restart |

### Key functions (`finance_engine.py`)

| Function | Role |
|----------|------|
| `set_api_key()` | Updates the in-process API key after the user saves a new one via the wizard |
| `validate_api_key()` | Tests a key against the Gemini API before saving it |
| `enrich_portfolio()` | Adds live prices, FX-converted values, and P&L to position dicts |
| `get_fx_rate()` | Fetches FX rate via yfinance with inverse fallback and in-process cache |
| `scan_portfolio_image()` | Sends a PIL image to Gemini vision; parses JSON positions from the response |
| `get_optimizer_recommendation()` | Builds situation report and calls Gemini text generation with fallback model list |
| `list_available_models()` | Returns models available on the configured API key |

---

## Credits

**Developer**: Mattias Milger  
**Email**: mattias.r.milger@gmail.com  
**GitHub**: [MattiasMilger](https://github.com/MattiasMilger/Vasenvaktaren)