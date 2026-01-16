# Proactive Monitoring & Anomaly Detection

Your agent now includes intelligent proactive monitoring and anomaly detection capabilities!

## 🎯 What It Does

Instead of waiting for users to ask about problems, your agent:
- **Continuously monitors** key metrics and logs
- **Detects anomalies** using multiple statistical methods
- **Alerts proactively** when issues are found
- **Investigates automatically** to understand root causes

## 🔬 Anomaly Detection Methods

### 1. Z-Score (Standard Deviation)
Detects points that are far from the mean.
- **Best for:** Normally distributed data
- **Threshold:** 3 standard deviations (configurable)
- **Example:** CPU spikes 4σ above normal = anomaly

### 2. IQR (Interquartile Range)
More robust to outliers than Z-score.
- **Best for:** Data with outliers
- **Threshold:** 1.5× IQR beyond quartiles
- **Example:** Response time jumps outside normal range

### 3. MAD (Median Absolute Deviation)
Very robust statistical method.
- **Best for:** Highly skewed data
- **Threshold:** 3.5× MAD from median
- **Example:** Error rates with occasional spikes

### 4. Rate of Change
Detects sudden changes.
- **Best for:** Catching rapid shifts
- **Threshold:** 50% change (configurable)
- **Example:** Traffic drops 60% in 5 minutes

## 🚀 Quick Start

### 1. Start Monitoring
```bash
# Start the proactive monitoring system
curl -X POST http://localhost:8000/monitoring/start

# Check status
curl http://localhost:8000/monitoring/status
```

### 2. Configure Targets
```bash
# Create a monitoring target
curl -X POST http://localhost:8000/monitoring/targets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api_error_rate",
    "query": "rate(http_requests_total{status=~\"5..\"}[5m])",
    "datasource_uid": "prometheus-uid",
    "query_type": "prometheus",
    "check_interval": 300,
    "detection_methods": ["zscore", "rate_change"],
    "severity_threshold": "medium",
    "enabled": true
  }'
```

### 3. View Alerts
```bash
# Get recent alerts
curl http://localhost:8000/monitoring/alerts?minutes=60

# Get critical alerts only
curl http://localhost:8000/monitoring/alerts?min_severity=critical
```

## 📊 Default Monitoring Targets

The system comes with sensible defaults (disabled by default):

### 1. Error Rate
```promql
rate(http_requests_total{status=~"5.."}[5m])
```
- **Check interval:** 5 minutes
- **Methods:** Z-score, Rate of change
- **Alerts on:** Unusual error spikes

