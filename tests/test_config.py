from pathlib import Path

from scholarship_agent.profiles import load_profiles, load_settings, load_sources

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_configuration_describes_both_people():
    root, settings = load_settings(ROOT / "config" / "settings.yaml")
    profiles = load_profiles(ROOT / "config")
    sources = load_sources(ROOT / "config")
    by_id = {profile.id: profile for profile in profiles}

    assert root == ROOT
    assert settings.database_path == ROOT / "data" / "opportunities.db"
    assert by_id["me"].degree_levels == ["phd"]
    assert by_id["me"].department == ""
    assert by_id["me"].disciplines == []
    assert by_id["sister"].degree_levels == ["masters"]
    assert by_id["sister"].department == ""
    assert "scholarship" in by_id["sister"].opportunity_types
    assert any(source.id == "euraxess" and source.enabled for source in sources)
    assert any(source.id == "euraxess_pages" and source.type == "euraxess_search" for source in sources)
    assert any(source.id == "opportunity_desk" and not source.enabled for source in sources)
