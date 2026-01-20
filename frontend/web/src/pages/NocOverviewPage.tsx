import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Play,
  Square,
  RefreshCw,
  Monitor,
  ArrowRight,
  Zap,
  Target,
  Bell,
  ChevronDown,
  ChevronRight,
  Webhook,
  Clock,
  FileText
} from 'lucide-react';
import { nocMonitoringApi, customersApi, alertsApi } from '@/services/api';
import { formatDistanceToNow } from 'date-fns';
import type { CustomerHealth, CustomerWebhookStatus } from '@/types';

// Status badge component
function StatusBadge({ status }: { status: string }) {
  const config = {
    healthy: { icon: CheckCircle2, color: 'text-green-500', bg: 'bg-green-500/10', label: 'Healthy' },
    warning: { icon: AlertTriangle, color: 'text-yellow-500', bg: 'bg-yellow-500/10', label: 'Major' },
    critical: { icon: XCircle, color: 'text-red-500', bg: 'bg-red-500/10', label: 'Critical' },
    unknown: { icon: HelpCircle, color: 'text-gray-500', bg: 'bg-gray-500/10', label: 'Unknown' },
  }[status] || { icon: HelpCircle, color: 'text-gray-500', bg: 'bg-gray-500/10', label: status };

  const Icon = config.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-sm font-medium ${config.bg} ${config.color}`}>
      <Icon className="w-4 h-4" />
      {config.label}
    </span>
  );
}

// Customer card component
function CustomerCard({
  customer,
  onStartMonitoring,
  onStopMonitoring,
  onViewDetails,
  isLoading
}: {
  customer: CustomerHealth;
  onStartMonitoring: () => void;
  onStopMonitoring: () => void;
  onViewDetails: () => void;
  isLoading: boolean;
}) {
  const statusColors = {
    healthy: 'border-green-500/30 hover:border-green-500/50',
    warning: 'border-yellow-500/30 hover:border-yellow-500/50',
    critical: 'border-red-500/30 hover:border-red-500/50 animate-pulse',
    unknown: 'border-gray-500/30 hover:border-gray-500/50',
  };

  return (
    <div
      className={`bg-gray-800 rounded-lg border-2 ${statusColors[customer.status as keyof typeof statusColors] || statusColors.unknown} 
        transition-all duration-200 overflow-hidden`}
    >
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${customer.is_monitoring ? 'bg-green-500/20' : 'bg-gray-700'}`}>
            <Monitor className={`w-5 h-5 ${customer.is_monitoring ? 'text-green-400' : 'text-gray-400'}`} />
          </div>
          <div>
            <h3 className="font-semibold text-white">{customer.customer_name}</h3>
            <p className="text-xs text-gray-400">
              {customer.is_monitoring ? 'Active monitoring' : 'Monitoring stopped'}
            </p>
          </div>
        </div>
        <StatusBadge status={customer.status} />
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-3 gap-2 p-4">
        <div className="text-center">
          <div className="flex items-center justify-center gap-1 text-blue-400">
            <Target className="w-4 h-4" />
            <span className="text-lg font-bold">{customer.enabled_targets}</span>
          </div>
          <p className="text-xs text-gray-500">Active Targets</p>
        </div>
        <div className="text-center">
          <div className="flex items-center justify-center gap-1 text-yellow-400">
            <Bell className="w-4 h-4" />
            <span className="text-lg font-bold">{customer.warning_alerts}</span>
          </div>
          <p className="text-xs text-gray-500">Warnings</p>
        </div>
        <div className="text-center">
          <div className="flex items-center justify-center gap-1 text-red-400">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-lg font-bold">{customer.critical_alerts}</span>
          </div>
          <p className="text-xs text-gray-500">Critical</p>
        </div>
      </div>

      {/* Last Check */}
      {customer.last_check && (
        <div className="px-4 pb-2">
          <p className="text-xs text-gray-500">
            Last check: {formatDistanceToNow(new Date(customer.last_check), { addSuffix: true })}
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex border-t border-gray-700">
        <button
          onClick={customer.is_monitoring ? onStopMonitoring : onStartMonitoring}
          disabled={isLoading}
          className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors
            ${customer.is_monitoring 
              ? 'text-red-400 hover:bg-red-500/10' 
              : 'text-green-400 hover:bg-green-500/10'}`}
        >
          {customer.is_monitoring ? (
            <>
              <Square className="w-4 h-4" />
              Stop
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              Start
            </>
          )}
        </button>
        <div className="w-px bg-gray-700" />
        <button
          onClick={onViewDetails}
          className="flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium text-blue-400 hover:bg-blue-500/10 transition-colors"
        >
          Details
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// Summary card component
function SummaryCard({
  title,
  value,
  icon: Icon,
  color,
  onClick
}: {
  title: string;
  value: number;
  icon: React.ElementType;
  color: string;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`bg-gray-800 rounded-lg p-4 border border-gray-700 ${onClick ? 'cursor-pointer hover:border-gray-600' : ''}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-gray-400 text-sm">{title}</p>
          <p className={`text-3xl font-bold ${color}`}>{value}</p>
        </div>
        <Icon className={`w-8 h-8 ${color} opacity-50`} />
      </div>
    </div>
  );
}

