import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import type { LiveExport } from './liveTypes';
import { eventText, human, number, supplyNames } from './liveTypes';
import { AlarmEvidence, CommandTable, PlanEvidence } from './LiveEvidence';

function downloadRecord(record: LiveExport) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(record, null, 2) + '\n'], { type: 'application/json' }),
  );
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `gridsense-session-${record.id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function LiveAnalysis({
  id,
  active,
  paused,
}: {
  id: string | null;
  active: boolean;
  paused: boolean;
}) {
  const [record, setRecord] = useState<LiveExport | null>(null);
  const [index, setIndex] = useState(0);
  const [evidence, setEvidence] = useState<'decision' | 'commands' | 'alarms' | 'raw'>('decision');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<{
    matched: boolean;
    ticks: number;
    native_snapshots: number;
    differences: string[];
  } | null>(null);
  const capture = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      const value = await api<LiveExport>(`/sessions/${id}/export`);
      setRecord(value);
      setIndex(value.frames.length - 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [id]);
  useEffect(() => {
    if (active) void capture();
  }, [active, capture]);
  async function checkReplay() {
    if (!id) return;
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      setReplay(await api(`/sessions/${id}/replay`, {}));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!id)
    return (
      <div className="panel live-panel-body">
        <h2>Select a live session</h2>
        <p>
          Open or create a session in Live Grid to see its timeline. Restoration lab compares
          separate snapshots.
        </p>
      </div>
    );
  const frame = record?.frames[index];
  const totals = record?.final.checkpoint.metrics;
  return (
    <div className="live-analysis" data-testid="live-analysis">
      <div className="live-analysis-toolbar">
        <span>
          {record
            ? `Captured through t=${record.final.checkpoint.now_s} s · revision ${record.final.revision}`
            : 'Loading recorded session…'}
          <small>This record stays fixed. Refresh to include newer events.</small>
        </span>
        <button className="secondary-button" onClick={() => void capture()} disabled={busy}>
          Refresh timeline
        </button>
        <button
          className="secondary-button"
          onClick={() => record && downloadRecord(record)}
          disabled={!record || busy}
        >
          Export captured session
        </button>
        <button
          className="secondary-button"
          onClick={() => void checkReplay()}
          disabled={busy || !paused}
        >
          Check session replay
        </button>
      </div>
      {!paused && (
        <p className="live-note">
          Replay needs a paused session with no unresolved requests. Viewing this record does not
          pause playback.
        </p>
      )}
      {busy && (
        <p role="status" className="busy-banner">
          Loading history or checking replay…
        </p>
      )}
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {replay && (
        <div role="status" className={replay.matched ? 'live-message' : 'error-banner'}>
          {replay.matched ? 'Strict replay matched' : 'Strict replay differs'} · server session
          through t={replay.ticks} s · {replay.native_snapshots} OpenDSS snapshots. This check uses
          the server record captured when replay was requested.
          {replay.differences.length > 0 && (
            <pre>{JSON.stringify(replay.differences, null, 2)}</pre>
          )}
        </div>
      )}
      {record && totals && (
        <>
          <div className="live-metrics">
            <div>
              <small>Unserved energy</small>
              <strong>
                {number(totals.unserved_kwh, 3)} <em>kWh</em>
              </strong>
            </div>
            <div>
              <small>Critical energy within grid limits</small>
              <strong>
                {number(totals.feasible_critical_served_kwh, 3)} <em>kWh</em>
              </strong>
            </div>
            <div>
              <small>Ticks with electrical violations</small>
              <strong>{totals.violation_ticks}</strong>
            </div>
            <div>
              <small>Physical switch changes</small>
              <strong>{totals.position_changes}</strong>
            </div>
          </div>
          <p className="live-note">
            Totals cover {totals.known_seconds} seconds with valid results. The{' '}
            {totals.unknown_seconds} seconds with unknown results are excluded. The final snapshot
            adds no energy. Critical energy counts only intervals within all model limits.
          </p>
          <section className="panel">
            <div className="panel-header">
              <h2>Incident timeline</h2>
              <span>{record.frames.length} OpenDSS snapshots</span>
            </div>
            <div className="table-scroll live-timeline-scroll">
              <table aria-label="Live incident timeline">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Physical events / switch response</th>
                    <th>Received evidence / decisions</th>
                    <th>Unserved demand</th>
                  </tr>
                </thead>
                <tbody>
                  {record.frames.map((row, i) => (
                    <tr key={row.at_s} className={index === i ? 'chosen-alternative' : ''}>
                      <td>
                        <button
                          className="secondary-button"
                          aria-label={`Inspect tick ${row.at_s}`}
                          aria-pressed={index === i}
                          onClick={() => setIndex(i)}
                        >
                          {row.at_s} s
                        </button>
                      </td>
                      <td>
                        {row.physical_events.map((q) => (
                          <small key={q.sequence}>{eventText(q.event)}</small>
                        ))}
                        {row.actuation_events.map((a, j) => (
                          <small key={j}>
                            {a.command_id}: {a.changed ? 'position changed' : 'no position change'}{' '}
                            · {a.equipment}
                            {a.reason && ` · ${a.reason}`}
                          </small>
                        ))}
                        {!row.physical_events.length &&
                          !row.actuation_events.length &&
                          'No physical change'}
                      </td>
                      <td>
                        {supplyNames[row.control.supply_status] ?? human(row.control.supply_status)}
                        {row.alarm_changes.map((a, j) => (
                          <small key={j}>
                            {a.kind} · {human(a.alarm.rule)} · {a.alarm.equipment}
                          </small>
                        ))}
                        {row.control_events.map((c, j) => (
                          <small key={j}>
                            {human(String(c.kind))}
                            {c.command_id ? ` · ${String(c.command_id)}` : ''}
                            {c.status ? ` · ${human(String(c.status))}` : ''}
                          </small>
                        ))}
                        {row.confirmation_events.map((c, j) => (
                          <small key={`c-${j}`}>
                            {human(String(c.kind))}
                            {c.status ? ` · ${human(String(c.status))}` : ''}
                            {c.accepted === false ? ' · rejected' : ''}
                          </small>
                        ))}
                      </td>
                      <td>
                        {number(row.electrical?.unserved_kw)} kW
                        {row.solver_error && (
                          <small className="live-warning">Unknown · {row.solver_error}</small>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {frame && (
            <>
              <div className="live-frame-heading">
                <h2>Recorded tick {frame.at_s} s</h2>
                <span className="live-tag">Historical evidence</span>
              </div>
              <nav className="evidence-nav" aria-label="Recorded tick evidence">
                {(['decision', 'commands', 'alarms', 'raw'] as const).map((next) => (
                  <button
                    key={next}
                    className={evidence === next ? 'active' : ''}
                    aria-pressed={evidence === next}
                    onClick={() => setEvidence(next)}
                  >
                    {
                      {
                        decision: 'Decision',
                        commands: 'Commands',
                        alarms: 'Alarms',
                        raw: 'Raw record',
                      }[next]
                    }
                  </button>
                ))}
              </nav>
              {evidence === 'decision' && (
                <PlanEvidence plan={frame.control.last_plan} at={frame.control.last_planned_at_s} />
              )}
              {evidence === 'commands' && <CommandTable control={frame.control} />}
              {evidence === 'alarms' && <AlarmEvidence alarms={frame.observation.alarms} />}
              {evidence === 'raw' && (
                <section className="panel live-panel-body" aria-label="Raw recorded tick">
                  <h3>Physical state, measurements, feedback and decisions</h3>
                  <pre>{JSON.stringify(frame, null, 2)}</pre>
                </section>
              )}
            </>
          )}
          <details className="panel live-panel-body">
            <summary>Configuration, actions and replay metadata</summary>
            <pre>
              {JSON.stringify(
                {
                  definition: record.definition,
                  manifest: record.manifest,
                  actions: record.actions,
                  content_sha256: record.content_sha256,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </>
      )}
    </div>
  );
}
