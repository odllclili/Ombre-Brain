from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "frontend" / "dashboard.html"


def test_desire_dashboard_is_reachable_from_the_main_navigation() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")

    assert 'data-tab="desire"' in html
    assert 'id="desire-view"' in html
    assert "target === 'desire'" in html


def test_desire_dashboard_reads_the_authenticated_read_only_state_route() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")

    assert "authFetch('/api/desire/state')" in html
    assert "async function loadDesireState" in html
    assert 'id="desire-drive-grid"' in html
    assert 'id="desire-gates"' in html
    assert 'id="desire-thoughts"' in html
