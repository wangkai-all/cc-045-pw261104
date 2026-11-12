import React from 'react'

const FIELD_TYPES = [
  ['object', '对象 object'],
  ['array', '数组 array'],
  ['text', '文本 text'],
  ['integer', '整数 integer'],
  ['decimal', '定点小数 decimal'],
  ['boolean', '布尔 boolean'],
  ['date', 'ISO 日期 date'],
]

let nodeSeq = 0
export function makeField(type = 'text') {
  nodeSeq += 1
  const field = {
    _key: `f${Date.now()}_${nodeSeq}`,
    name: '',
    type,
    required: false,
    nullable: true,
    has_default: false,
    default: '',
    aliases: [],
  }
  if (type === 'decimal') {
    field.precision = 10
    field.scale = 2
  }
  if (type === 'object') field.fields = []
  if (type === 'array') {
    field.items = {
      _key: `f${Date.now()}_${nodeSeq}_i`,
      name: '_items',
      type: 'text',
      required: false,
      nullable: true,
      has_default: false,
      default: '',
      aliases: [],
    }
  }
  return field
}

function toPayload(node) {
  const out = {
    name: node.name,
    type: node.type,
    required: !!node.required,
    nullable: !!node.nullable,
    has_default: !!node.has_default,
    aliases: node.aliases || [],
  }
  if (node.has_default) {
    out.default = parseDefault(node.default, node.type)
  }
  if (node.type === 'decimal') {
    out.precision = Number(node.precision)
    out.scale = Number(node.scale)
  }
  if (node.type === 'object') {
    out.fields = (node.fields || []).map(toPayload)
  }
  if (node.type === 'array') {
    const item = { ...toPayload(node.items), name: '_items' }
    out.items = item
  }
  return out
}

export function treeToPayload(roots) {
  return roots.map(toPayload)
}

export function fromPayload(fields) {
  let seq = 0
  const hydrate = (f) => {
    seq += 1
    const node = {
      _key: `h${Date.now()}_${seq}`,
      name: f.name,
      type: f.type,
      required: !!f.required,
      nullable: f.nullable !== false,
      has_default: !!f.has_default,
      default: f.has_default ? renderDefault(f.default) : '',
      aliases: f.aliases || [],
    }
    if (f.type === 'decimal') {
      node.precision = f.precision
      node.scale = f.scale
    }
    if (f.type === 'object') node.fields = (f.fields || []).map(hydrate)
    if (f.type === 'array') node.items = hydrate(f.items)
    return node
  }
  return fields.map(hydrate)
}

