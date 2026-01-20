import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Activity,
  Clock,
  Play,
  Square,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Server,
  Database,
  MessageSquare,
  Webhook,
  Settings,
  Copy,
  ExternalLink
} from 'lucide-react';
import { monitoringApi, alertsApi, mcpApi, nocMonitoringApi, webhooksApi } from '@/services/api';
import { formatDistanceToNow } from 'date-fns';

export default function MonitoringPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [selectedSeverity, setSelectedSeverity] = useState<string>('low');
  const [expandedAnalysisId, setExpandedAnalysisId] = useState<string | null>(null);
  const [currentCustomer, setCurrentCustomer] = useState<string | null>(null);
  const [showWebhookConfig, setShowWebhookConfig] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'analyses' | 'webhooks'>('analyses');

  // Listen for customer switch events
  useEffect(() => {
    const handleCustomerSwitch = (event: CustomEvent) => {
      setCurrentCustomer(event.detail.customer);
      // Invalidate queries to refetch with new customer
      queryClient.invalidateQueries({ queryKey: ['monitoring-status'] });
      queryClient.invalidateQueries({ queryKey: ['monitoring-targets'] });
      queryClient.invalidateQueries({ queryKey: ['monitoring-alerts'] });
      queryClient.invalidateQueries({ queryKey: ['customer-datasources'] });
      queryClient.invalidateQueries({ queryKey: ['customer-analyses'] });
      queryClient.invalidateQueries({ queryKey: ['webhook-config'] });
    };

    window.addEventListener('customerSwitch', handleCustomerSwitch as EventListener);
    return () => {
      window.removeEventListener('customerSwitch', handleCustomerSwitch as EventListener);
    };
  }, [queryClient]);

  // Fetch monitoring status (use new API if customer selected)
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['monitoring-status', currentCustomer],
    queryFn: () => currentCustomer 
      ? nocMonitoringApi.getStatus(currentCustomer)
      : monitoringApi.getStatus(),
    refetchInterval: 5000,
  });

  // Fetch targets (use new API if customer selected)
  const { data: targets = [], isLoading: targetsLoading } = useQuery({
    queryKey: ['monitoring-targets', currentCustomer],
    queryFn: () => currentCustomer
      ? nocMonitoringApi.getTargets(currentCustomer)
      : monitoringApi.getTargets(),
    refetchInterval: 10000,
  });

  // Fetch alerts (use new API if customer selected)
  const { data: alerts = [], isLoading: alertsLoading } = useQuery({
    queryKey: ['monitoring-alerts', selectedSeverity, currentCustomer],
    queryFn: () => currentCustomer
      ? nocMonitoringApi.getAlerts({ customer_name: currentCustomer, min_severity: selectedSeverity })
      : monitoringApi.getAlerts({ min_severity: selectedSeverity }),
    refetchInterval: 5000,
  });

  // Fetch datasources for current customer
  const { data: datasources = [] } = useQuery({
    queryKey: ['customer-datasources', currentCustomer],
    queryFn: () => currentCustomer ? nocMonitoringApi.getDatasources(currentCustomer) : Promise.resolve([]),
    enabled: !!currentCustomer,
  });

  const { data: mcpModeData, isLoading: mcpModeLoading } = useQuery({
    queryKey: ['mcp-execution-mode'],
    queryFn: mcpApi.getExecutionMode,
    refetchInterval: 15000,
  });

  const mcpMode = mcpModeData?.mode || 'suggest';

  // Fetch all webhooks status
  const { data: webhooksData, isLoading: webhooksLoading } = useQuery({
    queryKey: ['all-webhooks'],
    queryFn: webhooksApi.getAll,
    refetchInterval: 30000,
  });

  // Fetch analyses - either all or customer-specific
  const { data: analysesData, isLoading: analysesLoading } = useQuery({
    queryKey: ['alert-analyses', currentCustomer],
    queryFn: () => currentCustomer
      ? alertsApi.getAnalysesForCustomer(currentCustomer)
      : alertsApi.getAnalyses(),
    refetchInterval: 10000,
  });

  const analyses = analysesData?.analyses || [];

  const { data: analysisDetail, isLoading: analysisDetailLoading } = useQuery({
    queryKey: ['alert-analysis', expandedAnalysisId],
    queryFn: () => alertsApi.getAnalysis(expandedAnalysisId || ''),
    enabled: !!expandedAnalysisId,
  });

  // Fetch webhook config for current customer
  const { data: webhookConfig } = useQuery({
    queryKey: ['webhook-config', currentCustomer],
    queryFn: () => currentCustomer ? webhooksApi.getConfig(currentCustomer) : null,
    enabled: !!currentCustomer,
  });

  // Validate webhook mutation
  const validateWebhookMutation = useMutation({
    mutationFn: (customerName: string) => webhooksApi.validate(customerName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-webhooks'] });
    },
  });

  // Start monitoring mutation (use new API if customer selected)
  const startMutation = useMutation({
    mutationFn: () => currentCustomer 
      ? nocMonitoringApi.startMonitoring(currentCustomer)
      : monitoringApi.start(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monitoring-status'] });
    },
  });

  // Stop monitoring mutation (use new API if customer selected)
  const stopMutation = useMutation({
    mutationFn: () => currentCustomer
      ? nocMonitoringApi.stopMonitoring(currentCustomer)
      : monitoringApi.stop(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monitoring-status'] });
    },
  });

  const setMcpModeMutation = useMutation({
    mutationFn: (mode: string) => mcpApi.setExecutionMode(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp-execution-mode'] });
    },
  });

  // Enable/disable target mutations (use new API if customer selected)
  const enableMutation = useMutation({
    mutationFn: (name: string) => currentCustomer
      ? nocMonitoringApi.enableTarget(currentCustomer, name)
      : monitoringApi.enableTarget(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monitoring-targets'] });
    },
  });

  const disableMutation = useMutation({
    mutationFn: (name: string) => currentCustomer
      ? nocMonitoringApi.disableTarget(currentCustomer, name)
      : monitoringApi.disableTarget(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monitoring-targets'] });
    },
  });

  // Discover datasources mutation
  const discoverMutation = useMutation({
    mutationFn: () => currentCustomer 
      ? nocMonitoringApi.discoverDatasources(currentCustomer)
      : Promise.reject('No customer selected'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customer-datasources'] });
    },
  });

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'text-red-400 bg-red-500/20';
      case 'high':
        return 'text-orange-400 bg-orange-500/20';
      case 'medium':
        return 'text-yellow-400 bg-yellow-500/20';
      case 'low':
        return 'text-blue-400 bg-blue-500/20';
      default:
        return 'text-gray-400 bg-gray-500/20';
    }
  };

  const toggleAnalysis = (analysisId: string) => {
    setExpandedAnalysisId((current) => (current === analysisId ? null : analysisId));
  };

  const handleDiscussWithAgent = (analysis: typeof analysisDetail) => {
    if (!analysis) return;
    
    // Build context message with alert analysis details
    const contextMessage = `I would like some help investigating this alert:

**Alert:** ${analysis.alert_name}
**Severity:** ${analysis.severity}
**Status:** ${analysis.status}
${analysis.customer_name ? `**Customer:** ${analysis.customer_name}` : ''}

**Current AI Analysis:**
- **Root Cause Hypothesis:** ${analysis.investigation?.root_cause_hypothesis || 'Not available'}
- **Impact Assessment:** ${analysis.investigation?.impact_assessment || 'Not available'}
- **Recommended Actions:** ${analysis.investigation?.recommended_actions?.join(', ') || 'None'}
- **Confidence:** ${((analysis.investigation?.confidence || 0) * 100).toFixed(0)}%

${analysis.kb_matches?.length > 0 ? `**KB Matches:** ${analysis.kb_matches.map(m => m.title).join(', ')}` : ''}

Please help me investigate this further. Can you:
1. Query current metrics to see if the issue is still ongoing
2. Check for any related alerts or anomalies
3. Suggest additional troubleshooting steps`;

    // Store context in sessionStorage for ChatPage to pick up
    sessionStorage.setItem('alertAnalysisContext', JSON.stringify({
      analysisId: analysis.id,
      alertName: analysis.alert_name,
      severity: analysis.severity,
      customerName: analysis.customer_name,
      message: contextMessage,
      timestamp: new Date().toISOString()
    }));

    // Navigate to chat
    navigate('/chat');
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const getWebhookStatusColor = (status: string) => {
    switch (status) {
      case 'configured':
        return 'text-green-400 bg-green-500/20';
      case 'pending':
        return 'text-yellow-400 bg-yellow-500/20';
      case 'error':
        return 'text-red-400 bg-red-500/20';
      case 'not_configured':
        return 'text-gray-400 bg-gray-500/20';
      default:
        return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getWebhookStatusIcon = (status: string) => {
    switch (status) {
      case 'configured':
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'pending':
        return <Clock className="w-4 h-4 text-yellow-400" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-400" />;
      default:
        return <AlertCircle className="w-4 h-4 text-gray-400" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Customer Context Banner */}
      {currentCustomer && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Server className="w-5 h-5 text-blue-400" />
            <div>
              <span className="text-blue-400 font-medium">Customer:</span>
              <span className="ml-2 text-white font-semibold">{currentCustomer}</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {webhookConfig && (
              <div className="flex items-center gap-2 text-sm">
                {getWebhookStatusIcon(webhookConfig.status)}
                <span className={`px-2 py-0.5 rounded text-xs ${getWebhookStatusColor(webhookConfig.status)}`}>
                  {webhookConfig.status}
                </span>
                <span className="text-gray-400">
                  {webhookConfig.total_alerts_received} alerts received
                </span>
              </div>
            )}
            {datasources.length > 0 && (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Database className="w-4 h-4" />
                <span>{datasources.length} datasources</span>
              </div>
            )}
            <button
              onClick={() => discoverMutation.mutate()}
              disabled={discoverMutation.isPending}
              className="text-sm px-3 py-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded transition-colors"
            >
              {discoverMutation.isPending ? 'Discovering...' : 'Discover Datasources'}
            </button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button
            onClick={() => setActiveTab('analyses')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === 'analyses'
                ? 'bg-orange-500 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <span className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" />
              Alert Analyses
              {analyses.length > 0 && (
                <span className="bg-gray-800 px-2 py-0.5 rounded-full text-xs">
                  {analyses.length}
                </span>
              )}
            </span>
          </button>
          <button
            onClick={() => setActiveTab('webhooks')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === 'webhooks'
                ? 'bg-orange-500 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <span className="flex items-center gap-2">
              <Webhook className="w-4 h-4" />
              Webhook Status
              {webhooksData?.summary && (
                <span className="bg-gray-800 px-2 py-0.5 rounded-full text-xs">
                  {webhooksData.summary.customers_with_alerts}/{webhooksData.summary.total_customers}
                </span>
              )}
            </span>
          </button>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => queryClient.invalidateQueries()}
            className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* TODO: Proactive Monitoring Controls - Hidden for v1 release */}
      {/* MCP Commands toggle, Start/Stop Monitoring buttons, Status Cards */}
      {false && (
      <>
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Proactive Monitoring</h1>
        <div className="flex gap-2">
          <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300">
            <span className="uppercase tracking-wide text-gray-400">MCP Commands</span>
            <button
              onClick={() => setMcpModeMutation.mutate('suggest')}
              disabled={mcpModeLoading || setMcpModeMutation.isPending}
              className={`px-2 py-1 rounded ${
                mcpMode === 'suggest' ? 'bg-orange-500 text-white' : 'bg-gray-700 text-gray-300'
              }`}
            >
              Suggest
            </button>
            <button
              onClick={() => setMcpModeMutation.mutate('execute')}
              disabled={mcpModeLoading || setMcpModeMutation.isPending}
              className={`px-2 py-1 rounded ${
                mcpMode === 'execute' ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-300'
              }`}
            >
              Execute
            </button>
          </div>
          {status?.running ? (
            <button
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
            >
              <Square className="w-4 h-4" />
              Stop Monitoring
            </button>
          ) : (
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              className="bg-orange-500 hover:bg-orange-600 text-white px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
            >
              <Play className="w-4 h-4" />
              Start Monitoring
            </button>
          )}
          <button
            onClick={() => queryClient.invalidateQueries()}
            className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <div className="flex items-center gap-3">
            <div className={`w-12 h-12 ${status?.running ? 'bg-green-500/20' : 'bg-gray-500/20'} rounded-lg flex items-center justify-center`}>
              <Activity className={`w-6 h-6 ${status?.running ? 'text-green-400' : 'text-gray-400'}`} />
            </div>
            <div>
              <p className="text-gray-400 text-sm">Status</p>
              <p className="text-2xl font-bold">{statusLoading ? '...' : status?.running ? 'Running' : 'Stopped'}</p>
            </div>
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-blue-500/20 rounded-lg flex items-center justify-center">
              <Clock className="w-6 h-6 text-blue-400" />
            </div>
            <div>
              <p className="text-gray-400 text-sm">Active Targets</p>
              <p className="text-2xl font-bold">{statusLoading ? '...' : status?.enabled_targets || 0}</p>
            </div>
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-red-500/20 rounded-lg flex items-center justify-center">
              <AlertTriangle className="w-6 h-6 text-red-400" />
            </div>
            <div>
              <p className="text-gray-400 text-sm">Recent Alerts</p>
              <p className="text-2xl font-bold">{statusLoading ? '...' : status?.recent_alerts || 0}</p>
            </div>
          </div>
        </div>
      </div>
      </>
      )}

      {/* TODO: Monitoring Targets - Hidden for v1 release, will revisit later */}
      {/* Proactive monitoring targets configuration */}
      {false && (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h2 className="text-xl font-bold mb-4">Monitoring Targets</h2>
        {targetsLoading ? (
          <div className="text-center text-gray-400 py-12">Loading targets...</div>
        ) : targets.length === 0 ? (
          <div className="text-center text-gray-400 py-12">
            <p>No monitoring targets configured yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {targets.map((target) => (
              <div
                key={target.name}
                className="bg-gray-900/50 border border-gray-700 rounded-lg p-4 flex items-center justify-between"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-semibold">{target.name}</h3>
                    <span className={`px-2 py-1 rounded text-xs ${getSeverityColor(target.severity_threshold)}`}>
                      {target.severity_threshold}
                    </span>
                    <span className="text-xs text-gray-500">
                      {target.query_type}
                    </span>
                  </div>
                  <p className="text-sm text-gray-400 font-mono">{target.query}</p>
                  <div className="text-xs text-gray-500 mt-2">
                    Check every {target.check_interval}s | Methods: {target.detection_methods.join(', ')}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {target.enabled ? (
                    <>
                      <CheckCircle2 className="w-5 h-5 text-green-400" />
                      <button
                        onClick={() => disableMutation.mutate(target.name)}
                        disabled={disableMutation.isPending}
                        className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm transition-colors"
                      >
                        Disable
                      </button>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-5 h-5 text-gray-500" />
                      <button
                        onClick={() => enableMutation.mutate(target.name)}
                        disabled={enableMutation.isPending}
                        className="px-3 py-1 bg-orange-500 hover:bg-orange-600 rounded text-sm transition-colors"
                      >
                        Enable
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      )}

      {/* TODO: Recent Proactive Engine Alerts - Hidden for v1 release, will revisit later */}
      {/* Proactive anomaly detection alerts */}
      {false && (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">Recent Proactive Engine Alerts</h2>
          <select
            value={selectedSeverity}
            onChange={(e) => setSelectedSeverity(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-3 py-1 text-sm"
          >
            <option value="low">All Alerts</option>
            <option value="medium">Medium+</option>
            <option value="high">High+</option>
            <option value="critical">Critical Only</option>
          </select>
        </div>
        {alertsLoading ? (
          <div className="text-center text-gray-400 py-12">Loading alerts...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center text-gray-400 py-12">
            <AlertCircle className="w-12 h-12 mx-auto mb-3 text-gray-600" />
            <p>No proactive alerts to display.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {alerts.map((alert) => (
              <div
                key={alert.id}
                className={`border rounded-lg p-4 ${getSeverityColor(alert.severity)} border-current/20`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <AlertTriangle className="w-4 h-4" />
                      <span className="font-semibold">{alert.target_name}</span>
                      <span className="text-xs opacity-75">
                        {formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true })}
                      </span>
                    </div>
                    <p className="text-sm mb-2">{alert.summary}</p>
                    {alert.details && (
                      <p className="text-xs opacity-75">{alert.details}</p>
                    )}
                  </div>
                  {alert.acknowledged ? (
                    <span className="text-xs bg-green-500/20 text-green-400 px-2 py-1 rounded">
                      Acknowledged
                    </span>
                  ) : (
                    <button
                      className="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded transition-colors"
                    >
                      Acknowledge
                    </button>
                  )}
                </div>
                {alert.anomalies && alert.anomalies.length > 0 && (
                  <div className="text-xs mt-2 space-y-1">
                    {alert.anomalies.slice(0, 3).map((anomaly, idx) => (
                      <div key={idx} className="opacity-75">
                        {new Date(anomaly.timestamp).toLocaleTimeString()}: {anomaly.value.toFixed(2)}
                        (expected: {anomaly.expected.toFixed(2)}, deviation: {(anomaly.deviation * 100).toFixed(1)}%)
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      )}

      {/* Alert Analyses Tab */}
      {activeTab === 'analyses' && (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        {analysesLoading ? (
          <div className="text-center text-gray-400 py-12">Loading analyses...</div>
        ) : analyses.length === 0 ? (
          <div className="text-center text-gray-400 py-12">
            <AlertCircle className="w-12 h-12 mx-auto mb-3 text-gray-600" />
            <p>No alert analyses yet{currentCustomer ? ` for ${currentCustomer}` : ''}.</p>
            <p className="text-sm mt-2">Alerts received from AlertManager will be analyzed and shown here.</p>
            {currentCustomer && webhookConfig && (
              <div className="mt-4">
                <p className="text-sm text-gray-500">Webhook URL:</p>
                <code className="text-xs bg-gray-900 px-2 py-1 rounded text-orange-400">
                  {webhookConfig.webhook_url}
                </code>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {analyses.map((analysis) => (
              <div
                key={analysis.id}
                className="bg-gray-900/50 border border-gray-700 rounded-lg p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <AlertTriangle className="w-4 h-4 text-orange-400" />
                      <span className="font-semibold">{analysis.alert_name}</span>
                      <span className={`px-2 py-1 rounded text-xs ${getSeverityColor(analysis.severity)}`}>
                        {analysis.severity}
                      </span>
                      {analysis.received_at && (
                        <span className="text-xs opacity-75">
                          {formatDistanceToNow(new Date(analysis.received_at), { addSuffix: true })}
                        </span>
                      )}
                    </div>
                    {analysis.summary && (
                      <p className="text-sm text-gray-200">{analysis.summary}</p>
                    )}
                    <div className="text-xs text-gray-500 mt-2">
                      KB matches: {analysis.kb_matches.length > 0
                        ? analysis.kb_matches.map((match) => match.title).join(', ')
                        : 'None'}
                    </div>
                  </div>
                  <button
                    onClick={() => toggleAnalysis(analysis.id)}
                    className="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded transition-colors"
                  >
                    {expandedAnalysisId === analysis.id ? 'Hide' : 'View'} analysis
                  </button>
                </div>

                {expandedAnalysisId === analysis.id && (
                  <div className="mt-4 border-t border-gray-700 pt-4 text-sm text-gray-200 space-y-3">
                    {analysisDetailLoading && (
                      <div className="text-gray-400">Loading analysis details...</div>
                    )}
                    {!analysisDetailLoading && analysisDetail?.id === analysis.id && (
                      <>
                        <div>
                          <div className="text-xs uppercase tracking-wide text-gray-400">Root Cause</div>
                          <div>{analysisDetail.investigation.root_cause_hypothesis}</div>
                        </div>
                        <div>
                          <div className="text-xs uppercase tracking-wide text-gray-400">Impact</div>
                          <div>{analysisDetail.investigation.impact_assessment}</div>
                        </div>
                        <div>
                          <div className="text-xs uppercase tracking-wide text-gray-400">Recommended Actions</div>
                          <ul className="list-disc list-inside space-y-1">
                            {analysisDetail.investigation.recommended_actions.map((action, idx) => (
                              <li key={idx}>{action}</li>
                            ))}
                          </ul>
                        </div>
                        {analysisDetail.investigation.related_evidence.length > 0 && (
                          <div>
                            <div className="text-xs uppercase tracking-wide text-gray-400">Evidence</div>
                            <ul className="list-disc list-inside space-y-1 text-gray-300">
                              {analysisDetail.investigation.related_evidence.map((item, idx) => (
                                <li key={idx}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {analysisDetail.kb_matches.length > 0 && (
                          <div>
                            <div className="text-xs uppercase tracking-wide text-gray-400">Matched KB</div>
                            <ul className="list-disc list-inside space-y-1 text-gray-300">
                              {analysisDetail.kb_matches.map((match, idx) => (
                                <li key={idx}>
                                  {match.title} (score: {match.score})
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        
                        {/* Discuss with Agent Button */}
                        <div className="pt-3 border-t border-gray-700">
                          <button
                            onClick={() => handleDiscussWithAgent(analysisDetail)}
                            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors text-sm font-medium"
                          >
                            <MessageSquare className="w-4 h-4" />
                            Discuss with Agent
                          </button>
                          <p className="text-xs text-gray-500 mt-2">
                            Continue investigation with AI assistance
                          </p>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      )}

      {/* Webhooks Tab */}
      {activeTab === 'webhooks' && (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        {webhooksLoading ? (
          <div className="text-center text-gray-400 py-12">Loading webhook status...</div>
        ) : !webhooksData?.webhooks || webhooksData.webhooks.length === 0 ? (
          <div className="text-center text-gray-400 py-12">
            <Webhook className="w-12 h-12 mx-auto mb-3 text-gray-600" />
            <p>No webhook configurations found.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <div className="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
                <div className="text-sm text-gray-400">Total Customers</div>
                <div className="text-2xl font-bold">{webhooksData.summary.total_customers}</div>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
                <div className="text-sm text-gray-400">Receiving Alerts</div>
                <div className="text-2xl font-bold text-green-400">{webhooksData.summary.customers_with_alerts}</div>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
                <div className="text-sm text-gray-400">Configured</div>
                <div className="text-2xl font-bold text-green-400">{webhooksData.summary.by_status.configured || 0}</div>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
                <div className="text-sm text-gray-400">Pending</div>
                <div className="text-2xl font-bold text-yellow-400">{webhooksData.summary.by_status.pending || webhooksData.summary.by_status.unknown || 0}</div>
              </div>
            </div>

            {/* Webhook List */}
            <div className="space-y-3">
              {webhooksData.webhooks.map((webhook) => (
                <div
                  key={webhook.customer_name}
                  className="bg-gray-900/50 border border-gray-700 rounded-lg p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        {getWebhookStatusIcon(webhook.status)}
                        <span className="font-semibold">{webhook.customer_name}</span>
                        <span className={`px-2 py-0.5 rounded text-xs ${getWebhookStatusColor(webhook.status)}`}>
                          {webhook.status}
                        </span>
                        {webhook.total_alerts_received > 0 && (
                          <span className="text-xs text-green-400">
                            {webhook.total_alerts_received} alerts received
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-400 space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-gray-500">Webhook:</span>
                          <code className="bg-gray-800 px-2 py-0.5 rounded text-orange-400">
                            {webhook.webhook_url}
                          </code>
                          <button
                            onClick={() => copyToClipboard(webhook.webhook_url)}
                            className="text-gray-500 hover:text-gray-300"
                            title="Copy URL"
                          >
                            <Copy className="w-3 h-3" />
                          </button>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-gray-500">AlertManager:</span>
                          <code className="bg-gray-800 px-2 py-0.5 rounded text-blue-400">
                            {webhook.alertmanager_url}
                          </code>
                          <a
                            href={webhook.alertmanager_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-gray-500 hover:text-gray-300"
                            title="Open AlertManager"
                          >
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        </div>
                        {webhook.last_alert_received && (
                          <div>
                            <span className="text-gray-500">Last alert:</span>{' '}
                            {formatDistanceToNow(new Date(webhook.last_alert_received), { addSuffix: true })}
                          </div>
                        )}
                        {webhook.last_error && (
                          <div className="text-red-400">
                            <span className="text-gray-500">Error:</span> {webhook.last_error}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => validateWebhookMutation.mutate(webhook.customer_name)}
                        disabled={validateWebhookMutation.isPending}
                        className="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded transition-colors"
                      >
                        {validateWebhookMutation.isPending ? 'Validating...' : 'Validate'}
                      </button>
                      <button
                        onClick={() => setShowWebhookConfig(
                          showWebhookConfig === webhook.customer_name ? null : webhook.customer_name
                        )}
                        className="text-xs bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded transition-colors"
                      >
                        <Settings className="w-3 h-3 inline mr-1" />
                        Config
                      </button>
                    </div>
                  </div>

                  {/* Configuration Instructions */}
                  {showWebhookConfig === webhook.customer_name && (
                    <div className="mt-4 border-t border-gray-700 pt-4">
                      <div className="text-xs uppercase tracking-wide text-gray-400 mb-2">
                        AlertManager Configuration
                      </div>
                      <pre className="bg-gray-900 p-3 rounded text-xs text-gray-300 overflow-x-auto">
{`# Add to alertmanager.yml receivers section:
receivers:
  - name: 'sm3-webhook'
    webhook_configs:
      - url: '${webhook.webhook_url}'
        send_resolved: true

# Reference in route:
route:
  receiver: 'sm3-webhook'
  routes:
    - match_re:
        severity: critical|major
      receiver: 'sm3-webhook'
      continue: true`}
                      </pre>
                      <button
                        onClick={() => copyToClipboard(`receivers:
  - name: 'sm3-webhook'
    webhook_configs:
      - url: '${webhook.webhook_url}'
        send_resolved: true`)}
                        className="mt-2 text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                      >
                        <Copy className="w-3 h-3" />
                        Copy configuration
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  );
}
