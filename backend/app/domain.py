"""Domain model: field structure definitions.

A schema version stores a tree of FieldDef dicts (JSON-serialisable):

{
  "name": "price",
  "type": "decimal",            # object|array|text|integer|decimal|boolean|date
  "required": true,
  "nullable": false,
  "has_default": true,
  "default": "10.00",           # raw JSON value, only used when has_default
  "aliases": ["old_price"],     # former names understood by THIS version
  "precision": 10,              # decimal: total digits
  "scale": 2,                   # decimal: digits after the decimal point
  "fields": [FieldDef, ...],    # object only
  "items": FieldDef             # array only
}

The root of a version is an implicit object whose children are ``fields``.
"""
from __future__ import annotations

from typing import Any

FIELD_TYPES = {"object", "array", "text", "integer", "decimal", "boolean", "date"}


class StructureError(ValueError):
    """Raised when a field structure definition itself is malformed."""


def _require_type(value: Any, expected: type, path: str) -> None:
    if not isinstance(value, expected):
        raise StructureError(f"{path} 应为 {expected.__name__}，实际为 {type(value).__name__}")


def validate_structure(fields: Any, path: str = "$") -> None:
    """Validate a field-definition tree. Raises StructureError on malformed defs."""
    _require_type(fields, list, path)
    names: set[str] = set()
    for index, field in enumerate(fields):
        here = f"{path}[{index}]"
        _require_type(field, dict, here)
        name = field.get("name")
        _require_type(name, str, f"{here}.name")
        if not name:
            raise StructureError(f"{here}.name 不能为空")
        if name in names:
            raise StructureError(f"{here}: 字段名 {name!r} 重复")
        names.add(name)

        ftype = field.get("type")
        if ftype not in FIELD_TYPES:
            raise StructureError(f"{here}.type={ftype!r} 非法，允许: {sorted(FIELD_TYPES)}")

        for flag in ("required", "nullable", "has_default"):
            if flag in field and not isinstance(field[flag], bool):
                raise StructureError(f"{here}.{flag} 必须是布尔值")

        aliases = field.get("aliases", [])
        _require_type(aliases, list, f"{here}.aliases")
        if any(not isinstance(a, str) or not a for a in aliases):
            raise StructureError(f"{here}.aliases 必须是非空字符串数组")
        if len(set(aliases)) != len(aliases):
            raise StructureError(f"{here}.aliases 存在重复别名")

        if ftype == "decimal":
            precision = field.get("precision")
            scale = field.get("scale")
            if not isinstance(precision, int) or isinstance(precision, bool) or precision < 1:
                raise StructureError(f"{here}.precision 必须是正整数")
            if not isinstance(scale, int) or isinstance(scale, bool) or scale < 0:
                raise StructureError(f"{here}.scale 必须是非负整数")
            if scale > precision:
                raise StructureError(f"{here}.scale({scale}) 不能大于 precision({precision})")

        if ftype == "object":
            validate_structure(field.get("fields", []), f"{here}.fields")

        if ftype == "array":
            items = field.get("items")
            if not isinstance(items, dict):
                raise StructureError(f"{here}.items 必须是数组元素的字段定义")
            validate_structure([items], f"{here}.items")
            # element def carries no required/nullable semantics of its own key
            if items.get("name") != "_items":
                # normalise later; here just ensure a name exists for tree reuse
                raise StructureError(f"{here}.items.name 必须为 '_items'")

        if field.get("has_default") and "default" not in field:
            raise StructureError(f"{here}: 声明 has_default 时必须提供 default")

        if field.get("has_default"):
            _validate_default(field, here)


def _validate_default(field: dict, path: str) -> None:
    """A default value must itself satisfy the field's own type rules."""
    value = field["default"]
    ftype = field["type"]
    if value is None:
        if not field.get("nullable", True):
            raise StructureError(f"{path}.default 为 null，但字段声明不可空")
        return

    if ftype == "text":
        if not isinstance(value, str):
            raise StructureError(f"{path}.default 必须是字符串")
    elif ftype == "boolean":
        if not isinstance(value, bool):
            raise StructureError(f"{path}.default 必须是布尔值")
    elif ftype == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise StructureError(f"{path}.default 必须是整数，字符串不会隐式转换")
    elif ftype == "date":
        if not isinstance(value, str):
            raise StructureError(f"{path}.default 必须是 ISO 日期字符串")
        from datetime import date

        try:
            parsed = date.fromisoformat(value.strip())
        except ValueError as exc:
            raise StructureError(f"{path}.default {value!r} 不是合法日历日期") from exc
        if parsed.isoformat() != value.strip():
            raise StructureError(f"{path}.default 日期格式应为 YYYY-MM-DD")
    elif ftype == "decimal":
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise StructureError(f"{path}.default decimal 仅接受整数或数字字符串")
        from decimal import Decimal, InvalidOperation

        try:
            dec = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise StructureError(f"{path}.default {value!r} 不是合法 decimal") from exc
        if not dec.is_finite():
            raise StructureError(f"{path}.default 必须是有限小数")
        sign, digits, exponent = dec.as_tuple()
        total = len(digits)
        frac = max(-exponent, 0)
        if total > field["precision"]:
            raise StructureError(
                f"{path}.default 总位数 {total} 超过 precision={field['precision']}")
        if frac > field["scale"]:
            raise StructureError(
                f"{path}.default 小数位 {frac} 超过 scale={field['scale']}")
    elif ftype in ("object", "array"):
        if not isinstance(value, (dict, list)):
            raise StructureError(f"{path}.default 必须与 {ftype} 类型一致")


def normalise_field(field: dict) -> dict:
    """Return a complete field def with all optional keys filled in."""
    out: dict[str, Any] = {
        "name": field["name"],
        "type": field["type"],
        "required": bool(field.get("required", False)),
        "nullable": bool(field.get("nullable", True)),
        "has_default": bool(field.get("has_default", False)),
        "aliases": list(field.get("aliases", [])),
    }
    if out["has_default"]:
        out["default"] = field["default"]
    if field["type"] == "decimal":
        out["precision"] = int(field["precision"])
        out["scale"] = int(field["scale"])
    if field["type"] == "object":
        out["fields"] = [normalise_field(f) for f in field.get("fields", [])]
    if field["type"] == "array":
        out["items"] = normalise_field(field["items"])
    return out


def normalise_structure(fields: list[dict]) -> list[dict]:
    validate_structure(fields)
    return [normalise_field(f) for f in fields]


def index_fields(fields: list[dict]) -> dict[str, dict]:
    """Map every accepted key (canonical name + aliases) to its field def."""
    result: dict[str, dict] = {}
    for field in fields:
        result[field["name"]] = field
        for alias in field.get("aliases", []):
            result[alias] = field
    return result
