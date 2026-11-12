import { useEffect, useState } from 'react';
import { Pause, Play, SkipForward, Plus } from 'lucide-react';
import type { Network } from './types';
import { controlStatusNames, human, number, supplyNames } from './liveTypes';
import { useLiveSession } from './useLiveSession';
import { LiveTopology } from './LiveTopology';
import { AlarmEvidence, CommandTable, EquipmentPanel, PlanEvidence } from './LiveEvidence';
import { ActiveIncidents, NewSession, ScenarioControls } from './LiveScenario';
import { LiveAnalysis } from './LiveAnalysis';
import { DetailDialog } from './DetailDialog';
import './live.css';

function SessionMessages({
  live,
  onRecovered,
}: {
  live: ReturnType<typeof useLiveSession>;
  onRecovered?: () => void;
}) {
  return (
    <>
      {live.error && (
        <div className="error-banner" role="alert">
          <span>{live.error}</span>
          {!live.pending && (
            <button onClick={live.dismissError} aria-label="Dismiss session error">
              ×
            </button>
          )}
        </div>
      )}
      {live.readError && (
        <div className="error-banner" role="alert">
          <span>
            {live.readError} Last displayed time: t={live.session?.at_s ?? 'unknown'} s. Refresh to
            use the controls again.
          </span>
          <button className="secondary-button" onClick={() => void live.refresh().catch(() => {})}>
            Refresh live state
          </button>
        </div>
      )}
      {live.pending && !live.working && (
        <div className="live-message" role="status">
          <span>
            Unconfirmed request: {live.pending.label}. Retry to recover the server's receipt.
          </span>
          <button
            className="secondary-button"
            onClick={async () => {
              if (await live.retry()) onRecovered?.();
            }}
          >
            Retry same request
          </button>
        </div>
      )}
      {live.storageWarning && (
        <p className="live-warning">
          Sessions are still saved on the server. This browser cannot remember your selection or an
          unresolved request after a reload.
        </p>
      )}
      {live.working && (
        <div className="busy-banner" role="status">
          {live.working}… Waiting for server confirmation.
        </div>
      )}
    </>
  );
}

type LivePanel = 'equipment' | 'scenario' | 'new-session' | 'incident' | null;
type EvidenceView = 'alarms' | 'commands' | 'decision';

