"""
main.py — AI Portfolio Optimizer
Wizard-based, session-only (no persistence).
"""

import json
import os
import threading
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

import finance_engine as fe

# ---------------------------------------------------------------------------
# App-wide appearance
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONT_TITLE   = ("Segoe UI", 28, "bold")
FONT_HEADING = ("Segoe UI", 16, "bold")
FONT_BODY    = ("Segoe UI", 13)
FONT_SMALL   = ("Segoe UI", 11)
FONT_MONO    = ("Consolas", 12)

COLOR_BG     = "#1a1a2e"
COLOR_PANEL  = "#16213e"
COLOR_ACCENT = "#0f3460"
COLOR_BRAND  = "#e94560"
COLOR_TEXT   = "#eaeaea"
COLOR_MUTED  = "#888888"

# ---------------------------------------------------------------------------
# Persistent defaults (industries only)
# ---------------------------------------------------------------------------

_DEFAULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "defaults.json")


def _load_defaults() -> dict:
    try:
        with open(_DEFAULTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_defaults(data: dict) -> None:
    os.makedirs(os.path.dirname(_DEFAULTS_FILE), exist_ok=True)
    with open(_DEFAULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Reusable helpers
# ---------------------------------------------------------------------------

def _btn(parent, text, command, width=160, **kw):
    """Create a CTkButton. Pass any CTkButton kwarg directly (e.g. fg_color, hover_color)."""
    kw.setdefault("fg_color",    COLOR_ACCENT)
    kw.setdefault("hover_color", "#1a4a8a")
    return ctk.CTkButton(
        parent, text=text, command=command, width=width, font=FONT_BODY, **kw,
    )


def _label(parent, text, font=None, anchor="w", **kw):
    return ctk.CTkLabel(parent, text=text, font=font or FONT_BODY, anchor=anchor, **kw)


def _back_btn(parent, app):
    return _btn(
        parent, "← Back", command=app.go_back, width=100,
        fg_color="transparent", border_width=1,
        border_color=COLOR_MUTED, text_color=COLOR_MUTED,
    )


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI Portfolio Optimizer")
        self.geometry("900x660")
        self.minsize(800, 580)
        self.configure(fg_color=COLOR_BG)

        # Session state — reset by restart()
        self.session: dict = {}
        self._history: list[str] = []
        self._current_page: str = "title"

        # All pages share the same grid cell; tkraise() switches between them.
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.pages: dict[str, "WizardPage"] = {}
        for PageClass in [
            TitlePage, SourcePage, PositionsPage,
            RecModePage, IndustriesPage, RiskProfilePage,
            BudgetPage, ModelPage, ResultPage,
        ]:
            page = PageClass(self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[PageClass.NAME] = page

        self.goto("title")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, name: str, push_history: bool = True) -> None:
        if push_history and self._current_page != name:
            self._history.append(self._current_page)
        self._current_page = name
        page = self.pages[name]
        page.on_show()
        page.tkraise()

    def go_back(self) -> None:
        if self._history:
            prev = self._history.pop()
            self.goto(prev, push_history=False)

    def restart(self) -> None:
        self.session = {}
        self._history = []
        self._current_page = "title"
        for page in self.pages.values():
            page.on_reset()
        self.goto("title", push_history=False)


# ---------------------------------------------------------------------------
# Base wizard page
# ---------------------------------------------------------------------------

class WizardPage(ctk.CTkFrame):
    NAME = ""

    def __init__(self, app: App):
        super().__init__(app, fg_color=COLOR_BG)
        self.app = app
        self._build()

    def _build(self):
        """Override to construct widgets."""

    def on_show(self):
        """Called every time the page becomes visible."""

    def on_reset(self):
        """Called on app restart."""


# ---------------------------------------------------------------------------
# Page 1 — Title
# ---------------------------------------------------------------------------

class TitlePage(WizardPage):
    NAME = "title"

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        center = ctk.CTkFrame(self, fg_color="transparent")
        center.grid(row=0, column=0)

        _label(center, "AI Portfolio Optimizer",
               font=("Segoe UI", 36, "bold"), anchor="center",
               text_color=COLOR_BRAND).pack(pady=(0, 6))

        _label(center, "By Mattias Milger",
               font=FONT_SMALL, anchor="center",
               text_color=COLOR_MUTED).pack(pady=(0, 48))

        _btn(center, "Optimize Portfolio  →",
             command=lambda: self.app.goto("source"),
             width=220,
             fg_color=COLOR_BRAND,
             hover_color="#c73050").pack()


# ---------------------------------------------------------------------------
# Page 2 — Source selection
# ---------------------------------------------------------------------------

class SourcePage(WizardPage):
    NAME = "source"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _label(self, "How do you want to start?",
               font=FONT_HEADING, anchor="center").grid(
               row=0, column=0, pady=(40, 32))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0)

        _btn(btn_frame, "📷  Upload Portfolio Image",
             command=self._upload, width=240).pack(pady=10)

        _btn(btn_frame, "✏  Start from Scratch",
             command=self._scratch, width=240).pack(pady=10)

        _back_btn(self, self.app).grid(row=2, column=0, sticky="sw", padx=24, pady=16)

    def _scratch(self):
        self.app.session["positions"] = []
        self.app.goto("positions")

    def _upload(self):
        path = filedialog.askopenfilename(
            title="Select portfolio screenshot",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")],
        )
        if not path:
            return
        dlg = _ProgressDialog(self.app, "Scanning image…")

        def do_scan():
            model = self.app.session.get("model", "gemini-2.5-flash")
            positions, raw = fe.scan_portfolio_image(path, model_name=model)
            self.after(0, lambda: self._scan_done(dlg, positions, raw))

        threading.Thread(target=do_scan, daemon=True).start()

    def _scan_done(self, dlg: "_ProgressDialog", positions: list[dict], raw: str):
        dlg.close()
        if not positions:
            messagebox.showwarning("Scan result",
                                   f"No positions could be extracted.\n\n{raw[:400]}")
            self.app.session["positions"] = []
        else:
            clean = []
            for p in positions:
                try:
                    clean.append({
                        "ticker":            str(p.get("ticker") or "").upper().strip(),
                        "quantity":          float(p.get("quantity") or 0),
                        "avg_buy_price":     float(p.get("avg_buy_price") or 0),
                        "original_currency": str(p.get("original_currency") or "USD").upper().strip(),
                    })
                except (TypeError, ValueError):
                    pass
            self.app.session["positions"] = [p for p in clean if p["ticker"]]
        self.app.goto("positions")


# ---------------------------------------------------------------------------
# Page 3 — Review / edit positions
# ---------------------------------------------------------------------------

class PositionsPage(WizardPage):
    NAME = "positions"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(28, 8))
        hdr.grid_columnconfigure(1, weight=1)
        _label(hdr, "Review Positions", font=FONT_HEADING).grid(row=0, column=0, sticky="w")
        _btn(hdr, "+ Add Position", command=self._add_row, width=140).grid(
            row=0, column=2, sticky="e")

        # Scrollable list
        self._scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_PANEL, corner_radius=8)
        self._scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=4)
        self._scroll.grid_columnconfigure((0, 1, 2, 3), weight=1)

        for col, txt in enumerate(["Ticker", "Quantity", "Avg Price", "Currency"]):
            _label(self._scroll, txt, font=FONT_SMALL,
                   text_color=COLOR_MUTED).grid(row=0, column=col, sticky="w",
                                                padx=8, pady=(6, 2))

        self._rows: list[_PositionRow] = []

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=14)
        footer.grid_columnconfigure(1, weight=1)
        _back_btn(footer, self.app).grid(row=0, column=0, sticky="w")
        _btn(footer, "Continue  →", command=self._continue, width=140).grid(
            row=0, column=2, sticky="e")

    def on_show(self):
        self._clear_rows()
        for pos in self.app.session.get("positions", []):
            self._add_row(pos)

    def on_reset(self):
        self._clear_rows()

    def _clear_rows(self):
        for r in self._rows:
            r.destroy()
        self._rows.clear()

    def _add_row(self, data: dict | None = None):
        row_idx = len(self._rows) + 1
        r = _PositionRow(self._scroll, row_idx, data, on_delete=self._delete_row)
        self._rows.append(r)

    def _delete_row(self, row: "_PositionRow"):
        row.destroy()
        self._rows.remove(row)
        for i, r in enumerate(self._rows):
            r.regrid(i + 1)

    def _continue(self):
        positions = [r.get_data() for r in self._rows]
        positions = [p for p in positions if p]
        self.app.session["positions"] = positions
        if positions:
            self.app.goto("recmode")
        else:
            self.app.session["rec_new_stocks"] = False
            self.app.goto("industries")


