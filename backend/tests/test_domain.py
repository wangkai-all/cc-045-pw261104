"""Structure-definition validation, including default value type checks."""
import pytest

from app.domain import StructureError, normalise_structure


def field(**over):
    base = {"name": "f", "type": "text", "required": False, "nullable": True,
            "has_default": False, "aliases": []}
    base.update(over)
    return base


class TestStructureRejection:
    def test_unknown_type(self):
        with pytest.raises(StructureError):
            normalise_structure([field(type="float")])

    def test_duplicate_names(self):
        with pytest.raises(StructureError):
            normalise_structure([field(name="a"), field(name="a")])

    def test_decimal_scale_above_precision(self):
        with pytest.raises(StructureError):
            normalise_structure([field(name="d", type="decimal",
                                       precision=4, scale=5)])

    def test_array_requires_items(self):
        with pytest.raises(StructureError):
            normalise_structure([{"name": "a", "type": "array"}])

    def test_alias_must_be_nonempty_string(self):
        with pytest.raises(StructureError):
            normalise_structure([field(aliases=[""])])


class TestDefaultValues:
    def test_integer_default_rejects_string(self):
        with pytest.raises(StructureError):
            normalise_structure([field(type="integer", has_default=True, default="1")])

    def test_boolean_default_rejects_number(self):
        with pytest.raises(StructureError):
            normalise_structure([field(type="boolean", has_default=True, default=1)])

    def test_null_default_rejected_when_not_nullable(self):
        with pytest.raises(StructureError):
            normalise_structure([field(nullable=False, has_default=True, default=None)])

    def test_null_default_allowed_when_nullable(self):
        out = normalise_structure([field(nullable=True, has_default=True, default=None)])
        assert out[0]["default"] is None

    def test_decimal_default_checked_against_precision_and_scale(self):
        ok = normalise_structure([field(type="decimal", precision=8, scale=2,
                                        has_default=True, default="123.45")])
        assert ok[0]["default"] == "123.45"
        with pytest.raises(StructureError):
            normalise_structure([field(type="decimal", precision=8, scale=2,
                                       has_default=True, default="1.234")])
        with pytest.raises(StructureError):
            normalise_structure([field(type="decimal", precision=4, scale=2,
                                       has_default=True, default="12345.6")])

    def test_date_default_uses_real_calendar(self):
        with pytest.raises(StructureError):
            normalise_structure([field(type="date", has_default=True,
                                       default="2026-02-30")])
        out = normalise_structure([field(type="date", has_default=True,
                                         default="2026-11-13")])
        assert out[0]["default"] == "2026-11-13"
