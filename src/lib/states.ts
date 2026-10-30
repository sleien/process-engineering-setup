// Shared ASM1 state metadata — labels/units for charts, tables and the influent editor.
// The state list mirrors the backend's ASM1_STATES (server/simulate.py); the units are
// ASM1's own (Thetis ASM1_states.csv): COD for organics and biomass, N for nitrogen, and
// alkalinity in mol HCO3-/m³ = mmol/L. `pH` is not an ASM1 state: the backend estimates it
// from the alkalinity and each tank's dissolved CO2 (server/controllers.py, "pH").

export const STATE_META: Record<string, { label: string; unit: string }> = {
  S_S:   { label: 'Biodegradable soluble COD', unit: 'mg COD/L' },
  S_O:   { label: 'Dissolved oxygen',           unit: 'mg O₂/L' },
  S_NH:  { label: 'Ammonium',                   unit: 'mg N/L' },
  S_NO:  { label: 'Nitrate',                    unit: 'mg N/L' },
  X_BH:  { label: 'Heterotrophs',               unit: 'mg COD/L' },
  X_BA:  { label: 'Autotrophs',                 unit: 'mg COD/L' },
  X_S:   { label: 'Particulate COD',            unit: 'mg COD/L' },
  S_ND:  { label: 'Biodegradable N',            unit: 'mg N/L' },
  S_I:   { label: 'Inert soluble COD',          unit: 'mg COD/L' },
  X_I:   { label: 'Inert particulate COD',      unit: 'mg COD/L' },
  X_ND:  { label: 'Particulate organic N',      unit: 'mg N/L' },
  X_P:   { label: 'Particulate decay products', unit: 'mg COD/L' },
  S_N2:  { label: 'Dinitrogen gas',             unit: 'mg N/L' },
  S_ALK: { label: 'Alkalinity',                 unit: 'mmol/L' },
  pH:    { label: 'pH (estimated from alkalinity)', unit: '-' },
}
export const STATE_ORDER = [
  'S_S', 'S_O', 'S_NH', 'S_NO',
  'X_BH', 'X_BA', 'X_S', 'S_ND',
  'S_I', 'X_I', 'X_ND', 'X_P', 'S_N2',
  'S_ALK', 'pH',
]

/** The engine's built-in influent composition (BSM1 stabilisation feed, server/simulate.py).
 *  Shown as the "what do I get if I leave this blank" reference in the influent editor. */
export const ENGINE_DEFAULT_INFLUENT: Record<string, number> = {
  S_I: 30.0, S_S: 69.5, X_I: 51.2, X_S: 202.32,
  X_BH: 28.17, X_BA: 0.0, X_P: 0.0,
  S_O: 0.0, S_NO: 0.0, S_NH: 31.56, S_ND: 6.95,
  X_ND: 10.59, S_ALK: 7.0, S_N2: 0.0,
}

export const ENGINE_DEFAULT_FLOW_M3D = 2000.0
