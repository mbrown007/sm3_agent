import axios from 'axios';
import type {
  ChatRequest,
  ChatResponse,
  Alert,
  AlertAnalysisDetail,
  AlertAnalysisSummary,
  MonitoringTarget,
  MonitoringStatus,
  CacheStats,
  StreamChunk,
  GrafanaServersResponse,
  SwitchServerResponse,
  CustomerContainersHealth,
  CustomersResponse,
  NOCOverview,
  CustomerHealth,
  Datasource,
  CustomerMonitoringTarget,
  CustomerAlert
} from '@/types';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Chat API
export const chatApi = {
  send: async (request: ChatRequest): Promise<ChatResponse> => {
    const response = await api.post<ChatResponse>('/api/chat', request);
    return response.data;
  },

  stream: async function* (request: ChatRequest): AsyncGenerator<StreamChunk> {
    const response = await fetch(`${api.defaults.baseURL}/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const chunk: StreamChunk = JSON.parse(data);
            yield chunk;
          } catch (e) {
            console.error('Failed to parse SSE data:', data);
          }
        }
      }
    }
  },
};

// Monitoring API
export const monitoringApi = {
  getStatus: async (): Promise<MonitoringStatus> => {
    const response = await api.get<MonitoringStatus>('/monitoring/status');
    return response.data;
  },

  start: async (): Promise<{ status: string }> => {
    const response = await api.post('/monitoring/start');
    return response.data;
  },

  stop: async (): Promise<{ status: string }> => {
    const response = await api.post('/monitoring/stop');
    return response.data;
  },

  getTargets: async (): Promise<MonitoringTarget[]> => {
    const response = await api.get<MonitoringTarget[]>('/monitoring/targets');
    return response.data;
  },

  createTarget: async (target: Omit<MonitoringTarget, 'last_check' | 'next_check'>): Promise<MonitoringTarget> => {
    const response = await api.post<MonitoringTarget>('/monitoring/targets', target);
    return response.data;
  },

  deleteTarget: async (name: string): Promise<void> => {
    await api.delete(`/monitoring/targets/${name}`);
  },

  enableTarget: async (name: string): Promise<MonitoringTarget> => {
    const response = await api.patch<MonitoringTarget>(`/monitoring/targets/${name}/enable`);
    return response.data;
  },

  disableTarget: async (name: string): Promise<MonitoringTarget> => {
    const response = await api.patch<MonitoringTarget>(`/monitoring/targets/${name}/disable`);
    return response.data;
  },

  getAlerts: async (params?: { minutes?: number; min_severity?: string }): Promise<Alert[]> => {
    const response = await api.get<Alert[]>('/monitoring/alerts', { params });
    return response.data;
  },

  acknowledgeAlert: async (id: string, acknowledgedBy?: string): Promise<Alert> => {
    const response = await api.post<Alert>(`/monitoring/alerts/${id}/acknowledge`, {
      acknowledged_by: acknowledgedBy,
    });
    return response.data;
  },
};

// Alert Analysis API
export const alertsApi = {
  getAnalyses: async (): Promise<{ count: number; analyses: AlertAnalysisSummary[] }> => {
    const response = await api.get<{ count: number; analyses: AlertAnalysisSummary[] }>(
      '/api/alerts/analyses'
    );
    return response.data;
  },

  getAnalysis: async (analysisId: string): Promise<AlertAnalysisDetail> => {
    const response = await api.get<AlertAnalysisDetail>(`/api/alerts/analyses/${analysisId}`);
    return response.data;
  },

  getWebhookStatuses: async (): Promise<WebhookStatusResponse> => {
    const response = await api.get<WebhookStatusResponse>('/api/alerts/webhook-status');
    return response.data;
  },
};

// Cache API
export const cacheApi = {
  getStats: async (): Promise<CacheStats> => {
    const response = await api.get<CacheStats>('/cache/stats');
    return response.data;
  },

  clear: async (): Promise<{ status: string; entries_removed: number }> => {
    const response = await api.post('/cache/clear');
    return response.data;
  },
};

// MCP Control API
export const mcpApi = {
  getExecutionMode: async (): Promise<{ mode: string; allowlist: string[] }> => {
    const response = await api.get<{ mode: string; allowlist: string[] }>('/api/mcp/execution-mode');
    return response.data;
  },

  setExecutionMode: async (mode: string): Promise<{ mode: string }> => {
    const response = await api.post<{ mode: string }>('/api/mcp/execution-mode', { mode });
    return response.data;
  },
};

// Health API
export const healthApi = {
  check: async (): Promise<{ status: string; service: string }> => {
    const response = await api.get('/health');
    return response.data;
  },
};

// Grafana Servers API (backwards compatibility)
export const grafanaServersApi = {
  list: async (): Promise<GrafanaServersResponse> => {
    const response = await api.get<GrafanaServersResponse>('/api/grafana-servers');
    return response.data;
  },

  switch: async (serverName: string): Promise<SwitchServerResponse> => {
    const response = await api.post<SwitchServerResponse>('/api/grafana-servers/switch', {
      server_name: serverName,
    });
    return response.data;
  },
};

// Customers API (new multi-MCP format)
export const customersApi = {
  list: async (): Promise<CustomersResponse> => {
    const response = await api.get<CustomersResponse>('/api/customers');
    return response.data;
  },

  switch: async (customerName: string): Promise<SwitchServerResponse> => {
    const response = await api.post<SwitchServerResponse>('/api/customers/switch', {
      customer_name: customerName,
    });
    return response.data;
  },

  getContainerHealth: async (customerName: string): Promise<CustomerContainersHealth> => {
    const response = await api.get<CustomerContainersHealth>(`/api/containers/health/${customerName}`);
    return response.data;
  },
};

// Containers API
export const containersApi = {
  getActiveCustomers: async (): Promise<{ active_customers: string[]; max_warm: number; count: number }> => {
    const response = await api.get('/api/containers/active');
    return response.data;
  },

  cleanup: async (): Promise<{ success: boolean; removed_count: number; message?: string }> => {
    const response = await api.post('/api/containers/cleanup');
    return response.data;
  },
};

// NOC Monitoring API (v2 - multi-customer)
export const nocMonitoringApi = {
  // NOC Overview
  getNocOverview: async (): Promise<NOCOverview> => {
    const response = await api.get<NOCOverview>('/monitoring/noc');
    return response.data;
  },

  // Customer-specific status
  getStatus: async (customerName?: string): Promise<MonitoringStatus> => {
    const params = customerName ? { customer_name: customerName } : {};
    const response = await api.get<MonitoringStatus>('/monitoring/status', { params });
    return response.data;
  },

  // Start/Stop monitoring for a customer
  startMonitoring: async (customerName: string): Promise<{ status: string; customer: string }> => {
    const response = await api.post(`/monitoring/start/${customerName}`);
    return response.data;
  },

  stopMonitoring: async (customerName: string): Promise<{ status: string; customer: string }> => {
    const response = await api.post(`/monitoring/stop/${customerName}`);
    return response.data;
  },

  // Datasource discovery
  getDatasources: async (customerName: string): Promise<Datasource[]> => {
    const response = await api.get<Datasource[]>(`/monitoring/datasources/${customerName}`);
    return response.data;
  },

  discoverDatasources: async (customerName: string): Promise<{ status: string; count: number; datasources: Array<{ uid: string; name: string; type: string }> }> => {
    const response = await api.post(`/monitoring/datasources/${customerName}/discover`);
    return response.data;
  },

  // Customer-specific targets
  getTargets: async (customerName?: string): Promise<CustomerMonitoringTarget[]> => {
    const params = customerName ? { customer_name: customerName } : {};
    const response = await api.get<CustomerMonitoringTarget[]>('/monitoring/targets', { params });
    return response.data;
  },

  createTarget: async (customerName: string, target: Omit<MonitoringTarget, 'last_check' | 'next_check'>): Promise<CustomerMonitoringTarget> => {
    const response = await api.post<CustomerMonitoringTarget>(`/monitoring/targets/${customerName}`, target);
    return response.data;
  },

  createDefaultTargets: async (customerName: string, prometheusUid?: string): Promise<{ status: string; customer: string; datasource_uid: string; created_targets: string[] }> => {
    const params = prometheusUid ? { prometheus_uid: prometheusUid } : {};
    const response = await api.post(`/monitoring/targets/${customerName}/defaults`, null, { params });
    return response.data;
  },

  deleteTarget: async (customerName: string, targetName: string): Promise<void> => {
    await api.delete(`/monitoring/targets/${customerName}/${targetName}`);
  },

  enableTarget: async (customerName: string, targetName: string): Promise<{ status: string }> => {
    const response = await api.patch(`/monitoring/targets/${customerName}/${targetName}/enable`);
    return response.data;
  },

  disableTarget: async (customerName: string, targetName: string): Promise<{ status: string }> => {
    const response = await api.patch(`/monitoring/targets/${customerName}/${targetName}/disable`);
    return response.data;
  },

  // Customer-specific alerts
  getAlerts: async (params?: { customer_name?: string; minutes?: number; min_severity?: string; include_acknowledged?: boolean }): Promise<CustomerAlert[]> => {
    const response = await api.get<CustomerAlert[]>('/monitoring/alerts', { params });
    return response.data;
  },

  acknowledgeAlert: async (customerName: string, alertId: string, user?: string): Promise<{ status: string; alert_id: string }> => {
    const response = await api.post(`/monitoring/alerts/${customerName}/${alertId}/acknowledge`, { user });
    return response.data;
  },
};

export default api;
