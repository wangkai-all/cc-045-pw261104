"""Single-record validation rules."""
from app.validation import validate_record, validate_jsonl


def _field(name, ftype, **kw):
    base = {"name": name, "type": ftype, "required": False,
            "nullable": True, "has_default": False, "aliases": []}
    base.update(kw)
    if ftype == "decimal":
        base.setdefault("precision", 10)
        base.setdefault("scale", 2)
    if ftype == "array":
        base["items"] = {"name": "_items", "type": kw.pop("item_type", "text"),
                         "required": False, "nullable": True,
                         "has_default": False, "aliases": []}
    return base


class TestUndeclaredAndMissing:
    def test_undeclared_field_ignored(self):
        fields = [_field("a", "text")]
        assert validate_record({"a": "x", "ghost": 1}, fields) == []

    def test_missing_required_without_default_fails(self):
        fields = [_field("a", "text", required=True)]
        issues = validate_record({}, fields)
        assert len(issues) == 1 and issues[0].code == "missing_required"

    def test_missing_optional_is_fine(self):
        fields = [_field("a", "text")]
        assert validate_record({}, fields) == []

    def test_missing_with_default_is_filled_silently(self):
        fields = [_field("a", "text", required=True, has_default=True, default="z")]
        assert validate_record({}, fields) == []


class TestNull:
    def test_explicit_null_allowed_when_nullable(self):
        fields = [_field("a", "text", nullable=True)]
        assert validate_record({"a": None}, fields) == []

    def test_explicit_null_rejected_when_not_nullable(self):
        fields = [_field("a", "text", nullable=False)]
        issues = validate_record({"a": None}, fields)
        assert issues[0].code == "null_not_allowed"

    def test_nullable_false_with_default_still_rejects_explicit_null(self):
        fields = [_field("a", "text", nullable=False, has_default=True, default="z")]
        issues = validate_record({"a": None}, fields)
        assert issues[0].code == "null_not_allowed"


class TestIntegerDecimal:
    def test_integer_reads_into_decimal_losslessly(self):
        fields = [_field("price", "decimal", precision=10, scale=2)]
        assert validate_record({"price": 199}, fields) == []

    def test_integer_too_big_for_decimal_overflows(self):
        fields = [_field("price", "decimal", precision=5, scale=2)]
        issues = validate_record({"price": 123456}, fields)
        assert issues[0].code == "decimal_overflow"

    def test_decimal_string_never_read_as_integer(self):
        fields = [_field("qty", "integer")]
        issues = validate_record({"qty": "12"}, fields)
        assert issues[0].code == "type_mismatch"

    def test_float_never_read_as_integer(self):
        fields = [_field("qty", "integer")]
        issues = validate_record({"qty": 1.5}, fields)
        assert any(i.code == "type_mismatch" for i in issues)

    def test_bool_not_an_integer(self):
        fields = [_field("qty", "integer")]
        assert validate_record({"qty": True}, fields)[0].code == "type_mismatch"

    def test_decimal_precision_and_scale_separate(self):
        fields = [_field("amount", "decimal", precision=8, scale=2)]
        # total digits ok, fractional digits too many
        issues = validate_record({"amount": "12.345"}, fields)
        codes = {i.code for i in issues}
        assert "decimal_scale" in codes
        # integer part too long
        issues = validate_record({"amount": "1234567.8"}, fields)
        assert any(i.code == "decimal_overflow" for i in issues)
        # exactly at the boundary is fine
        assert validate_record({"amount": "123456.78"}, fields) == []

    def test_decimal_rejects_non_numeric_string(self):
        fields = [_field("amount", "decimal", precision=8, scale=2)]
        issues = validate_record({"amount": "abc"}, fields)
        assert issues[0].code == "type_mismatch"


class TestTextBooleanDate:
    def test_text_rejects_number_without_coercion(self):
        fields = [_field("name", "text")]
        assert validate_record({"name": 42}, fields)[0].code == "type_mismatch"

    def test_boolean_strict(self):
        fields = [_field("flag", "boolean")]
        assert validate_record({"flag": True}, fields) == []
        assert validate_record({"flag": 1}, fields)[0].code == "type_mismatch"

    def test_real_calendar_enforced(self):
        fields = [_field("day", "date")]
        assert validate_record({"day": "2026-02-28"}, fields) == []
        issues = validate_record({"day": "2026-02-30"}, fields)
        assert issues[0].code == "invalid_date"
        issues = validate_record({"day": "2026-13-01"}, fields)
        assert issues[0].code == "invalid_date"
        # 2024 is a leap year, 2026 is not
        assert validate_record({"day": "2024-02-29"}, fields) == []
        assert validate_record({"day": "2026-02-29"}, fields)[0].code == "invalid_date"


class TestNestedAndArray:
    def test_nested_object_path(self):
        fields = [_field("meta", "object",
                         fields=[_field("tag", "text", required=True)])]
        issues = validate_record({"meta": {"tag": "x"}}, fields)
        assert issues == []
        issues = validate_record({"meta": {}}, fields)
        assert issues[0].path == "$.meta.tag" and issues[0].code == "missing_required"

    def test_array_element_paths(self):
        fields = [_field("tags", "array", item_type="integer")]
        issues = validate_record({"tags": [1, "bad", 3]}, fields)
        assert len(issues) == 1
        assert issues[0].path == "$.tags[1]"

    def test_array_type_change_detected(self):
        fields = [_field("tags", "array", item_type="integer")]
        issues = validate_record({"tags": "not-an-array"}, fields)
        assert issues[0].code == "type_mismatch"


class TestAliases:
    def test_alias_accepted_as_canonical(self):
        fields = [_field("new_name", "text", aliases=["old_name"])]
        assert validate_record({"old_name": "v"}, fields) == []

    def test_alias_and_canonical_both_present_conflicts(self):
        fields = [_field("new_name", "text", aliases=["old_name"])]
        issues = validate_record({"old_name": "a", "new_name": "b"}, fields)
        assert issues[0].code == "duplicate_alias"


class TestJsonl:
    def test_line_numbers_and_paths(self):
        fields = [_field("qty", "integer", required=True)]
        doc = '{"qty": 1}\nnot-json\n{"other": 1}\n'
        report = validate_jsonl(doc, fields)
        assert report["total_lines"] == 3
        assert report["problem_count"] == 2
        assert report["lines"][1]["line"] == 2
        assert report["lines"][1]["issues"][0]["code"] == "invalid_json"
        assert report["lines"][2]["issues"][0]["path"] == "$.qty"
