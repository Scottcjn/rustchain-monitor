"""Regression tests for #68: a successful canonical balance must not read as 0.

The live node's ``GET /wallet/balance?miner_id=`` returns the canonical
``amount_rtc`` (alongside ``amount_i64``) and does **not** include the legacy
``balance_rtc`` key, e.g.::

    {"amount_i64": 21000000, "amount_rtc": 21.0, "miner_id": "stmr"}

``get_miner_balance`` used to read only ``balance_rtc`` and default to ``0.0``,
so a valid HTTP 200 with a nonzero balance silently became ``0.0`` — which then
flowed into the miner snapshot and history argument. These tests pin the fix:
decode the canonical ``amount_rtc`` first, keep the legacy alias as a fallback,
and keep a real zero / absent balance at ``0.0``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rustchain_monitor import RustChainMonitor  # noqa: E402

# Real shape captured from https://50.28.86.131/wallet/balance?miner_id=stmr
REAL_CANONICAL = '{"amount_i64":21000000,"amount_rtc":21.0,"miner_id":"stmr"}'


class FakeResponse:
    def __init__(self, body: str, *, status_code: int = 200, content_type: str = "application/json"):
        self.text = body
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}


def _install(monkeypatch, body: str):
    def fake_get(self, url, **kwargs):
        return FakeResponse(body)

    monkeypatch.setattr("requests.Session.get", fake_get)


def test_canonical_amount_rtc_is_decoded(monkeypatch):
    _install(monkeypatch, REAL_CANONICAL)
    assert RustChainMonitor("https://n1").get_miner_balance("stmr") == 21.0


def test_legacy_balance_rtc_alias_still_works(monkeypatch):
    _install(monkeypatch, '{"balance_rtc":12.5,"miner_id":"stmr"}')
    assert RustChainMonitor("https://n1").get_miner_balance("stmr") == 12.5


def test_genuine_zero_stays_zero(monkeypatch):
    _install(monkeypatch, '{"amount_i64":0,"amount_rtc":0.0,"miner_id":"stmr"}')
    assert RustChainMonitor("https://n1").get_miner_balance("stmr") == 0.0


def test_absent_balance_defaults_to_zero(monkeypatch):
    _install(monkeypatch, '{"miner_id":"stmr"}')
    assert RustChainMonitor("https://n1").get_miner_balance("stmr") == 0.0


def test_snapshot_and_history_receive_nonzero_balance(monkeypatch):
    """The canonical value must survive into the snapshot used for history."""
    payloads = {
        "/epoch": '{"epoch":292,"epoch_pot":1.5,"enrolled_miners":1}',
        "/api/miners": '{"miners":[{"miner":"stmr","device_arch":"g4"}]}',
        "/wallet/balance?miner_id=stmr": REAL_CANONICAL,
    }

    def fake_get(self, url, **kwargs):
        for path, body in payloads.items():
            if url.endswith(path):
                return FakeResponse(body)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("requests.Session.get", fake_get)
    snapshot = RustChainMonitor("https://n1").get_miner_snapshot("stmr")
    assert snapshot["balance_rtc"] == 21.0
