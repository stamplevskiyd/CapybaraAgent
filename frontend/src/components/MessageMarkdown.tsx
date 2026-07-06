/**
 * Markdown renderer for assistant messages: GFM + sanitized HTML + design-styled code blocks.
 *
 * Production export `MarkdownText` uses `MarkdownTextPrimitive` from @assistant-ui/react-markdown,
 * which reads text from the assistant-ui message context (no children prop). It is wired into
 * `MessagePrimitive.Content` in Task 8.
 *
 * `TestMarkdownHarness` uses react-markdown directly with the same plugins/components so the
 * same rendering behaviour can be unit-tested without a full assistant-ui runtime.
 */
import React from 'react'
import {
  MarkdownTextPrimitive,
  type MarkdownTextPrimitiveProps,
} from '@assistant-ui/react-markdown'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import { CodeBlock } from './CodeBlock'
import styles from './MessageMarkdown.module.css'

/**
 * Shared react-markdown `components` map, typed to satisfy both react-markdown's `Components`
 * and the extended type expected by `MarkdownTextPrimitive`.
 *
 * Fenced code blocks (those with a language class or a trailing newline in their text content)
 * are routed to `CodeBlock` which provides the language label and copy-to-clipboard button.
 * Inline code stays as a styled `<code>` element.
 *
 * This is Option A from the integration notes: overriding `components.code` to detect fenced
 * vs inline, chosen because `TestMarkdownHarness` uses react-markdown directly (the primitive
 * omits `children` from its props and requires a runtime context), so `components.code` is the
 * only route that is testable and works in both contexts.
 */
const markdownComponents: NonNullable<MarkdownTextPrimitiveProps['components']> = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  code({
    className,
    children,
  }: {
    className?: string
    children?: React.ReactNode
    [key: string]: any
  }) {
    const lang = /language-(\w+)/.exec(className ?? '')?.[1]
    const text = String(children ?? '')
    // Fenced blocks carry a language class or end with a newline; inline code does not.
    if (lang || text.includes('\n')) {
      return <CodeBlock code={text.replace(/\n$/, '')} language={lang} />
    }
    return <code className={styles.inlineCode}>{children}</code>
  },
}

/** Cast to react-markdown's Components for use in TestMarkdownHarness. */
const reactMarkdownComponents = markdownComponents as Components

/** Text-part renderer plugged into MessagePrimitive.Content in the Thread (Task 8). */
export function MarkdownText(): React.ReactElement {
  return (
    <MarkdownTextPrimitive
      className={styles.markdown}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={markdownComponents}
    />
  )
}

/**
 * Test-only: renders markdown from a static string without an assistant-ui runtime.
 *
 * `MarkdownTextPrimitive` omits `children` from its props and reads content from the
 * assistant-ui message context, so it cannot accept a static string. This harness uses
 * react-markdown directly with the same `remarkPlugins`, `rehypePlugins`, and `components`
 * map, exercising identical GFM/sanitize/code-routing behaviour.
 */
export function TestMarkdownHarness({ text }: { text: string }): React.ReactElement {
  return (
    <div className={styles.markdown}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={reactMarkdownComponents}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
