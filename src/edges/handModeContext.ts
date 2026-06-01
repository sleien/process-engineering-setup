import { createContext, useContext } from 'react'

/** Whether the editor is in "Hand" mode — pipes show a draggable depth handle and can be
 *  routed by dragging (see App's hand-drag handler and PipeEdge). */
export const HandModeContext = createContext(false)

export const useHandMode = () => useContext(HandModeContext)
