"""FastAPI application: schema maintenance, compatibility, uploads, mappings."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import storage
from .compat import compare_versions
from .config import ARTIFACT_DIR
from .domain import StructureError, normalise_structure
from .mapping import MappingError, preview_mapping, render_jsonl, validate_mapping
from .schemas_api import (
    CompareRequest,
    DraftUpdate,
    MappingGenerateRequest,
    MappingRequest,
    SchemaCreate,
    VersionCreate,
)
from .validation import validate_jsonl


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="数据集结构版本与兼容性服务", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---- schemas ------------------------------------------------------------------

@app.post("/api/schemas", status_code=201)
def create_schema(payload: SchemaCreate) -> dict:
    with storage.db() as conn:
        try:
            schema_id = storage.create_schema(conn, payload.name, payload.description)
        except Exception as exc:  # sqlite IntegrityError on unique name
            raise HTTPException(409, f"数据集 {payload.name!r} 已存在") from exc
        return storage.get_schema(conn, schema_id)


@app.get("/api/schemas")
def list_schemas() -> list[dict]:
    with storage.db() as conn:
        return storage.list_schemas(conn)


@app.get("/api/schemas/{schema_id}")
def get_schema(schema_id: int) -> dict:
    with storage.db() as conn:
        schema = storage.get_schema(conn, schema_id)
        if schema is None:
            raise HTTPException(404, "数据集不存在")
        schema["versions"] = storage.list_versions(conn, schema_id)
        return schema


# ---- versions -----------------------------------------------------------------

@app.post("/api/schemas/{schema_id}/versions", status_code=201)
def create_version(schema_id: int, payload: VersionCreate) -> dict:
    try:
        fields = normalise_structure(payload.fields)
    except StructureError as exc:
        raise HTTPException(422, f"字段结构不合法: {exc}") from exc
    with storage.db() as conn:
        if storage.get_schema(conn, schema_id) is None:
            raise HTTPException(404, "数据集不存在")
        try:
            version_id = storage.create_version(conn, schema_id, payload.version,
                                                payload.note, fields)
        except Exception as exc:
            raise HTTPException(409, f"版本号 {payload.version!r} 已存在") from exc
        return storage.get_version(conn, version_id)


@app.get("/api/versions/{version_id}")
def get_version(version_id: int) -> dict:
    with storage.db() as conn:
        version = storage.get_version(conn, version_id)
        if version is None:
            raise HTTPException(404, "版本不存在")
        return version


@app.put("/api/versions/{version_id}/draft")
def update_draft(version_id: int, payload: DraftUpdate) -> dict:
    try:
        fields = normalise_structure(payload.fields)
    except StructureError as exc:
        raise HTTPException(422, f"字段结构不合法: {exc}") from exc
    with storage.db() as conn:
        try:
            storage.update_draft_fields(conn, version_id, fields, payload.note)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return storage.get_version(conn, version_id)


@app.post("/api/versions/{version_id}/lock")
def lock_version(version_id: int) -> dict:
    with storage.db() as conn:
        try:
            storage.lock_version(conn, version_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return storage.get_version(conn, version_id)


# ---- compatibility ------------------------------------------------------------

@app.post("/api/compatibility")
def compatibility(payload: CompareRequest) -> dict:
    with storage.db() as conn:
        old = storage.get_version(conn, payload.old_version_id)
        new = storage.get_version(conn, payload.new_version_id)
        if old is None or new is None:
            raise HTTPException(404, "参与比较的版本不存在")
        report = compare_versions(old["fields"], new["fields"])
        return report.as_dict(old["version"], new["version"])


# ---- JSONL upload -------------------------------------------------------------

@app.post("/api/versions/{version_id}/uploads", status_code=201)
async def upload_jsonl(version_id: int, file: UploadFile = File(...)) -> dict:
    if not file.filename.lower().endswith(".jsonl"):
        raise HTTPException(422, "仅接受 .jsonl 文件")
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, f"文件不是 UTF-8 编码: {exc}") from exc

    with storage.db() as conn:
        version = storage.get_version(conn, version_id)
        if version is None:
            raise HTTPException(404, "版本不存在")
        report = validate_jsonl(text, version["fields"])
        source_path = ARTIFACT_DIR / f"upload_v{version_id}_{file.filename}"
        source_path.write_text(text, encoding="utf-8")
        upload_id = storage.save_upload(conn, version_id, file.filename, report,
                                        str(source_path))
        return {"upload_id": upload_id, **report}


@app.get("/api/versions/{version_id}/uploads")
def list_uploads(version_id: int) -> list[dict]:
    with storage.db() as conn:
        return storage.list_uploads(conn, version_id)


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: int) -> dict:
    with storage.db() as conn:
        upload = storage.get_upload(conn, upload_id)
        if upload is None:
            raise HTTPException(404, "上传记录不存在")
        return upload


# ---- explicit mapping / transformation ---------------------------------------

@app.post("/api/mappings/preview", status_code=201)
def mapping_preview(payload: MappingRequest) -> dict:
    rules = [r.model_dump(exclude_none=True) for r in payload.rules]
    try:
        validate_mapping(rules)
    except MappingError as exc:
        raise HTTPException(422, f"映射规则不合法: {exc}") from exc

    with storage.db() as conn:
        source = storage.get_version(conn, payload.source_version_id)
        target = storage.get_version(conn, payload.target_version_id)
        if source is None or target is None:
            raise HTTPException(404, "源或目标版本不存在")
        if source["status"] != "locked" or target["status"] != "locked":
            raise HTTPException(409, "结构版本必须先锁定，才能进行数据转换")

        if payload.upload_id is not None:
            upload = storage.get_upload(conn, payload.upload_id)
            if upload is None:
                raise HTTPException(404, "上传记录不存在")
            if upload["version_id"] != source["id"]:
                raise HTTPException(422, "上传数据的结构版本与映射源版本不一致")
            records = _read_jsonl_records(Path(upload["source_path"]))
        elif payload.inline_records is not None:
            records = payload.inline_records
        else:
            raise HTTPException(422, "需要 upload_id 或 inline_records 作为转换数据源")

        try:
            preview = preview_mapping(records, rules, target["fields"])
        except MappingError as exc:
            raise HTTPException(422, f"转换失败: {exc}") from exc

        mapping_id = storage.save_mapping(
            conn, source["id"], target["id"], rules, preview, artifact_path=None
        )
        return {"mapping_id": mapping_id, "status": "draft", **preview}


@app.post("/api/mappings/generate")
def mapping_generate(payload: MappingGenerateRequest) -> dict:
    with storage.db() as conn:
        mapping = storage.get_mapping(conn, payload.mapping_id)
        if mapping is None:
            raise HTTPException(404, "映射草稿不存在")
        if mapping["status"] == "generated":
            raise HTTPException(409, "该映射已生成过文件，转换不可重复执行")
        target = storage.get_version(conn, mapping["target_version_id"])
        content = render_jsonl(mapping["preview"]["rows"])
        artifact = ARTIFACT_DIR / f"mapping_{mapping['id']}_v{target['version']}.jsonl"
        artifact.write_text(content, encoding="utf-8")
        conn.execute(
            "UPDATE mappings SET status='generated', artifact_path=? WHERE id=?",
            (str(artifact), mapping["id"]),
        )
        return {
            "mapping_id": mapping["id"],
            "status": "generated",
            "artifact_path": str(artifact),
            "download_url": f"/api/mappings/{mapping['id']}/artifact",
            "rows": len(mapping["preview"]["rows"]),
        }


@app.get("/api/mappings/{mapping_id}")
def get_mapping(mapping_id: int) -> dict:
    with storage.db() as conn:
        mapping = storage.get_mapping(conn, mapping_id)
        if mapping is None:
            raise HTTPException(404, "映射不存在")
        return mapping


@app.get("/api/mappings/{mapping_id}/artifact")
def download_artifact(mapping_id: int) -> FileResponse:
    with storage.db() as conn:
        mapping = storage.get_mapping(conn, mapping_id)
        if mapping is None or not mapping.get("artifact_path"):
            raise HTTPException(404, "转换文件尚未生成")
        path = Path(mapping["artifact_path"])
    if not path.exists():
        raise HTTPException(404, "转换文件已丢失")
    return FileResponse(path, filename=path.name, media_type="application/x-ndjson")


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise HTTPException(404, "上传的源文件已丢失")
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"源文件第 {lineno} 行不是合法 JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise HTTPException(422, f"源文件第 {lineno} 行不是 JSON 对象")
        records.append(record)
    return records