### 2. Response Time (P95)
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```
- **Check interval:** 5 minutes
- **Methods:** Z-score, IQR
- **Alerts on:** Latency increases

### 3. CPU Usage
```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```
- **Check interval:** 3 minutes
- **Methods:** Z-score, IQR
- **Alerts on:** High CPU

### 4. Memory Usage
```promql
(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100
```
- **Check interval:** 5 minutes
- **Methods:** Z-score
- **Alerts on:** High memory

## 🛠️ API Reference

### Monitoring Control

#### Start Monitoring
```http
POST /monitoring/start
```
Begins continuous monitoring of all enabled targets.

#### Stop Monitoring
```http
POST /monitoring/stop
```
Stops all monitoring checks.

#### Get Status
```http
GET /monitoring/status
```
Returns current monitoring status.

**Response:**
```json
{
  "running": true,
  "targets_count": 4,
  "enabled_targets": 2,
  "total_alerts": 15,
  "recent_alerts": 3,
  "critical_alerts": 1
}
```

### Target Management

#### List Targets
```http
GET /monitoring/targets
```

#### Create Target
```http
POST /monitoring/targets
Content-Type: application/json

{
  "name": "api_error_rate",
  "query": "rate(http_requests_total{status=~\"5..\"}[5m])",
  "datasource_uid": "prometheus-uid",
  "query_type": "prometheus",
  "check_interval": 300,
  "detection_methods": ["zscore", "iqr", "rate_change"],
  "severity_threshold": "medium",
  "enabled": true
}
```

**Parameters:**
- `name`: Unique identifier for the target
- `query`: PromQL or LogQL query
- `datasource_uid`: Datasource UID from Grafana
- `query_type`: "prometheus" or "loki"
- `check_interval`: Seconds between checks
- `detection_methods`: Array of ["zscore", "iqr", "mad", "rate_change"]
- `severity_threshold`: "low", "medium", "high", "critical"
- `enabled`: Boolean

#### Delete Target
```http
DELETE /monitoring/targets/{name}
```

#### Enable/Disable Target
```http
PATCH /monitoring/targets/{name}/enable
PATCH /monitoring/targets/{name}/disable
```

### Alert Management

#### Get Alerts
```http
GET /monitoring/alerts?minutes=60&min_severity=medium&include_acknowledged=false
```

**Response:**
```json
[
  {
    "timestamp": "2025-12-18T19:30:00Z",
    "target_name": "api_error_rate",
    "anomaly_count": 3,
    "severity": "high",
    "acknowledged": false,
    "summary": "🔥 api_error_rate: Detected 3 anomalies using multiple methods"
  }
]
```

#### Acknowledge Alert
```http
POST /monitoring/alerts/{target_name}/acknowledge
```

### Ad-Hoc Analysis

#### Analyze Custom Data
```http
POST /monitoring/analyze
Content-Type: application/json

{
  "metric_name": "custom_metric",
  "data_points": [
    {"timestamp": "2025-12-18T19:00:00Z", "value": 100},
    {"timestamp": "2025-12-18T19:05:00Z", "value": 105},
    {"timestamp": "2025-12-18T19:10:00Z", "value": 250}
  ],
  "methods": ["zscore", "iqr"]
}
```

**Response:**
```json
[
  {
    "timestamp": "2025-12-18T19:10:00Z",
    "value": 250,
    "expected_value": 102.5,
    "deviation": 147.5,
    "severity": "high",
    "method": "zscore",
    "confidence": 0.95
  }
]
```

## 🎯 Use Cases

### 1. Automated Incident Detection
```bash
# Enable error rate monitoring
curl -X PATCH http://localhost:8000/monitoring/targets/error_rate/enable

# System automatically detects error spikes
# Alerts appear in GET /monitoring/alerts
```

### 2. Performance Degradation Detection
```bash
# Monitor response times
curl -X POST http://localhost:8000/monitoring/targets \
  -d '{
    "name": "p99_latency",
    "query": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))",
    ...
  }'
```

### 3. Capacity Planning
```bash
# Monitor resource usage trends
curl -X POST http://localhost:8000/monitoring/targets \
  -d '{
    "name": "disk_usage",
    "query": "disk_used_percent",
    ...
  }'
```

### 4. Custom Alerting
```bash
# Monitor business metrics
curl -X POST http://localhost:8000/monitoring/targets \
  -d '{
    "name": "payment_success_rate",
    "query": "rate(payments_successful[5m]) / rate(payments_total[5m])",
    ...
  }'
```

## 🔔 Notification Integration (Coming Soon)

Future enhancements will add:
- **Slack notifications** - Get alerts in Slack channels
- **Email notifications** - Send alerts via email
- **Webhook integration** - POST alerts to custom endpoints
- **PagerDuty integration** - Create incidents automatically
- **Teams integration** - Alert in Microsoft Teams

To register a callback now (advanced):
```python
from backend.agents.proactive import get_proactive_monitor

async def my_alert_handler(alert):
    print(f"Alert: {alert.target.name} - {alert.severity}")
    # Send notification here

monitor = get_proactive_monitor()
monitor.add_alert_callback(my_alert_handler)
```

## 📈 How It Works

```
┌─────────────────────┐
│  Proactive Monitor  │
│   (Background Loop) │
└──────────┬──────────┘
           │
           ├──> Check Target 1 (every 5 min)
           │    │
           │    ├──> Fetch Prometheus Data
           │    ├──> Detect Anomalies (Z-score, IQR)
           │    └──> Generate Alert (if found)
           │
           ├──> Check Target 2 (every 3 min)
           │    │
           │    ├──> Fetch Loki Logs
           │    ├──> Detect Anomalies (Rate change)
           │    └──> Generate Alert (if found)
           │
           └──> Notify via Callbacks
                │
                ├──> Store in alerts list
                ├──> Log to system
                └──> (Future: Slack, Email, etc.)
