"""Gateway: tier resolution, model list, embeddings, ledger."""

from app import gateway


def test_tier_resolution():
    assert gateway.resolve_tier("pill-tray-full") == "full"
    assert gateway.resolve_tier("pill-tray-frugal") == "frugal"
    assert gateway.resolve_tier(None, "full") == "full"
    assert gateway.resolve_tier(None, "frugal") == "frugal"
    assert gateway.resolve_tier("something-else") == "frugal"


def test_models_list_includes_both_tiers():
    data = gateway.list_models()
    ids = [m["id"] for m in data["data"]]
    assert "pill-tray-frugal" in ids
    assert "pill-tray-full" in ids


def test_embeddings_identical_descriptor_is_identical_vector():
    a = gateway.dispatch_embeddings("white round pill, size M, imprint marks some")
    b = gateway.dispatch_embeddings("white round pill, size M, imprint marks some")
    assert a["data"][0]["embedding"] == b["data"][0]["embedding"]
    assert gateway.CALL_LEDGER["embeddings"] == 2


def test_chat_ledger_counts_dispatches():
    gateway.dispatch_chat([{"role": "user", "content": "hello"}])
    assert gateway.CALL_LEDGER["chat"] == 1
    gateway.reset_ledger()
    assert gateway.CALL_LEDGER["chat"] == 0
