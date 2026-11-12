import { useEffect, useState } from 'react';
import {
  ArrowDownToLine,
  CheckCircle2,
  LoaderCircle,
  Play,
  RotateCcw,
  TriangleAlert,
} from 'lucide-react';
import { api } from './api';
import type { ElectricalResult, Scenario } from './types';
import './verification.css';

interface Case {
  schema_version: 1;
  title: string;
  feeder: 'teaching' | 'ieee13';
  fault: string;
  scenario: Scenario;
  contract: { minimum_restored_kw: number; minimum_critical_kw: number };
  origin: string;
}
interface Evaluation {
  controller: string;
  action: { id: string; label: string };
  electrical_pass: boolean;
  service_pass: boolean;
  passed: boolean;
  result: ElectricalResult;
  observation: unknown;
  predictions: unknown[];
}
interface TraceRow {
  at_s: number;
  event: string;
  detail: string;
  commanded_closed: boolean;
  physical_closed: boolean;
  actual_restored_kw: number;
  trackers: Record<string, { status: string; confirmed_closed: boolean }>;
}
interface EventResult {
  events: { kind: string; at_s: number; delay_s: number }[];
  trace: TraceRow[];
  is_failure: boolean;
  unserved_energy_kwh: number;
  duration_s: number;
  interpretation: string;
}
interface Regression {
  kind: 'regression';
  id: string;
  accepted: boolean;
  baseline: Evaluation;
  candidate: Evaluation;
  regressions: string[];
  interpretation: string;
  request: { case: Case; baseline: string; candidate: string };
  historical_baseline: { source_record_id: string } | null;
}
interface Temporal {
  kind: 'temporal';
  id: string;
  status: string;
  original: EventResult | null;
  reduced: EventResult | null;
  reduction: {
    evaluations: number;
    original_complexity: number[];
    reduced_complexity: number[];
    minimality: string;
  } | null;
  trials: { is_failure: boolean; evaluation: number }[];
  limitations: string[];
  request: { seed: number; budget: number; timeout_s: number; case: Case };
}
type Run = Regression | Temporal;
interface Reference {
  passed: boolean;
  max_error_pu: number;
  tolerance_pu: number;
  scope: string;
  reference: { title: string; url: string; note: string };
  rows: {
    node: string;
    published_pu: number;
    actual_pu: number;
    error_pu: number;
    passed: boolean;
  }[];
}
type Saved = { id: string; kind: string; title: string; created_at: string };
const policies = ['nominal-v1', 'guarded-v1', 'hold-v1'];
const fmt = (n: number, digits = 1) => n.toLocaleString('en-US', { maximumFractionDigits: digits });
const check = (pass: boolean) => (pass ? 'Pass' : 'Fail');

export type VerificationMode = 'regression' | 'temporal' | 'reference';

