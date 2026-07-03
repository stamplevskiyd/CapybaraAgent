import { parseSse, type SseEvent } from './sse'

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
}

test('parses events split across chunk boundaries', async () => {
  const stream = streamOf([
    'event: delta\ndata: {"text":"Hel',
    'lo"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n',
  ])
  const events: SseEvent[] = []
  for await (const e of parseSse(stream)) events.push(e)
  expect(events).toEqual([
    { event: 'delta', data: '{"text":"Hello"}' },
    { event: 'done', data: '{"message_id":"m1"}' },
  ])
})
