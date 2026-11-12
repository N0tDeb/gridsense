import { useState } from 'react';
import type { FormEvent } from 'react';
import type { Network } from './types';
import type { LivePolicy, LiveSession, PhysicalEvent } from './liveTypes';
import { eventText } from './liveTypes';
import { assetOptions } from './LiveEvidence';

export function NewSession({
  disabled,
  onCreate,
}: {
  disabled: boolean;
  onCreate: (config: Record<string, unknown>) => Promise<boolean>;
}) {
  const [title, setTitle] = useState('Live feeder session');
  const [horizon, setHorizon] = useState(60);
  const [policy, setPolicy] = useState<LivePolicy>('nominal');
  const [factors, setFactors] = useState({ a: 1, b: 1, c: 1 });
  const [latency, setLatency] = useState(0);
  const [actuationEstimate, setActuationEstimate] = useState(1);
  const [confirmationEstimate, setConfirmationEstimate] = useState(0);
  const [confirmationTimeout, setConfirmationTimeout] = useState(5);
  const [energyHorizon, setEnergyHorizon] = useState(10);
  async function submit(e: FormEvent) {
    e.preventDefault();
    await onCreate({
      title,
      horizon_s: horizon,
      initial_factors: factors,
      measurements: { latency_s: latency },
      control: {
        policy,
        confirmation_timeout_s: confirmationTimeout,
        planning_timing: {
          actuation_delay_s: actuationEstimate,
          confirmation_delay_s: confirmationEstimate,
          energy_horizon_s: energyHorizon,
        },
      },
    });
  }
  return (
    <form onSubmit={submit} className="live-new-session">
      <fieldset disabled={disabled}>
        <legend>Session settings</legend>
        <p className="live-note">
          Equipment starts available. High demand can still exceed electrical limits.
        </p>
        <div className="live-form-grid">
          <label className="live-field">
            Session title
            <input
              value={title}
              maxLength={100}
              required
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="live-field">
            Restoration policy
            <select
              aria-label="Restoration policy"
              value={policy}
              onChange={(e) => setPolicy(e.target.value as LivePolicy)}
            >
              <option value="nominal">Nominal · use demand estimates</option>
              <option value="guarded">Guarded · check demand samples</option>
              <option value="off">Off · no automatic switching</option>
            </select>
          </label>
          <label className="live-field">
            Session duration (s)
            <input
              type="number"
              min={1}
              max={600}
              required
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
            />
          </label>
          {(['a', 'b', 'c'] as const).map((feeder) => (
            <label className="live-field" key={feeder}>
              Feeder {feeder.toUpperCase()} demand (×)
              <input
                type="number"
                min={0.5}
                max={2}
                step={0.05}
                required
                value={factors[feeder]}
                onChange={(e) => setFactors({ ...factors, [feeder]: Number(e.target.value) })}
              />
            </label>
          ))}
          <label className="live-field">
            Measurement delay (s)
            <input
              type="number"
              min={0}
              max={30}
              value={latency}
              required
              onChange={(e) => setLatency(Number(e.target.value))}
            />
          </label>
        </div>
        <details>
          <summary>Planning assumptions</summary>
          <p className="live-note">
            These estimates guide switching decisions. Disturbance timing can differ. Estimated
            switching and confirmation together must fit the confirmation timeout.
          </p>
          <div className="live-form-grid">
            <label className="live-field">
              Estimated switching time (s)
              <input
                type="number"
                min={1}
                max={10}
                required
                value={actuationEstimate}
                onChange={(e) => setActuationEstimate(Number(e.target.value))}
              />
            </label>
            <label className="live-field">
              Estimated confirmation delay (s)
              <input
                type="number"
                min={0}
                max={30}
                required
                value={confirmationEstimate}
                onChange={(e) => setConfirmationEstimate(Number(e.target.value))}
              />
            </label>
            <label className="live-field">
              Confirmation timeout (s)
              <input
                type="number"
                min={1}
                max={30}
                required
                value={confirmationTimeout}
                onChange={(e) => setConfirmationTimeout(Number(e.target.value))}
              />
            </label>
            <label className="live-field">
              Energy comparison window (s)
              <input
                type="number"
                min={1}
                max={600}
                required
                value={energyHorizon}
                onChange={(e) => setEnergyHorizon(Number(e.target.value))}
              />
            </label>
          </div>
        </details>
        <p className="live-note">
          Guarded planning checks more demand cases. It can take longer and restore less load.
          Create a new session to change these settings.
        </p>
        <button className="primary-button" type="submit">
          Create live session
        </button>
      </fieldset>
    </form>
  );
}