export function Verification({
  ready,
  incidentId,
  mode,
  onModeChange,
}: {
  ready: boolean;
  incidentId: string | null;
  mode: VerificationMode;
  onModeChange: (mode: VerificationMode) => void;
}) {
  const [presets, setPresets] = useState<Case[]>([]);
  const [caseText, setCaseText] = useState('');
  const [baseline, setBaseline] = useState('nominal-v1');
  const [candidate, setCandidate] = useState('guarded-v1');
  const [seed, setSeed] = useState(42);
  const [budget, setBudget] = useState(12);
  const [timeout, setTimeoutValue] = useState(5);
  const [record, setRecord] = useState<Run | null>(null);
  const [history, setHistory] = useState<Saved[]>([]);
  const [reference, setReference] = useState<Reference | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [replayed, setReplayed] = useState<boolean | null>(null);

  useEffect(() => {
    api<Case[]>('/verification/presets')
      .then((value) => {
        setPresets(value);
        // A delayed preset response must not replace an already imported case.
        setCaseText((current) => current || JSON.stringify(value[0], null, 2));
      })
      .catch((e) => setError(e.message));
    api<Saved[]>('/verification/records')
      .then(setHistory)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let active = true;
    if (incidentId)
      api<Case>(`/verification/cases/from-incident/${incidentId}`)
        .then((value) => {
          if (!active) return;
          setCaseText(JSON.stringify(value, null, 2));
          onModeChange('regression');
          setRecord(null);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [incidentId, onModeChange]);

  async function perform(task: () => Promise<void>) {
    setBusy(true);
    setError('');
    setReplayed(null);
    try {
      await task();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveRun(path: string, body: unknown) {
    const value = await api<Run>(path, body);
    setRecord(value);
    setHistory(await api<Saved[]>('/verification/records'));
  }
  function open(run: Run) {
    setRecord(run);
    onModeChange(run.kind);
    setReplayed(null);
    if (run.kind === 'regression') {
      setCaseText(JSON.stringify(run.request.case, null, 2));
      setCandidate(run.request.candidate);
      setBaseline(run.request.baseline);
    } else {
      setSeed(run.request.seed);
      setBudget(run.request.budget);
      setTimeoutValue(run.request.timeout_s);
    }
  }
  const regression = mode === 'regression' && record?.kind === 'regression' ? record : null;
  const temporal = mode === 'temporal' && record?.kind === 'temporal' ? record : null;
  const deadline = temporal?.reduced?.trace.find((r) => r.event === 'timeout');
  let casePreview: Case | null = null;
  try {
    casePreview = JSON.parse(caseText);
  } catch {
    /* The server validates edited JSON on submit. */
  }

  return (
    <div className="verification-workspace">
      {error && (
        <div className="error-banner" role="alert">
          <TriangleAlert size={18} />
          {error}
        </div>
      )}
      {busy && (
        <div className="busy-banner" role="status">
          <LoaderCircle className="spin" size={16} />
          Running native electrical checks…
        </div>
      )}
      {mode === 'regression' && (
        <>
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Controller comparison</h2>
                <p>Compare two controllers against the same electrical and service requirements.</p>
              </div>
            </div>
            <div className="verification-form">
              <label>
                Test scenario
                <select
                  aria-label="Test scenario"
                  onChange={(e) => {
                    if (e.target.value) {
                      setCaseText(JSON.stringify(presets[Number(e.target.value)], null, 2));
                      setRecord(null);
                    }
                  }}
                  defaultValue=""
                >
                  <option value="">Choose a preset or edit the case below</option>
                  {presets.map((p, i) => (
                    <option value={i} key={p.title}>
                      {p.title}
                    </option>
                  ))}
                </select>
              </label>
              {casePreview?.contract &&
                typeof casePreview.title === 'string' &&
                typeof casePreview.fault === 'string' &&
                typeof casePreview.contract.minimum_restored_kw === 'number' &&
                typeof casePreview.contract.minimum_critical_kw === 'number' && (
                  <div className="verification-case-preview">
                    <b>{casePreview.title}</b>
                    <span>
                      {casePreview.feeder === 'ieee13'
                        ? 'Modified IEEE13 feeder'
                        : 'Custom teaching feeder'}{' '}
                      · isolated line {casePreview.fault}
                    </span>
                    <span>
                      Required: {casePreview.contract.minimum_restored_kw} kW restored;{' '}
                      {casePreview.contract.minimum_critical_kw} kW critical service.
                    </span>
                  </div>
                )}
              <div className="verification-controls">
                <label>
                  Baseline controller
                  <select value={baseline} onChange={(e) => setBaseline(e.target.value)}>
                    {policies.map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Candidate controller
                  <select value={candidate} onChange={(e) => setCandidate(e.target.value)}>
                    {policies.map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </select>
                </label>
                <button
                  className="primary-button"
                  disabled={busy || !ready || !caseText}
                  onClick={() =>
                    perform(() =>
                      saveRun('/verification/regressions', {
                        case: JSON.parse(caseText),
                        baseline,
                        candidate,
                      }),
                    )
                  }
                >
                  <Play size={15} />
                  Compare controllers
                </button>
              </div>
              <details>
                <summary>Scenario JSON and service requirements</summary>
                <p className="method-note">
                  Editing the minimum service requirements changes what is being tested. For IEEE13,
                  load_a is the actual aggregate demand factor; reported_b is the received factor.
                </p>
                <label>
                  Import scenario JSON
                  <input
                    type="file"
                    accept=".json,application/json"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file)
                        perform(async () => {
                          if (file.size > 2_000_000) throw new Error('Scenario file exceeds 2 MB.');
                          const value = JSON.parse(await file.text());
                          setCaseText(JSON.stringify(value.request?.case ?? value, null, 2));
                        });
                    }}
                  />
                </label>
                <textarea
                  aria-label="Scenario JSON"
                  rows={15}
                  spellCheck={false}
                  value={caseText}
                  onChange={(e) => setCaseText(e.target.value)}
                />
              </details>
              <p className="method-note">
                Hold makes no restoration attempt. Passing electrical limits alone does not meet a
                service requirement. Guarded checks use three demand samples, not every value in the
                range.
              </p>
            </div>
          </div>
          {regression && (
            <div className="panel" data-testid="regression-result">
              <div className="panel-header">
                <div>
                  <h2>
                    {regression.accepted
                      ? 'Requirements met · no service regression'
                      : 'Change needs review'}
                  </h2>
                  <p>
                    {regression.historical_baseline
                      ? `Compared with recorded outcome ${regression.historical_baseline.source_record_id.slice(0, 8)}`
                      : 'Both controllers use the same received information.'}
                  </p>
                </div>
                {regression.accepted ? <CheckCircle2 size={22} /> : <TriangleAlert size={22} />}
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Controller</th>
                      <th>Action</th>
                      <th>Electrical limits</th>
                      <th>Service requirements</th>
                      <th>Restored</th>
                      <th>Critical served</th>
                      <th>Max loading</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[regression.baseline, regression.candidate].map((r, i) => (
                      <tr key={i}>
                        <td>
                          <b>{i === 0 ? 'Baseline' : 'Candidate'}</b>
                          <small className="block-muted">{r.controller}</small>
                        </td>
                        <td>{r.action.id}</td>
                        <td>{check(r.electrical_pass)}</td>
                        <td>{check(r.service_pass)}</td>
                        <td>{fmt(r.result.restored_kw)} kW</td>
                        <td>{fmt(r.result.critical_served_kw)} kW</td>
                        <td>{fmt(r.result.max_loading_pct)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="verification-body">
                <p>
                  Required: {fmt(regression.request.case.contract.minimum_restored_kw)} kW restored;{' '}
                  {fmt(regression.request.case.contract.minimum_critical_kw)} kW critical service.
                </p>
                {regression.regressions.map((r) => (
                  <p className="violation-text" key={r}>
                    {r}
                  </p>
                ))}
                {[regression.baseline, regression.candidate].map((r, i) => (
                  <div key={i}>
                    {r.result.violations.map((v, j) => (
                      <p className="violation-text" key={j}>
                        {i === 0 ? 'Baseline' : 'Candidate'}: {v.message}
                      </p>
                    ))}
                  </div>
                ))}
                <details>
                  <summary>Controller inputs, predictions and electrical results</summary>
                  <pre className="raw-records">
                    {JSON.stringify(
                      {
                        baseline: regression.baseline,
                        candidate: regression.candidate,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
                <p className="method-note">{regression.interpretation}</p>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() =>
                    perform(() =>
                      saveRun(`/verification/records/${regression.id}/rerun`, {
                        candidate,
                      }),
                    )
                  }
                >
                  Compare with saved baseline
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {mode === 'temporal' && (
        <>
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Switch position and confirmation</h2>
                <p>
                  Find a failed switch closure with late confirmation, then simplify the sequence.
                </p>
              </div>
            </div>
            <div className="verification-form">
              <div className="verification-controls">
                <label>
                  Search seed
                  <input
                    aria-label="Search seed"
                    type="number"
                    min={0}
                    max={2147483647}
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                  />
                </label>
                <label>
                  Event sequences to test
                  <input
                    type="number"
                    min={1}
                    max={32}
                    value={budget}
                    onChange={(e) => setBudget(Number(e.target.value))}
                  />
                </label>
                <label>
                  Confirmation timeout (s)
                  <input
                    type="number"
                    min={2}
                    max={10}
                    value={timeout}
                    onChange={(e) => setTimeoutValue(Number(e.target.value))}
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={busy || !ready}
                  onClick={() =>
                    perform(() =>
                      saveRun('/verification/temporal', {
                        seed,
                        budget,
                        timeout_s: timeout,
                      }),
                    )
                  }
                >
                  <Play size={15} />
                  Search switch failures
                </button>
              </div>
              <p className="method-note">
                This test uses fresh demand and one tie-line closure. Optimistic-v1 deliberately
                assumes success. Confirmed-v2 waits for position feedback and reports an unknown
                state at the timeout. Both receive the same messages.
              </p>
            </div>
          </div>
          {temporal && (
            <div className="panel" data-testid="temporal-result">
              <div className="panel-header">
                <div>
                  <h2>
                    {temporal.reduced
                      ? 'False restoration claim reproduced'
                      : 'No failure found in this search'}
                  </h2>
                  <p>
                    {temporal.trials.filter((t) => t.is_failure).length} / {temporal.trials.length}{' '}
                    sequences made the optimistic tracker claim restoration incorrectly.
                  </p>
                </div>
              </div>
              {temporal.reduced && temporal.reduction && (
                <>
                  <div className="verification-body">
                    <p>
                      Reduction: {temporal.reduction.original_complexity[0]} →{' '}
                      {temporal.reduction.reduced_complexity[0]} events; delay/time score{' '}
                      {temporal.reduction.original_complexity[1]} →{' '}
                      {temporal.reduction.reduced_complexity[1]}. {temporal.reduction.evaluations}{' '}
                      reduction evaluations.
                    </p>
                    <p className="method-note">{temporal.reduction.minimality}</p>
                    <p>
                      <b>Simplified sequence:</b>{' '}
                      {temporal.reduced.events
                        .map((e) => `${e.kind}${e.delay_s ? ` (${e.delay_s}s)` : ''}`)
                        .join(' + ')}
                    </p>
                  </div>
                  {deadline && (
                    <div className="verification-deadline" data-testid="deadline-summary">
                      <b>At the {deadline.at_s}s timeout</b>
                      <div>
                        <span>Optimistic tracker</span>
                        <strong>{deadline.trackers['optimistic-v1'].status}</strong>
                      </div>
                      <div>
                        <span>Confirmed tracker</span>
                        <strong>{deadline.trackers['confirmed-v2'].status}</strong>
                      </div>
                      <div>
                        <span>Simulated restoration</span>
                        <strong>
                          {fmt(deadline.actual_restored_kw)} kW · switch{' '}
                          {deadline.physical_closed ? 'closed' : 'open'}
                        </strong>
                      </div>
                    </div>
                  )}
                  <p className="verification-table-hint">
                    Full sequence below. Scroll the table horizontally on a small screen.
                  </p>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Event</th>
                          <th>Command / physical</th>
                          <th>Optimistic tracker</th>
                          <th>Confirmed tracker</th>
                          <th>Simulated restored load</th>
                        </tr>
                      </thead>
                      <tbody>
                        {temporal.reduced.trace.map((r, i) => (
                          <tr key={i}>
                            <td>{r.at_s}s</td>
                            <td>{r.detail}</td>
                            <td>
                              {r.commanded_closed ? 'Close' : 'None'} /{' '}
                              {r.physical_closed ? 'closed' : 'open'}
                            </td>
                            <td>{r.trackers['optimistic-v1'].status}</td>
                            <td>
                              {r.trackers['confirmed-v2'].status}
                              <small className="block-muted">
                                Confirmed:{' '}
                                {r.trackers['confirmed-v2'].confirmed_closed
                                  ? 'closed'
                                  : 'open / unconfirmed'}
                              </small>
                            </td>
                            <td>{fmt(r.actual_restored_kw)} kW</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="verification-body">
                    <p>
                      {fmt(temporal.reduced.unserved_energy_kwh, 3)} kWh unserved over the{' '}
                      {temporal.reduced.duration_s}s recorded horizon.
                    </p>
                    <p>{temporal.reduced.interpretation}</p>
                  </div>
                </>
              )}
              <div className="verification-body">
                {temporal.limitations.map((l) => (
                  <p className="method-note" key={l}>
                    {l}
                  </p>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      {mode === 'reference' && (
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Published voltage reference</h2>
              <p>Original IEEE13 topology and loads, with regulator taps fixed to the reference.</p>
            </div>
            <button
              className="primary-button"
              disabled={busy || !ready}
              onClick={() =>
                perform(async () => setReference(await api<Reference>('/verification/reference')))
              }
            >
              <Play size={15} />
              Validate IEEE feeder
            </button>
          </div>
          <div className="verification-body">
            <p>
              Compare 29 published phase voltages with the OpenDSS IEEE 13-node model. This check
              uses no added restoration ties or experimental ratings.
            </p>
            <p className="method-note">
              Restoration experiments add ties, assumed ratings and critical loads. They use fixed
              taps and 0.90–1.10 pu voltage limits. Those changes need separate validation.
            </p>
          </div>
          <div className="verification-body">
            <p className="method-note">
              This checks voltages only. The native-default extended audit passes 52 of 56 checks.
              The separately configured constant-PQ reference passes 56 of 56. Four native-default
              current/power differences come from the load law and numerical convergence.
              ASSURANCE.md records each configuration and its scope.
            </p>
          </div>
          {reference && (
            <>
              <div className="verification-body" role="status">
                <b>{reference.passed ? 'Reference check passed' : 'Reference check failed'}</b>
                <p>
                  Maximum error {reference.max_error_pu.toFixed(6)} pu; tolerance{' '}
                  {reference.tolerance_pu} pu.
                </p>
                <p>
                  <a href={reference.reference.url} target="_blank" rel="noreferrer">
                    {reference.reference.title}
                  </a>
                </p>
                <p className="method-note">{reference.scope}</p>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Bus.phase</th>
                      <th>Published pu</th>
                      <th>OpenDSS pu</th>
                      <th>Error pu</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reference.rows.map((r) => (
                      <tr key={r.node}>
                        <td>{r.node}</td>
                        <td>{r.published_pu.toFixed(4)}</td>
                        <td>{r.actual_pu.toFixed(6)}</td>
                        <td>{r.error_pu.toFixed(6)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
      {(regression || temporal) && record && (
        <div className="verification-actions">
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() =>
              perform(async () => {
                const r = await api<{ matched: boolean }>(
                  `/verification/records/${record.id}/replay`,
                  {},
                );
                setReplayed(r.matched);
              })
            }
          >
            <RotateCcw size={15} />
            Verify recorded run
          </button>
          <a
            className="secondary-button"
            href={`/api/verification/records/${record.id}/export`}
            download
          >
            <ArrowDownToLine size={15} />
            Export complete run
          </a>
          {replayed !== null && (
            <span role="status">
              {replayed
                ? 'Replay matched the recorded run within numerical tolerance.'
                : 'Replay found differences.'}
            </span>
          )}
        </div>
      )}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Saved verification runs</h2>
            <p>
              Open a saved run to check replay or compare another controller against its outcome.
            </p>
          </div>
        </div>
        {history.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Experiment</th>
                  <th>Recorded</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {history.map((r) => (
                  <tr key={r.id}>
                    <td>{r.title}</td>
                    <td>
                      {r.kind === 'regression'
                        ? 'Controller comparison'
                        : r.kind === 'temporal'
                          ? 'Switch confirmation'
                          : r.kind}
                    </td>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td>
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() =>
                          perform(async () => open(await api<Run>(`/verification/records/${r.id}`)))
                        }
                        aria-label={`Open verification ${r.id}`}
                      >
                        Open run
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="verification-body">
            Run a controller comparison or switch-failure search to save the results here.
          </p>
        )}
      </div>
    </div>
  );
}
