import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  CheckCircle2,
  FlaskConical,
  LoaderCircle,
  Play,
  RotateCcw,
  Search,
  TriangleAlert,
} from 'lucide-react';
import { api } from './api';
import { variables } from './failureTypes';
import type {
  SearchInput,
  SearchRecord,
  SearchReplay,
  SearchSummary,
  Variable,
} from './failureTypes';
import './failure-search.css';

const labels: Record<Variable, string> = {
  load_a: 'Affected demand',
  load_b: 'Actual west demand',
  load_c: 'Actual east demand',
  reported_b: 'Reported west demand',
};
const initial: SearchInput = {
  policy: 'nominal',
  seed: 42,
  budget: 24,
  reduction_budget: 48,
  uncertainty_pct: 40,
  telemetry_age_s: 120,
  assumption_scope: 'inside',
  bounds: {
    load_a: { minimum: 0.75, maximum: 1.25 },
    load_b: { minimum: 0.5, maximum: 2 },
    load_c: { minimum: 0.5, maximum: 1.8 },
    reported_b: { minimum: 0.5, maximum: 1.5 },
  },
  reference: { load_a: 1, load_b: 0.8, load_c: 1, reported_b: 0.8 },
};
const categoryName = (value: string) => value.replaceAll('_', ' ');
const seconds = (value: number | null) => (value === null ? '—' : `${value.toFixed(1)}s`);

