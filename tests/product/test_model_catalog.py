import pytest

from pharma_proto.llm.catalog import MODEL_CATALOG, model_for


def test_model_catalog_has_exactly_three_providers_and_three_tiers():
    assert MODEL_CATALOG == {
        "openai": {
            "cheap": "gpt-5.6-luna",
            "normal": "gpt-5.6-terra",
            "good": "gpt-5.6-sol",
        },
        "gemini": {
            "cheap": "gemini-3.5-flash-lite",
            "normal": "gemini-3.7-flash",
            "good": "gemini-3.1-pro-preview",
        },
        "claude": {
            "cheap": "claude-haiku-4-5-20251001",
            "normal": "claude-sonnet-5",
            "good": "claude-opus-5",
        },
    }
    assert model_for("openai", "normal") == "gpt-5.6-terra"


@pytest.mark.parametrize(
    ("provider", "tier"),
    [("unknown", "normal"), ("openai", "unknown")],
)
def test_model_catalog_rejects_unknown_values(provider, tier):
    with pytest.raises(ValueError):
        model_for(provider, tier)
