import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function SchemaListPage({ onOpen }) {
  const [schemas, setSchemas] = useState([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    setSchemas(await api.listSchemas())
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    setError('')
    try {
      const created = await api.createSchema({ name: name.trim(), description })
      setName('')
      setDescription('')
      onOpen(created.id)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div>
      <div className="panel">
        <h2>数据集</h2>
        <div className="row">
          <input
            className="grow"
            placeholder="数据集名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="grow"
            placeholder="说明（可选）"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button className="btn" onClick={create} disabled={!name.trim()}>
            新建数据集
          </button>
        </div>
        {error && <p className="error-text small">{error}</p>}
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>名称</th><th>说明</th><th>版本数</th><th>创建时间</th><th />
            </tr>
          </thead>
          <tbody>
            {schemas.map((s) => (
              <tr key={s.id}>
                <td className="mono">{s.name}</td>
                <td>{s.description}</td>
                <td>{s.version_count}</td>
                <td className="small muted">{s.created_at}</td>
                <td>
                  <button className="clickable" onClick={() => onOpen(s.id)}>
                    打开 →
                  </button>
                </td>
              </tr>
            ))}
            {schemas.length === 0 && (
              <tr><td colSpan="5" className="muted">还没有数据集，先新建一个。</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