class _PositionRow:
    def __init__(self, parent: ctk.CTkScrollableFrame, grid_row: int,
                 data: dict | None, on_delete):
        self._parent = parent
        self._row = grid_row
        self._on_delete = on_delete

        self._ticker = ctk.CTkEntry(parent, width=100, font=FONT_BODY)
        self._qty    = ctk.CTkEntry(parent, width=100, font=FONT_BODY)
        self._price  = ctk.CTkEntry(parent, width=100, font=FONT_BODY)
        self._curr   = ctk.CTkEntry(parent, width=80,  font=FONT_BODY)
        self._del    = ctk.CTkButton(parent, text="✕", width=32, height=28,
                                     font=FONT_SMALL, fg_color="#6b2020",
                                     hover_color="#9b3030",
                                     command=lambda: on_delete(self))
        if data:
            self._ticker.insert(0, data.get("ticker", ""))
            self._qty.insert   (0, str(data.get("quantity", "")))
            self._price.insert (0, str(data.get("avg_buy_price", "")))
            self._curr.insert  (0, data.get("original_currency", "USD"))

        self._grid(grid_row)

    def _grid(self, row: int):
        p = {"padx": 6, "pady": 3}
        self._ticker.grid(row=row, column=0, sticky="ew", **p)
        self._qty.grid   (row=row, column=1, sticky="ew", **p)
        self._price.grid (row=row, column=2, sticky="ew", **p)
        self._curr.grid  (row=row, column=3, sticky="ew", **p)
        self._del.grid   (row=row, column=4, padx=(4, 6), pady=3)

    def regrid(self, row: int):
        self._row = row
        self._grid(row)

    def get_data(self) -> dict | None:
        ticker = self._ticker.get().strip().upper()
        if not ticker:
            return None
        try:
            qty   = float(self._qty.get().strip())
            price = float(self._price.get().strip())
        except ValueError:
            return None
        curr = self._curr.get().strip().upper() or "USD"
        return {"ticker": ticker, "quantity": qty,
                "avg_buy_price": price, "original_currency": curr}

    def destroy(self):
        for w in (self._ticker, self._qty, self._price, self._curr, self._del):
            w.destroy()


