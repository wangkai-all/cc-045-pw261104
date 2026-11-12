import React, { useState } from 'react'
import SchemaListPage from './pages/SchemaListPage'
import SchemaDetailPage from './pages/SchemaDetailPage'
import VersionDetailPage from './pages/VersionDetailPage'
import CompatibilityPage from './pages/CompatibilityPage'
import MappingPage from './pages/MappingPage'

const TABS = [
  ['schemas', '数据集与版本'],
  ['compare', '版本兼容性对比'],
  ['mapping', '显式数据转换'],
]

export default function App() {
  const [tab, setTab] = useState('schemas')
  const [schemaId, setSchemaId] = useState(null)
  const [versionId, setVersionId] = useState(null)

  const openSchema = (id) => {
    setSchemaId(id)
    setVersionId(null)
    setTab('schemas')
  }

  const openVersion = (id) => {
    setVersionId(id)
    setTab('schemas')
  }

  return (
    <div>
      <header className="app-header">
        <h1>数据集结构版本与兼容性平台</h1>
        <nav className="tabs">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              className={tab === key ? 'active' : ''}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <main>
        {tab === 'schemas' && !schemaId && (
          <SchemaListPage onOpen={openSchema} />
        )}
        {tab === 'schemas' && schemaId && !versionId && (
          <SchemaDetailPage
            schemaId={schemaId}
            onBack={() => setSchemaId(null)}
            onOpenVersion={openVersion}
          />
        )}
        {tab === 'schemas' && versionId && (
          <VersionDetailPage
            versionId={versionId}
            onBack={() => setVersionId(null)}
          />
        )}
        {tab === 'compare' && <CompatibilityPage />}
        {tab === 'mapping' && <MappingPage />}
      </main>
    </div>
  )
}
