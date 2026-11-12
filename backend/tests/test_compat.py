"""Bidirectional compatibility engine tests."""
from app.compat import compare_versions, SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING


def _f(name, ftype, *, required=False, nullable=True, has_default=False,
       default=None, aliases=None, precision=10, scale=2, fields=None,
       item_type=None):
    out = {"name": name, "type": ftype, "required": required, "nullable": nullable,
           "has_default": has_default, "aliases": aliases or []}
    if has_default:
        out["default"] = default
    if ftype == "decimal":
        out["precision"], out["scale"] = precision, scale
    if ftype == "object":
        out["fields"] = fields or []
    if ftype == "array":
        out["items"] = {"name": "_items", "type": item_type or "text",
                        "required": False, "nullable": True,
                        "has_default": False, "aliases": []}
    return out


def _codes(report, direction=None):
    findings = report.findings
    if direction:
        findings = [f for f in findings if f.direction == direction]
    return {(f.direction, f.path, f.code, f.severity) for f in findings}


class TestFieldAddition:
    def test_new_required_field_without_default_breaks_old_reader_only(self):
        old = [_f("a", "text", required=True)]
        new = [_f("a", "text", required=True),
               _f("b", "text", required=True)]
        r = compare_versions(old, new)
        d = r.as_dict("v1", "v2")
        # old program reading new file: b is undeclared -> ignored, fine
        assert d["old_reader_verdict"] == "compatible"
        # new program reading old file: b missing, required, no default
        assert d["new_reader_verdict"] == "incompatible"
        assert any(f.code == "missing_required" and f.direction == "new_reader"
                   for f in r.findings)

    def test_new_required_field_with_default_is_fine(self):
        old = [_f("a", "text", required=True)]
        new = [_f("a", "text", required=True),
               _f("b", "text", required=True, has_default=True, default="x")]
        d = compare_versions(old, new).as_dict("v1", "v2")
        assert d["overall"] == "compatible"

    def test_removed_field_ignored_by_reader_that_lacks_it(self):
        old = [_f("a", "text"), _f("b", "text")]
        new = [_f("a", "text")]
        d = compare_versions(old, new).as_dict("v1", "v2")
        assert d["overall"] == "compatible"
        # new reader meets old-file field b it never declared -> ignored
        assert any(f["code"] == "undeclared_ignored" and f["direction"] == "new_reader"
                   for f in d["findings"])
        # old reader finds its optional b absent in the new file -> tolerated
        assert any(f["code"] == "optional_absent" and f["direction"] == "old_reader"
                   for f in d["findings"])


class TestNullability:
    def test_nullable_tightening_errors(self):
        old = [_f("a", "text", nullable=True)]
        new = [_f("a", "text", nullable=False)]
        r = compare_versions(old, new)
        # new file cannot contain null -> old (nullable) reader fine;
        # old file may contain null -> new strict reader rejects it
        assert any(f.direction == "new_reader" and f.code == "null_not_allowed"
                   and f.severity == SEVERITY_ERROR for f in r.findings)
        d = r.as_dict("v1", "v2")
        assert d["new_reader_verdict"] == "incompatible"


class TestNumericCoercion:
    def test_int_to_decimal_is_asymmetric(self):
        old = [_f("x", "integer")]
        new = [_f("x", "decimal", precision=20, scale=2)]
        r = compare_versions(old, new)
        d = r.as_dict("v1", "v2")
        # new decimal program reads old integer files losslessly
        assert d["new_reader_verdict"] == "compatible"
        assert any(f["code"] == "int_to_decimal" and f["direction"] == "new_reader"
                   for f in d["findings"])
        # old integer program must reject new decimal files (no decimal->int)
        assert d["old_reader_verdict"] == "incompatible"
        assert any(f["code"] == "decimal_to_int" and f["direction"] == "old_reader"
                   for f in d["findings"])
        assert d["overall"] == "incompatible"

    def test_int_to_decimal_narrow_warns(self):
        old = [_f("x", "integer")]
        new = [_f("x", "decimal", precision=6, scale=2)]
        r = compare_versions(old, new)
        assert any(f.code == "int_to_decimal_risk" and f.severity == SEVERITY_WARNING
                   for f in r.findings)

    def test_decimal_to_integer_always_error(self):
        old = [_f("x", "decimal")]
        new = [_f("x", "integer")]
        r = compare_versions(old, new)
        assert any(f.code == "decimal_to_int" and f.severity == SEVERITY_ERROR
                   for f in r.findings)

    def test_text_number_no_implicit_coercion(self):
        old = [_f("x", "text")]
        new = [_f("x", "integer")]
        r = compare_versions(old, new)
        assert any(f.code == "string_coercion" and f.severity == SEVERITY_ERROR
                   for f in r.findings)

    def test_decimal_scale_narrowing_error_precision_warning(self):
        old = [_f("x", "decimal", precision=10, scale=4)]
        new = [_f("x", "decimal", precision=8, scale=2)]
        r = compare_versions(old, new)
        # old reader (10,4) on new file (8,2): everything new fits -> nothing
        # new reader (8,2) on old file (10,4): scale loss is an error
        new_reader = [f for f in r.findings if f.direction == "new_reader"]
        assert any(f.code == "scale_narrowed" and f.severity == SEVERITY_ERROR
                   for f in new_reader)
        assert any(f.code == "precision_narrowed" for f in new_reader)


class TestRename:
    def test_rename_with_alias_asymmetric(self):
        old = [_f("sku", "text", required=True)]
        new = [_f("product_code", "text", required=True, aliases=["sku"])]
        r = compare_versions(old, new)
        d = r.as_dict("v1", "v2")
        # new reader handles old file via alias
        assert d["new_reader_verdict"] == "compatible"
        # old reader cannot understand the new canonical name
        assert d["old_reader_verdict"] == "incompatible"
        assert any(f.code == "rename_unknown" and f.direction == "old_reader"
                   for f in r.findings)
        assert any(f.code == "rename_alias" and f.direction == "new_reader"
                   for f in r.findings)

    def test_rename_optional_field_old_reader_ignores(self):
        old = [_f("sku", "text")]
        new = [_f("product_code", "text", aliases=["sku"])]
        d = compare_versions(old, new).as_dict("v1", "v2")
        # old reader just ignores the unknown field; no required failure
        assert d["old_reader_verdict"] == "compatible"

class TestArrayAndObject:
    def test_array_item_type_change_both_directions(self):
        old = [_f("vals", "array", item_type="integer")]
        new = [_f("vals", "array", item_type="text")]
        r = compare_versions(old, new)
        paths = {f.path for f in r.findings}
        assert "$.vals[]" in paths
        assert any(f.severity == SEVERITY_ERROR for f in r.findings)

    def test_nested_required_addition(self):
        old = [_f("meta", "object", fields=[_f("a", "text")])]
        new = [_f("meta", "object",
                  fields=[_f("a", "text"), _f("b", "text", required=True)])]
        r = compare_versions(old, new)
        assert any(f.path == "$.meta.b" and f.code == "missing_required"
                   and f.direction == "new_reader" for f in r.findings)


class TestDate:
    def test_date_type_change_error(self):
        old = [_f("d", "date")]
        new = [_f("d", "text")]
        r = compare_versions(old, new)
        assert any(f.code in ("string_coercion", "date_type_change")
                   and f.severity == SEVERITY_ERROR for f in r.findings)