```

## 🔍 Example: Complete Workflow

### 1. Setup Monitoring
```bash
# Start monitoring
curl -X POST http://localhost:8000/monitoring/start

# Enable default error rate target
curl -X PATCH http://localhost:8000/monitoring/targets/error_rate/enable
```

### 2. System Detects Anomaly
```
[Background Check]
→ Fetch last hour of error rate data
→ Analyze with Z-score: 5.2σ above mean
→ Severity: HIGH (exceeds threshold of 3σ)
→ Generate Alert
```

### 3. View Alert
```bash
curl http://localhost:8000/monitoring/alerts

# Returns:
{
  "timestamp": "2025-12-18T19:45:00Z",
  "target_name": "error_rate",
  "anomaly_count": 1,
  "severity": "high",
  "summary": "🔥 error_rate: Detected zscore anomaly - value 0.15 (expected 0.02)"
}
```

### 4. Investigate with Agent
```bash
curl -X POST http://localhost:8000/api/chat \
  -d '{
    "message": "I see a high error rate alert. Can you investigate?",
    "session_id": "ops-123"
  }'

# Agent automatically:
# 1. Checks error logs
# 2. Correlates with deployments
# 3. Identifies affected services
# 4. Suggests remediation
```

### 5. Acknowledge Alert
```bash
curl -X POST http://localhost:8000/monitoring/alerts/error_rate/acknowledge
```

## ⚙️ Configuration

### Detection Sensitivity

Adjust thresholds in monitoring targets:

```python
# More sensitive (catches smaller anomalies)
"detection_methods": ["zscore"],  # Use single method
"severity_threshold": "low"       # Alert on low severity

# Less sensitive (only major issues)
"detection_methods": ["zscore", "iqr", "mad"],  # Require multiple methods
"severity_threshold": "high"                     # Only high severity
```

### Check Frequency

Balance between responsiveness and load:

```python
# High-frequency (critical metrics)
"check_interval": 60  # Every minute

# Standard (normal metrics)
"check_interval": 300  # Every 5 minutes

# Low-frequency (trends)
"check_interval": 900  # Every 15 minutes
```

## 📊 Metrics & Observability

The monitoring system itself can be monitored:

```bash
# Check system status
curl http://localhost:8000/monitoring/status

# View all targets and their last check times
curl http://localhost:8000/monitoring/targets

# Count alerts by severity
curl http://localhost:8000/monitoring/alerts | jq 'group_by(.severity) | map({severity: .[0].severity, count: length})'
```

## 🚨 Troubleshooting

### Monitoring not starting?
```bash
# Check logs
docker logs grafana-agent-backend

# Common issues:
# - MCP server not reachable
# - Invalid datasource UIDs
# - Insufficient permissions
```

### No alerts being generated?
```bash
# Check if targets are enabled
curl http://localhost:8000/monitoring/targets

# Verify data is being fetched
# Look for "Checking target" logs

# Lower sensitivity threshold
curl -X PATCH http://localhost:8000/monitoring/targets/error_rate \
  -d '{"severity_threshold": "low"}'
```

### Too many false positives?
```bash
# Increase detection threshold
# Use multiple methods (require agreement)
# Increase check interval
# Adjust severity threshold to "high"
```

## 🎓 Best Practices

1. **Start with defaults** - Enable one target at a time
2. **Tune thresholds** - Adjust based on your baseline
3. **Use multiple methods** - Reduces false positives
4. **Monitor the monitor** - Check `/monitoring/status` regularly
5. **Acknowledge alerts** - Keep alert list clean
6. **Investigate patterns** - Review alerts weekly to tune targets

## 🔮 Future Enhancements

Planned features:
- [ ] Machine learning-based anomaly detection
- [ ] Seasonal pattern recognition
- [ ] Automated root cause analysis
- [ ] Historical anomaly database
- [ ] Alert correlation (group related alerts)
- [ ] Custom detection algorithms
- [ ] Multi-metric anomaly detection
- [ ] Forecast-based alerting

## 📚 More Information

- **Anomaly Detection Code:** `backend/intelligence/anomaly.py`
- **Proactive Monitor:** `backend/agents/proactive.py`
- **API Endpoints:** `backend/api/monitoring.py`
- **Configuration:** Via REST API (no config files needed)

---

**Your agent is now proactively watching your systems!** 🚀
