# Grafana Chat Agent - Web UI

Modern React-based web interface for the Grafana MCP Chat Agent.

## Features

- **Chat Interface** - Interactive chat with the AI agent
- **Real-time Streaming** - Server-Sent Events for live responses
- **Proactive Monitoring** - Dashboard for monitoring targets and alerts
- **Cache Management** - View and manage cache statistics
- **Responsive Design** - Works on desktop and mobile devices

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Styling
- **React Router** - Navigation
- **TanStack Query** - Data fetching and caching
- **Axios** - HTTP client
- **Lucide React** - Icons

## Getting Started

### Prerequisites

- Node.js 18+ and npm
- Backend server running on `http://localhost:8000`

### Installation

```bash
# Install dependencies
npm install

# Copy environment variables
cp .env.example .env

# Start development server
npm run dev
```

The app will be available at `http://localhost:3000`.

### Environment Variables

Create a `.env` file:

```env
VITE_API_URL=http://localhost:8000
```

## Development

```bash
# Start dev server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

## Project Structure

```
src/
├── components/     # Reusable UI components
│   └── Layout.tsx  # Main layout with navigation
├── pages/          # Page components
│   ├── ChatPage.tsx       # Chat interface
│   └── MonitoringPage.tsx # Monitoring dashboard
├── services/       # API clients and services
│   └── api.ts      # Backend API client
├── types/          # TypeScript type definitions
│   └── index.ts    # Shared types
├── hooks/          # Custom React hooks
├── App.tsx         # Root component
├── main.tsx        # Entry point
└── index.css       # Global styles
```

## API Integration

The frontend communicates with the FastAPI backend through:

- **Chat API** - `/api/chat` (POST) and `/api/chat/stream` (SSE)
- **Monitoring API** - `/monitoring/*` endpoints
- **Cache API** - `/cache/*` endpoints
- **Health Check** - `/health`
- **Metrics** - `/metrics` (Prometheus format)

All API calls are proxied through Vite during development (see `vite.config.ts`).

## Features Roadmap

### Current (v0.2.0)
- [x] Basic UI foundation
- [x] Layout and navigation
- [x] Chat page (placeholder)
- [x] Monitoring page (placeholder)

### Next Steps
- [ ] Implement chat functionality with backend
- [ ] Add streaming support for real-time responses
- [ ] Build monitoring dashboard with live data
- [ ] Display alerts and anomalies
- [ ] Add cache statistics view
- [ ] Show tool call results in chat
- [ ] Display suggested follow-up questions

## Contributing

1. Follow the existing code style
2. Use TypeScript for all new code
3. Add types for all API responses
4. Test components before committing

## License

Same as the main project.
