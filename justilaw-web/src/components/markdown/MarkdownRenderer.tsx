import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { createLowlight } from 'lowlight'
import bash from 'highlight.js/lib/languages/bash'
import ini from 'highlight.js/lib/languages/ini'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import 'highlight.js/styles/github-dark.css'

// 只注册实际会用到的语言子集（法律文档场景），替代 rehype-highlight 默认的 37 语言 common 全集；
// 未注册语言的代码块会退化为纯文本渲染，不会报错
const lowlight = createLowlight()
lowlight.register('javascript', javascript)
lowlight.register('typescript', typescript)
lowlight.register('json', json)
lowlight.register('bash', bash)
lowlight.register('python', python)
lowlight.register('sql', sql)
lowlight.register('xml', xml)
lowlight.register('yaml', yaml)
lowlight.register('ini', ini)
// 常用别名
lowlight.register('js', javascript)
lowlight.register('ts', typescript)
lowlight.register('py', python)
lowlight.register('shell', bash)
lowlight.register('html', xml)

const REMARK_PLUGINS = [remarkGfm]
const highlightPlugin: [typeof rehypeHighlight, { languages: typeof lowlight }] = [
  rehypeHighlight,
  { languages: lowlight },
]
const REHYPE_PLUGINS = [highlightPlugin]
const COMPONENTS = {
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
}

/** memo + 模块级插件常量：content 不变时跳过整棵 markdown 树的重渲染 */
export const MarkdownRenderer = memo(function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-headings:mb-2 prose-headings:mt-4 prose-p:my-1.5 prose-li:my-0.5 prose-pre:my-3 prose-table:my-3">
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} components={COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  )
})
