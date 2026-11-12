import { useEffect, useMemo, useRef } from 'react';
import type { RefObject } from 'react';
import {
  ReactFlow,
  BaseEdge,
  getStraightPath,
  Background,
  Controls,
  Handle,
  Position,
  useNodesState,
  useNodesInitialized,
  useReactFlow,
  useInternalNode,
} from '@xyflow/react';
import type { Node, NodeProps, Edge, EdgeProps } from '@xyflow/react';
import type { Network, State, ElectricalResult } from './types';
import { number } from './liveTypes';

type AssetData = {
  id: string;
  label: string;
  root: boolean;
  critical: boolean;
  state?: State;
  result?: ElectricalResult | null;
  selected: string;
  select: (asset: string) => void;
};
type AssetNode = Node<AssetData, 'asset'>;
function Asset({ data: d }: NodeProps<AssetNode>) {
  const tx = d.root ? 'main' : `tx_${d.id}`;
  const unavailable = (kind: string, name: string) =>
    !!d.state?.equipment_outages.some((o) => o.kind === kind && o.equipment === name);
  const txOut = unavailable('transformer', tx);
  const txOpen = d.state?.open_transformers.includes(tx);
  const load = d.result?.load_measurements.find((r) => r.load_id === d.id);
  function assetButton(asset: string, label: string, reading: string, outage = false) {
    return (
      <button
        type="button"
        className={`live-asset-row nodrag nopan ${outage ? 'asset-outage' : ''} ${d.selected === asset ? 'asset-selected' : ''}`}
        onClick={() => d.select(asset)}
        aria-label={`Inspect ${asset}`}
      >
        <span>{label}</span>
        <strong>{reading}</strong>
      </button>
    );
  }
  return (
    <div className="live-asset-node">
      {d.root ? (
        <>
          {assetButton(
            'source:source',
            'Source · 33 kV',
            !d.state
              ? 'Awaiting solve'
              : unavailable('source', 'source')
                ? 'Unavailable · isolated'
                : !d.state.source_connected
                  ? 'Disconnected'
                  : `${number(d.result?.source_kw, 0)} kW`,
            unavailable('source', 'source'),
          )}
          <div className="asset-connection">↓</div>
          {assetButton(
            'transformer:main',
            'Main · 33 / 11 kV',
            txOut
              ? 'Unavailable · isolated'
              : txOpen
                ? 'Open'
                : `${number(d.result?.transformer_loading_pct.main)}% loading`,
            txOut || txOpen,
          )}
          <div className="live-mv">
            {assetButton(
              'bus:sub',
              'Substation · 11 kV',
              `${number(d.result?.voltages_pu.sub, 3)} pu`,
            )}
            <Handle type="source" position={Position.Bottom} id="bottom" />
            <Handle type="source" position={Position.Left} id="left" />
            <Handle type="source" position={Position.Right} id="right" />
          </div>
        </>
      ) : (
        <>
          <div className="live-mv">
            <Handle type="target" position={Position.Top} id="top" />
            <Handle type="target" position={Position.Left} id="left-in" />
            <Handle type="target" position={Position.Right} id="right-in" />
            <Handle type="source" position={Position.Left} id="left" />
            <Handle type="source" position={Position.Right} id="right" />
            {assetButton(
              `bus:${d.id}`,
              `${d.id.toUpperCase()} · 11 kV bus`,
              !d.result
                ? 'Awaiting solve'
                : d.result.energized_buses.includes(d.id)
                  ? `${number(d.result.voltages_pu[d.id], 3)} pu`
                  : 'De-energized',
            )}
          </div>
          <div className="asset-connection">↓ 11 / 0.415 kV</div>
          {assetButton(
            `transformer:${tx}`,
            tx,
            txOut
              ? 'Unavailable · isolated'
              : txOpen
                ? 'Open'
                : `${number(d.result?.transformer_loading_pct[tx])}% loading`,
            txOut || txOpen,
          )}
          <div className="asset-connection">
            ↓ {d.critical ? 'Critical load' : 'Aggregate load'}
          </div>
          {assetButton(
            `load:${d.id}`,
            d.label,
            !load
              ? 'Awaiting solve'
              : !load.energized
                ? 'Supply interrupted'
                : `${number(load.served_kw, 0)} kW · ${number(load.voltage_pu, 3)} pu`,
            !!load && !load.energized,
          )}
        </>
      )}
    </div>
  );
}
const nodeTypes = { asset: Asset };

function Connection(props: EdgeProps) {
  const source = useInternalNode(props.source);
  const target = useInternalNode(props.target);
  const [path, midpointX, midpointY] = getStraightPath(props);
  let labelX = midpointX;
  let labelY = midpointY;
  if (source?.measured.height && target?.measured.height) {
    const from = source.internals.positionAbsolute;
    const to = target.internals.positionAbsolute;
    // MV handles sit above the transformer/load rows. Place labels in the
    // inter-card gaps instead of at a path midpoint behind those rows.
    if (props.id.startsWith('seg')) {
      labelX = from.x + (source.measured.width ?? 230) / 2;
      labelY = (from.y + source.measured.height + to.y) / 2;
    } else if (props.id.startsWith('tie')) {
      labelY = (to.y + target.measured.height + from.y) / 2;
      const fraction = (labelY - props.sourceY) / (props.targetY - props.sourceY);
      labelX = props.sourceX + (props.targetX - props.sourceX) * fraction;
    } else {
      labelY = (from.y + source.measured.height + to.y) / 2;
    }
  }
  return (
    <BaseEdge
      id={props.id}
      path={path}
      labelX={labelX}
      labelY={labelY}
      label={props.label}
      labelStyle={props.labelStyle}
      labelBgStyle={props.labelBgStyle}
      labelBgPadding={props.labelBgPadding}
      interactionWidth={props.interactionWidth}
      style={props.style}
    />
  );
}
const edgeTypes = { connection: Connection };

