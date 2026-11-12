import type { ElectricalResult, Incident, Replay } from './types';

export const variables = ['load_a', 'load_b', 'load_c', 'reported_b'] as const;
export type Variable = (typeof variables)[number];
export type Point = Record<Variable, number>;
export interface SearchInput {
  policy: 'nominal' | 'guarded';
  seed: number;
  budget: number;
  reduction_budget: number;
  uncertainty_pct: number;
  telemetry_age_s: number;
  assumption_scope: 'inside' | 'unrestricted';
  bounds: Record<Variable, { minimum: number; maximum: number }>;
  reference: Point;
}
export interface Finding {
  category: string;
  is_failure: boolean;
  score: number;
  action: string;
  action_label: string;
  truth_inside_assumed_range: boolean;
  predicted_loading_pct: number;
  actual_loading_pct: number;
  restored_kw: number;
  violations: ElectricalResult['violations'];
  feasible_alternative: {
    action: string;
    label: string;
    feasible: boolean;
    restored_kw: number;
    critical_served_kw: number;
  };
}
export interface SearchMethod {
  strategy: string;
  evaluations: number;
  budget: number;
  space_exhausted: boolean;
  space_size: number;
  first_failure_evaluation: number | null;
  seconds_to_first_failure: number | null;
  elapsed_seconds: number;
  failing_scenarios: number;
  categories: Record<string, number>;
  trace: (Finding & { evaluation: number; point: Point })[];
}
export interface SearchRecord {
  id: string;
  created_at: string;
  request: SearchInput;
  status: 'failure_found' | 'no_failure_found';
  selected_strategy: string | null;
  strategies: Record<'directed' | 'random', SearchMethod>;
  original_incident: Incident | null;
  reduced_incident: Incident | null;
  original_finding: Finding | null;
  reduced_finding: Finding | null;
  reduction: {
    evaluations: number;
    budget: number;
    signature: { action: string; kind: string; element: string };
    original_complexity: number[];
    reduced_complexity: number[];
    neighborhood_exhausted: boolean;
    trace: {
      evaluation: number;
      point: Point;
      accepted: boolean;
      category: string;
      action: string;
      complexity: number[];
    }[];
  } | null;
  interpretation: string;
  comparison: string;
}
export interface SearchSummary {
  id: string;
  created_at: string;
  policy: string;
  status: string;
}
export interface SearchReplay extends Replay {
  cases: Record<string, { branches_checked: number; category: string }>;
}
