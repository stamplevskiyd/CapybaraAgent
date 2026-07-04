/** Renderable parts of a chat message. Text only today; tool-call/artifact/source reserved. */
export type MessagePart =
  | { type: 'text'; text: string }
// Future slices (no backend data yet) will add e.g.:
// | { type: 'tool-call'; toolName: string; args: unknown; result?: unknown; status: 'running' | 'complete' | 'error' }
// | { type: 'artifact'; id: string; title: string }
// | { type: 'source'; id: string; url: string; title: string }