function FitLayout({
  container,
  focus,
  onOverview,
}: {
  container: RefObject<HTMLDivElement | null>;
  focus: string;
  onOverview: () => void;
}) {
  const initialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!initialized || !container.current) return;
    let frame = 0;
    const resize = () => {
      if (!container.current?.clientWidth || !container.current.clientHeight) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        void fitView({
          padding: 0.09,
          duration: 0,
          nodes: focus ? [{ id: focus }] : undefined,
        });
      });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container.current);
    resize();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [container, fitView, initialized, focus]);
  return (
    <Controls
      showInteractive={false}
      position="top-right"
      onFitView={() => {
        onOverview();
        void fitView({ padding: 0.09, duration: 0 });
      }}
    />
  );
}

export function LiveTopology({
  network,
  state,
  result,
  selected,
  onSelect,
  focus,
  onOverview,
  animate = false,
}: {
  network: Network;
  state?: State;
  result?: ElectricalResult | null;
  selected: string;
  onSelect: (asset: string) => void;
  focus: string;
  onOverview: () => void;
  animate?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [displayNodes, setDisplayNodes, onNodesChange] = useNodesState<AssetNode>([]);
  const { nodes, edges } = useMemo(() => {
    const positions: Record<string, { x: number; y: number }> = {
      sub: { x: 340, y: 0 },
      a1: { x: 340, y: 235 },
      a2: { x: 340, y: 500 },
      b1: { x: 20, y: 205 },
      b2: { x: 20, y: 455 },
      c1: { x: 660, y: 205 },
      c2: { x: 660, y: 455 },
    };
    const nodes: AssetNode[] = network.buses.map((bus) => ({
      id: bus.id,
      type: 'asset',
      initialWidth: 230,
      initialHeight: bus.id === 'sub' ? 171 : 187,
      position: positions[bus.id],
      data: {
        id: bus.id,
        root: bus.id === 'sub',
        label: network.loads.find((l) => l.id === bus.id)?.label ?? bus.label,
        critical: !!network.loads.find((l) => l.id === bus.id)?.critical,
        state,
        result,
        selected,
        select: onSelect,
      },
    }));
    const edges: Edge[] = network.lines.map((line) => {
      const closed = !!state?.closed_lines.includes(line.id);
      const unavailable = !!state?.equipment_outages.some(
        (o) => o.kind === 'line' && o.equipment === line.id,
      );
      const locked = !!state?.locked_open.includes(line.id);
      const loading = result?.line_loading_pct[line.id];
      const active =
        closed &&
        !!result?.energized_buses.includes(line.from_bus) &&
        !!result?.energized_buses.includes(line.to_bus) &&
        (loading ?? 0) > 0.01;
      const tie = line.normally_open;
      const stateLabel = !state
        ? 'Awaiting solve'
        : unavailable
          ? 'UNAVAILABLE · OPEN'
          : locked
            ? 'LOCKED OPEN'
            : closed
              ? `CLOSED · ${number(loading)}%`
              : 'OPEN';
      const color =
        unavailable || (loading ?? 0) > 100 ? '#a44838' : active && tie ? '#187562' : '#6e7b8c';
      return {
        id: line.id,
        source: line.from_bus,
        target: line.to_bus,
        type: 'connection',
        sourceHandle:
          line.from_bus === 'sub'
            ? line.to_bus === 'b1'
              ? 'left'
              : line.to_bus === 'c1'
                ? 'right'
                : 'bottom'
            : line.id === 'tie_b'
              ? 'right'
              : 'left',
        targetHandle:
          line.id === 'tie_b'
            ? 'left-in'
            : line.id === 'tie_c'
              ? 'right-in'
              : line.id.startsWith('seg')
                ? 'left-in'
                : 'top',
        label: `${line.id} · ${stateLabel}`,
        animated: animate && active,
        style: {
          stroke: color,
          strokeWidth: active && tie ? 2.6 : 1.7,
          strokeDasharray: !closed ? '6 5' : undefined,
        },
        labelStyle: { fill: color, fontSize: 11, fontWeight: 600 },
        labelBgStyle: { fill: '#f7f9fb', fillOpacity: 0.96 },
        labelBgPadding: [4, 3] as [number, number],
        ariaLabel: `${line.id}: ${stateLabel}`,
        interactionWidth: 22,
      };
    });
    return { nodes, edges };
  }, [network, state, result, selected, onSelect, animate]);
  useEffect(() => {
    // Preserve measured dimensions across telemetry updates so handle geometry
    // remains available to edges. React Flow owns those measurements.
    setDisplayNodes((previous) =>
      nodes.map((node) => ({
        ...node,
        measured: previous.find((old) => old.id === node.id)?.measured,
      })),
    );
  }, [nodes, setDisplayNodes]);
  return (
    <div ref={container} className="live-topology" data-testid="live-topology">
      <ReactFlow
        nodes={displayNodes}
        onNodesChange={onNodesChange}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.09 }}
        minZoom={0.2}
        maxZoom={1.8}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        ariaLabelConfig={{
          'controls.ariaLabel': 'Diagram controls',
          'controls.zoomIn.ariaLabel': 'Zoom in',
          'controls.zoomOut.ariaLabel': 'Zoom out',
          'controls.fitView.ariaLabel': 'Show whole grid',
        }}
        onEdgeClick={(_, edge) => onSelect(`line:${edge.id}`)}
      >
        <FitLayout container={container} focus={focus} onOverview={onOverview} />
        <Background gap={24} size={1} color="#dce1e7" />
      </ReactFlow>
    </div>
  );
}
