import type { ElectricalResult, State } from './types';

export type LivePolicy = 'off' | 'nominal' | 'guarded';
export interface Signal {
  sequence: number;
  sensor_id: string;
  equipment: string;
  quantity: string;
  value: number | boolean | null;
  unit: string;
  measured_at_s: number;
  received_at_s: number | null;
  quality: 'valid' | 'deenergized' | 'invalid';
  source: string;
  age_s?: number;
  fresh?: boolean;
}
export interface Alarm {
  id: string;
  rule: string;
  equipment: string;
  sensor_id: string;
  raised_at_s: number;
  explanation: string;
  limit: number | boolean;
  reset_value: number | boolean;
  unit: string;
  trigger_rows: Signal[];
  cleared_at_s: number | null;
  clear_rows: Signal[];
}
export interface LiveObservation {
  at_s: number;
  remaining_horizon_s: number;
  uncertainty_model: { growth_pct_per_s: number; maximum_pct: number };
  signals: Signal[];
  alarms: Alarm[];
  demand_estimates: {
    load_id: string;
    kw: number | null;
    status: string;
    age_s: number | null;
    lower_kw: number | null;
    upper_kw: number | null;
    evidence: Signal[];
  }[];
}
export interface Operation {
  equipment: string;
  closed: boolean;
}
export interface Command {
  id: string;
  plan_id: string;
  operation: Operation;
  issued_at_s: number;
  deadline_s: number;
  status: 'pending' | 'confirmed' | 'failed' | 'unknown' | 'confirmed_late' | 'failed_late';
  received_at_s: number | null;
  measured_at_s: number | null;
  confirmed_position: boolean | null;
}
export interface LiveCandidate {
  operations: Operation[];
  normal_configuration: boolean;
  known_unsafe: boolean;
  completion_offset_s?: number;
  checked_operations?: number;
  rejection_reason?: string | null;
  energy?: {
    horizon_s: number;
    completion_s: number;
    critical_unserved_kwh: number | null;
    unserved_kwh: number | null;
    known: boolean;
    basis: string;
  };
  prediction: {
    feasible: boolean;
    samples_checked: number;
    samples_required: number;
    worst_loading_pct: number | null;
    violations: { kind: string; message: string }[];
    nominal: {
      feasible: boolean;
      critical_kw: number | null;
      served_kw: number | null;
      loading_pct: number | null;
      min_voltage_pu: number | null;
    };
  };
}
export interface LivePlan {
  goal: 'restore' | 'normal';
  policy: string;
  objective: string;
  reason: string;
  selected: LiveCandidate | null;
  feasible_choice: boolean;
  candidates: LiveCandidate[];
  structural_rejections: { operation: Operation; reason: string }[];
  budget: number;
  native_evaluations: number;
  budget_exhausted: boolean;
  native_cache_hits?: number;
  service_bound_pruned?: number;
  search_complete?: boolean;
  timing?: {
    actuation_delay_s: number;
    confirmation_delay_s: number;
    energy_horizon_s: number;
  };
  energy_horizon_s?: number;
  forecast_assumption?: string;
  measured_overloads?: { equipment: string; limit_pct: number; row: Signal }[];
  unsafe_exposures?: {
    equipment: string;
    load_ids: string[];
    demand_kw: Record<string, number>;
    row: Signal;
  }[];
  max_operations: number;
  input: Record<string, unknown>;
}
export interface LiveControl {
  status: string;
  reason: string;
  supply_status: string;
  commands: Record<string, Command>;
  pending_id: string | null;
  remaining: Operation[];
  last_plan: LivePlan | null;
  last_planned_at_s: number;
  plan_id: string | null;
  recovery_requested: boolean;
  decision_count: number;
  native_evaluations: number;
}
export type PhysicalEvent =
  | { kind: 'outage'; at_s: number; incident_id: string; equipment_kind: string; equipment: string }
  | { kind: 'repair'; at_s: number; incident_id: string }
  | { kind: 'demand'; at_s: number; feeder: string; factor: number }
  | { kind: 'transport'; at_s: number; equipment: string; latency_s: number; drop: boolean }
  | {
      kind: 'actuator';
      at_s: number;
      equipment: string;
      actuation_delay_s: number;
      fail: boolean;
      feedback_delay_s: number;
      drop_feedback: boolean;
    };
