export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface ApiClient {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  patch<T>(path: string, body?: unknown): Promise<T>
  del(path: string): Promise<void>
  stream(path: string, body: unknown, signal?: AbortSignal): Promise<Response>
  eventStream(path: string, signal?: AbortSignal): Promise<Response>
}

export function createApiClient(opts: {
  getToken: () => string | null
  onUnauthorized: () => void
}): ApiClient {
  async function request(path: string, init: RequestInit): Promise<Response> {
    const token = opts.getToken()
    const headers = new Headers(init.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`/api${path}`, { ...init, headers })
    if (res.status === 401) {
      opts.onUnauthorized()
      throw new ApiError(401, 'Unauthorized')
    }
    return res
  }
  async function json<T>(path: string, init: RequestInit): Promise<T> {
    const res = await request(path, init)
    if (!res.ok) throw new ApiError(res.status, await res.text())
    return (await res.json()) as T
  }
  async function stream(path: string, init: RequestInit): Promise<Response> {
    const res = await request(path, init)
    if (!res.ok) throw new ApiError(res.status, await res.text())
    return res
  }
  return {
    get: (path) => json(path, { method: 'GET' }),
    post: (path, body) =>
      json(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    patch: (path, body) =>
      json(path, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    del: async (path) => {
      const res = await request(path, { method: 'DELETE' })
      if (!res.ok) throw new ApiError(res.status, await res.text())
    },
    stream: (path, body, signal) =>
      stream(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      }),
    eventStream: (path, signal) => stream(path, { method: 'GET', signal }),
  }
}