# ---------------------------------------------------------------------------
# Page 4 — Recommend new stocks?
# ---------------------------------------------------------------------------

class RecModePage(WizardPage):
    NAME = "recmode"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _label(self, "Suggest New Assets?",
               font=FONT_HEADING, anchor="center").grid(
               row=0, column=0, pady=(60, 20))

        center = ctk.CTkFrame(self, fg_color="transparent")
        center.grid(row=1, column=0)

        self._var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            center,
            text="Yes — recommend new assets to add to my portfolio",
            variable=self._var, font=FONT_BODY,
        ).pack(pady=8)

        _label(center,
               "If unchecked, the AI will only rebalance your existing positions.",
               font=FONT_SMALL, text_color=COLOR_MUTED, anchor="center").pack(pady=(4, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=24)
        footer.grid_columnconfigure(1, weight=1)
        _back_btn(footer, self.app).grid(row=0, column=0, sticky="w")
        _btn(footer, "Continue  →", command=self._continue, width=140).grid(
            row=0, column=2, sticky="e")

    def on_show(self):
        self._var.set(self.app.session.get("rec_new_stocks", False))

    def _continue(self):
        self.app.session["rec_new_stocks"] = self._var.get()
        self.app.goto("industries")


# ---------------------------------------------------------------------------
# Page 5 — Investment preferences (industries + countries)
# ---------------------------------------------------------------------------

def _pref_block(parent, label_text: str, hint: str) -> tuple:
    """
    Build a labelled text-input block with a 'Save as Default' button.
    Returns (textbox_widget, save_btn_widget).
    """
    block = ctk.CTkFrame(parent, fg_color=COLOR_PANEL, corner_radius=8)
    block.pack(fill="x", padx=0, pady=(0, 12))
    block.grid_columnconfigure(0, weight=1)

    # Header row: label + save button
    hdr = ctk.CTkFrame(block, fg_color="transparent")
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
    hdr.grid_columnconfigure(0, weight=1)

    _label(hdr, label_text, font=FONT_BODY).grid(row=0, column=0, sticky="w")

    save_btn = _btn(hdr, "💾 Save as Default", command=lambda: None,
                    width=150, fg_color=COLOR_ACCENT)
    save_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

    _label(block, hint, font=FONT_SMALL, text_color=COLOR_MUTED,
           wraplength=680).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 4))

    txt = ctk.CTkTextbox(block, font=FONT_BODY, height=72)
    txt.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))

    return txt, save_btn