export interface QueuedEvent {
  sequence: number;
  event: PhysicalEvent;
}
export interface Receipt {
  id: string;
  revision: number;
  at_s: number;
  mode: 'paused' | 'running';
  rate: 1 | 5 | 10;
  pause_reason: string | null;
}
export interface LiveSession extends Receipt {
  title: string;
  horizon_s: number;
  observation: LiveObservation;
  control: LiveControl;
  control_settings: { policy: LivePolicy; [key: string]: unknown };
  simulation: {
    physical: State;
    electrical: ElectricalResult | null;
    solver_error: string | null;
    scheduled_events: QueuedEvent[];
  };
}
export interface EpisodeMetrics {
  known_seconds: number;
  unknown_seconds: number;
  unserved_kwh: number;
  served_kwh: number;
  feasible_critical_served_kwh: number;
  violation_ticks: number;
  position_changes: number;
  first_interruption_s: number | null;
  first_full_recovery_s: number | null;
}
export interface LiveFrame {
  at_s: number;
  physical: State;
  electrical: ElectricalResult | null;
  solver_error: string | null;
  physical_events: QueuedEvent[];
  alarm_changes: { kind: string; alarm: Alarm }[];
  actuation_events: {
    equipment: string;
    closed: boolean | null;
    changed: boolean;
    reason: string | null;
    command_id: string;
  }[];
  confirmation_events: Record<string, unknown>[];
  control_events: Record<string, unknown>[];
  observation: LiveObservation;
  control: LiveControl;
  metrics: EpisodeMetrics;
}
export interface LiveExport {
  kind: string;
  id: string;
  definition: { title: string; control: { policy: LivePolicy } };
  manifest: Record<string, unknown>;
  frames: LiveFrame[];
  actions: { revision: number; operation: string; payload: unknown }[];
  final: { revision: number; checkpoint: { metrics: EpisodeMetrics; now_s: number } };
  content_sha256: string;
}
export interface SessionSummary extends Receipt {
  created_at: string;
}
export interface PendingRequest {
  path: string;
  body: Record<string, unknown>;
  label: string;
}

export const human = (value: string) => value.replaceAll('_', ' ');
export const number = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString('en-US', { maximumFractionDigits: digits });
export const valueText = (value: Signal['value']) =>
  typeof value === 'boolean' ? String(value) : number(value, 4);
export const operationsText = (operations: Operation[]) =>
  operations.length
    ? operations.map((op) => `${op.closed ? 'Close' : 'Open'} ${op.equipment}`).join(' → ')
    : 'Hold current positions';
export const supplyNames: Record<string, string> = {
  normal_supply_verified: 'Normal supply verified',
  alternate_supply_verified: 'Alternate supply verified',
  partial_supply_verified: 'Partial supply verified',
  supply_interrupted: 'Supply interrupted',
  electrical_limits_violated: 'Electrical limits violated',
  awaiting_measurements: 'Awaiting valid measurements',
};
export const controlStatusNames: Record<string, string> = {
  off: 'Automatic switching off',
  paused: 'No new switch commands',
  confirmation_pending: 'Waiting for switch confirmation',
  confirmation_unknown: 'Switch confirmation unknown',
  insufficient_information: 'Insufficient measurements',
  command_limit: 'Switch command limit reached',
  monitoring: 'Monitoring',
  holding: 'Holding current configuration',
  decision_limit: 'Decision limit reached',
  evaluation_limit: 'Planning solve limit reached',
  attempt_limit: 'Switching attempt limit reached',
};
export function eventText(event: PhysicalEvent) {
  switch (event.kind) {
    case 'outage':
      return `Outage · ${event.equipment_kind}:${event.equipment} · ${event.incident_id}`;
    case 'repair':
      return `Repair complete · ${event.incident_id}`;
    case 'demand':
      return `Feeder ${event.feeder.toUpperCase()} demand → ${event.factor}×`;
    case 'transport':
      return `${event.equipment} measurements · ${event.drop ? 'drop new measurements' : `${event.latency_s} s delivery delay`}`;
    case 'actuator':
      return `${event.equipment} switch response · ${event.fail ? 'fails' : `${event.actuation_delay_s} s delay`} · ${event.drop_feedback ? 'confirmation dropped' : `${event.feedback_delay_s} s confirmation delay`}`;
  }
}
