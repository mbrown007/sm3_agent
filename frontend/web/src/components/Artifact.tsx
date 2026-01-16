import React, { useState, useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  Legend,
  AreaChart,
  Area,
} from 'recharts';
import {
  Copy,
  Check,
  Download,
  Maximize2,
  X,
  TrendingUp,
  TrendingDown,
  Minus,
  Users,
  Activity,
  AlertCircle,
  CheckCircle,
  Clock,
  Server,
  Phone,
  MessageSquare,
} from 'lucide-react';

// Color palette for charts
const CHART_COLORS = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#06b6d4', // cyan
  '#f97316', // orange
  '#84cc16', // lime
  '#ec4899', // pink
  '#6366f1', // indigo
];

// Icon mapping for metric cards
const ICON_MAP: Record<string, React.ElementType> = {
  users: Users,
  activity: Activity,
  alert: AlertCircle,
  success: CheckCircle,
  clock: Clock,
  server: Server,
  phone: Phone,
  message: MessageSquare,
  trending_up: TrendingUp,
  trending_down: TrendingDown,
};

// Types for artifact data
export interface ArtifactData {
  type: 'report' | 'chart' | 'table' | 'metric-cards' | 'raw';
  title?: string;
  subtitle?: string;
  description?: string;
  data?: unknown;
  chartType?: 'bar' | 'line' | 'pie' | 'area';
  metrics?: MetricCard[];
  columns?: TableColumn[];
  rows?: Record<string, unknown>[];
  sections?: ReportSection[];
}

interface MetricCard {
  label: string;
  value: string | number;
  change?: number;
  changeLabel?: string;
  icon?: string;
  color?: 'blue' | 'green' | 'red' | 'amber' | 'purple';
}

interface TableColumn {
  key: string;
  label: string;
  align?: 'left' | 'center' | 'right';
}

interface ReportSection {
  type: 'header' | 'summary' | 'metrics' | 'chart' | 'table' | 'text';
  title?: string;
  content?: string;
  data?: unknown;
  chartType?: 'bar' | 'line' | 'pie' | 'area';
  metrics?: MetricCard[];
  columns?: TableColumn[];
  rows?: Record<string, unknown>[];
}

interface ArtifactProps {
  content: string;
  className?: string;
}

// Parse artifact from content
export function parseArtifact(content: string): { artifact: ArtifactData | null; remainingContent: string } {
  // Look for ```artifact ... ``` blocks
  const artifactRegex = /```artifact\s*([\s\S]*?)```/;
  const match = content.match(artifactRegex);

  if (!match) {
    return { artifact: null, remainingContent: content };
  }

  try {
    const artifactJson = match[1].trim();
    const artifact = JSON.parse(artifactJson) as ArtifactData;
    const remainingContent = content.replace(match[0], '').trim();
    return { artifact, remainingContent };
  } catch (e) {
    console.error('Failed to parse artifact:', e);
    return { artifact: null, remainingContent: content };
  }
}

// Parse multiple artifacts from content
export function parseArtifacts(content: string): { artifacts: ArtifactData[]; remainingContent: string } {
  const artifacts: ArtifactData[] = [];
  let remaining = content;
  const artifactRegex = /```artifact\s*([\s\S]*?)```/g;
  let match;

  while ((match = artifactRegex.exec(content)) !== null) {
    try {
      const artifactJson = match[1].trim();
      const artifact = JSON.parse(artifactJson) as ArtifactData;
      artifacts.push(artifact);
      remaining = remaining.replace(match[0], '').trim();
    } catch (e) {
      console.error('Failed to parse artifact:', e);
    }
  }

  return { artifacts, remainingContent: remaining };
}

