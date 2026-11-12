"""Explicit mapping engine tests: draft -> preview -> generated file."""
import pytest

from app.mapping import MappingError, preview_mapping, render_jsonl, validate_mapping
from app.validation import validate_jsonl


def _target_fields():
    return [
        {"name": "product_code", "type": "text", "required": True,
         "nullable": False, "has_default": False, "aliases": ["sku"]},
        {"name": "price", "type": "decimal", "required": True,
         "nullable": False, "has_default": True, "default": "0.00",
         "aliases": [], "precision": 10, "scale": 2},
        {"name": "active", "type": "boolean", "required": True,
         "nullable": False, "has_default": True, "default": True, "aliases": []},
    ]


def test_preview_shows_changes_and_validates_target():
    records = [{"sku": "A-1", "price": "9.9", "legacy_note": "x"}]
    rules = [
        {"action": "rename", "source": "sku", "target": "product_code"},
        {"action": "set_default", "target": "active", "value": True},
        {"action": "drop", "source": "legacy_note"},
    ]
    preview = preview_mapping(records, rules, _target_fields())
    row = preview["rows"][0]
    assert row["after"]["product_code"] == "A-1"
    assert "sku" not in row["after"]
    assert "legacy_note" not in row["after"]
    assert row["valid_against_target"] is True
    assert any(w["code"] == "unmapped_field" and "legacy_note" in w["message"]
               for w in preview["warnings"])


def test_cast_integer_to_decimal_string():
    records = [{"sku": "A-1", "price": 12}]
    rules = [
        {"action": "rename", "source": "sku", "target": "product_code"},
        {"action": "cast_decimal", "source": "price", "target": "price"},
        {"action": "set_default", "target": "active", "value": True},
    ]
    preview = preview_mapping(records, rules, _target_fields())
    assert preview["rows"][0]["after"]["price"] == "12"
    assert preview["rows"][0]["valid_against_target"] is True


def test_generated_jsonl_round_trips_through_target_validation():
    records = [{"sku": "A-1", "price": "1.00"},
               {"sku": "A-2", "price": "2.50"}]
    rules = [
        {"action": "rename", "source": "sku", "target": "product_code"},
        {"action": "set_default", "target": "active", "value": False},
    ]
    preview = preview_mapping(records, rules, _target_fields())
    text = render_jsonl(preview["rows"])
    report = validate_jsonl(text, _target_fields())
    assert report["passed"] is True
    assert report["total_lines"] == 2


def test_invalid_mapping_rules_rejected():
    with pytest.raises(MappingError):
        validate_mapping([{"action": "teleport"}])
    with pytest.raises(MappingError):
        validate_mapping([{"action": "set_default", "target": "a"}])


def test_mapping_does_not_mutate_source_record():
    source = [{"sku": "A-1"}]
    rules = [{"action": "rename", "source": "sku", "target": "product_code"},
             {"action": "set_default", "target": "active", "value": True}]
    preview_mapping(source, rules, _target_fields())
    assert source == [{"sku": "A-1"}]
