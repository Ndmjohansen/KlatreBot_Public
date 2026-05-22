from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_memory_systemd_units_use_production_env_and_timer_cadence():
    service = (ROOT / "klatrebot-memory.service").read_text(encoding="utf-8")
    timer = (ROOT / "klatrebot-memory.timer").read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/klatrebot/klatrebot.env" in service
    assert "poetry run python3 -m klatrebot_v2.memory compile-rolling" in service
    assert "ReadWritePaths=@PROJECT_DIR@ @DATA_DIR@" in service
    assert "OnBootSec=10min" in timer
    assert "OnUnitActiveSec=120min" in timer
    assert "Persistent=true" in timer


def test_install_and_ci_deploy_memory_systemd_units():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    assert "klatrebot-memory.service" in install
    assert "klatrebot-memory.timer" in install
    assert "systemctl enable --now klatrebot-memory.timer" in install
    assert "USER_ALIASES_CONFIG_PATH=" in install
    assert "klatrebot-memory.service" in workflow
    assert "klatrebot-memory.timer" in workflow
    assert "systemctl enable --now klatrebot-memory.timer" in workflow
    assert "USER_ALIASES_CONFIG_PATH=${{ secrets.USER_ALIASES_CONFIG_PATH }}" in workflow
