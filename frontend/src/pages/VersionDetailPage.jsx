import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import FieldTreeEditor, { treeToPayload, fromPayload } from '../components/FieldTreeEditor'
import UploadPanel from '../components/UploadPanel'

export default function VersionDetailPage({ versionId, onBack }) {
  const [version, setVersion] = useState(null)
  const [roots, setRoots] = useState([])
  const [message, setMessage] = useState(null)
  const [uploads, setUploads] = useState([])

  const load = async () => {
    const data = await api.getVersion(versionId)
    setVersion(data)
    setRoots(fromPayload(data.fields))
    setUploads(await api.listUploads(versionId))
  }
  useEffect(() => { load() }, [versionId])

  const locked = version?.status === 'locked'

  const saveDraft = async () => {
    setMessage(null)
    try {
      const updated = await api.updateDraft(versionId, { fields: treeToPayload(roots) })
      setVersion(updated)
      setMessage({ kind: 'ok', text: '草稿已保存' })
    } catch (e) {
      setMessage({ kind: 'error', text: e.message })
    }
  }

  const lock = async () => {
    setMessage(null)
    try {
      const updated = await api.lockVersion(versionId)
      setVersion(updated)
      setMessage({ kind: 'ok', text: '结构版本已锁定，此后字段结构不可修改' })
    } catch (e) {
      setMessage({ kind: 'error', text: e.message })
    }
  }

  if (!version) return <p className="muted">加载中…</p>

  return (
    <div>
      <button className="btn ghost" onClick={onBack}>← 返回数据集</button>

      <div className="panel">
        <h2>
          版本 {version.version}{' '}
          <span className={`badge ${version.status}`}>
            {locked ? '已锁定' : '草稿'}
          </span>
        </h2>
        <p className="muted small">{version.note}</p>

        <FieldTreeEditor roots={roots} setRoots={setRoots} locked={locked} />

        {!locked && (
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn secondary" onClick={saveDraft}>保存草稿</button>
            <button
              className="btn"
              onClick={() => {
                if (window.confirm('锁定后结构将永久冻结，确认发布？')) lock()
              }}
            >
              发布并锁定
            </button>
          </div>
        )}
        {message && (
          <p className={message.kind === 'error' ? 'error-text' : 'ok-text'}>
            {message.text}
          </p>
        )}
      </div>

      <div className="panel">
        <h2>JSONL 上传逐行检查</h2>
        <UploadPanel versionId={versionId} onUploaded={load} uploads={uploads} />
      </div>
    </div>
  )
}
