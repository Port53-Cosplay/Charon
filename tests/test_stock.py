"""Tests for stock data lookup and formatting."""

import pytest

from charon.stock import StockData


class TestStockData:
    def _make_stock(self, **overrides):
        defaults = {
            "ticker": "CRWD",
            "company_name": "CrowdStrike Holdings",
            "current_price": 300.0,
            "currency": "$",
            "week_52_high": 400.0,
            "week_52_low": 200.0,
            "change_6m_pct": -15.0,
            "change_1y_pct": 10.0,
            "market_cap": 72e9,
            "sector": "Technology",
        }
        defaults.update(overrides)
        return StockData(**defaults)

    def test_off_high_pct(self):
        stock = self._make_stock(current_price=300.0, week_52_high=400.0)
        assert stock.off_high_pct == -25.0

    def test_off_high_at_high(self):
        stock = self._make_stock(current_price=400.0, week_52_high=400.0)
        assert stock.off_high_pct == 0.0

    def test_off_high_zero_high(self):
        stock = self._make_stock(current_price=100.0, week_52_high=0.0)
        assert stock.off_high_pct == 0.0

    def test_to_prompt_text_contains_key_data(self):
        stock = self._make_stock()
        text = stock.to_prompt_text()
        assert "CRWD" in text
        assert "300.00" in text
        assert "400.00" in text
        assert "-15.0%" in text
        assert "$72.0B" in text

    def test_to_prompt_text_trillion(self):
        stock = self._make_stock(market_cap=2.5e12)
        text = stock.to_prompt_text()
        assert "$2.5T" in text

    def test_to_prompt_text_million(self):
        stock = self._make_stock(market_cap=500e6)
        text = stock.to_prompt_text()
        assert "$500M" in text

    def test_to_prompt_text_no_changes(self):
        stock = self._make_stock(change_6m_pct=None, change_1y_pct=None)
        text = stock.to_prompt_text()
        assert "6-Month" not in text
        assert "1-Year" not in text

    def test_to_dict(self):
        stock = self._make_stock()
        d = stock.to_dict()
        assert d["ticker"] == "CRWD"
        assert d["off_high_pct"] == -25.0
        assert isinstance(d, dict)


class TestLookupStock:
    def test_nonexistent_company_returns_none(self):
        from charon.stock import lookup_stock
        result = lookup_stock("ZZZZXXXXXNOTAREALCOMPANY99999")
        assert result is None
