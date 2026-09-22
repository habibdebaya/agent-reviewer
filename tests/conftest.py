import pytest


@pytest.fixture(autouse=True)
def offline_tests(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