class IndustriesPage(WizardPage):
    NAME = "industries"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _label(self, "Investment Preferences", font=FONT_HEADING).grid(
            row=0, column=0, sticky="w", padx=32, pady=(28, 8))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=32, pady=4)
        scroll.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(scroll, fg_color="transparent")
        inner.pack(fill="x")

        self._ind_txt, self._ind_save = _pref_block(
            inner,
            "Target Industries",
            "Sectors or industries you prefer, e.g. Technology, Healthcare, Renewable Energy "
            "(optional, treated as a soft preference).",
        )
        self._ind_save.configure(command=lambda: self._save_field(
            "industries", self._ind_txt, self._ind_save))

        self._ctr_txt, self._ctr_save = _pref_block(
            inner,
            "Target Countries",
            "Countries or regions you want exposure to, e.g. Sweden, USA, Europe "
            "(optional, treated as a soft preference).",
        )
        self._ctr_save.configure(command=lambda: self._save_field(
            "countries", self._ctr_txt, self._ctr_save))

        self._ast_txt, self._ast_save = _pref_block(
            inner,
            "Asset Types",
            "Types of assets you prefer, e.g. Stocks, ETF, Bonds, REITs "
            "(optional, treated as a soft preference).",
        )
        self._ast_save.configure(command=lambda: self._save_field(
            "asset_types", self._ast_txt, self._ast_save))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=14)
        footer.grid_columnconfigure(1, weight=1)
        _back_btn(footer, self.app).grid(row=0, column=0, sticky="w")
        _btn(footer, "Continue  →", command=self._continue, width=140).grid(
            row=0, column=2, sticky="e")

    def on_show(self):
        defaults = _load_defaults()
        for key, txt in [
            ("industries", self._ind_txt),
            ("countries", self._ctr_txt),
            ("asset_types", self._ast_txt),
        ]:
            txt.delete("1.0", "end")
            value = self.app.session.get(key)
            if value is None:
                value = defaults.get(key, "")
            txt.insert("1.0", value)

    def _save_field(self, key: str, txt: ctk.CTkTextbox, btn: ctk.CTkButton):
        text = txt.get("1.0", "end").strip()
        defaults = _load_defaults()
        defaults[key] = text
        _save_defaults(defaults)
        btn.configure(text="✓ Saved!", fg_color="#1a6b3a")
        self.after(1500, lambda: btn.configure(text="💾 Save as Default",
                                               fg_color=COLOR_ACCENT))

    def _continue(self):
        self.app.session["industries"]  = self._ind_txt.get("1.0", "end").strip()
        self.app.session["countries"]   = self._ctr_txt.get("1.0", "end").strip()
        self.app.session["asset_types"] = self._ast_txt.get("1.0", "end").strip()
        self.app.goto("riskprofile")


