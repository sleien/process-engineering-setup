// Tiny LaTeX-ish parser for text labels: `^` = superscript, `_` = subscript.
// A single character is scripted (`m^3`, `X_s`); braces group several (`k_{s,xy}`, `r^{max}`).
// Used both for on-screen rendering (<sub>/<sup>) and for SVG export (<tspan> with dy shift).

export type RichSegment = { text: string; script?: 'sub' | 'sup' }

export function parseRich(input: string): RichSegment[] {
  const segments: RichSegment[] = []
  let buffer = ''
  let i = 0

  const flush = () => {
    if (buffer) {
      segments.push({ text: buffer })
      buffer = ''
    }
  }

  while (i < input.length) {
    const ch = input[i]
    if ((ch === '^' || ch === '_') && i + 1 < input.length) {
      const script: 'sub' | 'sup' = ch === '^' ? 'sup' : 'sub'
      i++
      if (input[i] === '{') {
        let end = input.indexOf('}', i + 1)
        if (end === -1) end = input.length
        flush()
        segments.push({ text: input.slice(i + 1, end), script })
        i = end + 1
      } else {
        flush()
        segments.push({ text: input[i], script })
        i++
      }
    } else {
      buffer += ch
      i++
    }
  }
  flush()
  return segments
}