// Webhook status row component
function WebhookStatusRow({ status }: { status: CustomerWebhookStatus }) {
  const hasReceivedAlerts = status.total_alerts_received > 0;
  
  return (
    <div className="flex items-center justify-between py-2 px-3 bg-gray-900/50 rounded border border-gray-700/50">
      <div className="flex items-center gap-3">
        <div className={`w-2 h-2 rounded-full ${hasReceivedAlerts ? 'bg-green-400' : 'bg-gray-500'}`} />
        <span className="font-medium text-sm">{status.customer_name}</span>
      </div>
      <div className="flex items-center gap-4 text-xs text-gray-400">
        {hasReceivedAlerts ? (
          <>
            <div className="flex items-center gap-1">
              <Bell className="w-3 h-3" />
              <span>{status.total_alerts_received} alerts</span>
            </div>
            <div className="flex items-center gap-1">
              <FileText className="w-3 h-3" />
              <span>{status.analysis_files} analyses</span>
            </div>
            {status.last_alert_received && (
              <div className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                <span>Last: {formatDistanceToNow(new Date(status.last_alert_received), { addSuffix: true })}</span>
              </div>
            )}
          </>
        ) : (
          <span className="text-gray-500">No alerts received</span>
        )}
        {status.mcp_containers_ready && (
          <span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">MCP Ready</span>
        )}
      </div>
    </div>
  );
}

