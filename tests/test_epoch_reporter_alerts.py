import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import epoch_reporter


def test_update_health_state_alerts_problem_and_recovery():
    state = epoch_reporter.default_state()

    problem_messages = epoch_reporter.update_health_state(
        state,
        {
            "ok": True,
            "db_rw": False,
            "tip_age_slots": 250,
            "backup_age_hours": 7.5,
            "version": "2.2.1-rip200",
        },
        node_url="https://node.example",
        tip_age_max=100,
        backup_age_max_hours=6.0,
    )
    recovery_messages = epoch_reporter.update_health_state(
        state,
        {
            "ok": True,
            "db_rw": True,
            "tip_age_slots": 0,
            "backup_age_hours": 1.0,
            "version": "2.2.1-rip200",
        },
        node_url="https://node.example",
        tip_age_max=100,
        backup_age_max_hours=6.0,
    )

    assert len(problem_messages) == 1
    assert "Network health alert" in problem_messages[0]
    assert "tip age 250 slots exceeds 100" in problem_messages[0]
    assert recovery_messages == ["Network health recovered\nNode: https://node.example\nVersion: 2.2.1-rip200"]


def test_update_miner_tracking_alerts_offline_and_recovery():
    state = epoch_reporter.default_state()

    first_messages = epoch_reporter.update_miner_tracking(
        state,
        [{"miner": "miner-a", "device_arch": "g4", "last_attest": 1000}],
        offline_polls=2,
    )
    second_messages = epoch_reporter.update_miner_tracking(state, [], offline_polls=2)
    third_messages = epoch_reporter.update_miner_tracking(state, [], offline_polls=2)
    recovery_messages = epoch_reporter.update_miner_tracking(
        state,
        [{"miner": "miner-a", "device_arch": "g4", "last_attest": 1060}],
        offline_polls=2,
    )

    assert first_messages == []
    assert second_messages == []
    assert len(third_messages) == 1
    assert "Miner offline alert" in third_messages[0]
    assert "Missed polls: 2" in third_messages[0]
    assert len(recovery_messages) == 1
    assert "Miner recovery alert" in recovery_messages[0]


def test_check_reward_alert_thresholds_and_deduping():
    state = epoch_reporter.default_state()
    epoch_data = {"epoch": 99, "epoch_pot": 2.5}

    first = epoch_reporter.check_reward_alert(state, epoch_data, reward_min=1.0, reward_max=2.0)
    duplicate = epoch_reporter.check_reward_alert(state, epoch_data, reward_min=1.0, reward_max=2.0)
    okay = epoch_reporter.check_reward_alert(state, {"epoch": 100, "epoch_pot": 1.5}, reward_min=1.0, reward_max=2.0)

    assert "Unexpected reward alert" in first
    assert duplicate is None
    assert okay is None


def test_run_once_posts_epoch_summary_and_alerts(monkeypatch):
    sent_messages = []
    moltbook_posts = []

    monkeypatch.setattr(
        epoch_reporter,
        "fetch_health",
        lambda node_url: {
            "ok": True,
            "db_rw": True,
            "tip_age_slots": 0,
            "backup_age_hours": 1.0,
            "version": "2.2.1-rip200",
        },
    )
    monkeypatch.setattr(
        epoch_reporter,
        "fetch_epoch",
        lambda node_url: {"epoch": 123, "epoch_pot": 1.5, "enrolled_miners": 2},
    )
    monkeypatch.setattr(
        epoch_reporter,
        "fetch_miners",
        lambda node_url: [
            {"miner": "miner-a", "device_arch": "g4", "last_attest": 1000},
            {"miner": "miner-b", "device_arch": "modern", "last_attest": 1001},
        ],
    )
    monkeypatch.setattr(
        epoch_reporter,
        "notify_channels",
        lambda message, **kwargs: sent_messages.append(message) or True,
    )
    monkeypatch.setattr(
        epoch_reporter,
        "post_to_moltbook",
        lambda api_key, api_url, message: moltbook_posts.append((api_key, api_url, message)) or True,
    )

    state = epoch_reporter.run_once(
        "https://node.example",
        epoch_reporter.default_state(),
        discord_webhook="discord",
        slack_webhook="slack",
        telegram_token="token",
        telegram_chat_id="chat",
        moltbook_key="moltbook-key",
        moltbook_url="https://moltbook.example/api/v1",
        reward_min=1.0,
        reward_max=2.0,
    )

    assert state["last_epoch"] == 123
    assert state["last_posted"] is not None
    assert len(sent_messages) == 1
    assert "Epoch 123 settled" in sent_messages[0]
    assert len(moltbook_posts) == 1
