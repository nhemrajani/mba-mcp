from mba_mcp import presets


def test_both_tracks_ship_a_pack():
    assert set(presets.available_packs()) == {"consulting", "investment_banking"}


def test_packs_are_well_formed():
    for name in presets.available_packs():
        pack = presets.load_pack(name)
        assert pack["companies"] and pack["note"]
        for company in pack["companies"]:
            assert company["name"] and company["careers_url"].startswith("https://")
            assert 1 <= int(company.get("priority", 2)) <= 3
            # A pre-resolved board must carry both halves or neither.
            assert bool(company.get("ats")) == bool(company.get("slug"))


def test_pack_lookup_accepts_track_aliases():
    assert presets.load_pack("finance")["pack"] == "investment_banking"
    assert presets.load_pack("MBB")["pack"] == "consulting"


def test_unknown_pack_lists_options():
    try:
        presets.load_pack("crypto")
    except presets.UnknownPack as exc:
        assert "consulting" in str(exc)
    else:
        raise AssertionError("expected UnknownPack")


def test_describe_packs_counts_companies():
    described = {pack["pack"]: pack for pack in presets.describe_packs()}
    assert described["investment_banking"]["companies"] >= 10
    assert described["consulting"]["label"]
