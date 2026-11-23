"""Shared test setup: saved SEC data, and no real network calls."""

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

# A placeholder, so tests never read anyone's real contact details
os.environ["SEC_USER_AGENT"] = "test-suite test@example.com"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def company():
    """Load saved SEC data for a ticker, e.g. company("AMZN")."""
    def load(ticker):
        return json.loads((FIXTURES / f"{ticker}.json").read_text())
    return load


class FakeResponse:
    """Stands in for a requests response."""

    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.body = body

    def json(self):
        if self.body is None:
            raise ValueError("not JSON")
        return self.body
