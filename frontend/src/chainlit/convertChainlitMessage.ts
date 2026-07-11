import type { IStep } from '@chainlit/react-client'
import type { ChatMessage, ToolCallState } from '../chat/messages'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseToolArgs(input: string | undefined): Record<string, unknown> {
  if (!input) return {}
  try {
    const parsed = JSON.parse(input) as unknown
    return isRecord(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function convertToolStep(step: IStep): ToolCallState {
  return {
    id: step.id,
    name: step.name,
    args: parseToolArgs(step.input),
    result: step.output || undefined,
    running: Boolean(step.streaming),
  }
}

function convertMessageStep(step: IStep): ChatMessage {
  return {
    id: step.id,
    role: step.type === 'user_message' ? 'user' : 'assistant',
    content: step.output,
    streaming: Boolean(step.streaming),
    error: step.isError || undefined,
  }
}

/**
 * Flatten Chainlit's step tree into the UI's message list.
 *
 * Chainlit parents everything produced inside `on_message` under a `run` step: the
 * assistant reply, error messages, and tool steps are all *children* (or siblings
 * within the run), not top-level messages. So the converter walks the tree:
 * user/assistant messages are emitted in traversal order, container steps (`run`,
 * etc.) are recursed into, and `tool` steps attach to the assistant message of the
 * same scope — the previous one if it already exists, otherwise the next one.
 */
export function convertChainlitMessages(steps: IStep[]): ChatMessage[] {
  const out: ChatMessage[] = []

  const walk = (nodes: IStep[]): void => {
    let pendingTools: ToolCallState[] = []
    for (const node of nodes) {
      if (node.type === 'user_message' || node.type === 'assistant_message') {
        const message = convertMessageStep(node)
        if (node.type === 'assistant_message' && pendingTools.length > 0) {
          message.toolCalls = pendingTools
          pendingTools = []
        }
        out.push(message)
        if (node.steps?.length) walk(node.steps)
      } else if (node.type === 'tool') {
        const tool = convertToolStep(node)
        const last = out[out.length - 1]
        if (last?.role === 'assistant') {
          last.toolCalls = [...(last.toolCalls ?? []), tool]
        } else {
          pendingTools.push(tool)
        }
      } else if (node.steps?.length) {
        walk(node.steps)
      }
    }
    // Tools with no assistant message yet (it streams in moments later): surface them
    // on a placeholder so a running tool is visible before the first token arrives.
    if (pendingTools.length > 0) {
      out.push({
        id: `tools-${pendingTools[0].id}`,
        role: 'assistant',
        content: '',
        streaming: true,
        toolCalls: pendingTools,
      })
    }
  }

  walk(steps)
  return out
}
