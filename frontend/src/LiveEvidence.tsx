import type { ElectricalResult, Network, State } from './types';
import type { Alarm, LiveControl, LiveObservation, LivePlan, Signal } from './liveTypes';
import { human, number, operationsText, valueText } from './liveTypes';

export function assetOptions(network: Network) {
  return [
    { id: 'source:source', label: 'Source · 33 kV' },
    { id: 'transformer:main', label: 'Main transformer · 33 / 11 kV' },
    ...network.lines.map((line) => ({
      id: `line:${line.id}`,
      label: `${line.id} · ${line.from_bus} → ${line.to_bus}`,
    })),
    ...network.buses.map((bus) => ({ id: `bus:${bus.id}`, label: `${bus.id} · 11 kV bus` })),
    ...network.loads.flatMap((load) => [
      { id: `transformer:tx_${load.id}`, label: `tx_${load.id} · ${load.label}` },
      { id: `load:${load.id}`, label: `${load.label} · aggregate load` },
      { id: `bus:${load.id}_lv`, label: `${load.id} · 0.415 kV bus` },
    ]),
  ];
}
export function SignalTable({
  rows,
  label = 'Received measurements',
}: {
  rows: Signal[];
  label?: string;
}) {
  return (
    <div className="table-scroll live-signals">
      <table aria-label={label}>
        <thead>
          <tr>
            <th>Sensor / sequence</th>
            <th>Value</th>
            <th>Measured / received</th>
            <th>Quality / age</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.sensor_id}-${row.sequence}`}>
              <td>
                <code>{row.sensor_id}</code>
                <small>#{row.sequence}</small>
              </td>
              <td>
                {valueText(row.value)} <small>{row.unit}</small>
              </td>
              <td>
                {row.measured_at_s} s / {row.received_at_s == null ? '—' : `${row.received_at_s} s`}
              </td>
              <td>
                {row.quality !== 'valid'
                  ? human(row.quality)
                  : row.fresh === false
                    ? 'Stale'
                    : row.fresh
                      ? 'Fresh'
                      : 'Valid (recorded)'}
                {row.age_s != null && <small>{row.age_s} s old</small>}
              </td>
              <td>{row.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && (
        <p className="live-note">No measurements have arrived for this equipment.</p>
      )}
    </div>
  );
}
export function EquipmentPanel({
  network,
  selected,
  onSelect,
  physical,
  result,
  observation,
  at,
}: {
  network: Network;
  selected: string;
  onSelect: (id: string) => void;
  physical?: State;
  result?: ElectricalResult | null;
  observation?: LiveObservation;
  at?: number;
}) {
  const [kind, name] = selected.split(':');
  const outages =
    physical?.equipment_outages.filter((o) => o.kind === kind && o.equipment === name) ?? [];
  const position = !physical
    ? null
    : kind === 'line'
      ? physical.closed_lines.includes(name)
      : kind === 'transformer'
        ? !physical.open_transformers.includes(name)
        : kind === 'source'
          ? physical.source_connected
          : null;
  const load = result?.load_measurements.find((row) => row.load_id === name);
  const estimate = observation?.demand_estimates.find((row) => row.load_id === name);
  const rows =
    observation?.signals.filter(
      (row) =>
        row.equipment === selected || (kind === 'load' && row.equipment === `bus:${name}_lv`),
    ) ?? [];
  const readings: [string, string][] =
    kind === 'line'
      ? [['Line loading', `${number(result?.line_loading_pct[name])}%`]]
      : kind === 'transformer'
        ? [['Winding loading', `${number(result?.transformer_loading_pct[name])}%`]]
        : kind === 'source'
          ? [
              [
                'OpenDSS source power',
                `${number(result?.source_kw)} kW / ${number(result?.source_kvar)} kvar`,
              ],
            ]
          : kind === 'bus'
            ? [['Minimum bus voltage', `${number(result?.voltages_pu[name], 4)} pu`]]
            : [
                ['Requested demand', `${number(load?.requested_kw)} kW`],
                ['Served demand', `${number(load?.served_kw)} kW`],
                [
                  'OpenDSS delivered power',
                  `${number(load?.native_kw)} kW / ${number(load?.native_kvar)} kvar`,
                ],
                ['LV voltage', `${number(load?.voltage_pu, 4)} pu`],
                [
                  'Supply',
                  !load
                    ? 'Unknown'
                    : !load.energized
                      ? 'Interrupted'
                      : load.voltage_compliant
                        ? 'Energized · voltage within limits'
                        : 'Energized · voltage outside limits',
                ],
              ];
  return (
    <section className="panel live-equipment" aria-label="Equipment inspection">
      <div className="panel-header">
        <h2>Equipment inspection</h2>
        <span className="live-tag">t={at ?? '—'} s</span>
      </div>
      <div className="live-panel-body">
        <label className="live-field">
          Inspect equipment
          <select
            aria-label="Inspect equipment"
            value={selected}
            onChange={(e) => onSelect(e.target.value)}
          >
            {assetOptions(network).map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <h3>Simulated physical state</h3>
        <dl className="live-readings">
          {position !== null && (
            <>
              <dt>Availability</dt>
              <dd>{outages.length ? 'Unavailable' : 'Available'}</dd>
              <dt>Physical position</dt>
              <dd>{position ? 'Closed / connected' : 'Open / disconnected'}</dd>
            </>
          )}
          {outages.length > 0 && (
            <>
              <dt>Active incidents</dt>
              <dd>{outages.map((o) => o.incident_id).join(', ')}</dd>
            </>
          )}
          {readings.map(([label, reading]) => (
            <div className="reading-pair" key={label}>
              <dt>{label}</dt>
              <dd>{result ? reading : 'Unknown — no valid power-flow result'}</dd>
            </div>
          ))}
        </dl>
        {kind === 'load' && (
          <p className="live-note">
            Served demand counts delivered active power up to the requested load. The OpenDSS
            reading retains the full terminal power.
          </p>
        )}
        {estimate && (
          <p className="live-note">
            Controller estimate: {number(estimate.kw)} kW · {estimate.status} ·{' '}
            {estimate.age_s ?? '—'} s old. Planning range: {number(estimate.lower_kw)}–
            {number(estimate.upper_kw)} kW. This estimate is separate from requested demand.
          </p>
        )}
        <h3>What the controller received</h3>
        <SignalTable rows={rows} />
        <details>
          <summary>Raw measurement records</summary>
          <pre>{JSON.stringify(rows, null, 2)}</pre>
        </details>
      </div>
    </section>
  );
}
export function AlarmEvidence({ alarms }: { alarms: Alarm[] }) {
  const ordered = [...alarms].sort(
    (a, b) =>
      Number(a.cleared_at_s !== null) - Number(b.cleared_at_s !== null) ||
      b.raised_at_s - a.raised_at_s,
  );
  return (
    <section className="panel live-alarm-panel">
      <div className="panel-header">
        <h2>Received alarms</h2>
        <span>{alarms.filter((a) => a.cleared_at_s === null).length} active</span>
      </div>
      <div className="live-panel-body">
        {!alarms.length && (
          <p className="live-note">
            No alarms recorded. Stale or missing readings do not confirm healthy operation.
          </p>
        )}
        {ordered.map((alarm) => (
          <details
            className={`live-alarm ${alarm.cleared_at_s === null ? 'alarm-active' : ''}`}
            key={alarm.id}
          >
            <summary>
              <strong>
                {human(alarm.rule)} · {alarm.equipment}
              </strong>
              <span>
                {alarm.cleared_at_s === null
                  ? `Active since ${alarm.raised_at_s} s`
                  : `Cleared at ${alarm.cleared_at_s} s`}
              </span>
            </summary>
            <p>{alarm.explanation}</p>
            <p>
              Rule: {alarm.rule} · alarm limit {valueText(alarm.limit)} {alarm.unit} · reset{' '}
              {valueText(alarm.reset_value)} {alarm.unit}.
            </p>
            <h3>Triggering measurements</h3>
            <SignalTable rows={alarm.trigger_rows} label={`Trigger rows for ${alarm.id}`} />
            {!!alarm.clear_rows.length && (
              <>
                <h3>Clearing measurements</h3>
                <SignalTable rows={alarm.clear_rows} label={`Clear rows for ${alarm.id}`} />
              </>
            )}
            <details>
              <summary>Raw alert record</summary>
              <pre>{JSON.stringify(alarm, null, 2)}</pre>
            </details>
          </details>
        ))}
      </div>
    </section>
  );
}
export function CommandTable({ control }: { control: LiveControl }) {
  return (
    <section className="panel live-command-panel">
      <div className="panel-header">
        <h2>Switch commands</h2>
        <span>{Object.keys(control.commands).length} issued</span>
      </div>
      <div className="live-panel-body">
        <p className="live-note">
          A command requests a position change. Position feedback confirms the switch; received
          electrical measurements confirm supply.
        </p>
        <div className="table-scroll">
          <table aria-label="Switch commands">
            <thead>
              <tr>
                <th>Command / plan</th>
                <th>Requested operation</th>
                <th>Issued / deadline</th>
                <th>Confirmation</th>
                <th>Measured / received</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(control.commands).map((command) => (
                <tr key={command.id}>
                  <td>
                    {command.id}
                    <small>{command.plan_id}</small>
                  </td>
                  <td>{operationsText([command.operation])}</td>
                  <td>
                    {command.issued_at_s} s / {command.deadline_s} s
                  </td>
                  <td
                    className={
                      ['pending', 'unknown', 'failed', 'failed_late'].includes(command.status)
                        ? 'live-warning'
                        : ''
                    }
                  >
                    {human(command.status)}
                    {command.confirmed_position !== null && (
                      <small>Reported {command.confirmed_position ? 'closed' : 'open'}</small>
                    )}
                  </td>
                  <td>
                    {command.measured_at_s ?? '—'} / {command.received_at_s ?? '—'} s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!Object.keys(control.commands).length && (
          <p className="live-note">No switching command has been issued.</p>
        )}
        {!!control.remaining.length && (
          <p>Next operations, checked again before issue: {operationsText(control.remaining)}</p>
        )}
      </div>
    </section>
  );
}
export function PlanEvidence({ plan, at }: { plan: LivePlan | null; at: number }) {
  if (!plan)
    return (
      <div className="panel live-panel-body">
        <h2>Restoration decision</h2>
        <p className="live-note">
          No plan recorded yet. The controller plans when received evidence calls for a change.
        </p>
      </div>
    );
  const key = (operations: LivePlan['candidates'][number]['operations']) =>
    JSON.stringify(operations);
  const measuredOverloads = plan.measured_overloads ?? [];
  const unsafeExposures = plan.unsafe_exposures ?? [];
  return (
    <section className="panel live-plan" data-testid="live-plan">
      <div className="panel-header">
        <h2>Restoration decision · t={at} s</h2>
        <span className="live-tag">Prediction · {plan.policy}</span>
      </div>
      <div className="live-panel-body">
        <h3>
          {plan.feasible_choice
            ? operationsText(plan.selected?.operations ?? [])
            : 'No checked plan meets the goal'}
        </h3>
        <p>{plan.reason}</p>
        <p className="live-note">
          {plan.objective} Aim:{' '}
          {plan.goal === 'normal'
            ? 'return to normal with no predicted loss of service at the end of the sequence'
            : 'restore service'}
          . Search used {plan.native_evaluations}/{plan.budget} OpenDSS solves, with at most{' '}
          {plan.max_operations} switching operations per plan. Better plans beyond these limits may
          be missed.
        </p>
        {plan.timing ? (
          <p className="live-note" data-testid="planning-timing">
            Timing assumption: {plan.timing.actuation_delay_s} s to switch and{' '}
            {plan.timing.confirmation_delay_s} s for confirmation. Energy is compared over the next{' '}
            {plan.energy_horizon_s} s. Guarded bounds grow while readings are held. Scenario
            response settings are separate; each next command is checked again against received
            evidence.
          </p>
        ) : (
          <p className="live-note">
            Switching times and predicted energy were not recorded for this plan.
          </p>
        )}
        {plan.selected?.energy?.known && (
          <p data-testid="planning-energy">
            Predicted unserved energy: {number(plan.selected.energy.unserved_kwh, 4)} kWh, including{' '}
            {number(plan.selected.energy.critical_unserved_kwh, 4)} kWh of critical demand. This
            uses held demand estimates; actual outcomes are recorded in the session timeline.
          </p>
        )}
        {measuredOverloads.length > 0 && (
          <p className="live-warning">
            Received overload:{' '}
            {measuredOverloads
              .map(
                (item) =>
                  `${item.equipment} at ${number(Number(item.row.value), 1)}% (measured at ${item.row.measured_at_s} s; limit ${item.limit_pct}%)`,
              )
              .join('; ')}
            . The first switch must reduce the affected load.
          </p>
        )}
        {plan.budget_exhausted && (
          <p className="live-warning">
            The solve budget was used up. Some alternatives may be unchecked.
          </p>
        )}
        <details>
          <summary>Compare {plan.candidates.length} evaluated alternatives</summary>
          {unsafeExposures.length > 0 && (
            <p className="live-note">
              {unsafeExposures.length} previously overloaded load combinations remain blocked while
              their received demand estimates are unchanged. Unrelated switching cannot clear this
              check.
            </p>
          )}
          {plan.timing && (
            <p>
              Predictions use received estimates and declared switching times. Switching and
              confirmation waits are checked. Distribution-transformer disconnects can shed load.
              Actual restoration can differ; guarded checks may miss violations between the sampled
              demand values.
            </p>
          )}
          <div className="table-scroll live-candidate-scroll">
            <table aria-label="Live restoration alternatives">
              <thead>
                <tr>
                  <th>Ordered operations</th>
                  <th>Predicted critical / total</th>
                  <th>Predicted unserved energy</th>
                  <th>Assumed completion</th>
                  <th>Worst tested loading</th>
                  <th>Samples</th>
                  <th>Constraints / selection</th>
                </tr>
              </thead>
              <tbody>
                {plan.candidates.map((candidate, i) => (
                  <tr
                    key={i}
                    className={
                      plan.selected && key(candidate.operations) === key(plan.selected.operations)
                        ? 'chosen-alternative'
                        : ''
                    }
                  >
                    <td>{operationsText(candidate.operations)}</td>
                    <td>
                      {number(candidate.prediction.nominal.critical_kw)} /{' '}
                      {number(candidate.prediction.nominal.served_kw)} kW
                    </td>
                    <td>
                      {candidate.energy
                        ? `${number(candidate.energy.unserved_kwh, 4)} kWh`
                        : 'Not recorded'}
                    </td>
                    <td>
                      {candidate.completion_offset_s == null
                        ? 'Not recorded'
                        : `${candidate.completion_offset_s} s`}
                    </td>
                    <td>{number(candidate.prediction.worst_loading_pct)}%</td>
                    <td>
                      {candidate.prediction.samples_checked}/{candidate.prediction.samples_required}
                    </td>
                    <td>
                      {candidate.known_unsafe
                        ? 'Previously observed unsafe'
                        : candidate.prediction.feasible
                          ? 'Passes sampled checks'
                          : 'Constraint violation'}
                      {candidate.rejection_reason && <small>{candidate.rejection_reason}</small>}
                      {plan.selected &&
                        key(candidate.operations) === key(plan.selected.operations) && (
                          <small>{plan.feasible_choice ? 'Selected' : 'Hold — goal not met'}</small>
                        )}
                      {candidate.prediction.violations.map((v, j) => (
                        <small key={j}>{v.message}</small>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!!plan.structural_rejections.length && (
            <details>
              <summary>Blocked switching operations</summary>
              <ul>
                {plan.structural_rejections.map((r, i) => (
                  <li key={i}>
                    {operationsText([r.operation])}: {r.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </details>
        <details>
          <summary>Planning inputs and raw decision</summary>
          <pre>{JSON.stringify(plan, null, 2)}</pre>
        </details>
      </div>
    </section>
  );
}