# ---------------------------------------------------------------------------
# Page 6 — Risk profile
# ---------------------------------------------------------------------------

RISK_PROFILES = ["Conservative", "Moderate", "Aggressive"]

RISK_DESCRIPTIONS = {
    "Conservative": "Focus on capital preservation. Prefer stable, dividend-paying stocks and bonds. Avoid high volatility.",
    "Moderate":     "Balanced approach. Accept some volatility in exchange for reasonable growth.",
    "Aggressive":   "Maximise growth. Accept high volatility and short-term losses for long-term gains.",
}


class RiskProfilePage(WizardPage):
    NAME = "riskprofile"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _label(self, "Risk Profile", font=FONT_HEADING).grid(
            row=0, column=0, sticky="w", padx=32, pady=(36, 8))

        inner = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=8)
        inner.grid(row=1, column=0, sticky="ew", padx=32, pady=4)
        inner.grid_columnconfigure(0, weight=1)

        self._var = ctk.StringVar(value="Moderate")

        for profile in RISK_PROFILES:
            row_frame = ctk.CTkFrame(inner, fg_color="transparent")
            row_frame.pack(fill="x", padx=16, pady=6)

            rb = ctk.CTkRadioButton(
                row_frame, text=profile,
                variable=self._var, value=profile,
                font=FONT_BODY,
                command=self._update_desc,
            )
            rb.pack(side="left")

        self._desc_lbl = _label(inner, RISK_DESCRIPTIONS["Moderate"],
                                font=FONT_SMALL, text_color=COLOR_MUTED,
                                anchor="w", wraplength=700)
        self._desc_lbl.pack(fill="x", padx=16, pady=(4, 16))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=14)
        footer.grid_columnconfigure(1, weight=1)
        _back_btn(footer, self.app).grid(row=0, column=0, sticky="w")
        _btn(footer, "Continue  →", command=self._continue, width=140).grid(
            row=0, column=2, sticky="e")

    def _update_desc(self):
        self._desc_lbl.configure(text=RISK_DESCRIPTIONS.get(self._var.get(), ""))

    def on_show(self):
        self._var.set(self.app.session.get("risk_profile", "Moderate"))
        self._update_desc()

    def _continue(self):
        self.app.session["risk_profile"] = self._var.get()
        self.app.goto("budget")


# ---------------------------------------------------------------------------
# Page 7 — Budget & currency
# ---------------------------------------------------------------------------

CURRENCIES = [
    "AED", "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP",
    "HKD", "HUF", "IDR", "ILS", "INR", "JPY", "KRW", "MXN", "MYR", "NOK",
    "NZD", "PHP", "PLN", "RON", "RUB", "SAR", "SEK", "SGD", "THB", "TRY",
    "TWD", "USD", "ZAR",
]