// Metric Card Component
function MetricCardComponent({ metric }: { metric: MetricCard }) {
  const Icon = metric.icon ? ICON_MAP[metric.icon] || Activity : Activity;
  const colorClasses = {
    blue: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
    green: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    red: 'bg-red-500/10 border-red-500/30 text-red-400',
    amber: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    purple: 'bg-purple-500/10 border-purple-500/30 text-purple-400',
  };
  const bgColor = colorClasses[metric.color || 'blue'];

  return (
    <div className={`rounded-lg border p-4 ${bgColor}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-400">{metric.label}</p>
          <p className="text-2xl font-bold mt-1">{metric.value}</p>
          {metric.change !== undefined && (
            <div className="flex items-center gap-1 mt-1 text-sm">
              {metric.change > 0 ? (
                <TrendingUp className="w-4 h-4 text-emerald-400" />
              ) : metric.change < 0 ? (
                <TrendingDown className="w-4 h-4 text-red-400" />
              ) : (
                <Minus className="w-4 h-4 text-gray-400" />
              )}
              <span className={metric.change > 0 ? 'text-emerald-400' : metric.change < 0 ? 'text-red-400' : 'text-gray-400'}>
                {metric.change > 0 ? '+' : ''}{metric.change}%
              </span>
              {metric.changeLabel && <span className="text-gray-500">{metric.changeLabel}</span>}
            </div>
          )}
        </div>
        <Icon className="w-8 h-8 opacity-50" />
      </div>
    </div>
  );
}

// Chart Component
function ChartComponent({ 
  data, 
  chartType = 'bar',
  height = 300 
}: { 
  data: unknown; 
  chartType?: 'bar' | 'line' | 'pie' | 'area';
  height?: number;
}) {
  const chartData = Array.isArray(data) ? data : [];
  
  if (chartData.length === 0) {
    return <div className="text-gray-500 text-center py-8">No chart data available</div>;
  }

  // Get data keys (excluding 'name' or 'label')
  const dataKeys = Object.keys(chartData[0] || {}).filter(
    (key) => key !== 'name' && key !== 'label' && typeof chartData[0][key] === 'number'
  );

  if (chartType === 'pie') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={chartData}
            dataKey={dataKeys[0] || 'value'}
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={100}
            label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
          >
            {chartData.map((_, index) => (
              <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: '8px',
            }}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === 'line') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
          <YAxis stroke="#9ca3af" fontSize={12} />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: '8px',
            }}
          />
          <Legend />
          {dataKeys.map((key, index) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={CHART_COLORS[index % CHART_COLORS.length]}
              strokeWidth={2}
              dot={{ fill: CHART_COLORS[index % CHART_COLORS.length] }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === 'area') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
          <YAxis stroke="#9ca3af" fontSize={12} />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: '8px',
            }}
          />
          <Legend />
          {dataKeys.map((key, index) => (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              stroke={CHART_COLORS[index % CHART_COLORS.length]}
              fill={CHART_COLORS[index % CHART_COLORS.length]}
              fillOpacity={0.3}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // Default: bar chart
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} angle={-45} textAnchor="end" height={80} />
        <YAxis stroke="#9ca3af" fontSize={12} />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1f2937',
            border: '1px solid #374151',
            borderRadius: '8px',
          }}
        />
        <Legend />
        {dataKeys.map((key, index) => (
          <Bar key={key} dataKey={key} fill={CHART_COLORS[index % CHART_COLORS.length]} radius={[4, 4, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

// Table Component
function TableComponent({ columns, rows }: { columns: TableColumn[]; rows: Record<string, unknown>[] }) {
  if (!columns || columns.length === 0 || !rows || rows.length === 0) {
    return <div className="text-gray-500 text-center py-4">No table data available</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-gray-700">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 text-sm font-semibold text-gray-300 ${
                  col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-gray-800 hover:bg-gray-800/50">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-4 py-3 text-sm ${
                    col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  {String(row[col.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Report Section Component
function ReportSectionComponent({ section }: { section: ReportSection }) {
  switch (section.type) {
    case 'header':
      return (
        <div className="mb-4">
          {section.title && <h2 className="text-xl font-bold">{section.title}</h2>}
          {section.content && <p className="text-gray-400 text-sm mt-1">{section.content}</p>}
        </div>
      );

    case 'summary':
      return (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 mb-4">
          {section.title && <h3 className="text-sm font-semibold text-blue-400 mb-2">{section.title}</h3>}
          {section.content && <p className="text-gray-300">{section.content}</p>}
        </div>
      );

    case 'metrics':
      return (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 mb-4">
          {section.metrics?.map((metric, index) => (
            <MetricCardComponent key={index} metric={metric} />
          ))}
        </div>
      );

    case 'chart':
      return (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4 mb-4">
          {section.title && <h3 className="text-sm font-semibold text-gray-300 mb-3">{section.title}</h3>}
          <ChartComponent data={section.data} chartType={section.chartType} />
        </div>
      );

    case 'table':
      return (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4 mb-4">
          {section.title && <h3 className="text-sm font-semibold text-gray-300 mb-3">{section.title}</h3>}
          <TableComponent columns={section.columns || []} rows={section.rows || []} />
        </div>
      );

    case 'text':
      return (
        <div className="mb-4">
          {section.title && <h3 className="text-sm font-semibold text-gray-300 mb-2">{section.title}</h3>}
          {section.content && <p className="text-gray-400">{section.content}</p>}
        </div>
      );

    default:
      return null;
  }
}

// Main Artifact Component
export function Artifact({ content, className = '' }: ArtifactProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const { artifact } = useMemo(() => parseArtifact(content), [content]);

  if (!artifact) {
    return null;
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(artifact, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error('Failed to copy:', e);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(artifact, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${artifact.title || 'artifact'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const renderContent = () => {
    switch (artifact.type) {
      case 'report':
        return (
          <div>
            {artifact.title && (
              <div className="mb-4 pb-3 border-b border-gray-700">
                <h2 className="text-xl font-bold">{artifact.title}</h2>
                {artifact.subtitle && <p className="text-gray-400 text-sm">{artifact.subtitle}</p>}
                {artifact.description && <p className="text-gray-500 text-sm mt-1">{artifact.description}</p>}
              </div>
            )}
            {artifact.sections?.map((section, index) => (
              <ReportSectionComponent key={index} section={section} />
            ))}
          </div>
        );

      case 'metric-cards':
        return (
          <div>
            {artifact.title && <h3 className="text-lg font-semibold mb-3">{artifact.title}</h3>}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {artifact.metrics?.map((metric, index) => (
                <MetricCardComponent key={index} metric={metric} />
              ))}
            </div>
          </div>
        );

      case 'chart':
        return (
          <div>
            {artifact.title && <h3 className="text-lg font-semibold mb-3">{artifact.title}</h3>}
            <ChartComponent data={artifact.data} chartType={artifact.chartType} />
          </div>
        );

      case 'table':
        return (
          <div>
            {artifact.title && <h3 className="text-lg font-semibold mb-3">{artifact.title}</h3>}
            <TableComponent columns={artifact.columns || []} rows={artifact.rows || []} />
          </div>
        );

      default:
        return (
          <pre className="text-sm text-gray-400 overflow-x-auto">
            {JSON.stringify(artifact, null, 2)}
          </pre>
        );
    }
  };

  return (
    <>
      <div className={`bg-gray-900 border border-gray-700 rounded-lg overflow-hidden ${className}`}>
        {/* Toolbar */}
        <div className="flex items-center justify-between px-3 py-2 bg-gray-800/50 border-b border-gray-700">
          <span className="text-xs text-gray-400 uppercase tracking-wide">
            {artifact.type === 'report' ? '📊 Report' : 
             artifact.type === 'chart' ? '📈 Chart' : 
             artifact.type === 'table' ? '📋 Table' :
             artifact.type === 'metric-cards' ? '🎯 Metrics' : '📄 Data'}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={handleCopy}
              className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-gray-200 transition-colors"
              title="Copy JSON"
            >
              {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
            </button>
            <button
              onClick={handleDownload}
              className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-gray-200 transition-colors"
              title="Download JSON"
            >
              <Download className="w-4 h-4" />
            </button>
            <button
              onClick={() => setIsExpanded(true)}
              className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-gray-200 transition-colors"
              title="Expand"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-4">
          {renderContent()}
        </div>
      </div>

      {/* Expanded Modal */}
      {isExpanded && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 bg-gray-800/50 border-b border-gray-700">
              <span className="font-semibold">{artifact.title || 'Artifact'}</span>
              <button
                onClick={() => setIsExpanded(false)}
                className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-gray-200 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              {renderContent()}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default Artifact;
