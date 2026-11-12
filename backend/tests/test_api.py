"""End-to-end API workflow: draft -> lock -> upload -> compare -> map."""
from io import BytesIO


def _make_schema(client, name="orders"):
    r = client.post("/api/schemas", json={"name": name, "description": "d"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _version(client, schema_id, version, fields, note=""):
    r = client.post(f"/api/schemas/{schema_id}/versions",
                    json={"version": version, "note": note, "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()["id"]


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


def test_full_workflow(client):
    schema_id = _make_schema(client, f"wf_{id(object())}")
    v1 = _version(client, schema_id, "1.0", V1_FIELDS)
    v2 = _version(client, schema_id, "2.0", V2_FIELDS)

    # locked structure rejects edits
    client.post(f"/api/versions/{v1}/lock")
    r = client.put(f"/api/versions/{v1}/draft", json={"fields": V1_FIELDS})
    assert r.status_code == 409
    client.post(f"/api/versions/{v2}/lock")

    # compatibility: rename + array item change + new required-with-default
    r = client.post("/api/compatibility",
                    json={"old_version_id": v1, "new_version_id": v2})
    assert r.status_code == 200
    report = r.json()
    codes = {(f["direction"], f["code"]) for f in report["findings"]}
    assert ("new_reader", "rename_alias") in codes
    assert ("old_reader", "rename_unknown") in codes
    assert report["overall"] == "incompatible"  # array text->integer + rename

    # upload a JSONL with the five required sample scenarios
    jsonl = "\n".join([
        '{"sku":"S1","qty":2,"price":10,"tags":["a"],"day":"2026-11-13"}',
        '{"sku":"S2","qty":1,"price":null,"tags":[],"day":"2026-02-30"}',
        '{"sku":"S3","qty":1,"price":"99.999","tags":[]}',
        '{"qty":1,"price":"1.00","tags":[]}',
        '{"sku":"S5","qty":"1","price":"1.00","tags":[]}',
    ])
    r = client.post(
        f"/api/versions/{v1}/uploads",
        files={"file": ("sample.jsonl", BytesIO(jsonl.encode()), "application/x-ndjson")},
    )
    assert r.status_code == 201, r.text
    upload = r.json()
    assert upload["total_lines"] == 5
    assert upload["problem_count"] == 4
    by_line = {row["line"]: row for row in upload["lines"]}
    # line 1: integer 10 reads losslessly into decimal -> clean
    assert by_line[1]["ok"] is True
    # line 2: explicit null on nullable decimal is fine, but Feb 30 invalid
    assert any(i["code"] == "invalid_date" for i in by_line[2]["issues"])
    # line 3: decimal scale overflow (99.999 vs scale=2)
    assert any(i["code"] == "decimal_scale" for i in by_line[3]["issues"])
    # line 4: missing required sku
    assert any(i["code"] == "missing_required" for i in by_line[4]["issues"])
    # line 5: string never coerces to integer
    assert any(i["code"] == "type_mismatch" and i["path"] == "$.qty"
               for i in by_line[5]["issues"])
    upload_id = upload["upload_id"]

    # explicit mapping draft, then generate
    rules = [
        {"action": "rename", "source": "sku", "target": "product_code"},
        {"action": "set_default", "target": "active", "value": True},
    ]
    r = client.post("/api/mappings/preview", json={
        "source_version_id": v1, "target_version_id": v2,
        "rules": rules, "upload_id": upload_id,
    })
    assert r.status_code == 201, r.text
    preview = r.json()
    assert preview["status"] == "draft"
    mapping_id = preview["mapping_id"]

    r = client.post("/api/mappings/generate", json={"mapping_id": mapping_id})
    assert r.status_code == 200, r.text
    generated = r.json()
    assert generated["status"] == "generated"

    # generation is one-shot
    r = client.post("/api/mappings/generate", json={"mapping_id": mapping_id})
    assert r.status_code == 409

    # artifact is downloadable JSONL
    r = client.get(generated["download_url"])
    assert r.status_code == 200
    assert len(r.text.strip().splitlines()) == 5


def test_draft_is_editable_and_validates_structure(client):
    schema_id = _make_schema(client, f"ed_{id(object())}")
    r = client.post(f"/api/schemas/{schema_id}/versions",
                    json={"version": "0.1", "fields": []})
    vid = r.json()["id"]
    bad = [{"name": "x", "type": "decimal", "precision": 4, "scale": 6}]
    r = client.put(f"/api/versions/{vid}/draft", json={"fields": bad})
    assert r.status_code == 422
    good = [{"name": "x", "type": "decimal", "precision": 6, "scale": 2}]
    r = client.put(f"/api/versions/{vid}/draft", json={"fields": good})
    assert r.status_code == 200


def test_mapping_requires_locked_versions(client):
    schema_id = _make_schema(client, f"lk_{id(object())}")
    v1 = _version(client, schema_id, "1.0", V1_FIELDS)
    v2 = _version(client, schema_id, "2.0", V2_FIELDS)
    r = client.post("/api/mappings/preview", json={
        "source_version_id": v1, "target_version_id": v2,
        "rules": [], "inline_records": [],
    })
    assert r.status_code == 409