class BudgetPage(WizardPage):
    NAME = "budget"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _label(self, "Budget & Currency", font=FONT_HEADING).grid(
            row=0, column=0, sticky="w", padx=32, pady=(36, 8))

        inner = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=8)
        inner.grid(row=1, column=0, sticky="ew", padx=32, pady=4)
        inner.grid_columnconfigure(1, weight=1)

        _label(inner, "Base currency:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=16, pady=(20, 6))
        self._curr_var = ctk.StringVar(value="SEK")
        # CTkComboBox = dropdown list + free typing for unlisted currencies
        ctk.CTkComboBox(inner, values=CURRENCIES, variable=self._curr_var,
                        width=140, font=FONT_BODY).grid(
            row=0, column=1, sticky="w", padx=8, pady=(20, 6))

        _label(inner, "Additional cash budget:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=16, pady=6)
        self._budget_entry = ctk.CTkEntry(inner, width=160, font=FONT_BODY,
                                          placeholder_text="0")
        self._budget_entry.grid(row=1, column=1, sticky="w", padx=8, pady=6)

        _label(inner,
               "Enter 0 or leave blank to rebalance within existing holdings only.\n"
               "A positive amount makes cash available for new purchases.\n"
               "Currency: pick from the list or type any 3-letter ISO code (e.g. SGD, BDT).",
               font=FONT_SMALL, text_color=COLOR_MUTED,
               wraplength=560).grid(row=2, column=0, columnspan=2,
                                    sticky="w", padx=16, pady=(0, 16))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=14)
        footer.grid_columnconfigure(1, weight=1)
        _back_btn(footer, self.app).grid(row=0, column=0, sticky="w")
        _btn(footer, "Continue  →", command=self._continue, width=140).grid(
            row=0, column=2, sticky="e")

    def on_show(self):
        self._curr_var.set(self.app.session.get("base_currency", "SEK"))
        self._budget_entry.delete(0, "end")
        budget = self.app.session.get("budget", 0)
        if budget:
            self._budget_entry.insert(0, str(budget))

    def _continue(self):
        self.app.session["base_currency"] = self._curr_var.get()
        try:
            self.app.session["budget"] = float(self._budget_entry.get().strip() or "0")
        except ValueError:
            self.app.session["budget"] = 0.0
        self.app.goto("model")


# ---------------------------------------------------------------------------
# Page 8 — AI model selection
# ---------------------------------------------------------------------------

class ModelPage(WizardPage):
    NAME = "model"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _label(self, "Choose AI Model", font=FONT_HEADING).grid(
            row=0, column=0, sticky="w", padx=32, pady=(36, 8))

        inner = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=8)
        inner.grid(row=1, column=0, sticky="ew", padx=32, pady=4)
        inner.grid_columnconfigure(1, weight=1)

        _label(inner, "Gemini model:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=16, pady=(20, 8))

        self._model_var = ctk.StringVar(value="gemini-2.5-flash")
        ctk.CTkOptionMenu(inner, values=fe.AVAILABLE_MODELS,
                          variable=self._model_var,
                          width=220, font=FONT_BODY).grid(
            row=0, column=1, sticky="w", padx=8, pady=(20, 8))

        _label(inner, "gemini-2.5-flash is the recommended default — fast and capable.",
               font=FONT_SMALL, text_color=COLOR_MUTED).grid(
               row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 20))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=14)
        footer.grid_columnconfigure(1, weight=1)
        _back_btn(footer, self.app).grid(row=0, column=0, sticky="w")
        _btn(footer, "✨  Start Analysis", command=self._start,
             width=180, fg_color=COLOR_BRAND, hover_color="#c73050").grid(
             row=0, column=2, sticky="e")

    def on_show(self):
        self._model_var.set(self.app.session.get("model", "gemini-2.5-flash"))

    def _start(self):
        self.app.session["model"] = self._model_var.get()
        self.app.goto("result")


# ---------------------------------------------------------------------------
# Page 9 — Results
# ---------------------------------------------------------------------------

