"""Safety gate: PHI redaction and medication-advice language."""

from app import safety


def test_phi_redaction_strips_email_and_phone():
    text, report = safety.redact_phi(
        "Tray for patient: jane@example.com, call 555-123-4567")
    assert "jane@example.com" not in text
    assert "555-123-4567" not in text
    assert report["EMAIL"] == 1
    assert report["PHONE"] == 1


def test_advice_phrases_are_detected():
    assert safety.find_advice_language("This is safe to take with food.")
    assert safety.find_advice_language("You should stop taking this.")
    assert safety.find_advice_language("Double up if you miss a dose.")
    assert safety.find_advice_language("For a pharmacist to review.") == []


def test_readme_disclaimer_is_verbatim_and_first():
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "README.md")
    text = open(path).read()
    disclaimer = open(os.path.expanduser(
        "~/workspace/goals/weekly-clinical-ai-product-launches/"
        "hidden_files/standard-disclaimer.md")).read()
    # The verbatim block (between the --- markers) must appear in the
    # README, and it must come before the first title.
    block = disclaimer.split("---")[1].strip()
    assert block in text
    assert text.index(block) < text.index("# PillTray")
