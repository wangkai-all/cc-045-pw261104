import React, { useState } from 'react'
import { api } from '../api/client'

const SEVERITY_LABEL = {
  invalid_json: 'JSON 语法',
  missing_required: '缺必填',
  null_not_allowed: 'null 不允许',
  type_mismatch: '类型不符',
  decimal_overflow: '小数越界',
  decimal_scale: '小数位超限',
  invalid_date: '非法日期',
  duplicate_alias: '别名冲突',
}

export default function UploadPanel({ versionId, onUploaded, uploads }) {
  const [file, setFile] = useState(null)
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const upload = async () => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const result = await api.uploadJsonl(versionId, file)
      setReport(result)
      onUploaded?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="row">
        <input
          type="file"
          accept=".jsonl,application/x-ndjson"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button className="btn" disabled={!file || busy} onClick={upload}>
          {busy ? '检查中…' : '上传并逐行检查'}
        </button>
      </div>
      {error && <p className="error-text small">{error}</p>}

      {report && (
        <div style={{ marginTop: 14 }}>
          <div className="row">
            <span className="badge ok">{report.ok_lines}/{report.total_lines} 行通过</span>
            {report.problem_count > 0 && (
              <span className="badge error">{report.problem_count} 行有问题</span>
            )}
          </div>
          {report.lines.map((line) => (
            <div key={line.line} className={`line-card ${line.ok ? 'pass' : 'fail'}`}>
              <div className="row">
                <strong>第 {line.line} 行</strong>
                {line.ok
                  ? <span className="badge ok">通过</span>
                  : <span className="badge error">{line.issues.length} 个问题</span>}
              </div>
              {line.issues.map((issue, i) => (
                <div key={i} className="small" style={{ marginTop: 4 }}>
                  <span className="mono">{issue.path}</span>{' '}
                  <span className="badge warning">{SEVERITY_LABEL[issue.code] || issue.code}</span>{' '}
                  <span className="muted">{issue.message}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {uploads?.length > 0 && (
        <>
          <h3>历史上传</h3>
          <table>
            <thead>
              <tr><th>文件</th><th>行数</th><th>问题行</th><th>结果</th><th>时间</th></tr>
            </thead>
            <tbody>
              {uploads.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.filename}</td>
                  <td>{u.total_lines}</td>
                  <td>{u.problem_count}</td>
                  <td>
                    {u.passed
                      ? <span className="badge ok">全部通过</span>
                      : <span className="badge error">存在问题</span>}
                  </td>
                  <td className="small muted">{u.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