export function LiveGrid({
  network,
  view,
  onAnalysis,
}: {
  network: Network;
  view: 'live' | 'analysis' | 'hidden';
  onAnalysis: () => void;
}) {
  const live = useLiveSession(view !== 'hidden');
  const [selected, setSelected] = useState('load:a1');
  const [panel, setPanel] = useState<LivePanel>(null);
  const [evidence, setEvidence] = useState<EvidenceView>('alarms');
  const [diagramView, setDiagramView] = useState('');
  const [motion, setMotion] = useState(
    () => !matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  const session = live.session;
  const blocked = !!live.working || !!live.pending || !!live.readError;
  const result = session?.simulation.electrical;
  const activeAlarms = session?.observation.alarms.filter((a) => a.cleared_at_s === null) ?? [];
  const stale =
    session?.observation.signals.filter((r) => r.quality === 'valid' && !r.fresh).length ?? 0;
  const invalid = session?.observation.signals.filter((r) => r.quality === 'invalid').length ?? 0;
  const finished = !!session && session.at_s >= session.horizon_s;
  useEffect(() => {
    setPanel(null);
  }, [live.id, view]);
  useEffect(() => {
    setDiagramView('');
  }, [live.id]);
  function inspect(asset = selected) {
    setSelected(asset);
    setPanel('equipment');
  }
  function inspectEvidence(next: EvidenceView) {
    setEvidence(next);
    setPanel('incident');
  }
  const close = () => setPanel(null);
  return (
    <div hidden={view === 'hidden'} className="live-workspace">
      {!panel && <SessionMessages live={live} />}
      <div hidden={view !== 'live'}>
        <div className="live-session-picker">
          <label className="live-field">
            Saved live session
            <select
              aria-label="Saved live session"
              value={live.id ?? ''}
              disabled={!!live.working || !!live.pending}
              onChange={(e) => live.choose(e.target.value)}
            >
              <option value="" disabled>
                Choose a saved session
              </option>
              {live.id && !live.history.some((row) => row.id === live.id) && (
                <option value={live.id}>{live.id.slice(0, 8)}</option>
              )}
              {live.history.map((row) => (
                <option key={row.id} value={row.id}>
                  {new Date(row.created_at).toLocaleString()} · {row.id.slice(0, 8)} · {row.mode}
                </option>
              ))}
            </select>
          </label>
          {session && (
            <div className="live-session-actions">
              <strong>{session.title}</strong>
              <button
                className="secondary-button"
                disabled={blocked || session.mode === 'running'}
                onClick={() => setPanel('new-session')}
              >
                <Plus size={15} />
                New session
              </button>
            </div>
          )}
        </div>
        {!session && (
          <section className="panel live-panel-body live-setup">
            <h2>Create a live session</h2>
            <NewSession disabled={!!live.working || !!live.pending} onCreate={live.create} />
          </section>
        )}
        {session && (
          <>
            <div className="live-clockbar">
              <div>
                <span className="live-clock" data-testid="live-clock">
                  t={session.at_s} s
                </span>
                <small>
                  {finished
                    ? 'Session finished'
                    : session.mode === 'running'
                      ? 'Playing'
                      : 'Paused'}{' '}
                  · ends at {session.horizon_s} s
                </small>
              </div>
              <div className="live-playback">
                <button
                  className="secondary-button"
                  disabled={blocked || session.mode !== 'paused' || finished}
                  onClick={() => void live.mutate('step')}
                >
                  <SkipForward size={15} />
                  Step one second
                </button>
                {session.mode === 'running' ? (
                  <button
                    className="primary-button"
                    disabled={blocked}
                    onClick={() => void live.mutate('pause')}
                  >
                    <Pause size={15} />
                    Pause session
                  </button>
                ) : (
                  <button
                    className="primary-button"
                    disabled={blocked || finished || !!session.simulation.solver_error}
                    onClick={() => void live.mutate('play')}
                  >
                    <Play size={15} />
                    Play session
                  </button>
                )}
                <label className="live-field">
                  Playback speed
                  <select
                    aria-label="Playback speed"
                    value={session.rate}
                    disabled={blocked}
                    onChange={(e) => void live.mutate('rate', { rate: Number(e.target.value) })}
                  >
                    <option value={1}>1×</option>
                    <option value={5}>5×</option>
                    <option value={10}>10×</option>
                  </select>
                </label>
                <button
                  className="secondary-button"
                  disabled={blocked || session.mode !== 'paused' || finished}
                  onClick={() => setPanel('scenario')}
                >
                  <Plus size={15} />
                  Add disturbance
                </button>
              </div>
            </div>
            <div className="live-session-feedback">
              <p className="live-note live-playback-note">
                One tick is one simulated second. Changing views does not pause playback.
              </p>
              {live.notice && (
                <p role="status" className="live-notice">
                  {live.notice}
                </p>
              )}
            </div>
            {session.pause_reason && (
              <p className={session.simulation.solver_error ? 'error-banner' : 'live-message'}>
                {session.pause_reason}
              </p>
            )}
            <div className="live-metrics" aria-label="Current simulated electrical results">
              <div>
                <small>Served demand</small>
                <strong>
                  {number(result?.served_kw, 0)} <em>kW</em>
                </strong>
                <span>of {number(result?.requested_kw, 0)} kW requested</span>
              </div>
              <div className={(result?.unserved_kw ?? 0) > 0.1 ? 'metric-warn' : ''}>
                <small>Unserved demand</small>
                <strong data-testid="live-unserved">
                  {number(result?.unserved_kw, 0)} <em>kW</em>
                </strong>
                <span>{number(result?.critical_served_kw, 0)} kW to critical loads</span>
              </div>
              <div className={(result?.max_loading_pct ?? 0) > 100 ? 'metric-warn' : ''}>
                <small>Highest equipment loading</small>
                <strong>
                  {number(result?.max_loading_pct)} <em>%</em>
                </strong>
                <span>Model limit: 100% of rated current</span>
              </div>
              <div>
                <small>Lowest energized voltage</small>
                <strong>
                  {number(result?.min_voltage_pu, 3)} <em>pu</em>
                </strong>
                <span>Model voltage limits: 0.95–1.05 pu</span>
              </div>
            </div>
          </>
        )}
        <div className="live-operation-layout">
          <section className="panel live-topology-panel">
            <div className="panel-header">
              <h2>Grid topology</h2>
              <div className="live-network-tools">
                <label className="live-field live-diagram-view">
                  View
                  <select
                    aria-label="Diagram view"
                    value={diagramView}
                    onChange={(event) => setDiagramView(event.target.value)}
                  >
                    <option value="">Whole grid</option>
                    {network.buses.map((bus) => (
                      <option key={bus.id} value={bus.id}>
                        {bus.id === 'sub'
                          ? 'Source and substation'
                          : `${bus.id.toUpperCase()} · ${network.loads.find((load) => load.id === bus.id)?.label ?? bus.label}`}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="secondary-button" onClick={() => inspect()}>
                  Inspect equipment
                </button>
              </div>
            </div>
            <LiveTopology
              network={network}
              state={session?.simulation.physical}
              result={result}
              selected={selected}
              onSelect={inspect}
              focus={diagramView}
              onOverview={() => setDiagramView('')}
              animate={motion && session?.mode === 'running' && !live.readError}
            />
            <div className="live-topology-caption">
              <div className="live-diagram-caption">
                <p>
                  Select equipment for its readings. Dashed lines are open. Line crossings are not
                  connections.
                </p>
                <span className="live-tag">
                  {session ? `OpenDSS · t=${session.at_s} s` : 'Not yet solved'}
                </span>
              </div>
              <div className="live-topology-options">
                <label className="live-checkbox">
                  <input
                    type="checkbox"
                    checked={motion}
                    onChange={(e) => setMotion(e.target.checked)}
                  />
                  Animate energized lines
                </label>
                <details>
                  <summary>Diagram guide</summary>
                  <p>
                    Each 11 kV bus feeds a transformer and a load group. Outage labels mark
                    unavailable equipment. Choose a group in View for larger readings, or zoom. Show
                    whole grid returns to the overview.
                  </p>
                  <p>
                    Moving lines show energized connections carrying load. Their speed does not
                    represent power or travel time. Reduced-motion settings turn animation off.
                  </p>
                </details>
              </div>
            </div>
          </section>
          <aside className="panel live-restoration-status">
            <div className="panel-header">
              <h2>Restoration status</h2>
              <span className="live-tag">Received evidence</span>
            </div>
            {session ? (
              <div className="live-panel-body">
                <div
                  className={`live-supply ${session.control.supply_status.includes('violated') || session.control.supply_status === 'supply_interrupted' ? 'live-warning' : ''}`}
                  data-testid="live-supply"
                >
                  <h3>
                    {supplyNames[session.control.supply_status] ??
                      human(session.control.supply_status)}
                  </h3>
                  <p
                    className={/unknown|failed/.test(session.control.status) ? 'live-warning' : ''}
                  >
                    {controlStatusNames[session.control.status] ?? human(session.control.status)}
                  </p>
                </div>
                {(session.control.supply_status !== 'normal_supply_verified' ||
                  activeAlarms.length > 0 ||
                  /unknown|failed/.test(session.control.status)) && <p>{session.control.reason}</p>}
                <dl className="live-readings">
                  <dt>Policy</dt>
                  <dd>{session.control_settings.policy}</dd>
                  <dt>Active alarms</dt>
                  <dd>{activeAlarms.length}</dd>
                </dl>
                {(stale > 0 || invalid > 0) && (
                  <p className="live-warning" role="status">
                    Received measurements: {stale} stale · {invalid} invalid.
                  </p>
                )}
                {session.control.recovery_requested && (
                  <p className="live-warning">
                    Return to normal requested. The controller still needs electrical checks and
                    switch confirmation.
                  </p>
                )}
                <ActiveIncidents
                  session={session}
                  disabled={blocked}
                  onSchedule={(events) => live.mutate('schedule', { events })}
                />
                {result && !result.feasible && (
                  <div className="live-constraint">
                    <h3>Simulated electrical violations</h3>
                    <ul>
                      {result.violations.map((v, i) => (
                        <li key={i}>{v.message}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {!result && (
                  <p className="live-warning">
                    Electrical results are unavailable. Supply and loading cannot be confirmed.
                  </p>
                )}
                <div className="live-evidence-links" aria-label="Live incident details">
                  <button className="secondary-button" onClick={() => inspectEvidence('alarms')}>
                    View alarms
                  </button>
                  <button className="secondary-button" onClick={() => inspectEvidence('commands')}>
                    Switch commands
                  </button>
                  <button className="secondary-button" onClick={() => inspectEvidence('decision')}>
                    Restoration decision
                  </button>
                </div>
                <button className="text-button" onClick={onAnalysis}>
                  View incident timeline
                </button>
              </div>
            ) : (
              <p className="live-panel-body live-note">
                Create a session to solve the feeder and receive measurements.
              </p>
            )}
          </aside>
        </div>
      </div>
      <DetailDialog
        open={panel === 'equipment'}
        title="Equipment inspection"
        drawer
        onClose={close}
      >
        {panel === 'equipment' && <SessionMessages live={live} onRecovered={close} />}
        <EquipmentPanel
          network={network}
          selected={selected}
          onSelect={setSelected}
          physical={session?.simulation.physical}
          result={result}
          observation={session?.observation}
          at={session?.at_s}
        />
      </DetailDialog>
      {session && (
        <>
          <DetailDialog open={panel === 'new-session'} title="New session" onClose={close}>
            {panel === 'new-session' && <SessionMessages live={live} onRecovered={close} />}
            <NewSession
              disabled={blocked || session.mode === 'running'}
              onCreate={async (config) => {
                const accepted = await live.create(config);
                if (accepted) close();
                return accepted;
              }}
            />
          </DetailDialog>
          <DetailDialog open={panel === 'scenario'} title="Add disturbance" onClose={close}>
            {panel === 'scenario' && <SessionMessages live={live} onRecovered={close} />}
            <ScenarioControls
              session={session}
              network={network}
              disabled={blocked}
              onSchedule={async (events) => {
                const accepted = await live.mutate('schedule', { events });
                if (accepted) close();
                return accepted;
              }}
            />
          </DetailDialog>
          <DetailDialog open={panel === 'incident'} title="Incident details" onClose={close}>
            {panel === 'incident' && <SessionMessages live={live} onRecovered={close} />}
            <nav className="evidence-nav" aria-label="Incident evidence">
              {(['alarms', 'commands', 'decision'] as const).map((next) => (
                <button
                  key={next}
                  className={evidence === next ? 'active' : ''}
                  aria-pressed={evidence === next}
                  onClick={() => setEvidence(next)}
                >
                  {{ alarms: 'Alarms', commands: 'Commands', decision: 'Decision' }[next]}
                </button>
              ))}
            </nav>
            {evidence === 'alarms' && <AlarmEvidence alarms={session.observation.alarms} />}
            {evidence === 'commands' && <CommandTable control={session.control} />}
            {evidence === 'decision' && (
              <PlanEvidence
                plan={session.control.last_plan}
                at={session.control.last_planned_at_s}
              />
            )}
            <details className="live-session-record">
              <summary>Session and controller details</summary>
              <dl className="live-readings">
                <dt>Session ID</dt>
                <dd>{session.id}</dd>
                <dt>Revision</dt>
                <dd>{session.revision}</dd>
                <dt>Controller state</dt>
                <dd>{session.control.status}</dd>
                <dt>OpenDSS planning solves</dt>
                <dd>{session.control.native_evaluations}</dd>
              </dl>
              <p>{session.control.reason}</p>
            </details>
          </DetailDialog>
        </>
      )}
      <div hidden={view !== 'analysis'}>
        <LiveAnalysis
          key={live.id}
          id={live.id}
          active={view === 'analysis'}
          paused={session?.mode === 'paused' && !blocked}
        />
      </div>
    </div>
  );
}