export function ScenarioControls({
  session,
  network,
  disabled,
  onSchedule,
}: {
  session: LiveSession;
  network: Network;
  disabled: boolean;
  onSchedule: (events: PhysicalEvent[]) => Promise<boolean>;
}) {
  const [kind, setKind] = useState<'outage' | 'demand' | 'transport' | 'actuator'>('outage');
  const [asset, setAsset] = useState('line:feed_a');
  const [feeder, setFeeder] = useState('a');
  const [factor, setFactor] = useState(1.5);
  const [repair, setRepair] = useState(false);
  const [repairDelay, setRepairDelay] = useState(8);
  const [latency, setLatency] = useState(0);
  const [drop, setDrop] = useState(false);
  const [delay, setDelay] = useState(1);
  const [fail, setFail] = useState(false);
  const [feedbackDelay, setFeedbackDelay] = useState(0);
  const [dropFeedback, setDropFeedback] = useState(false);
  const at = session.at_s + 1;
  const options = assetOptions(network).filter(
    (a) => kind === 'transport' || /^(line|source|transformer):/.test(a.id),
  );
  const selectedAsset = options.some((a) => a.id === asset) ? asset : 'line:feed_a';
  const queue = session.simulation.scheduled_events;
  async function submit(e: FormEvent) {
    e.preventDefault();
    let events: PhysicalEvent[];
    if (kind === 'outage') {
      const [equipment_kind, equipment] = selectedAsset.split(':');
      const incident_id = `outage-${crypto.randomUUID().slice(0, 8)}`;
      events = [{ kind, at_s: at, incident_id, equipment_kind, equipment }];
      if (repair) events.push({ kind: 'repair', at_s: at + repairDelay, incident_id });
    } else if (kind === 'demand') events = [{ kind, at_s: at, feeder, factor }];
    else if (kind === 'transport')
      events = [{ kind, at_s: at, equipment: selectedAsset, latency_s: latency, drop }];
    else
      events = [
        {
          kind,
          at_s: at,
          equipment: selectedAsset,
          actuation_delay_s: delay,
          fail,
          feedback_delay_s: feedbackDelay,
          drop_feedback: dropFeedback,
        },
      ];
    await onSchedule(events);
  }
  return (
    <section className="panel live-scenario">
      <div className="panel-header">
        <h2>Add disturbance</h2>
        <span className="live-tag">Simulator input</span>
      </div>
      <div className="live-panel-body">
        <p className="live-note">
          Pause to add an event for t={at} s, the next simulated second. The controller cannot see
          this queue or future repair times.
        </p>
        <form onSubmit={submit}>
          <fieldset disabled={disabled || session.mode !== 'paused' || at > session.horizon_s}>
            <div className="live-form-grid">
              <label className="live-field">
                Disturbance type
                <select
                  aria-label="Disturbance type"
                  value={kind}
                  onChange={(e) => setKind(e.target.value as typeof kind)}
                >
                  <option value="outage">Equipment outage</option>
                  <option value="demand">Demand change</option>
                  <option value="transport">Measurement delivery</option>
                  <option value="actuator">Switch response and confirmation</option>
                </select>
              </label>
              {kind !== 'demand' && (
                <label className="live-field">
                  Equipment
                  <select
                    aria-label="Equipment"
                    value={selectedAsset}
                    onChange={(e) => setAsset(e.target.value)}
                  >
                    {options.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {kind === 'demand' && (
                <>
                  <label className="live-field">
                    Demand feeder
                    <select
                      aria-label="Demand feeder"
                      value={feeder}
                      onChange={(e) => setFeeder(e.target.value)}
                    >
                      {['a', 'b', 'c'].map((f) => (
                        <option key={f} value={f}>
                          Feeder {f.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="live-field">
                    Demand multiplier (×)
                    <input
                      type="number"
                      min={0.5}
                      max={2}
                      step={0.05}
                      value={factor}
                      required
                      onChange={(e) => setFactor(Number(e.target.value))}
                    />
                  </label>
                </>
              )}
              {kind === 'outage' && (
                <>
                  <label className="live-checkbox">
                    <input
                      type="checkbox"
                      checked={repair}
                      onChange={(e) => setRepair(e.target.checked)}
                    />
                    Schedule simulated repair
                  </label>
                  {repair && (
                    <label className="live-field">
                      Repair delay after outage (s)
                      <input
                        type="number"
                        min={1}
                        max={Math.max(1, session.horizon_s - at)}
                        value={repairDelay}
                        required
                        onChange={(e) => setRepairDelay(Number(e.target.value))}
                      />
                    </label>
                  )}
                </>
              )}
              {kind === 'transport' && (
                <>
                  <label className="live-field">
                    Delivery delay (s)
                    <input
                      type="number"
                      min={0}
                      max={30}
                      value={latency}
                      required
                      onChange={(e) => setLatency(Number(e.target.value))}
                    />
                  </label>
                  <label className="live-checkbox">
                    <input
                      type="checkbox"
                      checked={drop}
                      onChange={(e) => setDrop(e.target.checked)}
                    />
                    Drop new measurements
                  </label>
                </>
              )}
              {kind === 'actuator' && (
                <>
                  <label className="live-field">
                    Switching delay (s)
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={delay}
                      required
                      onChange={(e) => setDelay(Number(e.target.value))}
                    />
                  </label>
                  <label className="live-field">
                    Confirmation delay (s)
                    <input
                      type="number"
                      min={0}
                      max={30}
                      value={feedbackDelay}
                      required
                      onChange={(e) => setFeedbackDelay(Number(e.target.value))}
                    />
                  </label>
                  <label className="live-checkbox">
                    <input
                      type="checkbox"
                      checked={fail}
                      onChange={(e) => setFail(e.target.checked)}
                    />
                    Simulate switch failure
                  </label>
                  <label className="live-checkbox">
                    <input
                      type="checkbox"
                      checked={dropFeedback}
                      onChange={(e) => setDropFeedback(e.target.checked)}
                    />
                    Drop command confirmation
                  </label>
                </>
              )}
            </div>
            <button className="secondary-button" type="submit">
              Schedule disturbance
            </button>
          </fieldset>
        </form>
        <p className="live-note">
          An outage isolates the whole device. Repair makes it available again; reconnecting it
          needs a checked switching sequence. Repair times are simulation settings.
        </p>
        <details>
          <summary>Scheduled events ({queue.length})</summary>
          <ol className="live-queue">
            {queue.map((q) => (
              <li key={q.sequence}>
                <b>t={q.event.at_s} s</b> {eventText(q.event)}
              </li>
            ))}
          </ol>
          {!queue.length && <p>No future events.</p>}
        </details>
      </div>
    </section>
  );
}

export function ActiveIncidents({
  session,
  disabled,
  onSchedule,
}: {
  session: LiveSession;
  disabled: boolean;
  onSchedule: (events: PhysicalEvent[]) => Promise<boolean>;
}) {
  const at = session.at_s + 1;
  const queue = session.simulation.scheduled_events;
  if (!session.simulation.physical.equipment_outages.length) return null;
  return (
    <div className="live-active-incidents" aria-label="Active equipment incidents">
      <h3>Equipment awaiting repair</h3>
      {session.simulation.physical.equipment_outages.map((o) => {
        const scheduled = queue.find(
          (q) => q.event.kind === 'repair' && q.event.incident_id === o.incident_id,
        );
        return (
          <div className="live-incident" key={o.incident_id}>
            <span>
              <strong>
                {o.kind}:{o.equipment}
              </strong>
              <small>{o.incident_id}</small>
            </span>
            {scheduled ? (
              <span>Repair scheduled · t={scheduled.event.at_s} s</span>
            ) : (
              <button
                className="secondary-button"
                disabled={disabled || session.mode !== 'paused' || at > session.horizon_s}
                onClick={() =>
                  void onSchedule([{ kind: 'repair', at_s: at, incident_id: o.incident_id }])
                }
              >
                Schedule repair for {o.equipment}
              </button>
            )}
          </div>
        );
      })}

      <p className="live-note">Alternate supply bypasses a fault; it does not repair equipment.</p>
    </div>
  );
}
