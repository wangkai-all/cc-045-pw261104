import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import FieldTreeEditor, { makeField, treeToPayload } from '../components/FieldTreeEditor'

export default function SchemaDetailPage({ schemaId, onBack, onOpenVersion }) {
  const [schema, setSchema] = useState(null)
  const [versionName, setVersionName] = useState('')
  const [note, setNote] = useState('')
  const [roots, setRoots] = useState([])
  const [feedback, setFeedback] = useState(null)

  const load = async () => {
    const data = await api.getSchema(schemaId)
    setSchema(data)
  }
  useEffect(() => { load() }, [schemaId])

  const createVersion = async () => {
    setFeedback(null)
    try {
      const created = await api.createVersion(schemaId, {
        version: versionName.trim(),
        note,
        fields: treeToPayload(roots),
      })
      setVersionName('')
      setNote('')
      setRoots([])
      await load()
      onOpenVersion(created.id)
    } catch (e) {
      setFeedback({ kind: 'error', message: e.message })
    }
  }

  if (!schema) return <p className="muted">加载中…</p>
  const locked = false

  return (
    <div>
      <button className="btn ghost" onClick={onBack}>← 返回数据集列表</button>

      <div className="panel">
        <h2>
          {schema.name} <span className="muted small">{schema.description}</span>
        </h2>
        <table>
          <thead>
            <tr><th>版本</th><th>状态</th><th>备注</th><th>创建时间</th><th /></tr>
          </thead>
          <tbody>
            {schema.versions.map((v) => (
              <tr key={v.id}>
                <td className="mono">{v.version}</td>
                <td><span className={`badge ${v.status}`}>{v.status === 'locked' ? '已锁定' : '草稿'}</span></td>
                <td>{v.note}</td>
                <td className="small muted">{v.created_at}</td>
                <td>
                  <button className="clickable" onClick={() => onOpenVersion(v.id)}>
                    管理 →
                  </button>
                </td>
              </tr>
            ))}
            {schema.versions.length === 0 && (
              <tr><td colSpan="5" className="muted">还没有版本。</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>新建结构版本（初始为草稿，可反复编辑；发布锁定后结构冻结）</h2>
        <div className="row">
          <input
            placeholder="版本号，例如 1.0 / 2.0"
            value={versionName}
            onChange={(e) => setVersionName(e.target.value)}
          />
          <input
            className="grow"
            placeholder="版本备注"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <h3>字段结构</h3>
        <FieldTreeEditor roots={roots} setRoots={setRoots} locked={locked} />
        <div className="row" style={{ marginTop: 14 }}>
          <button
            className="btn"
            disabled={!versionName.trim()}
            onClick={createVersion}
          >
            创建草稿版本
          </button>
        </div>
        {feedback && (
          <p className={feedback.kind === 'error' ? 'error-text' : 'ok-text'}>
            {feedback.message}
          </p>
        )}
      </div>
    </div>
  )
}