export function FailureSearch({
  ready,
  onOpenIncident,
  onSaved,
}: {
  ready: boolean;
  onOpenIncident: (id: string) => void;
  onSaved: () => Promise<void>;
}) {
  const [settings, setSettings] = useState<SearchInput>(initial);
  const [record, setRecord] = useState<SearchRecord | null>(null);
  const [history, setHistory] = useState<SearchSummary[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reproduction, setReproduction] = useState<SearchReplay | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (ready)
      api<SearchSummary[]>('/failure-searches')
        .then((data) => {
          if (!cancelled) setHistory(data);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    return () => {
      cancelled = true;
    };
  }, [ready]);

  function setNumber(
    key: 'seed' | 'budget' | 'reduction_budget' | 'uncertainty_pct' | 'telemetry_age_s',
    value: string,
  ) {
    setSettings((s) => ({ ...s, [key]: Number(value) }));
  }
  function setRange(key: Variable, field: 'minimum' | 'maximum' | 'reference', value: string) {
    setSettings((s) =>
      field === 'reference'
        ? { ...s, reference: { ...s.reference, [key]: Number(value) } }
        : {
            ...s,
            bounds: {
              ...s.bounds,
              [key]: { ...s.bounds[key], [field]: Number(value) },
            },
          },
    );
  }
  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy('Searching with both methods, then checking simpler cases');
    setError(null);
    try {
      const value = await api<SearchRecord>('/failure-searches', settings);
      setRecord(value);
      setReproduction(null);
      setHistory(await api<SearchSummary[]>('/failure-searches'));
      await onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function load(id: string) {
    setBusy('Opening saved search');
    setError(null);
    try {
      const value = await api<SearchRecord>(`/failure-searches/${id}`);
      setRecord(value);
      setSettings(value.request);
      setReproduction(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function reproduce() {
    if (!record) return;
    setBusy('Checking replay of both failure cases');
    setError(null);
    try {
      setReproduction(await api<SearchReplay>(`/failure-searches/${record.id}/replay`, {}));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const reduced = record?.reduced_finding;
  const reduction = record?.reduction;
  const changed = record && JSON.stringify(settings) !== JSON.stringify(record.request);
  const simplified =
    reduction && reduction.reduced_complexity.some((v, i) => v < reduction.original_complexity[i]);

  return (
    <div className="failure-workspace">
      {error && (
        <div className="error-banner" role="alert">
          <TriangleAlert size={17} />
          {error}
        </div>
      )}
      {busy && (
        <div className="busy-banner" role="status">
          <LoaderCircle className="spin" size={16} />
          {busy}… A full search may take a minute or more.
        </div>
      )}
      <div className="failure-layout">
        <aside className="panel search-settings">
          <div className="panel-header">
            <div>
              <h2>
                <Search size={17} />
                Search for an avoidable violation
              </h2>
              <p>Search four demand variables on the teaching feeder. Every trial runs OpenDSS.</p>
            </div>
          </div>
          <form onSubmit={run}>
            <fieldset disabled={!ready || !!busy}>
              <label>
                Controller under test
                <select
                  value={settings.policy}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      policy: e.target.value as SearchInput['policy'],
                    }))
                  }
                >
                  <option value="nominal">Nominal · reported demand</option>
                  <option value="guarded">Guarded · check demand samples</option>
                </select>
              </label>
              <label>
                Demand range to test
                <select
                  value={settings.assumption_scope}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      assumption_scope: e.target.value as SearchInput['assumption_scope'],
                    }))
                  }
                >
                  <option value="inside">Keep west demand inside the assumed range</option>
                  <option value="unrestricted">Allow west demand outside the assumed range</option>
                </select>
              </label>
              <div className="search-input-pair">
                <label>
                  Seed
                  <input
                    type="number"
                    min={0}
                    max={2147483647}
                    step={1}
                    required
                    value={settings.seed}
                    onChange={(e) => setNumber('seed', e.target.value)}
                  />
                </label>
                <label>
                  Trials per method
                  <input
                    type="number"
                    min={4}
                    max={64}
                    step={1}
                    required
                    value={settings.budget}
                    onChange={(e) => setNumber('budget', e.target.value)}
                  />
                </label>
                <label>
                  Simplification checks
                  <input
                    type="number"
                    min={0}
                    max={96}
                    step={1}
                    required
                    value={settings.reduction_budget}
                    onChange={(e) => setNumber('reduction_budget', e.target.value)}
                  />
                </label>
                <label>
                  Assumed range ±%
                  <input
                    type="number"
                    min={0}
                    max={80}
                    required
                    value={settings.uncertainty_pct}
                    onChange={(e) => setNumber('uncertainty_pct', e.target.value)}
                  />
                </label>
              </div>
              <details className="search-domain">
                <summary>Demand bounds and simplification reference</summary>
                <p>
                  Factors change in steps of 0.05. Simplification moves toward the reference while
                  keeping the selected action and the same constraint violation.
                </p>
                <div className="range-grid range-heading">
                  <span>Factor</span>
                  <span>Min</span>
                  <span>Max</span>
                  <span>Reference</span>
                </div>
                {variables.map((key) => (
                  <div className="range-grid" key={key}>
                    <span>{labels[key]}</span>
                    {(['minimum', 'maximum', 'reference'] as const).map((field) => (
                      <input
                        key={field}
                        aria-label={`${labels[key]} ${field}`}
                        type="number"
                        min={0.5}
                        max={key === 'load_a' ? 1.5 : 2}
                        step={0.05}
                        required
                        value={
                          field === 'reference'
                            ? settings.reference[key]
                            : settings.bounds[key][field]
                        }
                        onChange={(e) => setRange(key, field, e.target.value)}
                      />
                    ))}
                  </div>
                ))}
                <label>
                  West reading age (s)
                  <input
                    type="number"
                    min={1}
                    max={3600}
                    step={1}
                    required
                    value={settings.telemetry_age_s}
                    onChange={(e) => setNumber('telemetry_age_s', e.target.value)}
                  />
                </label>
                <p>
                  Age tells you how old the reading is, not how far it is from actual demand.
                  Affected and east demand readings are assumed accurate.
                </p>
              </details>
              <button className="primary-button search-run" type="submit">
                <Play size={14} />
                Compare searches
              </button>
            </fieldset>
            <p className="method-note">
              Both searches use the same seed and trial count. The first four samples match.
              Directed search then tries nearby changes and wider exploration. Simplification has
              its own budget.
            </p>
          </form>
        </aside>
        <section className="search-results">
          {!record ? (
            <div className="panel search-intro">
              <FlaskConical size={28} />
              <h2>Find and simplify a failing case</h2>
              <p>
                A target case must start within modeled limits, choose a route that violates a
                limit, and have a feasible alternative that serves critical demand.
              </p>
              <p>
                The evaluator checks each route against actual simulated demand. The controller only
                sees the measurements it receives.
              </p>
              <div className="search-process">
                <span>01 · Discover</span>
                <span>02 · Simplify</span>
                <span>03 · Reproduce</span>
              </div>
            </div>
          ) : (
            <>
              <div className="results-caption">
                <span>
                  Saved search · {record.request.policy} · seed {record.request.seed} ·{' '}
                  {record.id.slice(0, 8)}
                </span>
                {changed && (
                  <span className="badge badge-neutral">
                    Settings changed · showing saved result
                  </span>
                )}
              </div>
              <div className="panel search-comparison">
                <div className="panel-header">
                  <div>
                    <h2>{reduced ? 'Avoidable violation found' : 'No target failure found'}</h2>
                    <p>
                      {record.request.assumption_scope === 'inside'
                        ? 'Actual west demand stayed inside the declared uncertainty range.'
                        : 'The search allowed actual demand to exceed the declared range.'}
                    </p>
                  </div>
                  <a
                    className="secondary-button"
                    href={`/api/failure-searches/${record.id}/export`}
                    download
                  >
                    <ArrowDownToLine size={14} />
                    Export search JSON
                  </a>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Method</th>
                        <th>Trials used</th>
                        <th>First failure</th>
                        <th>Failing trials</th>
                        <th>Time to first</th>
                        <th>Total time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(['directed', 'random'] as const).map((key) => {
                        const m = record.strategies[key];
                        return (
                          <tr key={key}>
                            <td>
                              <b>{key === 'directed' ? 'Directed search' : 'Uniform random'}</b>
                            </td>
                            <td>
                              {m.evaluations} / {m.budget}
                            </td>
                            <td>{m.first_failure_evaluation ?? 'Not found'}</td>
                            <td>{m.failing_scenarios}</td>
                            <td>{seconds(m.seconds_to_first_failure)}</td>
                            <td>{seconds(m.elapsed_seconds)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="search-note">
                  {reduced
                    ? `Simplifying the first ${record.selected_strategy} failure. Counts are failing scenarios sampled, not distinct bugs.`
                    : 'No failure was found within this search. That does not establish safety. You can try another seed, budget or demand range.'}{' '}
                  Time includes complete incident evaluations and excludes reduction and replay.
                </p>
                <details className="search-details">
                  <summary>Outcome categories and search trace</summary>
                  {(['directed', 'random'] as const).map((key) => (
                    <div key={key}>
                      <h3>{key === 'directed' ? 'Directed search' : 'Uniform random'}</h3>
                      <p>
                        {Object.entries(record.strategies[key].categories)
                          .map(([c, n]) => `${categoryName(c)}: ${n}`)
                          .join(' · ')}
                        {record.strategies[key].space_exhausted
                          ? ' · All admissible grid points evaluated'
                          : ''}
                      </p>
                      <div className="table-scroll search-trace">
                        <table>
                          <thead>
                            <tr>
                              <th>Trial</th>
                              <th>Affected</th>
                              <th>West actual</th>
                              <th>East actual</th>
                              <th>West reported</th>
                              <th>Result</th>
                            </tr>
                          </thead>
                          <tbody>
                            {record.strategies[key].trace.map((row) => (
                              <tr key={row.evaluation}>
                                <td>{row.evaluation}</td>
                                {variables.map((k) => (
                                  <td key={k}>{row.point[k].toFixed(2)}×</td>
                                ))}
                                <td>{categoryName(row.category)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </details>
              </div>
              {reduced && reduction && record.original_incident && record.reduced_incident && (
                <div className="panel reduced-case">
                  <div className="panel-header">
                    <div>
                      <h2>
                        {simplified
                          ? 'Same failure · simpler demand case'
                          : 'The failing case could not be simplified'}
                      </h2>
                      <p>
                        {reduction.evaluations} / {reduction.budget} simplification checks ·{' '}
                        {reduction.neighborhood_exhausted
                          ? 'No simpler case kept the same failure in this search'
                          : 'Simplification budget used up'}
                      </p>
                    </div>
                    <span
                      className={`badge ${reduced.truth_inside_assumed_range ? 'badge-neutral' : 'badge-warn'}`}
                    >
                      {reduced.truth_inside_assumed_range
                        ? 'Inside assumed range'
                        : 'Assumed range exceeded'}
                    </span>
                  </div>
                  <div className="failure-proof">
                    <div>
                      <span>SELECTED ACTION</span>
                      <h3>{reduced.action_label}</h3>
                      <p>
                        Estimated max loading <b>{reduced.predicted_loading_pct.toFixed(1)}%</b> →
                        actual <b>{reduced.actual_loading_pct.toFixed(1)}%</b>
                      </p>
                      {reduced.violations.map((v, i) => (
                        <p className="constraint-failure" key={i}>
                          <TriangleAlert size={13} />
                          {v.message}
                        </p>
                      ))}
                    </div>
                    <div>
                      <span>ALTERNATIVE USING SIMULATED DEMAND</span>
                      <h3>{reduced.feasible_alternative.label}</h3>
                      <p>
                        {reduced.feasible_alternative.restored_kw.toFixed(0)} kW restored ·{' '}
                        {reduced.feasible_alternative.critical_served_kw.toFixed(0)} kW critical
                        served.
                      </p>
                      <p>This comparison uses demand that the controller did not receive.</p>
                    </div>
                  </div>
                  <div className="table-scroll">
                    <table aria-label="Failure simplification">
                      <thead>
                        <tr>
                          <th>Demand factor</th>
                          <th>Reference</th>
                          <th>Original</th>
                          <th>Reduced</th>
                        </tr>
                      </thead>
                      <tbody>
                        {variables.map((k) => (
                          <tr key={k}>
                            <td>{labels[k]}</td>
                            <td>{record.request.reference[k].toFixed(2)}×</td>
                            <td>{record.original_incident!.scenario[k].toFixed(2)}×</td>
                            <td>
                              <b>{record.reduced_incident!.scenario[k].toFixed(2)}×</b>
                            </td>
                          </tr>
                        ))}
                        <tr>
                          <td>Deviating variables / grid steps</td>
                          <td>0 / 0</td>
                          <td>{reduction.original_complexity.join(' / ')}</td>
                          <td>{reduction.reduced_complexity.join(' / ')}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div className="search-case-actions">
                    <button
                      className="secondary-button"
                      disabled={!!busy}
                      onClick={() => onOpenIncident(record.original_incident!.id)}
                    >
                      Open original incident
                      <ArrowRight size={14} />
                    </button>
                    <button
                      className="secondary-button"
                      disabled={!!busy}
                      onClick={() => onOpenIncident(record.reduced_incident!.id)}
                    >
                      Open simplified incident
                      <ArrowRight size={14} />
                    </button>
                    <button className="primary-button" disabled={!!busy} onClick={reproduce}>
                      <RotateCcw size={14} />
                      Replay failure cases
                    </button>
                  </div>
                  <p className="search-note">
                    Simplification preserves the selected action, {reduction.signature.element} /{' '}
                    {categoryName(reduction.signature.kind)}, and whether the demand assumption was
                    exceeded. A smaller case may still exist outside this search.
                  </p>
                  <details className="search-details">
                    <summary>Inspect simplification checks</summary>
                    <div className="table-scroll search-trace">
                      <table>
                        <thead>
                          <tr>
                            <th>Check</th>
                            <th>Affected</th>
                            <th>West actual</th>
                            <th>East actual</th>
                            <th>West reported</th>
                            <th>Kept?</th>
                          </tr>
                        </thead>
                        <tbody>
                          {reduction.trace.map((row) => (
                            <tr key={row.evaluation}>
                              <td>{row.evaluation}</td>
                              {variables.map((k) => (
                                <td key={k}>{row.point[k].toFixed(2)}×</td>
                              ))}
                              <td>
                                {row.accepted
                                  ? 'Yes · failure preserved'
                                  : categoryName(row.category)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </div>
              )}
              {reproduction && (
                <div
                  className={`replay-banner ${reproduction.matched ? 'matched' : 'mismatch'}`}
                  role="status"
                >
                  {reproduction.matched ? <CheckCircle2 size={19} /> : <TriangleAlert size={19} />}
                  <div>
                    <b>
                      {reproduction.matched
                        ? 'Original and reduced failures reproduced.'
                        : 'Reproduction found a difference.'}
                    </b>
                    <p>
                      Controller decisions rerun;{' '}
                      {Object.values(reproduction.cases).reduce(
                        (n, c) => n + c.branches_checked,
                        0,
                      )}{' '}
                      recorded electrical branches checked. Tolerance {reproduction.tolerance}.
                    </p>
                    {reproduction.differences.length > 0 && (
                      <p>{reproduction.differences.join(', ')}</p>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
          {history.length > 0 && (
            <div className="panel search-history">
              <div className="panel-header">
                <h2>Saved searches</h2>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Search</th>
                      <th>Controller</th>
                      <th>Result</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <b>{row.id.slice(0, 8)}</b>
                          <small className="block-muted">
                            {new Date(row.created_at).toLocaleString()}
                          </small>
                        </td>
                        <td>{row.policy}</td>
                        <td>
                          {row.status === 'failure_found' ? 'Failure found' : 'No target found'}
                        </td>
                        <td>
                          <button
                            className="secondary-button"
                            disabled={!!busy}
                            aria-label={`Open search ${row.id.slice(0, 8)}`}
                            onClick={() => load(row.id)}
                          >
                            Open
                            <ArrowRight size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
