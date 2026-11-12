"""Explicit data transformation between LOCKED schema versions.

Structural compatibility never performs conversion itself. To move data from
one locked version to another the user defines an explicit field mapping:

* ``rename``      — copy source path to a different target path;
* ``cast_decimal``— decimal -> text (rendered) or integer -> decimal string;
* ``set_default`` — synthesise a constant for a newly required field;
* ``drop``        — leave an old field behind.

Every run first produces a DRAFT preview (per-row before/after diffs and
unmapped-field warnings). Only the explicit ``generate`` step writes a new
JSONL artifact; the source file is never modified.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .domain import index_fields
from .validation import validate_record


class MappingError(ValueError):
    pass


ALLOWED_ACTIONS = {"rename", "cast_decimal", "set_default", "drop"}


def _get_path(record: dict, dotted: str) -> tuple[bool, Any]:
    """Dotted path with []-less array support is intentionally out of scope;
    mappings address top-level and nested object fields only."""
    cur: Any = record
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _set_path(record: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = record
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _cast_value(value: Any, target_field: dict) -> Any:
    ttype = target_field["type"]
    if value is None:
        return None
    if ttype == "decimal":
        if isinstance(value, bool):
            raise MappingError("布尔值不能转换为 decimal")
        if isinstance(value, int):
            text = str(value)
        elif isinstance(value, str):
            text = value.strip()
        else:
            raise MappingError(f"无法把 {type(value).__name__} 显式转换为 decimal")
        try:
            Decimal(text)
        except InvalidOperation as exc:
            raise MappingError(f"{text!r} 不是合法 decimal") from exc
        return text
    if ttype == "text":
        if isinstance(value, (str, int, bool)):
            return str(value)
        raise MappingError(f"仅标量可渲染为 text，收到 {type(value).__name__}")
    raise MappingError(f"映射不支持向 {ttype} 类型的显式转换")


def validate_mapping(mapping: Any) -> list[dict]:
    if not isinstance(mapping, list):
        raise MappingError("映射必须是规则数组")
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for idx, rule in enumerate(mapping):
        if not isinstance(rule, dict):
            raise MappingError(f"规则 {idx} 必须是对象")
        action = rule.get("action")
        if action not in ALLOWED_ACTIONS:
            raise MappingError(f"规则 {idx} 的 action={action!r} 非法，允许 {sorted(ALLOWED_ACTIONS)}")
        if action == "set_default":
            for key in ("target", "value"):
                if key not in rule:
                    raise MappingError(f"规则 {idx} set_default 缺少 {key}")
            if rule["target"] in seen_targets:
                raise MappingError(f"目标字段 {rule['target']} 被重复映射")
            seen_targets.add(rule["target"])
        elif action == "drop":
            if "source" not in rule:
                raise MappingError(f"规则 {idx} drop 缺少 source")
            seen_sources.add(rule["source"])
        else:
            for key in ("source", "target"):
                if key not in rule:
                    raise MappingError(f"规则 {idx} {action} 缺少 {key}")
            if rule["source"] in seen_sources:
                raise MappingError(f"源字段 {rule['source']} 被重复映射")
            if rule["target"] in seen_targets:
                raise MappingError(f"目标字段 {rule['target']} 被重复映射")
            seen_sources.add(rule["source"])
            seen_targets.add(rule["target"])
    return mapping


def _flat_names(fields: list[dict], prefix: str = "") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in fields:
        name = f"{prefix}{f['name']}"
        out[name] = f
        if f["type"] == "object":
            out.update(_flat_names(f.get("fields", []), f"{name}."))
    return out


def preview_mapping(records: list[dict], mapping: list[dict],
                    target_fields: list[dict]) -> dict:
    target_flat = _flat_names(target_fields)
    target_top = index_fields(target_fields)

    rows: list[dict] = []
    warnings: list[dict] = []
    for row_idx, record in enumerate(records, start=1):
        result = json.loads(json.dumps(record))  # deep copy, JSON-safe
        changes: list[dict] = []
        for rule in mapping:
            action = rule["action"]
            if action == "set_default":
                target = rule["target"]
                _set_path(result, target, rule["value"])
                changes.append({"type": "set_default", "target": target,
                                "after": rule["value"]})
                continue
            found, value = _get_path(record, rule["source"])
            if not found:
                warnings.append({"row": row_idx, "code": "source_missing",
                                 "message": f"源字段 {rule['source']} 不存在，跳过规则"})
                continue
            if action == "drop":
                _drop_path(result, rule["source"])
                changes.append({"type": "drop", "source": rule["source"], "before": value})
                continue
            target_field = target_flat.get(rule["target"].split(".")[-1])
            if action == "cast_decimal":
                if target_field is None:
                    raise MappingError(f"目标字段 {rule['target']} 在新版本中不存在")
                new_value = _cast_value(value, target_field)
            else:  # rename
                new_value = value
            _drop_path(result, rule["source"])
            _set_path(result, rule["target"], new_value)
            changes.append({"type": action, "source": rule["source"],
                            "target": rule["target"], "before": value, "after": new_value})

        # check unmapped top-level source fields that the target does not know
        for key in record:
            if key not in target_top:
                warnings.append({"row": row_idx, "code": "unmapped_field",
                                 "message": f"源字段 {key!r} 无映射规则且新版本未声明，将被忽略"})

        issues = validate_record(result, target_fields)
        rows.append({
            "row": row_idx,
            "before": record,
            "after": result,
            "changes": changes,
            "valid_against_target": not issues,
            "issues": [i.as_dict() for i in issues],
        })

    return {
        "total_rows": len(records),
        "valid_rows": sum(1 for r in rows if r["valid_against_target"]),
        "warnings": warnings,
        "rows": rows,
    }


def _drop_path(record: dict, dotted: str) -> None:
    parts = dotted.split(".")
    cur: Any = record
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def render_jsonl(preview_rows: list[dict]) -> str:
    return "".join(json.dumps(r["after"], ensure_ascii=False) + "\n" for r in preview_rows)
