import { useEffect, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  useReactFlow,
  useStore,
} from '@xyflow/react';
import type { NodeProps, Node, Edge } from '@xyflow/react';
import { Building2, Hospital, Home, UtilityPole, Zap } from 'lucide-react';
import type { ElectricalResult, Network, State } from './types';

type BusData = {
  label: string;
  sub: boolean;
  critical: boolean;
  live: boolean;
  voltage?: number;
  served?: number;
  preview: boolean;
  selected: boolean;
};
type BusNode = Node<BusData, 'bus'>;

function Bus({ data }: NodeProps<BusNode>) {
  const Icon = data.sub
    ? UtilityPole
    : data.critical
      ? Hospital
      : data.label.includes('Residential')
        ? Home
        : Building2;
  return (
    <div
      className={`bus-node ${!data.live ? 'bus-out' : ''} ${data.selected ? 'bus-selected' : ''}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="bus-title">
        <Icon size={15} />
        <span>{data.label}</span>
        {data.critical && <span className="critical-dot" title="Critical demand" />}
      </div>
      <div className="bus-reading">
        {data.sub
          ? '33 / 11 kV'
          : data.preview
            ? 'Awaiting solve'
            : data.live
              ? `${data.voltage?.toFixed(3)} pu`
              : 'Out of service'}
      </div>
      <div className="bus-caption">
        {data.sub
          ? 'Source available'
          : data.preview
            ? data.critical
              ? 'Critical demand'
              : 'Demand bus'
            : data.live
              ? `${Math.round(data.served ?? 0)} kW served`
              : 'Isolated · 0 kW served'}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { bus: Bus };

function FitLayout() {
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!width || !height) return;
    const frame = requestAnimationFrame(() => {
      void fitView({ padding: 0.13, duration: 0 });
    });
    return () => cancelAnimationFrame(frame);
  }, [width, height, fitView]);
  return <Controls showInteractive={false} />;
}

export function Topology({
  network,
  state,
  result,
  selectedBus,
  onSelect,
}: {
  network: Network;
  state?: State;
  result?: ElectricalResult;
  selectedBus: string | null;
  onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: BusNode[] = network.buses.map((bus) => {
      const load = network.loads.find((l) => l.bus === bus.id);
      const reading = result?.load_measurements.find((l) => l.load_id === bus.id);
      return {
        id: bus.id,
        type: 'bus',
        position: { x: bus.x, y: bus.y },
        data: {
          label: bus.label,
          sub: bus.id === 'sub',
          critical: !!load?.critical,
          live: result ? result.energized_buses.includes(bus.id) : !bus.id.startsWith('a'),
          voltage: reading?.voltage_pu,
          served: reading?.served_kw,
          preview: !result,
          selected: selectedBus === bus.id,
        },
      };
    });
    const edges: Edge[] = network.lines.map((line) => {
      const closed = state
        ? state.closed_lines.includes(line.id)
        : !line.normally_open && line.id !== network.faulted_line;
      const faulted = line.id === network.faulted_line;
      const loading = result?.line_loading_pct[line.id] ?? 0;
      const overloaded = loading > 100;
      const tie = line.normally_open;
      const color = faulted
        ? '#a95a49'
        : overloaded
          ? '#bd493d'
          : closed && tie
            ? '#14806c'
            : closed
              ? '#7e8c9d'
              : '#aeb7c3';
      return {
        id: line.id,
        source: line.from_bus,
        target: line.to_bus,
        type: 'straight',
        label: faulted
          ? 'ISOLATED'
          : tie
            ? `${line.id === 'tie_b' ? 'TIE B' : 'TIE C'} · ${closed ? `${loading.toFixed(0)}%` : 'OPEN'}`
            : result && closed
              ? `${loading.toFixed(0)}%`
              : undefined,
        style: {
          stroke: color,
          strokeWidth: closed && tie ? 2.6 : 1.6,
          strokeDasharray: closed ? undefined : '5 5',
        },
        labelStyle: { fill: color, fontSize: 10, fontWeight: 700 },
        labelBgStyle: { fill: '#fafbfc', fillOpacity: 0.96 },
        labelBgPadding: [6, 4] as [number, number],
        ariaLabel: `${line.label}, ${faulted ? 'faulted and isolated' : closed ? 'closed' : 'open'}, ${loading.toFixed(1)} percent loading`,
      };
    });
    return { nodes, edges };
  }, [network, state, result, selectedBus]);
  return (
    <div className="topology-canvas" data-testid="topology">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.13 }}
        minZoom={0.1}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelect(node.id)}
        proOptions={{ hideAttribution: false }}
      >
        <Background color="#dce1e7" gap={23} size={1} />
        <FitLayout />
      </ReactFlow>
      <div className="network-label">
        <Zap size={12} /> GS six-load feeder <span>Balanced · 3 phase</span>
      </div>
    </div>
  );
}
