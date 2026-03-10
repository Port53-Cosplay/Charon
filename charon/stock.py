"""Stock price lookup for company financial health signals."""

from dataclasses import dataclass
from typing import Any


@dataclass
class StockData:
    """Stock price data for a company."""
    ticker: str
    company_name: str
    current_price: float
    currency: str
    week_52_high: float
    week_52_low: float
    change_6m_pct: float | None
    change_1y_pct: float | None
    market_cap: float | None
    sector: str

    @property
    def off_high_pct(self) -> float:
        """How far below the 52-week high (as a negative percentage)."""
        if self.week_52_high == 0:
            return 0.0
        return round(((self.current_price - self.week_52_high) / self.week_52_high) * 100, 1)

    def to_prompt_text(self) -> str:
        """Format stock data as text for injection into AI prompts."""
        lines = [
            f"Stock Ticker: {self.ticker}",
            f"Current Price: {self.currency}{self.current_price:.2f}",
            f"52-Week High: {self.currency}{self.week_52_high:.2f}",
            f"52-Week Low: {self.currency}{self.week_52_low:.2f}",
            f"Off 52-Week High: {self.off_high_pct:+.1f}%",
        ]
        if self.change_6m_pct is not None:
            lines.append(f"6-Month Change: {self.change_6m_pct:+.1f}%")
        if self.change_1y_pct is not None:
            lines.append(f"1-Year Change: {self.change_1y_pct:+.1f}%")
        if self.market_cap:
            if self.market_cap >= 1e12:
                cap_str = f"${self.market_cap / 1e12:.1f}T"
            elif self.market_cap >= 1e9:
                cap_str = f"${self.market_cap / 1e9:.1f}B"
            else:
                cap_str = f"${self.market_cap / 1e6:.0f}M"
            lines.append(f"Market Cap: {cap_str}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "current_price": self.current_price,
            "currency": self.currency,
            "week_52_high": self.week_52_high,
            "week_52_low": self.week_52_low,
            "off_high_pct": self.off_high_pct,
            "change_6m_pct": self.change_6m_pct,
            "change_1y_pct": self.change_1y_pct,
            "market_cap": self.market_cap,
            "sector": self.sector,
        }


def lookup_stock(company_name: str) -> StockData | None:
    """Look up stock data for a company. Returns None if not found or private."""
    try:
        import yfinance as yf
    except ImportError:
        return None

    # Search for the ticker
    try:
        search = yf.Search(company_name, max_results=5)
        quotes = search.quotes if hasattr(search, 'quotes') else []
    except Exception:
        return None

    if not quotes:
        return None

    # Find the best match (prefer equity types)
    ticker_symbol = None
    for quote in quotes:
        qtype = quote.get("quoteType", "")
        if qtype == "EQUITY":
            ticker_symbol = quote.get("symbol")
            break
    if not ticker_symbol and quotes:
        ticker_symbol = quotes[0].get("symbol")

    if not ticker_symbol:
        return None

    # Fetch the stock data
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        if not info or "currentPrice" not in info:
            # Try regularMarketPrice as fallback
            price = info.get("regularMarketPrice")
            if not price:
                return None
        else:
            price = info["currentPrice"]

        # Get historical data for change calculations
        change_6m = None
        change_1y = None
        try:
            hist = ticker.history(period="1y")
            if len(hist) > 0:
                current = hist["Close"].iloc[-1]
                if len(hist) >= 126:  # ~6 months of trading days
                    price_6m_ago = hist["Close"].iloc[-126]
                    change_6m = round(((current - price_6m_ago) / price_6m_ago) * 100, 1)
                if len(hist) >= 252:  # ~1 year of trading days
                    price_1y_ago = hist["Close"].iloc[0]
                    change_1y = round(((current - price_1y_ago) / price_1y_ago) * 100, 1)
        except Exception:
            pass

        return StockData(
            ticker=ticker_symbol,
            company_name=info.get("shortName", company_name),
            current_price=float(price),
            currency="$" if info.get("currency", "USD") == "USD" else info.get("currency", "") + " ",
            week_52_high=float(info.get("fiftyTwoWeekHigh", 0)),
            week_52_low=float(info.get("fiftyTwoWeekLow", 0)),
            change_6m_pct=change_6m,
            change_1y_pct=change_1y,
            market_cap=info.get("marketCap"),
            sector=info.get("sector", "Unknown"),
        )

    except Exception:
        return None
