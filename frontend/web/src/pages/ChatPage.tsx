import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Loader2, Wrench } from 'lucide-react';
import { chatApi } from '@/services/api';
import { MarkdownContent } from '@/components/MarkdownContent';
import { Artifact, parseArtifacts } from '@/components/Artifact';
import type { Message, ToolCall } from '@/types';

interface AlertAnalysisContext {
  analysisId: string;
  alertName: string;
  severity: string;
  customerName?: string;
  message: string;
  timestamp: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const [showToolCalls, setShowToolCalls] = useState(true);
  const [pendingContext, setPendingContext] = useState<AlertAnalysisContext | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const hasProcessedContext = useRef(false);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    const saved = localStorage.getItem('showToolCalls');
    if (saved !== null) {
      setShowToolCalls(saved === 'true');
    }

    // Listen for toggle events from Layout header
    const handleToolCallsToggle = (e: CustomEvent) => {
      setShowToolCalls(e.detail);
    };
    window.addEventListener('toolCallsToggle', handleToolCallsToggle as EventListener);
    return () => window.removeEventListener('toolCallsToggle', handleToolCallsToggle as EventListener);
  }, []);

  // Check for alert analysis context from MonitoringPage
  useEffect(() => {
    if (hasProcessedContext.current) return;
    
    const contextStr = sessionStorage.getItem('alertAnalysisContext');
    if (contextStr) {
      try {
        const context: AlertAnalysisContext = JSON.parse(contextStr);
        // Clear it immediately to prevent re-processing
        sessionStorage.removeItem('alertAnalysisContext');
        hasProcessedContext.current = true;
        
        // Set the context to trigger auto-send
        setPendingContext(context);
      } catch (e) {
        console.error('Failed to parse alert context:', e);
        sessionStorage.removeItem('alertAnalysisContext');
      }
    }
  }, []);

  // Auto-send message when context is set
  useEffect(() => {
    if (pendingContext && !isLoading && messages.length === 0) {
      // Trigger send with the context message
      sendMessage(pendingContext.message);
      setPendingContext(null);
    }
  }, [pendingContext, isLoading, messages.length]);

  const sendMessage = useCallback(async (messageText: string) => {
    if (!messageText.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // Create assistant message placeholder
      const assistantMessageId = `${Date.now()}-assistant`;
      const assistantMessage: Message = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        isStreaming: true,
        toolCalls: [],
        suggestions: [],
      };

      setMessages((prev) => [...prev, assistantMessage]);

      let accumulatedContent = '';
      let toolCalls: ToolCall[] = [];
      let suggestions: string[] = [];

      // Stream the response
      for await (const chunk of chatApi.stream({
        message: messageText,
        session_id: sessionId,
      })) {
        console.log('[DEBUG] Received chunk:', chunk.type, chunk);
        
        if (chunk.type === 'token' && chunk.message) {
          console.log('[DEBUG] Token chunk length:', chunk.message.length, 'accumulated so far:', accumulatedContent.length);
          accumulatedContent += chunk.message;
          console.log('[DEBUG] New accumulated length:', accumulatedContent.length);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: accumulatedContent }
                : msg
            )
          );
        } else if (chunk.type === 'tool') {
          const toolCall: ToolCall = {
            tool: chunk.tool || 'unknown',
            arguments: chunk.arguments || {},
            result: chunk.result,
          };
          toolCalls.push(toolCall);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, toolCalls: [...toolCalls] }
                : msg
            )
          );
        } else if (chunk.type === 'complete') {
          // Only use complete.message as fallback if no tokens were received
          if (chunk.message && accumulatedContent.trim().length === 0) {
            console.log('[DEBUG] No tokens received, using complete.message as fallback');
            accumulatedContent = chunk.message;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId
                  ? { ...msg, content: accumulatedContent }
                  : msg
              )
            );
          } else {
            console.log('[DEBUG] Keeping accumulated content from tokens:', accumulatedContent.length);
          }
        } else if (chunk.type === 'error') {
          accumulatedContent = `Error: ${chunk.message || 'An error occurred'}`;
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: accumulatedContent }
                : msg
            )
          );
        }
      }

      // Mark streaming as complete
      console.log('[DEBUG] Streaming complete. Final accumulated content length:', accumulatedContent.length);
      console.log('[DEBUG] Tool calls count:', toolCalls.length);
      
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, isStreaming: false, suggestions }
            : msg
        )
      );
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: Message = {
        id: `${Date.now()}-error`,
        role: 'assistant',
        content: 'Sorry, an error occurred while processing your request. Please try again.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, sessionId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    await sendMessage(input);
  };

  const handleSuggestionClick = (suggestion: string) => {
    setInput(suggestion);
  };

  return (
    <div className="h-[calc(100vh-12rem)] flex flex-col">
      <div className="flex-1 overflow-y-auto space-y-4 pb-4 pt-2">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-center">
            <div>
              <h2 className="text-2xl font-bold mb-2">Welcome to Sabio Monitoring Agent</h2>
              <p className="text-gray-400 mb-6">
                Ask me anything about your monitoring dashboards, metrics, and logs.
              </p>
              <div className="flex flex-wrap gap-2 justify-center max-w-4xl">
                {[
                  'Show me all active alerts in order of priority',
                  'Show me recently resolved alerts that alerted the same time the previous day',
                  'Show me all linux servers with swap higher than 70%',
                  'Review API usage metrics for this Genesys Cloud monitoring instance, highlight anything of concern, look back over last 10 days',
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => handleSuggestionClick(suggestion)}
                    className="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm transition-colors text-left"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-3xl rounded-lg px-4 py-3 ${
                  message.role === 'user'
                    ? 'bg-blue-600/20 text-white'
                    : 'bg-gray-800 text-gray-100'
                }`}
              >
                {message.role === 'user' ? (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                ) : (
                  <>
                    {/* Parse artifacts and render separately */}
                    {(() => {
                      const { artifacts, remainingContent } = parseArtifacts(message.content);
                      return (
                        <>
                          {remainingContent && <MarkdownContent content={remainingContent} />}
                          {artifacts.map((artifact, idx) => (
                            <Artifact 
                              key={idx} 
                              content={`\`\`\`artifact\n${JSON.stringify(artifact)}\n\`\`\``} 
                              className="mt-3" 
                            />
                          ))}
                        </>
                      );
                    })()}
                  </>
                )}

                {/* Tool calls */}
                {showToolCalls && message.toolCalls && message.toolCalls.length > 0 && (
                  <details className="mt-3 bg-gray-900/40 border border-gray-700 rounded">
                    <summary className="cursor-pointer select-none px-3 py-2 text-xs text-gray-300 flex items-center gap-2">
                      <Wrench className="w-3 h-3 text-blue-400" />
                      <span className="uppercase tracking-wide">
                        Tool calls ({message.toolCalls.length})
                      </span>
                    </summary>
                    <div className="px-3 pb-3 space-y-2">
                      {message.toolCalls.map((toolCall, idx) => (
                        <div
                          key={idx}
                          className="bg-gray-900/50 border border-gray-700 rounded p-2 text-sm"
                        >
                          <div className="flex items-center gap-2 text-blue-400 mb-1">
                            <Wrench className="w-3 h-3" />
                            <span className="font-mono">{toolCall.tool}</span>
                          </div>
                          {toolCall.result && (
                            <div className="text-xs text-gray-400 mt-1 max-h-32 overflow-y-auto">
                              <pre className="whitespace-pre-wrap break-words">
                                {typeof toolCall.result === 'string'
                                  ? toolCall.result
                                  : JSON.stringify(toolCall.result, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                {/* Suggestions */}
                {message.suggestions && message.suggestions.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {message.suggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs transition-colors"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                )}

                <div className="text-xs text-gray-500 mt-2 flex items-center gap-2">
                  <span>{message.timestamp.toLocaleTimeString()}</span>
                  {message.isStreaming && (
                    <span className="flex items-center gap-1">
                      <span className="animate-pulse">●</span>
                      <span>streaming</span>
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
        {isLoading && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-lg px-4 py-3">
              <Loader2 className="w-5 h-5 animate-spin text-blue-400" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your monitoring metrics, dashboards, or logs..."
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 focus:outline-none focus:border-blue-500 transition-colors"
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-lg px-6 py-3 transition-colors flex items-center gap-2"
        >
          <Send className="w-5 h-5" />
          <span>Send</span>
        </button>
      </form>
    </div>
  );
}
