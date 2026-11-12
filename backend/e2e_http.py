"""End-to-end HTTP smoke test against a running uvicorn server.

Usage:  ../.venv/bin/python -I e2e_http.py [base_url]
Asserts every headline rule through the real API boundary.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SAMPLES = Path(__file__).resolve().parent / "samples"

V1 = [
    {"name": "sku", "type": "text", "required": True, "nullable": False},
    {"name": "qty", "type": "integer", "required": True, "nullable": False},
    {"name": "price", "type": "decimal", "required": False, "nullable": True,
     "precision": 8, "scale": 2},
    {"name": "tags", "type": "array", "required": False, "nullable": True,
     "items": {"name": "_items", "type": "text"}},
    {"name": "day", "type": "date", "required": False, "nullable": True},
]
V2 = [
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


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label} {detail}")
    if not condition:
        raise SystemExit(f"断言失败: {label} {detail}")


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=10)
    assert c.get("/api/health").json()["status"] == "ok"

    name = f"e2e_demo_{__import__('time').time_ns()}"
    sid = c.post("/api/schemas", json={"name": name}).json()["id"]
    v1 = c.post(f"/api/schemas/{sid}/versions",
                json={"version": "1.0", "fields": V1}).json()["id"]
    v2 = c.post(f"/api/schemas/{sid}/versions",
                json={"version": "2.0", "fields": V2}).json()["id"]
    print("1) 结构维护：草稿创建成功")

    # malformed structure rejected
    bad = c.post(f"/api/schemas/{sid}/versions", json={
        "version": "bad",
        "fields": [{"name": "x", "type": "decimal", "precision": 4, "scale": 6}],
    })
    check("结构定义非法时返回 422", bad.status_code == 422)

    c.post(f"/api/versions/{v1}/lock")
    c.post(f"/api/versions/{v2}/lock")
    locked = c.put(f"/api/versions/{v1}/draft", json={"fields": V1})
    check("锁定版本拒绝结构修改 (409)", locked.status_code == 409)

    print("2) JSONL 上传逐行检查")
    with (SAMPLES / "v1_data.jsonl").open("rb") as fh:
        up = c.post(
            f"/api/versions/{v1}/uploads",
            files={"file": ("v1_data.jsonl", fh, "application/x-ndjson")},
        ).json()
    check("5 行样本识别", up["total_lines"] == 5)
    check("4 行有问题", up["problem_count"] == 4, f"实际 {up['problem_count']}")
    codes = {(row["line"], i["code"]) for row in up["lines"] for i in row["issues"]}
    check("非法日期", (2, "invalid_date") in codes)
    check("小数越界(scale)", (3, "decimal_scale") in codes)
    check("缺必填", (4, "missing_required") in codes)
    check("字符串不转整数", (5, "type_mismatch") in codes)
    check("第1行整数无损入 decimal", up["lines"][0]["ok"] is True)

    print("3) 双向兼容性")
    rep = c.post("/api/compatibility",
                 json={"old_version_id": v1, "new_version_id": v2}).json()
    findings = {(f["direction"], f["code"]) for f in rep["findings"]}
    check("总体不兼容", rep["overall"] == "incompatible")
    check("新读取方识别改名别名", ("new_reader", "rename_alias") in findings)
    check("旧读取方不认识新字段名", ("old_reader", "rename_unknown") in findings)
    check("数组元素类型变化报错",
          any(f["direction"] == "old_reader" and f["path"] == "$.tags[]"
              for f in rep["findings"]))
    check("可空收紧导致 null 报错", ("new_reader", "null_not_allowed") in findings)

    print("4) 显式映射：草稿 -> 预览 -> 生成")
    rules = [
        {"action": "rename", "source": "sku", "target": "product_code"},
        {"action": "set_default", "target": "active", "value": True},
    ]
    pv = c.post("/api/mappings/preview", json={
        "source_version_id": v1, "target_version_id": v2,
        "rules": rules, "upload_id": up["upload_id"],
    })
    check("预览创建成功 (201)", pv.status_code == 201, pv.text)
    preview = pv.json()
    check("预览为草稿态", preview["status"] == "draft")
    check("含逐行变化", all("changes" in r for r in preview["rows"]))
    mid = preview["mapping_id"]

    gen = c.post("/api/mappings/generate", json={"mapping_id": mid}).json()
    check("生成一次后状态为 generated", gen["status"] == "generated")
    again = c.post("/api/mappings/generate", json={"mapping_id": mid})
    check("重复生成被拒绝 (409)", again.status_code == 409)

    artifact = c.get(gen["download_url"])
    check("产物可下载且为 5 行 JSONL",
          artifact.status_code == 200 and len(artifact.text.strip().splitlines()) == 5)
    first = json.loads(artifact.text.splitlines()[0])
    check("改名规则生效", "product_code" in first and "sku" not in first)
    check("默认值补齐", first.get("active") is True)

    print("\n全部端到端断言通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
