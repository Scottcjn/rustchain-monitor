import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor


def test_parse_listen_address_accepts_explicit_and_default_hosts():
    assert rustchain_monitor.parse_listen_address("127.0.0.1:9090") == ("127.0.0.1", 9090)
    assert rustchain_monitor.parse_listen_address(":8080") == ("0.0.0.0", 8080)


def test_parse_listen_address_preserves_colon_rich_hosts():
    assert rustchain_monitor.parse_listen_address("::1:9090") == ("::1", 9090)


@pytest.mark.parametrize("listen", ["localhost", "localhost:", ":"])
def test_parse_listen_address_rejects_missing_port(listen):
    with pytest.raises(ValueError, match="host:port"):
        rustchain_monitor.parse_listen_address(listen)


@pytest.mark.parametrize("listen", ["localhost:0", "localhost:65536"])
def test_parse_listen_address_rejects_out_of_range_ports(listen):
    with pytest.raises(ValueError, match="between 1 and 65535"):
        rustchain_monitor.parse_listen_address(listen)


def test_parse_listen_address_rejects_non_numeric_port():
    with pytest.raises(ValueError):
        rustchain_monitor.parse_listen_address("localhost:http")
