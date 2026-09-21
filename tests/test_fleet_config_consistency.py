"""The fleet is described in four places; they must agree and none may point at a retired host.

- rustchain_monitor.DEFAULT_MULTI_NODE_TARGETS (source of truth)
- nodes.example.json
- dashboard/index.html (NODES array, hand-maintained JavaScript)
- README.md / dashboard/README.md prose
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor  # noqa: E402

DASHBOARD_HTML = (ROOT / "dashboard" / "index.html").read_text()
README = (ROOT / "README.md").read_text()
DASHBOARD_README = (ROOT / "dashboard" / "README.md").read_text()
RETIRED_HOST = "38.76.217.189"


def _dashboard_nodes() -> list[dict]:
    """Parse the NODES array literal in dashboard/index.html without a JS engine."""
    match = re.search(r"const NODES = \[(.*?)\n\];", DASHBOARD_HTML, re.S)
    assert match, "dashboard/index.html must define `const NODES = [...]`"
    nodes = []
    for block in re.findall(r"\{(.*?)\n  \}", match.group(1), re.S):
        fields = dict(re.findall(r"^\s*(\w+):\s*(.+?),\s*$", block, re.M))
        nodes.append(
            {
                "id": fields["id"].strip("'\""),
                "url": fields["url"].strip("'\""),
                "enabled": fields.get("enabled", "true").strip() != "false",
            }
        )
    assert nodes, "could not parse any node entries from dashboard/index.html"
    return nodes


def test_dashboard_node_list_matches_python_defaults():
    dashboard = [(n["id"], n["url"], n["enabled"]) for n in _dashboard_nodes()]
    defaults = [(t["node_id"], t["url"], t["enabled"]) for t in rustchain_monitor.default_multi_node_targets()]
    assert dashboard == defaults


def test_dashboard_derives_probe_urls_from_node_url():
    for node in _dashboard_nodes():
        assert f"healthUrl: '{node['url']}/health'" in DASHBOARD_HTML
        assert f"epochUrl: '{node['url']}/epoch'" in DASHBOARD_HTML
        assert f"minersUrl: '{node['url']}/api/miners'" in DASHBOARD_HTML


def test_no_target_points_at_the_retired_node4_host():
    """The host answers 200 HTML on every path; anything probing it would report it healthy forever."""
    assert not any(RETIRED_HOST in n["url"] for n in _dashboard_nodes())
    assert not any(RETIRED_HOST in t["url"] for t in rustchain_monitor.default_multi_node_targets())
    assert not any(RETIRED_HOST in t["url"] for t in rustchain_monitor.load_node_targets(ROOT / "nodes.example.json"))
    assert not re.search(rf"https?://{re.escape(RETIRED_HOST)}(?![^\n]*retired)", DASHBOARD_HTML)


def test_dashboard_validates_body_not_just_status():
    assert "non-JSON 200 (possible hijacked/parked host)" in DASHBOARD_HTML
    assert "isJsonContentType" in DASHBOARD_HTML
    assert "enabled === false" in DASHBOARD_HTML  # disabled nodes are not probed


def test_docs_state_the_real_node_count():
    live = [t for t in rustchain_monitor.default_multi_node_targets() if t["enabled"]]
    assert len(live) == 2
    assert "two live attestation nodes" in README
    assert "two live nodes" in DASHBOARD_README
    for stale_phrase in ("all 3 RustChain", "Active Nodes: 3", "Attestation:     3 nodes", "3-node fleet", "all 3 nodes"):
        assert stale_phrase not in README, stale_phrase
        assert stale_phrase not in DASHBOARD_README, stale_phrase
