import type { IStep } from '@chainlit/react-client'
import type { ChatMessage, ToolCallState } from '../chat/useChatStream'

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

function convertToolStep(step: IStep): ToolCallState | null {
  if (step.type !== 'tool') return null
  return {
    id: step.id,
    name: step.name,
    args: parseToolArgs(step.input),
    result: step.output || undefined,
    running: Boolean(step.streaming),
  }
}

function isToolCall(toolCall: ToolCallState | null): toolCall is ToolCallState {
  return toolCall !== null
}

export function convertChainlitMessage(step: IStep): ChatMessage | null {
  if (step.type !== 'user_message' && step.type !== 'assistant_message') return null

  const toolCalls = (step.steps ?? []).map(convertToolStep).filter(isToolCall)
  return {
    id: step.id,
    role: step.type === 'user_message' ? 'user' : 'assistant',
    content: step.output,
    streaming: Boolean(step.streaming),
    error: step.isError || undefined,
    toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
  }
}
