from app import redflags as rf
from app import risk


def test_model_alone_can_raise_the_alarm():
    assert risk.fuse(88, 0, set())["level"] == "SCAM"


def test_rules_alone_cannot_raise_the_alarm():
    out = risk.fuse(5, 0, {rf.AUTHORITY, rf.OTP_REQUEST, rf.URGENCY})
    assert not out["combo"]
    assert out["level"] != "SCAM"


def test_combo_sets_floor_when_model_concurs():
    out = risk.fuse(45, 0, {rf.ARREST_THREAT, rf.MONEY_REQUEST})
    assert out["combo"] and out["risk"] >= risk.COMBO_FLOOR and out["level"] == "SCAM"


def test_risk_is_sticky_across_a_quiet_chunk():
    out = risk.fuse(10, 90, set())
    assert out["model_risk"] == 90 - risk.DECAY
    assert out["level"] == "SCAM"


def test_bounds():
    assert risk.fuse(100, 100, set(rf.CODES))["risk"] == 100
    assert risk.fuse(0, 0, set())["risk"] == 0


def test_rule_combo_alone_still_reaches_caution():
    # A caller who talks the model down ("this call is safe") can't silence a pretext + extraction combo entirely.
    out = risk.fuse(0, 0, {rf.AUTHORITY, rf.OTP_REQUEST})
    assert not out["combo"] and out["level"] == "CAUTION"
