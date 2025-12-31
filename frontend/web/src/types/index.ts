export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
  suggestions?: string[];
  isStreaming?: boolean;
}

export interface ToolCall {
  tool: string;
  arguments: Record<string, any>;
  result?: any;
  duration?: number;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
}

export interface ChatResponse {
  message: string;
  tool_calls?: ToolCall[];
  suggestions?: string[];
}

export interface StreamChunk {
  type: 'start' | 'token' | 'tool' | 'error' | 'complete' | 'done';
  message?: string;
  tool?: string;
  arguments?: Record<string, any>;
  result?: any;
}

export interface Alert {
  id: string;
  timestamp: string;
  target_name: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  summary: string;
  details: string;
  anomalies: Anomaly[];
  acknowledged: boolean;
  acknowledged_at?: string;
  acknowledged_by?: string;
}

export interface AlertAnalysisMatch {
  title: string;
  alert_name?: string | null;
  source_file: string;
  score: number;
  matched_terms: string[];
}

export interface AlertAnalysisInvestigation {
  summary: string;
  root_cause_hypothesis: string;
  impact_assessment: string;
  recommended_actions: string[];
  related_evidence: string[];
  confidence: number;
  investigated_at: string;
}

export interface AlertAnalysisSummary {
  id: string;
  alert_name: string;
  severity: string;
  status: string;
  received_at?: string;
  kb_matches: AlertAnalysisMatch[];
  summary: string;
  confidence: number;
}

export interface AlertAnalysisDetail {
  id: string;
  source: string;
  status: string;
  alert_name: string;
  severity: string;
  received_at: string;
  labels: Record<string, any>;
  annotations: Record<string, any>;
  kb_matches: AlertAnalysisMatch[];
  investigation: AlertAnalysisInvestigation;
  raw_response?: string;
}

export interface Anomaly {
  index: number;
  timestamp: string;
  value: number;
  expected: number;
  deviation: number;
  severity: 'low' | 'medium' | 'high' | 'critical';
  confidence: number;
  method: string;
  context?: Record<string, any>;
}

export interface MonitoringTarget {
  name: string;
  query: string;
  datasource_uid: string;
  query_type: 'prometheus' | 'loki';
  check_interval: number;
  detection_methods: string[];
  severity_threshold: 'low' | 'medium' | 'high' | 'critical';
  enabled: boolean;
  last_check?: string;
  next_check?: string;
}

export interface MonitoringStatus {
  running: boolean;
  targets_count: number;
  enabled_targets: number;
  recent_alerts: number;
  last_check?: string;
}

export interface CacheStats {
  size: number;
  max_size: number;
  hits: number;
  misses: number;
  hit_rate_percent: number;
  evictions: number;
}
