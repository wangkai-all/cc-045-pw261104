"""Bidirectional compatibility between two schema versions.

For any pair of versions we always check BOTH reading directions, standing in
the shoes of each reader:

* ``old_reader`` — a program built against the old version reading a new file;
* ``new_reader`` — a program built against the new version reading an old file.

Shared assumptions both readers obey:

* undeclared fields are ignored;
* a missing field is tolerated only when the reader's definition has a default
  (otherwise a required field fails, an optional one is simply absent);
* explicit ``null`` is judged against the reader's own nullable rule;
* no implicit string<->number or decimal->integer coercion;
* integer -> decimal is lossless only when the reader's decimal has room.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

from .domain import index_fields

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass
class Finding:
    direction: str          # old_reader | new_reader
    path: str
    code: str
    severity: str
    message: str

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "path": self.path,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class CompatibilityReport:
    findings: list[Finding] = dc_field(default_factory=list)

    def add(self, direction: str, path: str, code: str, severity: str, message: str) -> None:
        self.findings.append(Finding(direction, path, code, severity, message))

    def _verdict(self, direction: str) -> str:
        scoped = [f for f in self.findings if f.direction == direction]
        if any(f.severity == SEVERITY_ERROR for f in scoped):
            return "incompatible"
        if any(f.severity == SEVERITY_WARNING for f in scoped):
            return "compatible_with_warnings"
        return "compatible"

    def as_dict(self, old_version: str, new_version: str) -> dict:
        old_verdict = self._verdict("old_reader")
        new_verdict = self._verdict("new_reader")
        if "incompatible" in (old_verdict, new_verdict):
            overall = "incompatible"
        elif "compatible_with_warnings" in (old_verdict, new_verdict):
            overall = "compatible_with_warnings"
        else:
            overall = "compatible"
        return {
            "old_version": old_version,
            "new_version": new_version,
            "overall": overall,
            "old_reader_verdict": old_verdict,
            "new_reader_verdict": new_verdict,
            "findings": [f.as_dict() for f in self.findings],
        }


def _type_pair_compatible(source: dict, reader: dict, direction: str,
                          path: str, report: CompatibilityReport) -> None:
    """Can a value produced for ``source`` be read by the ``reader`` definition?"""
    st, rt = source["type"], reader["type"]
    if st == rt:
        if st == "decimal":
            _check_decimal_bounds(source, reader, direction, path, report)
        elif st == "object":
            _compare_children(source.get("fields", []), reader.get("fields", []),
                              direction, path, report)
        elif st == "array":
            # array items are always present in full when the array itself is;
            # recurse with item-level required/nullable semantics reset below.
            _compare_items(source["items"], reader["items"], direction, path, report)
        return

    # integer -> decimal: lossless when reader precision holds every integer
    if st == "integer" and rt == "decimal":
        reader_int_digits = reader["precision"] - reader["scale"]
        if reader_int_digits >= 18:
            report.add(direction, path, "int_to_decimal", SEVERITY_INFO,
                       f"integer 可无损读成 decimal({reader['precision']},{reader['scale']})")
        else:
            report.add(direction, path, "int_to_decimal_risk", SEVERITY_WARNING,
                       f"integer 读成 decimal({reader['precision']},{reader['scale']})："
                       f"仅 {reader_int_digits} 个整数位，超过即溢出")
        return
    if st == "decimal" and rt == "integer":
        report.add(direction, path, "decimal_to_int", SEVERITY_ERROR,
                   "decimal 不能自动读成 integer，禁止隐式截断/取整")
        return

    if {st, rt} & {"text"} and st != rt:
        report.add(direction, path, "string_coercion", SEVERITY_ERROR,
                   f"{st} 与 {rt} 之间不做隐式字符串转换")
        return

    if "date" in (st, rt) and st != rt:
        report.add(direction, path, "date_type_change", SEVERITY_ERROR,
                   f"date 与 {rt if st == 'date' else st} 类型不兼容")
        return

    if "boolean" in (st, rt) and st != rt:
        report.add(direction, path, "bool_type_change", SEVERITY_ERROR,
                   f"boolean 与 {rt if st == 'boolean' else st} 类型不兼容")
        return

    if st in ("object", "array") or rt in ("object", "array"):
        report.add(direction, path, "structure_type_change", SEVERITY_ERROR,
                   f"{st} 与 {rt} 结构类型不兼容")
        return

    report.add(direction, path, "type_change", SEVERITY_ERROR,
               f"{st} 与 {rt} 类型不兼容")


def _check_decimal_bounds(source: dict, reader: dict, direction: str,
                          path: str, report: CompatibilityReport) -> None:
    sp, ss = source["precision"], source["scale"]
    rp, rs = reader["precision"], reader["scale"]
    if rp < sp:
        report.add(direction, path, "precision_narrowed", SEVERITY_WARNING,
                   f"读取方总位数 {rp} 小于数据声明 {sp}，大值会溢出")
    if rs < ss:
        report.add(direction, path, "scale_narrowed", SEVERITY_ERROR,
                   f"读取方小数位 {rs} 小于数据声明 {ss}，无法无损表示小数部分")
    if (sp - ss) > (rp - rs):
        report.add(direction, path, "integer_part_narrowed", SEVERITY_WARNING,
                   f"读取方整数位 {rp - rs} 小于数据声明 {sp - ss}")


def _nullability(source: dict, reader: dict, direction: str,
                 path: str, report: CompatibilityReport) -> None:
    if source.get("nullable", True) and not reader.get("nullable", True):
        report.add(direction, path, "null_not_allowed", SEVERITY_ERROR,
                   "数据侧允许 null，读取方声明不可为空：显式 null 将被拒绝")


def _presence(source: dict, reader: dict, direction: str,
              path: str, report: CompatibilityReport) -> None:
    """Reader may encounter an absent key (field missing on the data side)."""
    if reader.get("has_default"):
        if not source.get("has_default"):
            report.add(direction, path, "default_fills", SEVERITY_INFO,
                       "数据中缺字段时，读取方用自身默认值补齐")
        return
    if reader.get("required", False) and not source.get("required", False):
        report.add(direction, path, "missing_required", SEVERITY_ERROR,
                   "读取方要求必填且无默认值，但数据侧该字段可能缺失")


def _compare_items(source_item: dict, reader_item: dict, direction: str,
                   path: str, report: CompatibilityReport) -> None:
    item_path = f"{path}[]"
    _type_pair_compatible(source_item, reader_item, direction, item_path, report)
    _nullability(source_item, reader_item, direction, item_path, report)


def _compare_children(source_fields: list[dict], reader_fields: list[dict],
                      direction: str, base_path: str, report: CompatibilityReport) -> None:
    source_lookup = index_fields(source_fields)
    reader_lookup = index_fields(reader_fields)

    source_canonical = {f["name"]: f for f in source_fields}
    reader_canonical = {f["name"]: f for f in reader_fields}

    for reader in reader_fields:
        path = f"{base_path}.{reader['name']}" if base_path else f"$.{reader['name']}"
        match = _match_source_field(reader, source_lookup)
        if match is None:
            # reader knows a field the data file never carries
            if reader.get("has_default"):
                report.add(direction, path, "default_fills", SEVERITY_INFO,
                           "新文件没有该字段，读取方用默认值补齐")
            elif reader.get("required", False):
                report.add(direction, path, "missing_required", SEVERITY_ERROR,
                           "新文件缺少该必填字段且读取方没有默认值")
            else:
                report.add(direction, path, "optional_absent", SEVERITY_INFO,
                           "新文件没有该可选字段，按缺失处理")
            continue
        _type_pair_compatible(match, reader, direction, path, report)
        _nullability(match, reader, direction, path, report)
        _presence(match, reader, direction, path, report)

    for source in source_fields:
        if source["name"] in reader_canonical:
            continue
        # aliases: a reader may still know the field under an old name, but
        # only when the canonical names genuinely differ (a rename, not a
        # shared-name field that was already compared above)
        aliased = reader_lookup.get(source["name"])
        path = f"{base_path}.{source['name']}" if base_path else f"$.{source['name']}"
        if aliased is not None and aliased["name"] != source["name"]:
            report.add(direction, path, "alias_read", SEVERITY_INFO,
                       f"读取方通过别名 {source['name']!r} 读取为 {aliased['name']!r}")
            continue
        report.add(direction, path, "undeclared_ignored", SEVERITY_INFO,
                   "读取方未声明该字段，按规则统一忽略")


def _match_source_field(reader: dict, source_lookup: dict[str, dict]) -> Optional[dict]:
    if reader["name"] in source_lookup:
        return source_lookup[reader["name"]]
    for alias in reader.get("aliases", []):
        if alias in source_lookup:
            return source_lookup[alias]
    return None


def compare_versions(old_fields: list[dict], new_fields: list[dict]) -> CompatibilityReport:
    report = CompatibilityReport()
    # Old program reads a NEW file: source=new, reader=old
    _compare_children(new_fields, old_fields, "old_reader", "$", report)
    # New program reads an OLD file: source=old, reader=new
    _compare_children(old_fields, new_fields, "new_reader", "$", report)

    # Explicit rename semantics: new reader can use aliases on old files,
    # but the old reader can never understand the new canonical name.
    old_names = {f["name"] for f in old_fields}
    new_names = {f["name"] for f in new_fields}
    for new_field in new_fields:
        for alias in new_field.get("aliases", []):
            if alias in old_names and new_field["name"] not in old_names:
                path = f"$.{new_field['name']}"
                report.add("new_reader", path, "rename_alias", SEVERITY_INFO,
                           f"新版本通过别名 {alias!r} 读取旧文件的同名字段，改名可被新读取方识别")
                if _old_required_no_default(alias, old_fields):
                    report.add("old_reader", path, "rename_unknown", SEVERITY_ERROR,
                               f"旧版本只认识 {alias!r}，不会自动理解新字段名 "
                               f"{new_field['name']!r}：新文件里该字段对旧程序不可见，"
                               "且旧定义必填无默认值将报错")
                else:
                    report.add("old_reader", path, "rename_unknown", SEVERITY_INFO,
                               f"旧版本只认识 {alias!r}，不会自动理解新字段名 "
                               f"{new_field['name']!r}：新文件里该字段对旧程序不可见，"
                               "按未声明字段忽略（旧定义可选或有默认值）")
    return report


def _old_required_no_default(name: str, old_fields: list[dict]) -> bool:
    for field in old_fields:
        if field["name"] == name:
            return field.get("required", False) and not field.get("has_default")
    return False
