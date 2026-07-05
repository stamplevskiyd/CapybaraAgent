/** react-syntax-highlighter (Prism) style built from the design handoff code palette. */
import type { CSSProperties } from 'react'

const mono = "'JetBrains Mono', monospace"

export const prismTheme: Record<string, CSSProperties> = {
  'code[class*="language-"]': {
    color: '#d6cdc3',
    fontFamily: mono,
    fontSize: '12.5px',
    lineHeight: 1.7,
    background: 'none',
  },
  'pre[class*="language-"]': {
    color: '#d6cdc3',
    fontFamily: mono,
    fontSize: '12.5px',
    lineHeight: 1.7,
    background: 'none',
    margin: 0,
    padding: 0,
    overflow: 'auto',
  },
  comment: { color: '#7a7268' },
  prolog: { color: '#7a7268' },
  doctype: { color: '#7a7268' },
  cdata: { color: '#7a7268' },
  punctuation: { color: '#d6cdc3' },
  keyword: { color: '#c58fd6' },
  'attr-name': { color: '#cbb48c' },
  tag: { color: '#e0967a' },
  string: { color: '#8fbf9e' },
  char: { color: '#8fbf9e' },
  function: { color: '#8fbcdb' },
  'class-name': { color: '#8fbcdb' },
  builtin: { color: '#8fbcdb' },
  number: { color: '#8fbf9e' },
  operator: { color: '#d6cdc3' },
}