function renderDefault(value) {
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function parseDefault(raw, type) {
  if (typeof raw !== 'string') return raw
  const text = raw.trim()
  if (type === 'integer') return Number(text)
  if (type === 'decimal' || type === 'text' || type === 'date') return text
  if (type === 'boolean') return text === 'true'
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function updateNode(roots, key, updater) {
  const walk = (nodes) => nodes.map((n) => {
    if (n._key === key) return updater(n)
    if (n.type === 'object' && n.fields) {
      return { ...n, fields: walk(n.fields) }
    }
    if (n.type === 'array' && n.items) {
      const items = walk([n.items])
      return { ...n, items: items[0] }
    }
    return n
  })
  return walk(roots)
}

function removeNode(roots, key) {
  const walk = (nodes) =>
    nodes.filter((n) => n._key !== key).map((n) => {
      if (n.type === 'object' && n.fields) return { ...n, fields: walk(n.fields) }
      if (n.type === 'array' && n.items && n.items._key === key) {
        return { ...n, items: makeField('text') }
      }
      if (n.type === 'array' && n.items) {
        const items = walk([n.items])
        return { ...n, items: items[0] }
      }
      return n
    })
  return walk(roots)
}

function changeType(node, newType) {
  const next = { ...node, type: newType }
  if (newType === 'decimal') {
    next.precision = node.precision ?? 10
    next.scale = node.scale ?? 2
  }
  if (newType === 'object' && !node.fields) next.fields = []
  if (newType === 'array' && !node.items) next.items = makeField('text')
  return next
}

function FieldNodeView({ node, roots, setRoots, depth }) {
  const patch = (updater) => setRoots(updateNode(roots, node._key, updater))
  const isItem = node.name === '_items'

  return (
    <div className="field-node">
      <div className="field-head">
        {isItem ? (
          <strong className="muted">数组元素</strong>
        ) : (
          <input
            className="grow"
            placeholder="字段名"
            value={node.name}
            onChange={(e) => patch((n) => ({ ...n, name: e.target.value }))}
          />
        )}
        <select
          value={node.type}
          onChange={(e) => patch((n) => changeType(n, e.target.value))}
        >
          {FIELD_TYPES.map(([v, label]) => (
            <option key={v} value={v}>{label}</option>
          ))}
        </select>
        {!isItem && (
          <button
            className="btn ghost small"
            onClick={() => setRoots(removeNode(roots, node._key))}
          >
            删除
          </button>
        )}
      </div>

      <div className="field-meta">
        <label className="inline">
          <input
            type="checkbox"
            checked={!!node.required}
            disabled={isItem}
            onChange={(e) => patch((n) => ({ ...n, required: e.target.checked }))}
          />
          必填
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={node.nullable !== false}
            onChange={(e) => patch((n) => ({ ...n, nullable: e.target.checked }))}
          />
          可空
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={!!node.has_default}
            onChange={(e) => patch((n) => ({ ...n, has_default: e.target.checked }))}
          />
          有默认值
        </label>
      </div>

      {node.has_default && (
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted small">默认值（按类型解析）：</span>
          <input
            className="grow"
            placeholder={
              node.type === 'boolean' ? 'true / false'
                : node.type === 'integer' ? '例如 0'
                : node.type === 'decimal' ? '例如 0.00'
                : node.type === 'date' ? 'YYYY-MM-DD'
                : '默认内容'
            }
            value={node.default ?? ''}
            onChange={(e) => patch((n) => ({ ...n, default: e.target.value }))}
          />
        </div>
      )}

      {!isItem && node.type !== 'object' && (
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted small">旧字段别名（逗号分隔，用于改名兼容）：</span>
          <input
            className="grow"
            placeholder="例如 old_name, legacy_name"
            value={(node.aliases || []).join(', ')}
            onChange={(e) => patch((n) => ({
              ...n,
              aliases: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
            }))}
          />
        </div>
      )}

      {node.type === 'decimal' && (
        <div className="row" style={{ marginTop: 8 }}>
          <label className="inline small">
            总位数 precision
            <input
              type="number" min="1" style={{ width: 90 }}
              value={node.precision}
              onChange={(e) => patch((n) => ({ ...n, precision: e.target.value }))}
            />
          </label>
          <label className="inline small">
            小数位数 scale
            <input
              type="number" min="0" style={{ width: 90 }}
              value={node.scale}
              onChange={(e) => patch((n) => ({ ...n, scale: e.target.value }))}
            />
          </label>
          {Number(node.scale) > Number(node.precision) && (
            <span className="error-text small">scale 不能大于 precision</span>
          )}
        </div>
      )}

      {node.type === 'object' && (
        <div className="children">
          {(node.fields || []).map((child) => (
            <FieldNodeView
              key={child._key}
              node={child}
              roots={roots}
              setRoots={setRoots}
              depth={depth + 1}
            />
          ))}
          <button
            className="btn secondary small"
            onClick={() => patch((n) => ({
              ...n,
              fields: [...(n.fields || []), makeField('text')],
            }))}
          >
            + 子字段
          </button>
        </div>
      )}

      {node.type === 'array' && node.items && (
        <div className="children">
          <FieldNodeView
            key={node.items._key}
            node={node.items}
            roots={roots}
            setRoots={setRoots}
            depth={depth + 1}
          />
        </div>
      )}
    </div>
  )
}

export default function FieldTreeEditor({ roots, setRoots, locked }) {
  return (
    <div>
      {roots.map((node) => (
        <FieldNodeView
          key={node._key}
          node={node}
          roots={roots}
          setRoots={setRoots}
          depth={0}
        />
      ))}
      <div className="row">
        <button
          className="btn secondary"
          disabled={locked}
          onClick={() => setRoots([...roots, makeField('text')])}
        >
          + 顶层字段
        </button>
        {locked && <span className="muted small">版本已锁定，字段结构不可修改</span>}
      </div>
    </div>
  )
}
