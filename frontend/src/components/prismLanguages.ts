/**
 * Registers Prism grammars on the PrismLight highlighter, with common fence aliases.
 *
 * PrismLight ships with no grammars: without these registrations every code block
 * renders as plain text and the token palette in prismTheme.ts never applies.
 * Importing this module (done once in CodeBlock) performs the registration.
 * Unregistered languages still fall back to plain text.
 */
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c'
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff'
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import toml from 'react-syntax-highlighter/dist/esm/languages/prism/toml'
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'

/** Grammar → the fence names it should answer to (canonical name first). */
const GRAMMARS: [unknown, string[]][] = [
  [bash, ['bash', 'sh', 'shell', 'zsh']],
  [c, ['c']],
  [cpp, ['cpp', 'c++']],
  [css, ['css']],
  [diff, ['diff']],
  [docker, ['docker', 'dockerfile']],
  [go, ['go', 'golang']],
  [java, ['java']],
  [javascript, ['javascript', 'js']],
  [json, ['json']],
  [jsx, ['jsx']],
  [markdown, ['markdown', 'md']],
  [markup, ['markup', 'html', 'xml']],
  [python, ['python', 'py']],
  [rust, ['rust', 'rs']],
  [sql, ['sql']],
  [toml, ['toml']],
  [tsx, ['tsx']],
  [typescript, ['typescript', 'ts']],
  [yaml, ['yaml', 'yml']],
]

for (const [grammar, names] of GRAMMARS) {
  for (const name of names) {
    SyntaxHighlighter.registerLanguage(name, grammar)
  }
}
