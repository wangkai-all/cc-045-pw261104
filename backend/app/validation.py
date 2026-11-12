"""Record / JSONL value validation against a locked field structure.

Rules implemented (from the project specification):

* undeclared fields are ignored;
* a missing key is filled from ``default`` only when ``has_default`` is set,
  otherwise it fails exactly when the field is required;
* an explicit ``null`` is accepted only when the field is nullable;
* integers read losslessly into decimals of sufficient precision, but decimals
  never widen into integers; strings are never coerced to numbers;
* decimal total digits and fractional digits are validated separately;
* date strings are checked against the real calendar (no Feb 30 etc.);
* nested objects and arrays recurse, reporting full dotted/``[]`` paths.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from .domain import index_fields

_MAX_SAFE_INT_DIGITS = 18  # guard against absurdly large integer literals


class Issue:
    __slots__ = ("path", "code", "message")

    def __init__(self, path: str, code: str, message: str):
        self.path = path
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"path": self.path, "code": self.code, "message": self.message}


def _issue(path: str, code: str, message: str) -> Issue:
    return Issue(path, code, message)


def _check_decimal(raw: Any, field: dict, path: str) -> list[Issue]:
    precision = field["precision"]
    scale = field["scale"]
    integer_digits = precision - scale

    if isinstance(raw, bool):  # bool is a subclass of int — reject explicitly
        return [_issue(path, "type_mismatch", f"布尔值不能作为 decimal 读取")]

    if isinstance(raw, int):
        # integer -> decimal is allowed when the decimal has enough room
        digits = len(str(abs(raw)))
        if digits > precision:
            return [_issue(path, "decimal_overflow",
                           f"整数 {raw} 有 {digits} 位，超过 decimal({precision},{scale}) 总位数")]
        if integer_digits < digits:
            return [_issue(path, "decimal_overflow",
                           f"整数 {raw} 需要 {digits} 位整数位，"
                           f"decimal({precision},{scale}) 仅允许 {integer_digits} 位")]
        return []

    if not isinstance(raw, str):
        return [_issue(path, "type_mismatch",
                       f"decimal 只接受数字或数字字符串，收到 {type(raw).__name__}；字符串不会隐式转数字")]

    text = raw.strip()
    try:
        value = Decimal(text)
    except InvalidOperation:
        return [_issue(path, "type_mismatch", f"{raw!r} 不是合法的定点小数字符串")]

    if not value.is_finite():
        return [_issue(path, "type_mismatch", f"{raw!r} 不是有限小数")]

    sign, digits, exponent = value.as_tuple()
    digit_count = len(digits)
    frac_digits = max(-exponent, 0)
    int_digits = max(digit_count - frac_digits, 0)

    problems = []
    if digit_count > precision:
        problems.append(_issue(path, "decimal_overflow",
                               f"{text} 总位数 {digit_count} 超过 precision={precision}"))
    if frac_digits > scale:
        problems.append(_issue(path, "decimal_scale",
                               f"{text} 小数位数 {frac_digits} 超过 scale={scale}"))
    if int_digits > integer_digits:
        problems.append(_issue(path, "decimal_overflow",
                               f"{text} 整数位数 {int_digits} 超过允许的 {integer_digits} 位"))
    return problems


def _check_integer(raw: Any, path: str) -> list[Issue]:
    if isinstance(raw, bool):
        return [_issue(path, "type_mismatch", "布尔值不能作为 integer 读取")]
    if isinstance(raw, int):
        if len(str(abs(raw))) > _MAX_SAFE_INT_DIGITS:
            return [_issue(path, "integer_overflow", f"整数 {raw} 超过 {_MAX_SAFE_INT_DIGITS} 位安全范围")]
        return []
    if isinstance(raw, float):
        return [_issue(path, "type_mismatch",
                       "浮点数/小数不能自动读成 integer（小数不会隐式转整数）")]
    return [_issue(path, "type_mismatch",
                   f"integer 只接受整数字面量，收到 {type(raw).__name__}；字符串不会隐式转数字")]


def _check_date(raw: Any, path: str) -> list[Issue]:
    if not isinstance(raw, str):
        return [_issue(path, "type_mismatch", f"date 必须是 ISO 日期字符串，收到 {type(raw).__name__}")]
    text = raw.strip()
    # ISO 8601 calendar date: YYYY-MM-DD. fromisoformat enforces a real calendar.
    try:
        from datetime import date

        parsed = date.fromisoformat(text)
    except ValueError:
        return [_issue(path, "invalid_date", f"{raw!r} 不是合法 ISO 日期或真实日历不存在该日期")]
    if parsed.isoformat() != text:
        return [_issue(path, "invalid_date",
                       f"{raw!r} 格式不规范，应为 YYYY-MM-DD（例如 {parsed.isoformat()}）")]
    return []


def _check_scalar(raw: Any, field: dict, path: str) -> list[Issue]:
    ftype = field["type"]
    if ftype == "text":
        if not isinstance(raw, str):
            return [_issue(path, "type_mismatch",
                           f"text 只接受字符串，收到 {type(raw).__name__}，不做隐式转换")]
        return []
    if ftype == "boolean":
        if not isinstance(raw, bool):
            return [_issue(path, "type_mismatch",
                           f"boolean 只接受 true/false，收到 {type(raw).__name__}")]
        return []
    if ftype == "integer":
        return _check_integer(raw, path)
    if ftype == "decimal":
        return _check_decimal(raw, field, path)
    if ftype == "date":
        return _check_date(raw, path)
    return [_issue(path, "type_mismatch", f"未知类型 {ftype}")]


def validate_value(raw: Any, field: dict, path: str) -> list[Issue]:
    """Validate one value against one field definition (handles null + recursion)."""
    if raw is None:
        if field.get("nullable", True):
            return []
        return [_issue(path, "null_not_allowed", f"字段 {field['name']!r} 不可为空，收到显式 null")]

    ftype = field["type"]
    if ftype == "object":
        if not isinstance(raw, dict):
            return [_issue(path, "type_mismatch",
                           f"期望 object，收到 {type(raw).__name__}")]
        return validate_record(raw, field.get("fields", []), path)

    if ftype == "array":
        if not isinstance(raw, list):
            return [_issue(path, "type_mismatch",
                           f"期望 array，收到 {type(raw).__name__}")]
        issues: list[Issue] = []
        item_def = field["items"]
        for idx, item in enumerate(raw):
            issues.extend(validate_value(item, item_def, f"{path}[{idx}]"))
        return issues

    return _check_scalar(raw, field, path)


def validate_record(record: dict, fields: list[dict], base_path: str = "$") -> list[Issue]:
    """Validate one JSON object against a field list. Undeclared keys ignored."""
    if not isinstance(record, dict):
        return [_issue(base_path, "type_mismatch",
                       f"每行必须是 JSON 对象，收到 {type(record).__name__}")]

    lookup = index_fields(fields)
    seen_canonical: set[str] = set()
    issues: list[Issue] = []

    for key, value in record.items():
        field = lookup.get(key)
        if field is None:
            continue  # undeclared fields are uniformly ignored
        canonical = field["name"]
        if canonical in seen_canonical:
            issues.append(_issue(f"{base_path}.{key}", "duplicate_alias",
                                 f"字段 {key!r} 与已出现的 {canonical!r} 指向同一字段（别名冲突）"))
            continue
        seen_canonical.add(canonical)
        child_path = f"{base_path}.{canonical}" if base_path != "$" else f"$.{canonical}"
        issues.extend(validate_value(value, field, child_path))

    for field in fields:
        if field["name"] in seen_canonical:
            continue
        path = f"{base_path}.{field['name']}" if base_path != "$" else f"$.{field['name']}"
        if field.get("has_default"):
            continue  # missing key with a default is filled automatically
        if field.get("required", False):
            issues.append(_issue(path, "missing_required",
                                 f"缺少必填字段 {field['name']!r} 且未声明默认值"))
        # optional + no default + absent: fine
    return issues


def validate_jsonl(text: str, fields: list[dict]) -> dict:
    """Parse and validate a whole JSONL document, locating problems by line."""
    line_reports: list[dict] = []
    total = 0
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        total += 1
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            line_reports.append({
                "line": lineno,
                "ok": False,
                "issues": [{
                    "path": "$",
                    "code": "invalid_json",
                    "message": f"JSON 解析失败: {exc.msg} (列 {exc.colno})",
                }],
            })
            continue
        issues = validate_record(record, fields)
        line_reports.append({
            "line": lineno,
            "ok": not issues,
            "issues": [i.as_dict() for i in issues],
        })

    problem_lines = [r for r in line_reports if not r["ok"]]
    return {
        "total_lines": total,
        "ok_lines": total - len(problem_lines),
        "problem_count": len(problem_lines),
        "passed": not problem_lines,
        "lines": line_reports,
    }
