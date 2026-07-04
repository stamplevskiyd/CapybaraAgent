/** Syntax-highlighted code block with a language label and a copy-to-clipboard button. */
import { useState } from 'react'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { prismTheme } from './prismTheme'
import styles from './CodeBlock.module.css'

export function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard can be unavailable (insecure context) or denied; ignore silently.
    }
  }
  return (
    <div className={styles.block}>
      <div className={styles.header}>
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.lang}>{language ?? 'text'}</span>
        <button type="button" className={styles.copy} onClick={copy}>
          {copied ? 'Скопировано' : 'Копировать'}
        </button>
      </div>
      <div className={styles.body}>
        <SyntaxHighlighter language={language} style={prismTheme} customStyle={{ background: 'none', margin: 0, padding: 0 }}>
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}