class ResultPage(WizardPage):
    NAME = "result"

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- Header ---
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 4))
        hdr.grid_columnconfigure(1, weight=1)
        _label(hdr, "AI Recommendation", font=FONT_HEADING).grid(row=0, column=0, sticky="w")
        self._status_lbl = _label(hdr, "", font=FONT_SMALL, text_color=COLOR_MUTED)
        self._status_lbl.grid(row=0, column=1, sticky="e", padx=8)

        # --- Recommendation textbox ---
        self._textbox = ctk.CTkTextbox(
            self, font=FONT_MONO, wrap="word",
            fg_color=COLOR_PANEL, corner_radius=8,
        )
        self._textbox.grid(row=1, column=0, sticky="nsew", padx=24, pady=4)
        self._textbox.configure(state="disabled")

        # --- Chat section ---
        chat_hdr = ctk.CTkFrame(self, fg_color="transparent")
        chat_hdr.grid(row=2, column=0, sticky="ew", padx=24, pady=(6, 2))
        _label(chat_hdr, "Discuss with AI", font=FONT_SMALL, text_color=COLOR_MUTED).pack(side="left")

        self._chat_box = ctk.CTkTextbox(
            self, font=FONT_BODY, wrap="word",
            fg_color=COLOR_PANEL, corner_radius=8,
            height=140,
        )
        self._chat_box.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 4))
        self._chat_box.configure(state="disabled")
        self._chat_box._textbox.tag_configure("user_lbl", foreground="#7eb8f7", font=("Segoe UI", 12, "bold"))
        self._chat_box._textbox.tag_configure("user_txt", foreground="#cce0ff")
        self._chat_box._textbox.tag_configure("ai_lbl",   foreground="#a8e6a3", font=("Segoe UI", 12, "bold"))
        self._chat_box._textbox.tag_configure("ai_txt",   foreground="#eaeaea")

        chat_input = ctk.CTkFrame(self, fg_color="transparent")
        chat_input.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 4))
        chat_input.grid_columnconfigure(0, weight=1)

        self._chat_entry = ctk.CTkEntry(
            chat_input,
            placeholder_text="Ask about the recommendations… e.g. 'I'd rather keep AAPL, what else could I sell?'",
            font=FONT_BODY, height=36,
        )
        self._chat_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._chat_entry.bind("<Return>", lambda _: self._send_chat())
        self._chat_entry.configure(state="disabled")

        self._send_btn = _btn(chat_input, "Send", command=self._send_chat, width=80, state="disabled")
        self._send_btn.grid(row=0, column=1)

        # --- Footer ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=24, pady=14)

        self._save_btn = _btn(footer, "💾  Save", command=self._save,
                               width=110, state="disabled")
        self._save_btn.pack(side="left", padx=(0, 8))

        self._rethink_btn = _btn(footer, "🔄  Rethink", command=self._rethink,
                                  width=120, state="disabled")
        self._rethink_btn.pack(side="left", padx=(0, 8))

        _btn(footer, "↺  Restart", command=self.app.restart,
             width=110, fg_color="#3a2020", hover_color="#5a3030").pack(side="right")

        # Internal chat state
        self._situation_report: str = ""
        self._initial_recommendation: str = ""
        self._chat_history: list[dict] = []

    def on_show(self):
        self._set_text("")
        self._status_lbl.configure(text="Fetching live prices…")
        self._save_btn.configure(state="disabled")
        self._rethink_btn.configure(state="disabled")
        self._clear_chat()
        threading.Thread(target=self._run_analysis, daemon=True).start()

    def on_reset(self):
        self._set_text("")
        self._status_lbl.configure(text="")
        self._clear_chat()

    # ------------------------------------------------------------------
    # Analysis pipeline
    # ------------------------------------------------------------------

    def _run_analysis(self):
        s = self.app.session
        positions    = s.get("positions", [])
        base_cur     = s.get("base_currency", "SEK")
        industries   = s.get("industries", "")
        countries    = s.get("countries", "")
        asset_types  = s.get("asset_types", "")
        risk_profile = s.get("risk_profile", "Moderate")
        budget       = s.get("budget", 0.0)
        rec_new      = s.get("rec_new_stocks", False)
        model        = s.get("model", "gemini-2.5-flash")

        self.after(0, lambda: self._status_lbl.configure(text="Fetching live prices…"))
        try:
            enriched = fe.enrich_portfolio(positions, base_cur) if positions else []
        except Exception as exc:
            self.after(0, lambda: self._show_error(f"Price fetch error: {exc}"))
            return

        self._situation_report = fe.build_situation_report(
            enriched_portfolio=enriched,
            industries=industries,
            budget=budget,
            base_currency=base_cur,
            countries=countries,
            asset_types=asset_types,
            risk_profile=risk_profile,
        )

        self.after(0, lambda: self._status_lbl.configure(text="Asking AI…"))
        result = fe.get_optimizer_recommendation(
            enriched_portfolio=enriched,
            industries=industries,
            countries=countries,
            asset_types=asset_types,
            risk_profile=risk_profile,
            budget=budget,
            base_currency=base_cur,
            rec_new_stocks=rec_new,
            preferred_model=model,
        )
        self.after(0, lambda: self._show_result(result))

    def _show_result(self, text: str):
        self._set_text(text)
        self._initial_recommendation = text
        self._status_lbl.configure(text="Done.")
        self._save_btn.configure(state="normal")
        self._rethink_btn.configure(state="normal")
        self._chat_entry.configure(state="normal")
        self._send_btn.configure(state="normal")
        self._append_chat_msg("ai", "Analysis complete. Ask me anything about the recommendations above.")

    def _show_error(self, msg: str):
        self._set_text(f"Error:\n\n{msg}")
        self._status_lbl.configure(text="Failed.")
        self._rethink_btn.configure(state="normal")

    def _set_text(self, text: str):
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        if text:
            self._textbox.insert("1.0", text)
        self._textbox.configure(state="disabled")

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------

    def _clear_chat(self):
        self._chat_history = []
        self._initial_recommendation = ""
        self._situation_report = ""
        self._chat_box.configure(state="normal")
        self._chat_box.delete("1.0", "end")
        self._chat_box.configure(state="disabled")
        self._chat_entry.configure(state="disabled")
        self._send_btn.configure(state="disabled")

    def _append_chat_msg(self, role: str, text: str):
        self._chat_box.configure(state="normal")
        existing = self._chat_box._textbox.get("1.0", "end-1c")
        if existing:
            self._chat_box._textbox.insert("end", "\n")
        if role == "user":
            self._chat_box._textbox.insert("end", "You\n", "user_lbl")
            self._chat_box._textbox.insert("end", text + "\n", "user_txt")
        else:
            self._chat_box._textbox.insert("end", "AI\n", "ai_lbl")
            self._chat_box._textbox.insert("end", text + "\n", "ai_txt")
        self._chat_box.configure(state="disabled")
        self._chat_box._textbox.see("end")

    def _send_chat(self):
        msg = self._chat_entry.get().strip()
        if not msg or not self._situation_report:
            return
        model = self.app.session.get("model", "gemini-2.5-flash")
        self._chat_entry.delete(0, "end")
        self._chat_entry.configure(state="disabled")
        self._send_btn.configure(state="disabled")
        self._append_chat_msg("user", msg)
        threading.Thread(target=self._run_chat, args=(msg, model), daemon=True).start()

    def _run_chat(self, user_message: str, model: str):
        reply = fe.chat_about_recommendation(
            situation_report=self._situation_report,
            initial_recommendation=self._initial_recommendation,
            chat_history=self._chat_history,
            user_message=user_message,
            preferred_model=model,
        )
        self._chat_history.append({"role": "user", "text": user_message})
        self._chat_history.append({"role": "model", "text": reply})
        self.after(0, lambda: self._on_chat_reply(reply))

    def _on_chat_reply(self, reply: str):
        self._append_chat_msg("ai", reply)
        self._chat_entry.configure(state="normal")
        self._send_btn.configure(state="normal")
        self._chat_entry.focus()

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _save(self):
        text = self._textbox.get("1.0", "end").strip()
        if not text:
            return
        os.makedirs("reports", exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        path = os.path.join("reports", f"{date_str}.txt")
        n = 1
        while os.path.exists(path):
            path = os.path.join("reports", f"{date_str} ({n}).txt")
            n += 1
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("Saved", f"Report saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _rethink(self):
        self._save_btn.configure(state="disabled")
        self._rethink_btn.configure(state="disabled")
        self._set_text("")
        self._status_lbl.configure(text="Retrying…")
        self._clear_chat()
        threading.Thread(target=self._run_analysis, daemon=True).start()


# ---------------------------------------------------------------------------
# Helper — loading dialog shown during image scan
# ---------------------------------------------------------------------------

class _ProgressDialog(ctk.CTkToplevel):
    def __init__(self, parent, message: str):
        super().__init__(parent)
        self.title("")
        self.geometry("300x100")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=COLOR_PANEL)
        ctk.CTkLabel(self, text=message, font=FONT_BODY).pack(
            expand=True, fill="both", padx=20, pady=20)
        self.update()

    def close(self):
        self.grab_release()
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("AI Portfolio Optimizer starting…", flush=True)
    app = App()
    app.mainloop()
    print("AI Portfolio Optimizer closed.", flush=True)
