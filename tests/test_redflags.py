import json
from pathlib import Path

import pytest

from app import redflags as rf
from app import risk

SCRIPTS = Path(__file__).resolve().parent.parent / "samples" / "scripts"


def caller_text(stem: str) -> str:
    script = json.loads((SCRIPTS / f"{stem}.json").read_text(encoding="utf-8"))
    return "\n".join(line["text"] for line in script["lines"] if line["speaker"] == "Caller")


def codes(text: str) -> set[str]:
    return {h["code"] for h in rf.match_rules(text)}


def test_every_flag_has_label_explanation_and_weight_in_all_languages():
    for code in rf.CODES:
        assert code in rf.WEIGHTS
        for lang in ("en", "hi", "gu"):
            assert rf.LABELS[code][lang]
            assert rf.EXPLAIN[code][lang]


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("01_digital_arrest_hi", {rf.AUTHORITY, rf.ARREST_THREAT, rf.SECRECY, rf.MONEY_REQUEST, rf.URGENCY}),
        ("02_fake_kyc_gu", {rf.AUTHORITY, rf.OTP_REQUEST, rf.URGENCY}),
        ("03_fake_courier_hi", {rf.AUTHORITY, rf.MONEY_REQUEST, rf.REMOTE_ACCESS, rf.SECRECY}),
    ],
)
def test_rules_catch_the_scripted_scams(stem, expected):
    assert expected <= codes(caller_text(stem))


def test_genuine_delivery_call_raises_no_rule_flags():
    assert codes(caller_text("04_genuine_delivery_gu")) == set()


def test_genuine_bank_call_trips_a_keyword_but_stays_safe():
    # "bank never asks for OTP" contains the word OTP: the rules see it, the two-key design keeps the call SAFE.
    found = codes(caller_text("05_genuine_bank_hi"))
    assert rf.OTP_REQUEST in found
    assert risk.fuse(model_prob=5, prev_model=0, codes=found)["level"] == "SAFE"


def test_english_gloss_is_matched_too():
    assert rf.REMOTE_ACCESS in codes("Please install AnyDesk so I can guide you")
    assert rf.SECRECY in codes("Do not tell anyone, not even your family")
    assert codes("Payment is already done, nothing to pay. No hurry.") == set()
