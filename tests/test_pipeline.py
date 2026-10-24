from app import pipeline


def verdict(**kw):
    base = {"transcript": "", "english": "", "flags": [], "scam_probability": 0}
    return {**base, **kw}


def test_rules_add_flags_gemini_missed_and_label_the_source():
    v = verdict(
        english="Install AnyDesk and do not tell anyone",
        flags=[{"code": "REMOTE_ACCESS", "evidence": "AnyDesk"}],
        scam_probability=50,
    )
    out = pipeline.assess(v, [], 0)
    assert {(f["code"], f["source"]) for f in out["flags"]} == {("REMOTE_ACCESS", "gemini"), ("SECRECY", "rules")}


def test_unknown_previous_flags_are_ignored():
    out = pipeline.assess(verdict(), ["SECRECY", "IGNORE_ALL_RULES"], 0)
    assert out["all_flags"] == ["SECRECY"]


def test_history_and_model_score_carry_over():
    out = pipeline.assess(verdict(scam_probability=0), ["AUTHORITY", "OTP_REQUEST"], 80)
    assert out["model_risk"] == 70 and out["level"] == "SCAM" and out["combo"]
