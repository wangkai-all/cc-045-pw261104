const BASE = ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: options.body instanceof FormData
      ? undefined
      : { 'Content-Type': 'application/json' },
    ...options,
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : `HTTP ${res.status}`
    throw new Error(detail)
  }
  return data
}

export const api = {
  listSchemas: () => request('/api/schemas'),
  createSchema: (payload) => request('/api/schemas', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  getSchema: (id) => request(`/api/schemas/${id}`),
  createVersion: (schemaId, payload) =>
    request(`/api/schemas/${schemaId}/versions`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  getVersion: (id) => request(`/api/versions/${id}`),
  updateDraft: (id, payload) => request(`/api/versions/${id}/draft`, {
    method: 'PUT', body: JSON.stringify(payload),
  }),
  lockVersion: (id) => request(`/api/versions/${id}/lock`, { method: 'POST' }),
  compare: (payload) => request('/api/compatibility', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  uploadJsonl: (versionId, file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`/api/versions/${versionId}/uploads`, {
      method: 'POST', body: form,
    })
  },
  listUploads: (versionId) => request(`/api/versions/${versionId}/uploads`),
  getUpload: (id) => request(`/api/uploads/${id}`),
  previewMapping: (payload) => request('/api/mappings/preview', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  generateMapping: (mappingId) => request('/api/mappings/generate', {
    method: 'POST', body: JSON.stringify({ mapping_id: mappingId }),
  }),
  getMapping: (id) => request(`/api/mappings/${id}`),
}
