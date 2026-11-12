"""End-to-end demonstration using only the domain layer (no server required).

Run from the backend directory:

    ../.venv/bin/python -I seed_demo.py

It exercises the five required sample scenarios against the two locked schema
versions, prints every line-level finding, the bidirectional compatibility
verdicts, and finally the explicit mapping draft + generated JSONL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.compat import compare_versions
from app.domain import normalise_structure
from app.mapping import preview_mapping, render_jsonl
from app.validation import validate_jsonl

SAMPLES = Path(__file__).resolve().parent / "samples"
OUTPUT = Path(__file__).resolve().parent / "data" / "demo_output"

V1_FIELDS = [
    {"name": "sku", "type": "text", "required": True, "nullable": False},
    {"name": "qty", "type": "integer", "required": True, "nullable": False},
    {"name": "price", "type": "decimal", "required": False, "nullable": True,
     "precision": 8, "scale": 2},
    {"name": "tags", "type": "array", "required": False, "nullable": True,
     "items": {"name": "_items", "type": "text"}},
    {"name": "day", "type": "date", "required": False, "nullable": True},
]

V2_FIELDS = [
    {"name": "product_code", "type": "text", "required": True, "nullable": False,
     "aliases": ["sku"]},
    {"name": "qty", "type": "integer", "required": True, "nullable": False},
    {"name": "price", "type": "decimal", "required": True, "nullable": False,
     "has_default": True, "default": "0.00", "precision": 10, "scale": 2},
    {"name": "tags", "type": "array", "required": False, "nullable": True,
     "items": {"name": "_items", "type": "integer"}},
    {"name": "day", "type": "date", "required": False, "nullable": True},
    {"name": "active", "type": "boolean", "required": True, "nullable": False,
     "has_default": True, "default": True},
]


def main() -> int:
    v1 = normalise_structure(V1_FIELDS)
    v2 = normalise_structure(V2_FIELDS)

    print("=" * 70)
    print("1) JSONL 逐行校验（问题定位到行号与嵌套字段）")
    print("=" * 70)
    text = (SAMPLES / "v1_data.jsonl").read_text(encoding="utf-8")
    report = validate_jsonl(text, v1)
    for row in report["lines"]:
        status = "PASS" if row["ok"] else "FAIL"
        print(f"  第 {row['line']} 行 [{status}]")
        for issue in row["issues"]:
            print(f"      {issue['path']}  {issue['code']}  {issue['message']}")
    print(f"  汇总: {report['ok_lines']}/{report['total_lines']} 行通过\n")

    print("=" * 70)
    print("2) 两版双向兼容性（分别站在新旧读取方）")
    print("=" * 70)
    result = compare_versions(v1, v2).as_dict("v1", "v2")
    print(f"  总体结论: {result['overall']}")
    print(f"  旧程序读新文件: {result['old_reader_verdict']}")
    print(f"  新程序读旧文件: {result['new_reader_verdict']}")
    for finding in result["findings"]:
        print(f"  [{finding['direction']:<10}] {finding['severity']:<7} "
              f"{finding['path']:<18} {finding['code']:<22} {finding['message']}")
    print()

    print("=" * 70)
    print("3) 显式映射：先展示草稿与变化，再生成新文件")
    print("=" * 70)
    rules = json.loads((SAMPLES / "mapping_rules.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    preview = preview_mapping(records, rules, v2)
    for row in preview["rows"]:
        print(f"  第 {row['row']} 行 目标校验: "
              f"{'有效' if row['valid_against_target'] else '仍有问题'}")
        for change in row["changes"]:
            print(f"      {change['type']}: {json.dumps(change, ensure_ascii=False)}")
    for warning in preview["warnings"]:
        print(f"  [warning] 第 {warning['row']} 行 {warning['message']}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT / "v2_generated.jsonl"
    out_path.write_text(render_jsonl(preview["rows"]), encoding="utf-8")
    print(f"\n  已生成: {out_path}")
    print("  注意：结构版本始终锁定；转换是独立的显式映射，不构成结构本身兼容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
