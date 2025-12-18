import axios from 'axios';
import type {
  ChatRequest,
  ChatResponse,
  Alert,
  MonitoringTarget,
  MonitoringStatus,
  CacheStats,
  StreamChunk
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

// Health API
export const healthApi = {
  check: async (): Promise<{ status: string; service: string }> => {
    const response = await api.get('/health');
    return response.data;
  },
};

export default api;
