import importlib.util
import sys
from pathlib import Path

import yaml

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "render_site_yml.py"
_spec = importlib.util.spec_from_file_location("render_site_yml", _MODULE_PATH)
render_site_yml = importlib.util.module_from_spec(_spec)
sys.modules["render_site_yml"] = render_site_yml
_spec.loader.exec_module(render_site_yml)


def test_render_common_uses_hosts_all():
    plays = yaml.safe_load(render_site_yml.render(["common", "display", "gpio"]))

    assert [p["hosts"] for p in plays] == ["all", "display", "gpio"]
    assert [p["roles"] for p in plays] == [["common"], ["display"], ["gpio"]]
    assert all(p["become"] is True for p in plays)


def test_render_preserves_order():
    plays = yaml.safe_load(render_site_yml.render(["gpio", "display"]))

    assert [p["hosts"] for p in plays] == ["gpio", "display"]


def test_render_empty_order_produces_empty_playbook():
    plays = yaml.safe_load(render_site_yml.render([]))

    assert plays == []


def test_load_order_missing_file_returns_empty_list(tmp_path):
    assert render_site_yml.load_order(tmp_path / "does-not-exist.yaml") == []


def test_render_to_file_writes_valid_yaml(tmp_path):
    site_path = tmp_path / "site.yml"

    render_site_yml.render_to_file(["common", "kiosk"], site_path)

    plays = yaml.safe_load(site_path.read_text())
    assert len(plays) == 2
    assert plays[1]["hosts"] == "kiosk"
