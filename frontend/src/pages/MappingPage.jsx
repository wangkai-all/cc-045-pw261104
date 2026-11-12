import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

const ACTIONS = [
  ['rename', '改名 rename（source → target）'],
  ['cast_decimal', '显式转 decimal（整数/字符串 → decimal 字符串）'],
  ['set_default', '补默认值 set_default（target + value）'],
  ['drop', '丢弃字段 drop（source）'],
]

function emptyRule() {
  return { action: 'rename', source: '', target: '', value: '' }
}

export default function MappingPage() {
  const [schemas, setSchemas] = useState([])
  const [sourceId, setSourceId] = useState('')
  const [targetId, setTargetId] = useState('')
  const [uploadId, setUploadId] = useState('')
  const [sourceUploads, setSourceUploads] = useState([])
  const [rules, setRules] = useState([emptyRule()])
  const [preview, setPreview] = useState(null)
  const [generated, setGenerated] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.listSchemas().then(async (list) => {
      const detailed = await Promise.all(list.map((s) => api.getSchema(s.id)))
      setSchemas(detailed)
    })
  }, [])

  useEffect(() => {
    setUploadId('')
    setSourceUploads([])
    if (sourceId) {
      api.listUploads(sourceId).then(setSourceUploads)
    }
  }, [sourceId])

  const allVersions = schemas.flatMap((s) =>
    (s.versions || []).map((v) => ({ ...v, schemaName: s.name })),
  )

  const updateRule = (i, patch) => {
    setRules(rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }

  const runPreview = async () => {
    setBusy(true)
    setError('')
    setGenerated(null)
    try {
      const payloadRules = rules.map((r) => {
        const out = { action: r.action }
        if (r.action === 'set_default') {
          out.target = r.target
          out.value = parseValue(r.value)
        } else if (r.action === 'drop') {
          out.source = r.source
        } else {
          out.source = r.source
          out.target = r.target
        }
        return out
      })
      const result = await api.previewMapping({
        source_version_id: Number(sourceId),
        target_version_id: Number(targetId),
        rules: payloadRules,
        upload_id: uploadId ? Number(uploadId) : undefined,
      })
      setPreview(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const generate = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.generateMapping(preview.mapping_id)
      setGenerated(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="panel">
        <h2>显式数据转换（结构锁定后，独立于兼容性）</h2>
        <p className="muted small">
          先保存映射草稿并预览逐行 before/after 变化，确认后才生成新 JSONL 文件；
          转换能力不构成结构本身兼容，且每个草稿只允许生成一次。
        </p>

        <div className="row">
          <select className="grow" value={sourceId} onChange={(e) => { setSourceId(e.target.value); setUploadId('') }}>
            <option value="">源版本（已锁定）…</option>
            {allVersions.filter((v) => v.status === 'locked').map((v) => (
              <option key={v.id} value={v.id}>{v.schemaName} @ {v.version}</option>
            ))}
          </select>
          <select className="grow" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
            <option value="">目标版本（已锁定）…</option>
            {allVersions.filter((v) => v.status === 'locked').map((v) => (
              <option key={v.id} value={v.id}>{v.schemaName} @ {v.version}</option>
            ))}
          </select>
        </div>

        <h3>数据源（源版本下的历史上传）</h3>
        <select className="grow" value={uploadId} onChange={(e) => setUploadId(e.target.value)}>
          <option value="">选择已上传的 JSONL…</option>
          {sourceUploads.map((u) => (
            <option key={u.id} value={u.id}>
              {u.filename}（{u.total_lines} 行，{u.problem_count} 行有问题）
            </option>
          ))}
        </select>
        {sourceId && sourceUploads.length === 0 && (
          <p className="muted small">该源版本还没有上传记录，请先在版本管理页上传 JSONL。</p>
        )}

        <h3>映射规则</h3>
        {rules.map((rule, i) => (
          <div className="field-node" key={i}>
            <select value={rule.action} onChange={(e) => updateRule(i, { action: e.target.value })}>
              {ACTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            <div className="row" style={{ marginTop: 8 }}>
              {rule.action !== 'set_default' && (
                <input
                  className="grow"
                  placeholder="source 源字段（支持点号嵌套）"
                  value={rule.source}
                  onChange={(e) => updateRule(i, { source: e.target.value })}
                />
              )}
              {rule.action !== 'drop' && (
                <input
                  className="grow"
                  placeholder="target 目标字段"
                  value={rule.target}
                  onChange={(e) => updateRule(i, { target: e.target.value })}
                />
              )}
              {rule.action === 'set_default' && (
                <input
                  className="grow"
                  placeholder="value 默认值（true/false、数字或字符串）"
                  value={rule.value}
                  onChange={(e) => updateRule(i, { value: e.target.value })}
                />
              )}
              <button
                className="btn ghost"
                onClick={() => setRules(rules.filter((_, idx) => idx !== i))}
                disabled={rules.length === 1}
              >
                移除
              </button>
            </div>
          </div>
        ))}
        <div className="row">
          <button className="btn secondary" onClick={() => setRules([...rules, emptyRule()])}>
            + 规则
          </button>
          <button
            className="btn"
            disabled={!sourceId || !targetId || !uploadId || busy}
            onClick={runPreview}
          >
            {busy ? '处理中…' : '生成草稿预览'}
          </button>
        </div>
        {error && <p className="error-text small">{error}</p>}
      </div>

      {preview && (
        <div className="panel">
          <h2>
            映射草稿 #{preview.mapping_id}{' '}
            <span className="badge draft">{preview.status === 'draft' ? '草稿' : preview.status}</span>
          </h2>
          <div className="row">
            <span className="badge ok">有效行 {preview.valid_rows}/{preview.total_rows}</span>
            {preview.warnings.length > 0 && (
              <span className="badge warning">{preview.warnings.length} 条警告</span>
            )}
          </div>

          {preview.warnings.length > 0 && (
            <>
              <h3>警告</h3>
              {preview.warnings.slice(0, 20).map((w, i) => (
                <p key={i} className="small warning-text">第 {w.row} 行：{w.message}</p>
              ))}
            </>
          )}

          <h3>逐行变化（before → after）</h3>
          {preview.rows.map((row) => (
            <div key={row.row} className={`line-card ${row.valid_against_target ? 'pass' : 'fail'}`}>
              <div className="row">
                <strong>第 {row.row} 行</strong>
                <span className={`badge ${row.valid_against_target ? 'ok' : 'error'}`}>
                  {row.valid_against_target ? '符合目标结构' : '目标校验仍有问题'}
                </span>
              </div>
              {row.changes.map((c, i) => (
                <p key={i} className="small mono" style={{ margin: '4px 0' }}>
                  {c.type}: {JSON.stringify(c.before ?? null)} → {JSON.stringify(c.after ?? null)}
                </p>
              ))}
              {!row.valid_against_target && row.issues.map((iss, i) => (
                <p key={i} className="small error-text" style={{ margin: '2px 0' }}>
                  {iss.path} {iss.code} — {iss.message}
                </p>
              ))}
            </div>
          ))}

          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={busy || generated} onClick={generate}>
              {generated ? '已生成' : '确认并生成新 JSONL 文件'}
            </button>
            {generated && (
              <a className="btn secondary" href={generated.download_url} download>
                下载 {generated.rows} 行结果文件
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function parseValue(raw) {
  const text = raw.trim()
  if (text === 'true') return true
  if (text === 'false') return false
  if (text !== '' && !Number.isNaN(Number(text))) return Number(text)
  return text
}
