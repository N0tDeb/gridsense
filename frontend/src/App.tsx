import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Database,
  FileClock,
  FlaskConical,
  Gauge,
  GitBranch,
  Layers3,
  LoaderCircle,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
  Unplug,
  Zap,
} from 'lucide-react';
import { api } from './api';
import { FailureChart } from './FailureChart';
import { FailureSearch } from './FailureSearch';
import { Verification } from './Verification';
import type { VerificationMode } from './Verification';
import { DetailDialog } from './DetailDialog';
import { Topology } from './Topology';
import { LiveGrid } from './LiveGrid';
import { version as appVersion } from '../package.json';
import type {
  ElectricalResult,
  Incident,
  Network,
  Policy,
  Preset,
  Replay,
  Review,
  Scenario,
  Summary,
  Sweep,
} from './types';

const initial: Scenario = {
  title: 'Stale west-feeder telemetry',
  load_a: 1,
  load_b: 1.5,
  load_c: 0.9,
  reported_b: 0.85,
  telemetry_age_s: 120,
  uncertainty_pct: 80,
  policy: 'guarded',
};
const policyNames: Record<Policy, string> = {
  nominal: 'Nominal',
  guarded: 'Guarded',
  oracle: 'Full-information reference',
};
const format = (n: number, digits = 0) =>
  n.toLocaleString('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
const stamp = (s: string) =>
  new Date(s).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

function Badge({ good, children }: { good?: boolean; children: ReactNode }) {
  return (
    <span
      className={`badge ${good === undefined ? 'badge-neutral' : good ? 'badge-good' : 'badge-warn'}`}
    >
      {good === undefined ? null : good ? <Check size={11} /> : <TriangleAlert size={11} />}
      {children}
    </span>
  );
}
function NumberField({
  label,
  hint,
  value,
  min,
  max,
  step = 0.05,
  suffix = '×',
  change,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  change: (n: number) => void;
}) {
  return (
    <label className="number-field">
      <span>
        <b>{label}</b>
        {hint && <small>{hint}</small>}
      </span>
      <span className="number-input">
        <input
          aria-label={label}
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          required
          onChange={(e) => change(Number(e.target.value))}
        />
        <i>{suffix}</i>
      </span>
    </label>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty-state">
      <Layers3 size={28} />
      <h2>No incident selected</h2>
      <p>{children}</p>
    </div>
  );
}
function Metric({
  label,
  value,
  unit,
  detail,
  icon,
  warn,
}: {
  label: string;
  value: string;
  unit?: string;
  detail: string;
  icon: ReactNode;
  warn?: boolean;
}) {
  return (
    <div className={`metric ${warn ? 'metric-warn' : ''}`}>
      <div className="metric-label">
        {label}
        {icon}
      </div>
      <div className="metric-value">
        {value}
        <span>{unit}</span>
      </div>
      <small>{detail}</small>
    </div>
  );
}
function ResultTable({ result }: { result: ElectricalResult }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Demand point</th>
            <th>Requested</th>
            <th>Served</th>
            <th>Voltage</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {result.load_measurements.map((row) => (
            <tr key={row.load_id}>
              <td>
                {row.label}
                {row.critical && <span className="inline-note">Critical</span>}
              </td>
              <td>{format(row.requested_kw)} kW</td>
              <td>{format(row.served_kw)} kW</td>
              <td>{row.energized ? `${row.voltage_pu.toFixed(3)} pu` : '—'}</td>
              <td>
                <Badge good={row.energized}>{row.energized ? 'Energized' : 'Out of service'}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [network, setNetwork] = useState<Network | null>(null);
  const [ready, setReady] = useState(false);
  const [engineUnavailable, setEngineUnavailable] = useState(false);
  const [engineMessage, setEngineMessage] = useState<string | undefined>();
  const [presets, setPresets] = useState<Preset[]>([]);
  const [scenario, setScenario] = useState<Scenario>(initial);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [archive, setArchive] = useState<Summary[]>([]);
  const [tab, setTab] = useState<
    'live' | 'live-analysis' | 'lab' | 'evidence' | 'archive' | 'failure' | 'verification'
  >('live');
  const [aboutOpen, setAboutOpen] = useState(false);
  const [verificationMode, setVerificationMode] = useState<VerificationMode>('regression');
  const [verificationIncidentId, setVerificationIncidentId] = useState<string | null>(null);
  const [viewPolicy, setViewPolicy] = useState<Policy>('guarded');
  const [before, setBefore] = useState(false);
  const [selectedBus, setSelectedBus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replayResult, setReplayResult] = useState<Replay | null>(null);
  const [sweepResult, setSweepResult] = useState<Sweep | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [note, setNote] = useState('');
  const [search, setSearch] = useState('');
  const [showRaw, setShowRaw] = useState(false);

  function adopt(value: Incident) {
    setIncident(value);
    setViewPolicy(value.scenario.policy);
    setBefore(false);
    setSelectedBus(null);
    setReplayResult(null);
    setSweepResult(null);
    setReviews([]);
    setNote('');
  }
  async function loadIncident(id: string) {
    setBusy('Loading incident');
    setError(null);
    try {
      const [value, history] = await Promise.all([
        api<Incident>(`/incidents/${id}`),
        api<Review[]>(`/incidents/${id}/reviews`),
      ]);
      adopt(value);
      setScenario(value.scenario);
      setReviews(history);
      setTab('lab');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<{ status: string }>('/health'),
      api<Network>('/network'),
      api<Preset[]>('/presets'),
      api<Summary[]>('/incidents'),
    ])
      .then(([health, model, examples, history]) => {
        if (cancelled) return;
        setReady(health.status === 'ready');
        setEngineUnavailable(health.status !== 'ready');
        setNetwork(model);
        setPresets(examples);
        setArchive(history);
      })
      .catch((e) => {
        if (!cancelled) {
          setEngineUnavailable(true);
          setEngineMessage(e.message);
          setError(`Cannot connect to GridSense. ${e.message} Start the Python server and reload.`);
        }
      });
    let checking = false;
    const timer = window.setInterval(async () => {
      if (checking) return;
      checking = true;
      try {
        const health = await api<{ status: string }>('/health');
        if (!cancelled) {
          setReady(health.status === 'ready');
          setEngineUnavailable(health.status !== 'ready');
          setEngineMessage(undefined);
        }
      } catch (e) {
        if (!cancelled) {
          setReady(false);
          setEngineUnavailable(true);
          setEngineMessage((e as Error).message);
        }
      } finally {
        checking = false;
      }
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy('Solving restoration alternatives');
    setError(null);
    try {
      const value = await api<Incident>('/incidents', scenario);
      adopt(value);
      setArchive(await api<Summary[]>('/incidents'));
      setTab('lab');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function replayIncident() {
    if (!incident) return;
    setBusy('Checking recorded outcomes');
    setError(null);
    try {
      setReplayResult(await api<Replay>(`/incidents/${incident.id}/replay`, {}));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function runSweep() {
    if (!incident) return;
    setBusy('Testing nine west-demand settings');
    setError(null);
    try {
      setSweepResult(
        await api<Sweep>('/sweeps', {
          base: incident.scenario,
          minimum: 0.6,
          maximum: 1.9,
          points: 9,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function review(verdict: 'accepted' | 'questioned') {
    if (!incident) return;
    setBusy('Saving review');
    setError(null);
    try {
      setReviews(
        await api<Review[]>(`/incidents/${incident.id}/reviews`, {
          verdict,
          note,
        }),
      );
      setNote('');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  function field(key: keyof Scenario, value: number | string) {
    setScenario((s) => ({ ...s, [key]: value }));
  }

  const changed = incident && JSON.stringify(scenario) !== JSON.stringify(incident.scenario);
  const outcome = incident?.outcomes[viewPolicy];
  const result = before ? incident?.before : outcome?.result;
  const decision = incident?.decisions[viewPolicy];
  const displayedNetwork = incident?.manifest.network ?? network;
  const selectedReading = result?.load_measurements.find((r) => r.load_id === selectedBus);

  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setTab('live');
          }}
          aria-label="GridSense home"
        >
          <span className="brand-symbol">
            <GitBranch size={21} />
          </span>
          <span>GridSense</span>
        </a>
        <div className="topbar-right">
          <span className="environment">SIMULATION</span>
          <span className="engine-status" role="status" title={engineMessage}>
            <i className={ready ? 'ready' : ''} />
            {ready
              ? 'OpenDSS ready'
              : engineUnavailable
                ? 'Engine unavailable'
                : 'Connecting to engine'}
          </span>
        </div>
      </header>
      <nav className="main-nav" aria-label="Workspace">
        <button
          className={tab === 'live' ? 'active' : ''}
          aria-current={tab === 'live' ? 'page' : undefined}
          onClick={() => setTab('live')}
        >
          <Activity size={16} />
          Live Grid
        </button>
        <button
          className={['live-analysis', 'lab', 'evidence', 'archive'].includes(tab) ? 'active' : ''}
          aria-current={
            ['live-analysis', 'lab', 'evidence', 'archive'].includes(tab) ? 'page' : undefined
          }
          onClick={() => setTab('live-analysis')}
        >
          <FileClock size={16} />
          Incident analysis
        </button>
        <button
          className={tab === 'verification' || tab === 'failure' ? 'active' : ''}
          aria-current={tab === 'verification' || tab === 'failure' ? 'page' : undefined}
          onClick={() => setTab('verification')}
        >
          <CheckCircle2 size={16} />
          Controller tests
        </button>
      </nav>
      <main>
        <div className="page-heading">
          <div>
            <h1>
              {tab === 'live'
                ? 'Live Grid'
                : tab === 'live-analysis'
                  ? 'Incident analysis'
                  : tab === 'lab'
                    ? 'Restoration lab'
                    : tab === 'evidence'
                      ? 'Decision evidence'
                      : tab === 'failure'
                        ? 'Failure search'
                        : tab === 'verification'
                          ? 'Controller tests'
                          : 'Incident archive'}
            </h1>
            <p>
              {tab === 'live'
                ? 'Add a disturbance and follow the grid response.'
                : tab === 'live-analysis'
                  ? 'Review recorded events, measurements and controller decisions.'
                  : tab === 'lab'
                    ? 'Compare switching choices and their electrical consequences.'
                    : tab === 'evidence'
                      ? 'Compare received readings, predictions and simulated outcomes.'
                      : tab === 'failure'
                        ? 'Find an avoidable violation and simplify the case.'
                        : tab === 'verification'
                          ? 'Compare controllers, check switch confirmation and test reference voltages.'
                          : 'Open, export, or replay a saved incident.'}
            </p>
          </div>
          <button className="text-button workspace-help" onClick={() => setAboutOpen(true)}>
            <CircleHelp size={16} /> About this simulation
          </button>
        </div>
        {['live-analysis', 'lab', 'evidence', 'archive'].includes(tab) && (
          <nav className="workspace-subnav" aria-label="Analysis tools">
            <button
              className={tab === 'live-analysis' ? 'active' : ''}
              onClick={() => setTab('live-analysis')}
            >
              Live session timeline
            </button>
            <button
              className={tab === 'lab' || tab === 'evidence' ? 'active' : ''}
              onClick={() => setTab('lab')}
            >
              Restoration lab
            </button>
            <button className={tab === 'archive' ? 'active' : ''} onClick={() => setTab('archive')}>
              Incident archive <span className="nav-count">{archive.length}</span>
            </button>
          </nav>
        )}
        {['verification', 'failure'].includes(tab) && (
          <nav className="workspace-subnav" aria-label="Controller tools">
            {(
              [
                ['regression', 'Controller comparison'],
                ['temporal', 'Switch confirmation'],
                ['reference', 'IEEE feeder check'],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                className={tab === 'verification' && verificationMode === mode ? 'active' : ''}
                aria-current={
                  tab === 'verification' && verificationMode === mode ? 'page' : undefined
                }
                onClick={() => {
                  setVerificationMode(mode);
                  setTab('verification');
                }}
              >
                {label}
              </button>
            ))}
            <button className={tab === 'failure' ? 'active' : ''} onClick={() => setTab('failure')}>
              Failure search
            </button>
          </nav>
        )}
        {error && (
          <div className="error-banner" role="alert">
            <TriangleAlert size={18} />
            <span>{error}</span>
            <button onClick={() => setError(null)} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}
        {busy && (
          <div className="busy-banner" role="status">
            <LoaderCircle size={15} className="spin" />
            {busy}…
          </div>
        )}

        {network && (
          <LiveGrid
            network={network}
            view={tab === 'live' ? 'live' : tab === 'live-analysis' ? 'analysis' : 'hidden'}
            onAnalysis={() => setTab('live-analysis')}
          />
        )}

        {tab === 'lab' && (
          <div className="lab-layout">
            <aside className="scenario-panel panel">
              <div className="panel-header">
                <h2>
                  <SlidersHorizontal size={17} />
                  Scenario settings
                </h2>
                <span className="step-number">01</span>
              </div>
              <form onSubmit={run}>
                <div className="preset-label">START WITH A SCENARIO</div>
                <div className="preset-options">
                  {presets.map((p) => (
                    <button
                      type="button"
                      key={p.id}
                      className={scenario.title === p.scenario.title ? 'selected' : ''}
                      title={p.description}
                      onClick={() => setScenario(p.scenario)}
                    >
                      {p.id === 'stale'
                        ? 'Stale reading'
                        : p.id === 'fresh'
                          ? 'Fresh readings'
                          : 'High feeder demand'}
                    </button>
                  ))}
                </div>
                <label className="title-field">
                  Incident title
                  <input
                    value={scenario.title}
                    maxLength={100}
                    required
                    onChange={(e) => field('title', e.target.value)}
                  />
                </label>
                <div className="isolation-note">
                  <Unplug size={17} />
                  <div>
                    <b>Section A is isolated</b>
                    <span>
                      Incoming line unavailable and locked open.
                      <br />
                      400 kW critical + 600 kW residential at 1×.
                    </span>
                  </div>
                </div>
                <div className="control-section">
                  <div className="section-label">
                    SIMULATED DEMAND <span>Evaluator only</span>
                  </div>
                  <NumberField
                    label="Affected demand"
                    hint={`${format(1000 * scenario.load_a)} kW before isolation`}
                    value={scenario.load_a}
                    min={0.5}
                    max={1.5}
                    change={(n) => field('load_a', n)}
                  />
                  <NumberField
                    label="Actual west demand"
                    hint={`${format(700 * scenario.load_b)} kW · hidden from controller`}
                    value={scenario.load_b}
                    min={0.5}
                    max={2}
                    change={(n) => field('load_b', n)}
                  />
                  <NumberField
                    label="Actual east demand"
                    hint={`${format(850 * scenario.load_c)} kW · current telemetry`}
                    value={scenario.load_c}
                    min={0.5}
                    max={2}
                    change={(n) => field('load_c', n)}
                  />
                </div>
                <div className="control-section">
                  <div className="section-label">RECEIVED DEMAND</div>
                  <NumberField
                    label="Reported west demand"
                    hint={`${format(700 * scenario.reported_b)} kW · last received reading`}
                    value={scenario.reported_b}
                    min={0.5}
                    max={2}
                    change={(n) => field('reported_b', n)}
                  />
                  <NumberField
                    label="West reading age"
                    value={scenario.telemetry_age_s}
                    min={0}
                    max={3600}
                    step={1}
                    suffix="s"
                    change={(n) => field('telemetry_age_s', n)}
                  />
                  <NumberField
                    label="Assumed uncertainty"
                    hint="Range around the reported west demand"
                    value={scenario.uncertainty_pct}
                    min={0}
                    max={80}
                    step={1}
                    suffix="%"
                    change={(n) => field('uncertainty_pct', n)}
                  />
                </div>
                <label className="policy-field">
                  Controller to apply
                  <select value={scenario.policy} onChange={(e) => field('policy', e.target.value)}>
                    <option value="guarded">Guarded · check demand samples</option>
                    <option value="nominal">Nominal · use reported demand</option>
                  </select>
                </label>
                <button
                  className="primary-button run-button"
                  type="submit"
                  disabled={!ready || !!busy}
                >
                  <Play size={15} fill="currentColor" />
                  Run restoration
                  <ArrowRight size={16} />
                </button>
                <p className="form-footnote">
                  Each run saves a new incident. The physical fault stays isolated after service
                  returns.
                </p>
              </form>
            </aside>
            <section className="lab-results">
              <div className="results-caption">
                <span>
                  {incident ? (
                    <>
                      <span className="tiny-dot" />
                      Recorded run · {stamp(incident.created_at)}
                    </>
                  ) : (
                    'Configure a scenario, then run the electrical comparison.'
                  )}
                </span>
                {changed && <Badge>Settings changed · showing previous run</Badge>}
              </div>
              <div className="metrics-grid">
                <Metric
                  label="Affected demand restored"
                  value={result ? format(result.restored_kw) : '—'}
                  unit="kW"
                  detail={
                    result
                      ? `${format(result.unserved_kw)} kW remains unserved`
                      : 'From the OpenDSS load powers'
                  }
                  icon={<Zap size={15} />}
                />
                <Metric
                  label="Critical demand served"
                  value={result ? format(result.critical_served_kw) : '—'}
                  unit="kW"
                  detail="Medical campus · first priority"
                  icon={<ShieldCheck size={15} />}
                />
                <Metric
                  label="Highest equipment loading"
                  value={result ? format(result.max_loading_pct, 1) : '—'}
                  unit="%"
                  detail="Model limit: 100% of rated current"
                  icon={<Gauge size={15} />}
                  warn={!!result && result.max_loading_pct > 100}
                />
                <Metric
                  label="Lowest energized voltage"
                  value={result?.min_voltage_pu ? result.min_voltage_pu.toFixed(3) : '—'}
                  unit="pu"
                  detail="Model voltage limits: 0.95–1.05 pu"
                  icon={<Activity size={15} />}
                  warn={!!result?.min_voltage_pu && result.min_voltage_pu < 0.95}
                />
              </div>
              <div className="panel topology-panel">
                <div className="panel-header">
                  <div>
                    <h2>Electrical network</h2>
                    <p>
                      {incident
                        ? incident.scenario.title
                        : 'A small feeder with two alternate supply paths'}
                    </p>
                  </div>
                  <div className="segmented" aria-label="Electrical snapshot">
                    <button
                      className={before ? 'selected' : ''}
                      disabled={!incident}
                      onClick={() => setBefore(true)}
                    >
                      After isolation
                    </button>
                    <button
                      className={!before ? 'selected' : ''}
                      disabled={!incident}
                      onClick={() => setBefore(false)}
                    >
                      After decision
                    </button>
                  </div>
                </div>
                {incident && (
                  <div className="policy-strip">
                    <span>Inspect controller</span>
                    {(['nominal', 'guarded', 'oracle'] as Policy[]).map((p) => (
                      <button
                        key={p}
                        className={viewPolicy === p ? 'selected' : ''}
                        onClick={() => {
                          setViewPolicy(p);
                          setBefore(false);
                        }}
                      >
                        {policyNames[p]}
                        {p === incident.scenario.policy && <small>APPLIED</small>}
                      </button>
                    ))}
                  </div>
                )}
                {displayedNetwork && (
                  <Topology
                    network={displayedNetwork}
                    state={before ? incident?.initial_state : outcome?.final_state}
                    result={result}
                    selectedBus={selectedBus}
                    onSelect={setSelectedBus}
                  />
                )}
                {!incident && (
                  <div className="topology-empty-note">
                    <CircleHelp size={14} />
                    Topology preview. Electrical readings appear after a simulation.
                  </div>
                )}
                <div className="topology-legend">
                  <span>
                    <i className="legend-line" />
                    Primary path
                  </span>
                  <span>
                    <i className="legend-line backup" />
                    Closed backup
                  </span>
                  <span>
                    <i className="legend-line open" />
                    Open / isolated
                  </span>
                  <span>
                    <i className="legend-critical" />
                    Critical demand
                  </span>
                  <small>Click a demand point to inspect it</small>
                </div>
                {selectedReading && (
                  <div className="node-inspector">
                    <b>{selectedReading.label}</b>
                    <span>
                      {format(selectedReading.served_kw)} / {format(selectedReading.requested_kw)}{' '}
                      kW served
                    </span>
                    <span>
                      {selectedReading.energized
                        ? `${selectedReading.voltage_pu.toFixed(4)} pu`
                        : 'Not energized'}
                    </span>
                    <button onClick={() => setTab('evidence')}>
                      View evidence <ChevronRight size={13} />
                    </button>
                  </div>
                )}
              </div>
              {incident && decision && outcome && (
                <div
                  className={`decision-summary panel ${outcome.result.feasible ? '' : 'decision-violation'}`}
                >
                  <div className="decision-icon">
                    {outcome.result.feasible ? (
                      <ShieldCheck size={23} />
                    ) : (
                      <TriangleAlert size={23} />
                    )}
                  </div>
                  <div>
                    <div className="eyebrow">{policyNames[viewPolicy].toUpperCase()} DECISION</div>
                    <h3>{decision.selected_action.label}</h3>
                    <p>{decision.rationale}</p>
                    {viewPolicy === 'oracle' && (
                      <p className="muted">
                        This reference uses the simulated demand that the other controllers cannot
                        see.
                      </p>
                    )}
                    {outcome.result.violations.map((v, i) => (
                      <p key={i} className="violation-text">
                        Observed consequence: {v.message}
                      </p>
                    ))}
                  </div>
                  <button className="text-button" onClick={() => setTab('evidence')}>
                    Decision evidence
                    <ArrowRight size={16} />
                  </button>
                </div>
              )}
              {!incident && (
                <div className="getting-started">
                  <span>
                    01 <b>Set an incident</b>
                  </span>
                  <ChevronRight size={15} />
                  <span>
                    02 <b>Compare decisions</b>
                  </span>
                  <ChevronRight size={15} />
                  <span>
                    03 <b>Inspect the evidence</b>
                  </span>
                </div>
              )}
              {incident && (
                <details className="panel demand-sweep">
                  <summary>
                    Demand sweep <span>Test changing west-feeder demand</span>
                  </summary>
                  <div className="panel-header">
                    <div>
                      <h2>Test the demand range</h2>
                      <p>Keep received readings fixed and vary actual west demand.</p>
                    </div>
                    <button
                      className="secondary-button"
                      disabled={!!busy || incident.scenario.telemetry_age_s === 0}
                      onClick={runSweep}
                    >
                      <FlaskConical size={15} />
                      Run demand sweep
                    </button>
                  </div>
                  {sweepResult ? (
                    <div className="sweep-body">
                      <FailureChart sweep={sweepResult} />
                      <p className="method-note">{sweepResult.interpretation}</p>
                      <div className="export-links">
                        <a href={`/api/sweeps/${sweepResult.id}/export`} download>
                          <ArrowDownToLine size={14} />
                          Export sweep JSON
                        </a>
                        <a href={`/api/sweeps/${sweepResult.id}/export?format=parquet`} download>
                          <ArrowDownToLine size={14} />
                          Export results Parquet
                        </a>
                      </div>
                      <details>
                        <summary>Inspect all {sweepResult.rows.length} simulated outcomes</summary>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>West kW</th>
                                <th>Controller</th>
                                <th>Action</th>
                                <th>Restored kW</th>
                                <th>Max loading</th>
                                <th>Limits</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sweepResult.rows.map((r, i) => (
                                <tr key={i}>
                                  <td>{format(r.west_demand_kw)}</td>
                                  <td>{policyNames[r.policy]}</td>
                                  <td>{r.action}</td>
                                  <td>{format(r.restored_kw)}</td>
                                  <td>{format(r.max_loading_pct, 1)}%</td>
                                  <td>
                                    <Badge good={r.feasible}>
                                      {r.feasible ? 'Pass' : 'Violation'}
                                    </Badge>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    </div>
                  ) : (
                    <div className="sweep-placeholder">
                      <Activity size={22} />
                      <p>
                        {incident.scenario.telemetry_age_s === 0
                          ? 'Choose a stale-reading scenario to vary demand while holding the received readings fixed.'
                          : 'Nine demand settings, three policies. Each point uses a new OpenDSS solve.'}
                      </p>
                    </div>
                  )}
                </details>
              )}
            </section>
          </div>
        )}

        {tab === 'evidence' &&
          (!incident || !decision || !outcome ? (
            <Empty>
              Run a restoration scenario or open an incident from the archive to inspect its
              evidence.
            </Empty>
          ) : (
            <div className="evidence-layout">
              <div className="incident-bar">
                <div>
                  <Badge good={incident.outcomes[incident.scenario.policy].result.feasible}>
                    {incident.outcomes[incident.scenario.policy].result.feasible
                      ? 'Applied action passes modeled limits'
                      : 'Applied action violates a modeled limit'}
                  </Badge>
                  <h2>{incident.scenario.title}</h2>
                  <span>
                    {stamp(incident.created_at)} · {incident.id.slice(0, 8)}
                  </span>
                </div>
                <div className="button-row">
                  <button
                    className="secondary-button"
                    onClick={() => {
                      setVerificationIncidentId(incident.id);
                      setVerificationMode('regression');
                      setTab('verification');
                    }}
                  >
                    Test controller changes
                  </button>
                  <button className="secondary-button" onClick={replayIncident} disabled={!!busy}>
                    <RotateCcw size={15} />
                    Verify replay
                  </button>
                  <a
                    className="secondary-button"
                    href={`/api/incidents/${incident.id}/export`}
                    download
                  >
                    <ArrowDownToLine size={15} />
                    Export incident
                  </a>
                </div>
              </div>
              {replayResult && (
                <div
                  className={`replay-banner ${replayResult.matched ? 'matched' : 'mismatch'}`}
                  role="status"
                >
                  {replayResult.matched ? <CheckCircle2 size={19} /> : <TriangleAlert size={19} />}
                  <div>
                    <b>
                      {replayResult.matched
                        ? 'Replay matched every recorded branch.'
                        : 'Replay found a difference.'}
                    </b>
                    <p>
                      {replayResult.method} Numeric tolerance: {replayResult.tolerance}.
                    </p>
                    {replayResult.differences.length > 0 && (
                      <code>{replayResult.differences.join(', ')}</code>
                    )}
                  </div>
                </div>
              )}
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Incident sequence</h2>
                    <p>Recorded actions and outcomes for the applied controller.</p>
                  </div>
                  <Badge>Physical fault remains isolated</Badge>
                </div>
                <div className="timeline">
                  {incident.timeline.map((t) => (
                    <div className="timeline-item" key={t.step}>
                      <span>{t.step}</span>
                      <div>
                        <h3>{t.event}</h3>
                        <p>{t.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2>What the controller received</h2>
                    <p>
                      Simulated demand readings received by the controller. OpenDSS electrical
                      results are shown separately below.
                    </p>
                  </div>
                  <button className="text-button" onClick={() => setShowRaw(!showRaw)}>
                    <Database size={15} />
                    {showRaw ? 'Hide raw records' : 'Show raw records'}
                  </button>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Sensor / demand point</th>
                        <th>Received value</th>
                        <th>Base demand</th>
                        <th>Measurement time</th>
                        <th>Age</th>
                        <th>Quality</th>
                      </tr>
                    </thead>
                    <tbody>
                      {incident.observation.rows.map((row) => (
                        <tr key={row.sensor_id}>
                          <td>
                            <b>{row.load_id.toUpperCase()}</b>
                            <small className="block-muted">{row.sensor_id}</small>
                          </td>
                          <td>
                            {format(row.value, 1)} {row.unit}
                          </td>
                          <td>
                            {incident.manifest.network.loads.find((l) => l.id === row.load_id)?.kw}{' '}
                            kW
                          </td>
                          <td>{new Date(row.measurement_at).toLocaleTimeString()}</td>
                          <td>{row.age_s}s</td>
                          <td>
                            <Badge good={row.quality === 'current'}>{row.quality}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {showRaw && (
                  <pre className="raw-records">{JSON.stringify(incident.observation, null, 2)}</pre>
                )}
              </div>
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Why this action?</h2>
                    <p>Compare predicted loading with the OpenDSS result.</p>
                  </div>
                  <select
                    aria-label="Evidence controller"
                    value={viewPolicy}
                    onChange={(e) => setViewPolicy(e.target.value as Policy)}
                  >
                    {(['nominal', 'guarded', 'oracle'] as Policy[]).map((p) => (
                      <option value={p} key={p}>
                        {policyNames[p]}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="objective-note">{decision.objective}</p>
                <div className="table-scroll">
                  <table className="candidate-table">
                    <thead>
                      <tr>
                        <th>Alternative</th>
                        <th>Predicted loading</th>
                        <th>Worst sampled loading</th>
                        <th>Controller check</th>
                        <th>Simulated loading</th>
                        <th>Simulated outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {decision.candidates.map((c) => {
                        const actual = incident.alternatives.find(
                          (a) => a.action.id === c.action.id,
                        )!.result;
                        return (
                          <tr
                            key={c.action.id}
                            className={
                              c.action.id === decision.selected_action.id ? 'selected-row' : ''
                            }
                          >
                            <td>
                              <b>{c.action.label}</b>
                              {c.action.id === decision.selected_action.id && (
                                <span className="inline-note">Selected</span>
                              )}
                              <small className="block-muted">
                                Switch operations: {c.action.operations.length} ·{' '}
                                {format(actual.restored_kw)} kW restored
                              </small>
                            </td>
                            <td>{format(c.nominal.max_loading_pct, 1)}%</td>
                            <td>
                              {format(c.worst_loading_pct, 1)}%
                              <small className="block-muted">Load cases: {c.sample_count}</small>
                            </td>
                            <td>
                              <Badge good={c.feasible}>{c.feasible ? 'Pass' : 'Reject'}</Badge>
                            </td>
                            <td>{format(actual.max_loading_pct, 1)}%</td>
                            <td>
                              <Badge good={actual.feasible}>
                                {actual.feasible ? 'Within limits' : 'Violation'}
                              </Badge>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="candidate-reasons">
                  {decision.candidates
                    .filter((c) => c.rejected_reasons.length)
                    .map((c) => (
                      <details key={c.action.id}>
                        <summary>{c.action.label}: why it was rejected</summary>
                        {c.rejected_reasons.map((r, i) => (
                          <p key={i}>{r}</p>
                        ))}
                      </details>
                    ))}
                </div>
              </div>
              <div className="two-column">
                <div className="panel">
                  <div className="panel-header">
                    <div>
                      <h2>Switching sequence</h2>
                      <p>
                        {policyNames[viewPolicy]} · {outcome.action.label}
                      </p>
                    </div>
                  </div>
                  <div className="switch-list">
                    {outcome.action.operations.length ? (
                      outcome.action.operations.map((op, i) => (
                        <div key={i}>
                          <span className="step-number">{i + 1}</span>
                          <div>
                            <b>
                              {op.closed ? 'Close' : 'Open'} {op.line}
                            </b>
                            <small>
                              {outcome.steps[i].feasible
                                ? 'Intermediate state passes modeled limits'
                                : 'Intermediate electrical violation'}{' '}
                              · {format(outcome.steps[i].restored_kw)} kW restored
                            </small>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p>No switching. Keep the section isolated.</p>
                    )}
                  </div>
                </div>
                <div className="panel">
                  <div className="panel-header">
                    <h2>Model and uncertainty</h2>
                  </div>
                  <div className="model-details">
                    <p>
                      <b>West reading age:</b> {incident.observation.age_s}s
                    </p>
                    <p>
                      <b>Assumed west-demand range:</b> ±{incident.observation.uncertainty_pct}%
                      when stale
                    </p>
                    <p>
                      <b>Uncertainty check:</b> lower, nominal and upper demand. Values between
                      those samples are not checked.
                    </p>
                    <p>
                      <b>Feeder:</b> {incident.manifest.network.id}
                    </p>
                    <p>
                      <b>Losses in this outcome:</b> {format(outcome.result.losses_kw, 2)} kW
                    </p>
                    <details>
                      <summary>Version and reproducibility details</summary>
                      <pre>{JSON.stringify(incident.manifest, null, 2)}</pre>
                    </details>
                  </div>
                </div>
              </div>
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Simulated electrical results</h2>
                    <p>{policyNames[viewPolicy]} · OpenDSS load powers and voltages</p>
                  </div>
                  <Badge good={outcome.result.converged}>
                    {outcome.result.converged ? 'OpenDSS converged' : 'Solver did not converge'}
                  </Badge>
                </div>
                <ResultTable result={outcome.result} />
                {outcome.result.violations.length > 0 && (
                  <div className="violations-box">
                    {outcome.result.violations.map((v, i) => (
                      <p key={i}>
                        <TriangleAlert size={14} />
                        {v.message}
                      </p>
                    ))}
                  </div>
                )}
              </div>
              <div className="two-column">
                <div className="panel">
                  <div className="panel-header">
                    <h2>Review this incident</h2>
                    <Badge>Saved review history</Badge>
                  </div>
                  <div className="review-form">
                    <label htmlFor="review-note">Review note</label>
                    <textarea
                      id="review-note"
                      value={note}
                      maxLength={2000}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="What did you check? What needs a closer look?"
                    />
                    <div className="button-row">
                      <button
                        className="secondary-button"
                        disabled={!!busy}
                        onClick={() => review('accepted')}
                      >
                        <Check size={15} />
                        Accept analysis
                      </button>
                      <button
                        className="secondary-button"
                        disabled={!!busy}
                        onClick={() => review('questioned')}
                      >
                        <CircleHelp size={15} />
                        Question analysis
                      </button>
                    </div>
                    <p className="method-note">
                      Notes are saved with the incident. Reviews do not change its results or
                      controller behavior.
                    </p>
                    {reviews.map((r) => (
                      <div className="review-entry" key={r.id}>
                        <b>
                          {r.verdict === 'accepted' ? 'Analysis accepted' : 'Analysis questioned'}
                        </b>
                        <span>{stamp(r.created_at)}</span>
                        <p>{r.note || 'No note added.'}</p>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="panel">
                  <div className="panel-header">
                    <h2>Assumptions and limits</h2>
                    <CircleHelp size={17} />
                  </div>
                  <ul className="scope-list">
                    {incident.limits.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ))}

        {tab === 'archive' && (
          <div className="panel archive-panel">
            <div className="panel-header">
              <div>
                <h2>
                  Recorded incidents <span className="nav-count">{archive.length}</span>
                </h2>
                <p>Saved electrical snapshots, controller inputs and switching sequences.</p>
              </div>
              <label className="search-box">
                <Search size={16} />
                <input
                  aria-label="Search incidents"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search incidents…"
                />
              </label>
            </div>
            {archive.length === 0 ? (
              <Empty>
                Your first simulation will appear here. Return to the restoration lab and run a
                scenario.
              </Empty>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Incident</th>
                      <th>Recorded</th>
                      <th>Applied controller</th>
                      <th>Snapshot</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {archive
                      .filter(
                        (a) =>
                          a.title.toLowerCase().includes(search.toLowerCase()) ||
                          a.id.includes(search),
                      )
                      .map((a) => (
                        <tr key={a.id}>
                          <td>
                            <b>{a.title}</b>
                            <small className="block-muted">{a.id.slice(0, 8)}</small>
                          </td>
                          <td>{stamp(a.created_at)}</td>
                          <td>{policyNames[a.policy as Policy]}</td>
                          <td>
                            <span className="saved-label">
                              <Database size={13} />
                              Saved
                            </span>
                          </td>
                          <td>
                            <button
                              className="secondary-button"
                              disabled={!!busy}
                              onClick={() => loadIncident(a.id)}
                              aria-label={`Open ${a.title}`}
                            >
                              Open incident
                              <ArrowRight size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <div hidden={tab !== 'failure'}>
          <FailureSearch
            ready={ready}
            onOpenIncident={loadIncident}
            onSaved={async () => setArchive(await api<Summary[]>('/incidents'))}
          />
        </div>
        <div hidden={tab !== 'verification'}>
          <Verification
            ready={ready}
            incidentId={verificationIncidentId}
            mode={verificationMode}
            onModeChange={setVerificationMode}
          />
        </div>
      </main>
      <footer>
        <span>GridSense · Simulation workspace</span>
        <span>v{appVersion}</span>
      </footer>
      <DetailDialog
        open={aboutOpen}
        title="About this simulation"
        onClose={() => setAboutOpen(false)}
      >
        <p>
          GridSense runs a local distribution-grid simulation with native OpenDSS power-flow
          calculations. It has no connection to a utility grid.
        </p>
        <p>
          Live Grid shows the simulated electrical state. The controller uses received measurements,
          which may be delayed or missing. Equipment inspection shows both separately.
        </p>
        <p>
          Each tick is one simulated second. Slow solves can delay playback. Switching and repair
          times are scenario settings. Repair makes equipment available; returning to normal supply
          needs a checked reconnection.
        </p>
        <p>
          Plans are checked for a radial network, bus voltage and equipment loading within a search
          budget. Guarded control tests a finite set of demand values. These checks cannot guarantee
          the best possible plan or safety on a real grid.
        </p>
      </DetailDialog>
    </div>
  );
}
