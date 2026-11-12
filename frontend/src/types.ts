export type Policy = 'nominal' | 'guarded' | 'oracle';
export interface Scenario {
  title: string;
  load_a: number;
  load_b: number;
  load_c: number;
  reported_b: number;
  telemetry_age_s: number;
  uncertainty_pct: number;
  policy: 'nominal' | 'guarded';
}
export interface Network {
  id: string;
  description: string;
  faulted_line: string;
  voltage_limits_pu: number[];
  buses: { id: string; label: string; x: number; y: number }[];
  lines: {
    id: string;
    from_bus: string;
    to_bus: string;
    length_km: number;
    normal_amps: number;
    normally_open: boolean;
    label: string;
  }[];
  loads: {
    id: string;
    bus: string;
    label: string;
    feeder: string;
    kw: number;
    kva: number;
    critical: boolean;
  }[];
}
export interface ElectricalResult {
  converged: boolean;
  feasible: boolean;
  voltages_pu: Record<string, number>;
  line_loading_pct: Record<string, number>;
  transformer_loading_pct: Record<string, number>;
  served_kw: number;
  critical_served_kw: number;
  requested_kw: number;
  unserved_kw: number;
  restored_kw: number;
  restoration_baseline_kw: Record<string, number>;
  min_voltage_pu: number | null;
  max_loading_pct: number;
  losses_kw: number;
  native_load_kw: number | null;
  native_load_kvar: number | null;
  source_kw: number | null;
  source_kvar: number | null;
  losses_kvar: number | null;
  balance_residual_kw: number | null;
  balance_residual_kvar: number | null;
  voltage_compliant_served_kw: number | null;
  energized_buses: string[];
  violations: {
    kind: string;
    element: string;
    value: number | null;
    limit: number | null;
    message: string;
  }[];
  load_measurements: {
    load_id: string;
    label: string;
    critical: boolean;
    requested_kw: number;
    served_kw: number;
    native_kw?: number | null;
    native_kvar?: number | null;
    quality?: 'solved' | 'unconverged';
    voltage_compliant?: boolean;
    energized: boolean;
    voltage_pu: number;
    voltage_max_pu?: number;
    bus_min_voltage_pu?: number;
    connection?: 'wye' | 'delta';
    phase_nodes?: number[];
    voltage_basis?: 'phase-to-neutral' | 'phase-to-phase';
    voltage_base_kv?: number;
    load_voltage_base_kv?: number;
    voltage_branches_v?: Record<string, number>;
    voltage_branches_pu?: Record<string, number>;
    voltage_on_load_base_pu?: Record<string, number>;
  }[];
}
export interface Action {
  id: string;
  label: string;
  operations: { line: string; closed: boolean }[];
}
export interface State {
  load_factors: Record<string, number>;
  closed_lines: string[];
  locked_open: string[];
  equipment_outages: {
    incident_id: string;
    kind: 'line' | 'transformer' | 'source';
    equipment: string;
  }[];
  open_transformers: string[];
  source_connected: boolean;
}
export interface Outcome {
  action: Action;
  final_state: State;
  result: ElectricalResult;
  steps: ElectricalResult[];
}
export interface Candidate {
  action: Action;
  nominal: ElectricalResult;
  feasible: boolean;
  sample_count: number;
  worst_loading_pct: number;
  worst_voltage_pu: number | null;
  rejected_reasons: string[];
}
export interface Decision {
  policy: Policy;
  selected_action: Action;
  feasible_choice: boolean;
  rationale: string;
  candidates: Candidate[];
  objective: string;
}
export interface Observation {
  recorded_at: string;
  measurement_at: string;
  age_s: number;
  load_factors: Record<string, number>;
  uncertainty_pct: number;
  rows: {
    sensor_id: string;
    load_id: string;
    measurement: string;
    value: number;
    unit: string;
    measurement_at: string;
    received_at: string;
    age_s: number;
    quality: string;
    source: string;
  }[];
}
export interface Incident {
  id: string;
  created_at: string;
  scenario: Scenario;
  observation: Observation;
  initial_state: State;
  before: ElectricalResult;
  decisions: Record<Policy, Decision>;
  outcomes: Record<Policy, Outcome>;
  alternatives: Outcome[];
  timeline: { step: number; event: string; detail: string }[];
  limits: string[];
  manifest: {
    app_version: string;
    network: Network;
    network_sha256: string;
    implementation_sha256: string;
    solver_version: string;
    simulation_mode: string;
  };
}
export interface Preset {
  id: string;
  description: string;
  scenario: Scenario;
}
export interface Summary {
  id: string;
  title: string;
  created_at: string;
  policy: string;
}
export interface Review {
  id: number;
  created_at: string;
  verdict: string;
  note: string;
}
export interface Replay {
  matched: boolean;
  differences: string[];
  checked_at: string;
  tolerance: number;
  method: string;
}
export interface SweepRow {
  west_load_factor: number;
  west_demand_kw: number;
  policy: Policy;
  action: string;
  feasible: boolean;
  restored_kw: number;
  critical_served_kw: number;
  unserved_kw: number;
  max_loading_pct: number;
  min_voltage_pu: number;
  switch_count: number;
  violations: string;
}
export interface Sweep {
  id: string;
  created_at: string;
  rows: SweepRow[];
  interpretation: string;
}
