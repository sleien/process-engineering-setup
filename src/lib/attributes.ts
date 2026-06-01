// Editable engineering attributes per unit type, shown in the Properties panel.
// Values are stored as strings in node.data.attributes (free text so users can enter
// numbers, ranges, or notes); they are persisted in the saved project.

export type AttrDef = { key: string; label: string; unit?: string }

const REACTOR: AttrDef[] = [
  { key: 'V', label: 'Volume', unit: 'm³' },
  { key: 'MLSS', label: 'MLSS', unit: 'g/m³' },
  { key: 'DO', label: 'DO', unit: 'mg/L' },
  { key: 'SRT', label: 'SRT', unit: 'd' },
  { key: 'T', label: 'Temperature', unit: '°C' },
]

const ATTRS: Record<string, AttrDef[]> = {
  screen: [{ key: 'spacing', label: 'Bar spacing', unit: 'mm' }],
  equalization_basin: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'HRT', label: 'HRT', unit: 'h' },
  ],
  CSTR: REACTOR,
  empty_CSTR: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'MLSS', label: 'MLSS', unit: 'g/m³' },
  ],
  anoxic_CSTR: REACTOR,
  aerated_CSTR: [...REACTOR, { key: 'kLa', label: 'kLa', unit: '1/d' }],
  aerated_CSTR_off: [...REACTOR, { key: 'kLa', label: 'kLa', unit: '1/d' }],
  switch_CSTR: REACTOR,
  sbr: [...REACTOR, { key: 'cycle', label: 'Cycle time', unit: 'h' }],
  trickling_filter: [
    { key: 'V', label: 'Volume', unit: 'm³' },
    { key: 'area', label: 'Specific surface', unit: 'm²/m³' },
    { key: 'recirc', label: 'Recirculation ratio' },
  ],
  clarifier: [
    { key: 'A', label: 'Surface area', unit: 'm²' },
    { key: 'depth', label: 'Side water depth', unit: 'm' },
    { key: 'SOR', label: 'Overflow rate', unit: 'm/h' },
    { key: 'Qr', label: 'Recycle (RAS) flow', unit: 'm³/d' },
  ],
}

export function getUnitAttrs(unitId: string): AttrDef[] {
  return ATTRS[unitId] ?? [{ key: 'V', label: 'Volume', unit: 'm³' }]
}

/** Compact "key = value unit" lines for the attributes that have a value set — used for the
 *  on-canvas readout under a unit and for the SVG export. */
export function attrReadout(
  unitId: string,
  attributes?: Record<string, string>,
): { key: string; text: string }[] {
  const vals = attributes ?? {}
  return getUnitAttrs(unitId)
    .filter((d) => (vals[d.key] ?? '').trim() !== '')
    .map((d) => ({ key: d.key, text: `${d.key} = ${vals[d.key]!.trim()}${d.unit ? ` ${d.unit}` : ''}` }))
}
