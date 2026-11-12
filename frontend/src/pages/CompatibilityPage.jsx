import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

function VersionPicker({ schemas, label, value, onChange }) {
  const [schemaId, setSchemaId] = useState('')
  const versions = useMemo(
    () => schemas.find((s) => String(s.id) === String(schemaId))?.versions || [],
    [schemas, schemaId],
  )

  return (
    <div className="row">
      <strong style={{ minWidth: 130 }}>{label}</strong>
      <select
        value={schemaId}
        onChange={(e) => { setSchemaId(e.target.value); onChange('') }}
      >
        <option value="">选择数据集…</option>
        {schemas.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">选择版本…</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version}（{v.status === 'locked' ? '已锁定' : '草稿'}）
          </option>
        ))}
      </select>
    </div>
  )
}

const VERDICT_TEXT = {
  compatible: '兼容',
  compatible_with_warnings: '兼容但有警告',
  incompatible: '不兼容',
}

export default function CompatibilityPage() {
  const [schemas, setSchemas] = useState([])
  const [oldId, setOldId] = useState('')
  const [newId, setNewId] = useState('')
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.listSchemas().then(async (list) => {
      const detailed = await Promise.all(list.map((s) => api.getSchema(s.id)))
      setSchemas(detailed)
    })
  }, [])

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      setReport(await api.compare({
        old_version_id: Number(oldId),
        new_version_id: Number(newId),
      }))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const groups = report
    ? { old_reader: [], new_reader: [] }
    : null
  if (report) {
    for (const f of report.findings) groups[f.direction].push(f)
  }

  return (
    <div>
      <div className="panel">
        <h2>两版双向兼容性对比</h2>
        <p className="muted small">
          分别站在「旧读取方读新文件」和「新读取方读旧文件」两个方向检查；
          未声明字段统一忽略、缺字段仅在有默认值时补齐、显式 null 按可空规则判断。
        </p>
        <VersionPicker schemas={schemas} label="旧版本" value={oldId} onChange={setOldId} />
        <div style={{ height: 8 }} />
        <VersionPicker schemas={schemas} label="新版本" value={newId} onChange={setNewId} />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={!oldId || !newId || busy} onClick={run}>
            {busy ? '分析中…' : '开始对比'}
          </button>
        </div>
        {error && <p className="error-text small">{error}</p>}
      </div>

      {report && (
        <div className="panel">
          <div className={`verdict-box ${report.overall}`}>
            <strong>总体结论：{VERDICT_TEXT[report.overall]}</strong>
            <div className="small" style={{ marginTop: 6 }}>
              旧程序读新文件：
              <span className={`badge ${report.old_reader_verdict === 'incompatible' ? 'error' : report.old_reader_verdict === 'compatible' ? 'ok' : 'warning'}`}>
                {VERDICT_TEXT[report.old_reader_verdict]}
              </span>{' '}
              ／ 新程序读旧文件：
              <span className={`badge ${report.new_reader_verdict === 'incompatible' ? 'error' : report.new_reader_verdict === 'compatible' ? 'ok' : 'warning'}`}>
                {VERDICT_TEXT[report.new_reader_verdict]}
              </span>
            </div>
          </div>

          {['old_reader', 'new_reader'].map((dir) => (
            <div key={dir}>
              <h3>{dir === 'old_reader' ? '旧读取方（旧程序读新文件）' : '新读取方（新程序读旧文件）'}</h3>
              {groups[dir].length === 0 && <p className="muted small">无发现，完全兼容。</p>}
              {groups[dir].map((f, i) => (
                <div key={i} className={`finding ${f.severity}`}>
                  <div className="row">
                    <span className={`badge ${f.severity}`}>{f.severity}</span>
                    <span className="mono">{f.path}</span>
                    <span className="badge info">{f.code}</span>
                  </div>
                  <div className="small" style={{ marginTop: 4 }}>{f.message}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