export default function NocOverviewPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<'all' | 'critical' | 'warning' | 'healthy' | 'unknown'>('all');
  const [webhookStatusExpanded, setWebhookStatusExpanded] = useState(false);

  // Fetch NOC overview
  const { data: overview, isLoading, error } = useQuery({
    queryKey: ['noc-overview'],
    queryFn: nocMonitoringApi.getNocOverview,
    refetchInterval: 5000, // Refresh every 5 seconds
  });

  // Fetch webhook statuses
  const { data: webhookStatuses } = useQuery({
    queryKey: ['webhook-statuses'],
    queryFn: alertsApi.getWebhookStatuses,
    refetchInterval: 10000, // Refresh every 10 seconds
  });

  // Start/stop monitoring mutations
  const startMutation = useMutation({
    mutationFn: (customerName: string) => nocMonitoringApi.startMonitoring(customerName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['noc-overview'] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: (customerName: string) => nocMonitoringApi.stopMonitoring(customerName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['noc-overview'] });
    },
  });

  // Navigate to customer details
  const viewCustomerDetails = async (customerName: string) => {
    // Switch to the customer and navigate to monitoring page
    await customersApi.switch(customerName);
    navigate('/monitoring');
  };

  // Filter customers
  const filteredCustomers = overview?.customers.filter(c => {
    if (filter === 'all') return true;
    return c.status === filter;
  }) || [];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900">
        <div className="flex flex-col items-center gap-4">
          <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
          <p className="text-gray-400">Loading NOC Dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900">
        <div className="text-center">
          <XCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-white mb-2">Failed to Load Dashboard</h2>
          <p className="text-gray-400">{(error as Error).message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <Activity className="w-6 h-6 text-blue-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold">NOC Dashboard</h1>
              <p className="text-sm text-gray-400">Multi-Customer Monitoring Overview</p>
            </div>
          </div>
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ['noc-overview'] })}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <SummaryCard
            title="Total Customers"
            value={overview?.total_customers || 0}
            icon={Monitor}
            color="text-white"
            onClick={() => setFilter('all')}
          />
          <SummaryCard
            title="Monitoring Active"
            value={overview?.monitoring_customers || 0}
            icon={Zap}
            color="text-blue-400"
          />
          <SummaryCard
            title="Critical"
            value={overview?.critical_count || 0}
            icon={XCircle}
            color="text-red-400"
            onClick={() => setFilter('critical')}
          />
          <SummaryCard
            title="Major"
            value={overview?.warning_count || 0}
            icon={AlertTriangle}
            color="text-yellow-400"
            onClick={() => setFilter('warning')}
          />
          <SummaryCard
            title="Healthy"
            value={overview?.healthy_count || 0}
            icon={CheckCircle2}
            color="text-green-400"
            onClick={() => setFilter('healthy')}
          />
          <SummaryCard
            title="Unknown"
            value={overview?.unknown_count || 0}
            icon={HelpCircle}
            color="text-gray-400"
            onClick={() => setFilter('unknown')}
          />
        </div>

        {/* Filter Tabs */}
        <div className="flex gap-2 overflow-x-auto pb-2">
          {(['all', 'critical', 'warning', 'healthy', 'unknown'] as const).map((f) => {
            const countKey = `${f}_count` as 'critical_count' | 'warning_count' | 'healthy_count' | 'unknown_count';
            const count = f !== 'all' && overview ? (overview[countKey] as number) || 0 : 0;
            const label = f === 'warning' ? 'Major' : f.charAt(0).toUpperCase() + f.slice(1);
            
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors
                  ${filter === f 
                    ? 'bg-blue-500 text-white' 
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
              >
                {label}
                {f !== 'all' && (
                  <span className="ml-2 px-1.5 py-0.5 rounded bg-gray-700 text-xs">
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Customer Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCustomers.map((customer) => (
            <CustomerCard
              key={customer.customer_name}
              customer={customer}
              onStartMonitoring={() => startMutation.mutate(customer.customer_name)}
              onStopMonitoring={() => stopMutation.mutate(customer.customer_name)}
              onViewDetails={() => viewCustomerDetails(customer.customer_name)}
              isLoading={startMutation.isPending || stopMutation.isPending}
            />
          ))}
        </div>

        {/* Webhook Status Section */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <button
            onClick={() => setWebhookStatusExpanded(!webhookStatusExpanded)}
            className="w-full flex items-center justify-between p-4 hover:bg-gray-700/50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <Webhook className="w-5 h-5 text-blue-400" />
              <span className="font-semibold">AlertManager Webhook Status</span>
              {webhookStatuses && (
                <span className="text-sm text-gray-400">
                  ({webhookStatuses.customers_with_alerts} of {webhookStatuses.total_customers} receiving alerts)
                </span>
              )}
            </div>
            {webhookStatusExpanded ? (
              <ChevronDown className="w-5 h-5 text-gray-400" />
            ) : (
              <ChevronRight className="w-5 h-5 text-gray-400" />
            )}
          </button>
          
          {webhookStatusExpanded && webhookStatuses && (
            <div className="p-4 pt-0 space-y-2">
              <div className="text-xs text-gray-500 mb-3">
                Configure AlertManager to POST alerts to: <code className="bg-gray-900 px-2 py-1 rounded">/api/alerts/ingest/&#123;customer_name&#125;</code>
              </div>
              {webhookStatuses.customers.map((status: CustomerWebhookStatus) => (
                <WebhookStatusRow key={status.customer_name} status={status} />
              ))}
            </div>
          )}
        </div>

        {/* Empty State */}
        {filteredCustomers.length === 0 && (
          <div className="text-center py-12">
            <Monitor className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-400 mb-2">
              {filter === 'all' ? 'No customers configured' : `No customers with ${filter} status`}
            </h3>
            <p className="text-gray-500">
              {filter === 'all' 
                ? 'Add customers to start monitoring' 
                : 'Try selecting a different filter'}
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
