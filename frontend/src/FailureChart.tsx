import type { Policy, Sweep } from './types';

const colors: Record<Policy, string> = {
  nominal: '#b45443',
  guarded: '#147d69',
  oracle: '#617fa9',
};
const labels = {
  nominal: 'Nominal',
  guarded: 'Guarded',
  oracle: 'Full-information reference',
};

export function FailureChart({ sweep }: { sweep: Sweep }) {
  const rows = sweep.rows;
  const xs = rows.map((r) => r.west_demand_kw),
    ys = rows.map((r) => r.max_loading_pct);
  const xmin = Math.min(...xs),
    xmax = Math.max(...xs),
    ymax = Math.max(120, Math.ceil(Math.max(...ys) / 20) * 20);
  const x = (v: number) => 62 + ((v - xmin) / (xmax - xmin)) * 690;
  const y = (v: number) => 234 - (v / ymax) * 194;
  return (
    <>
      <svg
        viewBox="0 0 790 282"
        className="failure-chart"
        role="img"
        aria-label="Maximum equipment loading as actual west demand increases. The 100 percent line is the model's loading limit. Detailed results follow."
      >
        <rect x="62" y="40" width="690" height={y(100) - 40} fill="#fbefed" />
        {[0, 40, 80, 100, ymax]
          .filter((v, i, arr) => arr.indexOf(v) === i)
          .map((v) => (
            <g key={v}>
              <line
                x1="62"
                x2="752"
                y1={y(v)}
                y2={y(v)}
                stroke={v === 100 ? '#bc796e' : '#e7eaf0'}
                strokeDasharray={v === 100 ? '5 4' : undefined}
              />
              <text x="50" y={y(v) + 4} textAnchor="end">
                {v}%
              </text>
            </g>
          ))}
        <text x="752" y={y(100) - 8} textAnchor="end" className="chart-limit">
          Model loading limit
        </text>
        {(['nominal', 'guarded', 'oracle'] as Policy[]).map((policy) => {
          const points = rows.filter((r) => r.policy === policy);
          return (
            <g key={policy}>
              <polyline
                points={points
                  .map((r) => `${x(r.west_demand_kw)},${y(r.max_loading_pct)}`)
                  .join(' ')}
                fill="none"
                stroke={colors[policy]}
                strokeWidth="2.5"
                strokeDasharray={policy === 'oracle' ? '5 5' : undefined}
              />
              {points.map((r, i) => (
                <circle
                  key={i}
                  cx={x(r.west_demand_kw)}
                  cy={y(r.max_loading_pct)}
                  r={policy === 'oracle' ? 2 : 3.5}
                  fill={colors[policy]}
                >
                  <title>
                    {labels[policy]}: {r.west_demand_kw.toFixed(0)} kW,{' '}
                    {r.max_loading_pct.toFixed(1)}%, {r.action}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
        {[xmin, (xmin + xmax) / 2, xmax].map((v) => (
          <text key={v} x={x(v)} y="253" textAnchor="middle">
            {v.toFixed(0)}
          </text>
        ))}
        <text x="407" y="276" textAnchor="middle">
          Actual west-feeder demand (kW)
        </text>
      </svg>
      <div className="chart-legend">
        {(['nominal', 'guarded', 'oracle'] as Policy[]).map((policy) => (
          <span key={policy}>
            <i style={{ background: colors[policy] }} />
            {labels[policy]}
          </span>
        ))}
      </div>
    </>
  );
}
