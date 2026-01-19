import { ReactNode, useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { MessageSquare, Activity, Github, Server, ChevronDown, Check, Loader2, AlertCircle, Phone, Monitor, RefreshCw } from 'lucide-react';
import { customersApi, grafanaServersApi } from '@/services/api';
import type { CustomerInfo } from '@/types';

interface LayoutProps {
  children: ReactNode;
}

// MCP type icons and colors
const mcpTypeConfig: Record<string, { icon: typeof Server; color: string; label: string }> = {
  grafana: { icon: Activity, color: 'text-orange-400', label: 'Grafana' },
  alertmanager: { icon: AlertCircle, color: 'text-red-400', label: 'Alerts' },
  genesys: { icon: Phone, color: 'text-blue-400', label: 'Genesys' },
};

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const [customers, setCustomers] = useState<CustomerInfo[]>([]);
  const [currentCustomer, setCurrentCustomer] = useState<string | null>(null);
  const [connectedMcps, setConnectedMcps] = useState<string[]>([]);
  const [mcpHealth, setMcpHealth] = useState<Record<string, boolean>>({});
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const [switchProgress, setSwitchProgress] = useState<string>('');
  const [showToolCalls, setShowToolCalls] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem('showToolCalls');
    if (saved !== null) {
      setShowToolCalls(saved === 'true');
    }
  }, []);

  const handleToggleToolCalls = () => {
    setShowToolCalls((prev) => {
      const next = !prev;
      localStorage.setItem('showToolCalls', String(next));
      window.dispatchEvent(new CustomEvent('toolCallsToggle', { detail: next }));
      return next;
    });
  };

  const isActive = (path: string) => location.pathname === path;

  useEffect(() => {
    loadCustomers();
  }, []);

  const loadCustomers = async () => {
    try {
      setIsLoading(true);
      // Try new customers API first, fall back to legacy grafana-servers
      try {
        const response = await customersApi.list();
        setCustomers(response.customers);
        setCurrentCustomer(response.current || response.default || null);
        
        // Load health for current customer
        if (response.current || response.default) {
          loadCustomerHealth(response.current || response.default!);
        }
      } catch {
        // Fall back to legacy API
        const response = await grafanaServersApi.list();
        setCustomers(response.servers.map(s => ({
          name: s.name,
          description: s.description,
          host: s.description,
          mcp_servers: [{ type: 'grafana', url: s.url }]
        })));
        setCurrentCustomer(response.current || response.default || null);
      }
    } catch (error) {
      console.error('Failed to load customers:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const loadCustomerHealth = async (customerName: string) => {
    try {
      const health = await customersApi.getContainerHealth(customerName);
      const healthMap: Record<string, boolean> = {};
      health.containers.forEach(container => {
        healthMap[container.mcp_type] = container.is_healthy;
      });
      setMcpHealth(healthMap);
    } catch (error) {
      console.error('Failed to load customer health:', error);
      setMcpHealth({});
    }
  };

  const handleCustomerSwitch = async (customerName: string) => {
    if (customerName === currentCustomer || isSwitching) return;
    
    try {
      setIsSwitching(true);
      setSwitchProgress('Starting containers...');
      setIsDropdownOpen(false);
      
      const response = await customersApi.switch(customerName);
      
      if (response.success) {
        setCurrentCustomer(customerName);
        setConnectedMcps(response.connected_mcps || []);
        setSwitchProgress('');
        
        // Load health status
        loadCustomerHealth(customerName);
        
        // Dispatch event for other components to know customer changed
        window.dispatchEvent(new CustomEvent('customerSwitch', { 
          detail: { 
            customer: customerName, 
            connectedMcps: response.connected_mcps,
            toolCount: response.tool_count 
          } 
        }));
      } else {
        console.error('Failed to switch customer:', response.message);
        setSwitchProgress(`Error: ${response.message}`);
        setTimeout(() => setSwitchProgress(''), 3000);
      }
    } catch (error) {
      console.error('Error switching customer:', error);
      setSwitchProgress('Connection failed');
      setTimeout(() => setSwitchProgress(''), 3000);
    } finally {
      setIsSwitching(false);
    }
  };

  const handleReconnect = async () => {
    if (!currentCustomer || isSwitching) return;
    
    try {
      setIsSwitching(true);
      setSwitchProgress('Reconnecting...');
      
      const response = await customersApi.reconnect();
      
      if (response.success) {
        setConnectedMcps(response.connected_mcps || []);
        setSwitchProgress('');
        
        // Load health status
        loadCustomerHealth(currentCustomer);
        
        // Dispatch event for other components to know customer reconnected
        window.dispatchEvent(new CustomEvent('customerSwitch', { 
          detail: { 
            customer: currentCustomer, 
            connectedMcps: response.connected_mcps,
            toolCount: response.tool_count 
          } 
        }));
      } else {
        console.error('Failed to reconnect:', response.message);
        setSwitchProgress(`Error: ${response.message}`);
        setTimeout(() => setSwitchProgress(''), 3000);
      }
    } catch (error) {
      console.error('Error reconnecting:', error);
      setSwitchProgress('Reconnect failed');
      setTimeout(() => setSwitchProgress(''), 3000);
    } finally {
      setIsSwitching(false);
    }
  };

  const currentCustomerInfo = customers.find(c => c.name === currentCustomer);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link to="/" className="flex items-center gap-3 text-xl font-bold">
              <img src="/sabio.svg" alt="Sabio" className="h-8 w-auto" />
              <span>Monitoring Agent</span>
            </Link>

            <nav className="flex gap-1">
              <Link
                to="/chat"
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                  isActive('/chat')
                    ? 'bg-blue-600/20 text-blue-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                <MessageSquare className="w-4 h-4" />
                <span>Chat</span>
              </Link>

              <Link
                to="/noc"
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                  isActive('/noc')
                    ? 'bg-blue-600/20 text-blue-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                <Monitor className="w-4 h-4" />
                <span>NOC</span>
              </Link>

              <Link
                to="/monitoring"
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                  isActive('/monitoring')
                    ? 'bg-blue-600/20 text-blue-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                <Activity className="w-4 h-4" />
                <span>Monitoring</span>
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-4">
            {/* Tool Calls Toggle */}
            <button
              type="button"
              onClick={handleToggleToolCalls}
              className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200 transition-colors"
            >
              <span className="uppercase tracking-wide">Tool calls</span>
              <span className="text-gray-300">{showToolCalls ? 'On' : 'Off'}</span>
              <span
                className={`h-4 w-8 rounded-full p-0.5 transition-colors ${showToolCalls ? 'bg-blue-600' : 'bg-gray-700'}`}
              >
                <span
                  className={`block h-3 w-3 rounded-full bg-white transition-transform ${showToolCalls ? 'translate-x-4' : 'translate-x-0'}`}
                />
              </span>
            </button>

            {/* Customer Selector Dropdown */}
            {customers.length > 0 && (
              <div className="relative">
                <button
                  onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                  disabled={isLoading || isSwitching}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors text-sm border border-gray-700"
                >
                  {isSwitching ? (
                    <Loader2 className="w-4 h-4 animate-spin text-orange-400" />
                  ) : (
                    <Server className="w-4 h-4 text-orange-400" />
                  )}
                  <span className="max-w-[150px] truncate">
                    {currentCustomerInfo?.name || 'Select Customer'}
                  </span>
                  {/* Connected MCP indicators with health status */}
                  {connectedMcps.length > 0 && !isSwitching && (
                    <div className="flex gap-1 ml-1">
                      {connectedMcps.map(mcp => {
                        const config = mcpTypeConfig[mcp];
                        if (!config) return null;
                        const Icon = config.icon;
                        const isHealthy = mcpHealth[mcp];
                        const healthColor = isHealthy === true ? 'text-green-400' : isHealthy === false ? 'text-red-400' : config.color;
                        return (
                          <div key={mcp} title={`${config.label}${isHealthy !== undefined ? ` - ${isHealthy ? 'Healthy' : 'Unhealthy'}` : ''}`} className="relative">
                            <Icon className={`w-3 h-3 ${healthColor}`} />
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <ChevronDown className={`w-4 h-4 transition-transform ${isDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {/* Switch progress indicator */}
                {switchProgress && (
                  <div className="absolute right-0 mt-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-400">
                    {switchProgress}
                  </div>
                )}

                {isDropdownOpen && (
                  <>
                    <div 
                      className="fixed inset-0 z-10" 
                      onClick={() => setIsDropdownOpen(false)}
                    />
                    <div className="absolute right-0 mt-2 w-80 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-20 py-1 max-h-96 overflow-y-auto">
                      <div className="px-3 py-2 text-xs text-gray-500 uppercase tracking-wider border-b border-gray-700">
                        Customers
                      </div>
                      {customers.map((customer) => (
                        <button
                          key={customer.name}
                          onClick={() => handleCustomerSwitch(customer.name)}
                          disabled={isSwitching}
                          className={`w-full px-3 py-2 text-left hover:bg-gray-700 transition-colors flex items-start gap-3 ${
                            customer.name === currentCustomer ? 'bg-gray-700/50' : ''
                          }`}
                        >
                          <div className="flex-shrink-0 mt-0.5">
                            {customer.name === currentCustomer ? (
                              <Check className="w-4 h-4 text-green-400" />
                            ) : (
                              <div className="w-4 h-4" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-sm truncate">{customer.name}</span>
                              {/* MCP type badges */}
                              <div className="flex gap-1">
                                {customer.mcp_servers.map(server => {
                                  const config = mcpTypeConfig[server.type];
                                  if (!config) return null;
                                  const Icon = config.icon;
                                  return (
                                    <div key={server.type} title={config.label}>
                                      <Icon className={`w-3 h-3 ${config.color} opacity-60`} />
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                            {customer.description && (
                              <div className="text-xs text-gray-500 truncate">{customer.description}</div>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Reconnect Button */}
            {currentCustomer && (
              <button
                onClick={handleReconnect}
                disabled={isSwitching}
                title="Reconnect MCP containers"
                className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors border border-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw className={`w-4 h-4 text-gray-400 ${isSwitching ? 'animate-spin' : ''}`} />
              </button>
            )}

            <a
              href="https://github.com/grafana/mcp-grafana"
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-400 hover:text-white transition-colors"
            >
              <Github className="w-5 h-5" />
            </a>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="container mx-auto px-4 py-6">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800 mt-12">
        <div className="container mx-auto px-4 py-6 text-center text-gray-500 text-sm">
          <p>Monitoring Agent v0.2.0 - Powered by Sabio</p>
        </div>
      </footer>
    </div>
  );
}
