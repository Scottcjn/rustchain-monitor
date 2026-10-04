import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import epoch_reporter


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"epoch": 1}


@pytest.fixture
def captured_get(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse()

    monkeypatch.setattr(epoch_reporter.requests, "get", fake_get)
    return calls


def test_default_node_is_domain_not_bare_ip():
    assert epoch_reporter.DEFAULT_NODE == "https://rustchain.org"


def test_fetch_verifies_tls_by_default(monkeypatch, captured_get):
    monkeypatch.delenv(epoch_reporter.INSECURE_TLS_ENV, raising=False)
    assert epoch_reporter.fetch_epoch("https://node.example") == {"epoch": 1}
    url, kwargs = captured_get[0]
    assert url == "https://node.example/epoch"
    assert kwargs["verify"] is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "garbage"])
def test_non_truthy_opt_out_values_keep_verification_on(monkeypatch, captured_get, value):
    monkeypatch.setenv(epoch_reporter.INSECURE_TLS_ENV, value)
    epoch_reporter.fetch_health("https://node.example")
    assert captured_get[0][1]["verify"] is True


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_explicit_opt_out_disables_verification(monkeypatch, captured_get, value):
    monkeypatch.setenv(epoch_reporter.INSECURE_TLS_ENV, value)
    epoch_reporter.fetch_miners("https://10.0.0.5")
    assert captured_get[0][1]["verify"] is False


def test_tls_failure_returns_none_instead_of_trusting_response(monkeypatch, capsys):
    monkeypatch.delenv(epoch_reporter.INSECURE_TLS_ENV, raising=False)

    def fake_get(url, **kwargs):
        raise requests.exceptions.SSLError("certificate verify failed")

    monkeypatch.setattr(epoch_reporter.requests, "get", fake_get)
    assert epoch_reporter.fetch_epoch("https://node.example") is None
    assert "certificate verify failed" in capsys.readouterr().err


def test_module_does_not_silence_insecure_request_warnings():
    source = Path(epoch_reporter.__file__).read_text()
    assert "disable_warnings" not in source
    assert "verify=False" not in source
