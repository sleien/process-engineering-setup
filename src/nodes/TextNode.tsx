import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { useReactFlow, type NodeProps } from '@xyflow/react'
import type { TextNode } from '../lib/types'
import { parseRich } from '../lib/textFormat'

function RichText({ text }: { text: string }) {
  return (
    <>
      {text.split('\n').map((line, li) => (
        <span className="text-line" key={li}>
          {parseRich(line).map((seg, i) =>
            seg.script === 'sup' ? (
              <sup key={i}>{seg.text}</sup>
            ) : seg.script === 'sub' ? (
              <sub key={i}>{seg.text}</sub>
            ) : (
              <span key={i}>{seg.text}</span>
            ),
          )}
        </span>
      ))}
    </>
  )
}

function TextNodeComponent({ id, data, selected }: NodeProps<TextNode>) {
  const { updateNodeData } = useReactFlow()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(data.text)
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => setValue(data.text), [data.text])
  useEffect(() => {
    if (editing && ref.current) {
      ref.current.focus()
      ref.current.select()
    }
  }, [editing])

  const commit = useCallback(() => {
    setEditing(false)
    updateNodeData(id, { text: value })
  }, [id, value, updateNodeData])

  return (
    <div
      className={`text-node${selected ? ' selected' : ''}`}
      style={{ fontSize: data.fontSize ?? 14 }}
      onDoubleClick={() => setEditing(true)}
    >
      {editing ? (
        <textarea
          ref={ref}
          className="nodrag text-node-input"
          value={value}
          rows={Math.max(1, value.split('\n').length)}
          onChange={(e) => setValue(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              commit()
            } else if (e.key === 'Escape') {
              setValue(data.text)
              setEditing(false)
            }
          }}
        />
      ) : (
        <span className={`text-node-label${data.text ? '' : ' placeholder'}`}>
          {data.text ? <RichText text={data.text} /> : 'Double-click to edit'}
        </span>
      )}
    </div>
  )
}

export default memo(TextNodeComponent)
