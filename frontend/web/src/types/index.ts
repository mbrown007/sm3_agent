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
  customer_name?: string;
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

// Grafana Server types
export interface GrafanaServer {
  name: string;
  url: string;
  description: string;
}

export interface GrafanaServersResponse {
  servers: GrafanaServer[];
  current: string | null;
  default: string | null;
}

export interface SwitchServerResponse {
  success: boolean;
  server_name: string;
  server_url?: string;
  message: string;
  mcp_server_count?: number;
  connected_mcps?: string[];
  failed_mcps?: string[];
  tool_count?: number;
  is_starting?: boolean;
}

// Container health types
export interface ContainerHealthStatus {
  mcp_type: string;
  is_healthy: boolean;
  state: string;
  container_name: string;
  port?: number;
  url: string;
  error_message?: string;
}

export interface CustomerContainersHealth {
  customer_name: string;
  all_healthy: boolean;
  containers: ContainerHealthStatus[];
}

// Customer types (new multi-MCP format)
export interface MCPServerInfo {
  type: string;
  url: string;
}

export interface CustomerInfo {
  name: string;
  description: string;
  host: string;
  has_genesys?: boolean;
  mcp_servers: MCPServerInfo[];
}

export interface CustomersResponse {
  customers: CustomerInfo[];
  current: string | null;
  default: string | null;
}

// NOC Dashboard types (multi-customer monitoring)
export interface CustomerHealth {
  customer_name: string;
  is_monitoring: boolean;
  targets_count: number;
  enabled_targets: number;
  total_alerts: number;
  critical_alerts: number;
  warning_alerts: number;
  last_check?: string;
  status: 'healthy' | 'warning' | 'critical' | 'unknown';
}

export interface NOCOverview {
  total_customers: number;
  monitoring_customers: number;
  healthy_count: number;
  warning_count: number;
  critical_count: number;
  unknown_count: number;
  customers: CustomerHealth[];
}

export interface Datasource {
  uid: string;
  name: string;
  type: string;
  url?: string;
  is_default: boolean;
}

export interface CustomerMonitoringTarget extends MonitoringTarget {
  customer_name: string;
  last_error?: string;
}

export interface CustomerAlert extends Alert {
  customer_name: string;
}

// Webhook Status types
export interface CustomerWebhookStatus {
  customer_name: string;
  webhook_url: string;
  last_alert_received: string | null;
  total_alerts_received: number;
  pending_analyses: number;
  completed_analyses: number;
  last_analysis_completed: string | null;
  mcp_containers_ready: boolean;
  analysis_files: number;
  errors: string[];
}

export interface WebhookStatusResponse {
  customers: CustomerWebhookStatus[];
  total_customers: number;
  customers_with_alerts: number;
}
