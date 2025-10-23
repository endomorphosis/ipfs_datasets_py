# Comprehensive MCP Dashboard with GraphRAG Integration

This document describes the comprehensive MCP dashboard that integrates all GraphRAG features from previous prototypes into a single, unified interface.

## Overview

The enhanced MCP dashboard provides a complete suite of tools for:
- **MCP Tool Management**: Discovery, execution, and monitoring of MCP tools
- **GraphRAG Processing**: Advanced website analysis with knowledge graph extraction
- **Analytics Dashboard**: Real-time monitoring and performance metrics
- **RAG Query Interface**: Interactive query system with visualizations
- **Investigation Tools**: Content analysis and investigation capabilities

## Features Integrated

### 1. GraphRAG Processing (`/mcp/graphrag`)
- **Complete Advanced GraphRAG System**: Website processing and analysis
- **Enhanced knowledge extraction**: Multi-pass processing with quality assessment
- **Advanced media processing**: Video/audio transcription and analysis
- **Performance optimization**: Adaptive resource management
- **Real-time progress monitoring**: Live updates for processing sessions

**Usage:**
```bash
# Start GraphRAG processing
curl -X POST http://localhost:8080/api/mcp/graphrag/process \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "mode": "comprehensive"}'

# Check processing status
curl http://localhost:8080/api/mcp/graphrag/sessions/{session_id}
```

### 2. Analytics Dashboard (`/mcp/analytics`)
- **Real-time processing monitoring**: Live updates and status tracking
- **Content quality assessment**: Scoring and quality metrics
- **Performance analytics**: Trend analysis and optimization insights
- **User behavior analytics**: Usage patterns and system efficiency
- **Interactive visualizations**: Charts and graphs using Plotly

**Key Metrics:**
- Total websites processed
- Success rates and failure analysis
- Average processing times
- Query performance metrics
- System resource utilization

### 3. RAG Query Interface (`/mcp/rag`)
- **Interactive query execution**: Real-time query processing
- **Context-aware responses**: Enhanced with domain-specific knowledge
- **Visualization capabilities**: Query result visualization
- **Historical query tracking**: Session management and history

**Usage:**
```bash
# Execute RAG query
curl -X POST http://localhost:8080/api/mcp/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the main topics?", "context": {"domain": "technology"}}'
```

### 4. Investigation Tools (`/mcp/investigation`)
- **Content analysis**: Comprehensive content investigation
- **Entity extraction**: Identification of key entities and relationships
- **Sentiment analysis**: Content sentiment evaluation
- **Credibility assessment**: Source credibility scoring
- **Multi-format support**: Articles, documents, multimedia content

**Analysis Types:**
- `comprehensive`: Full analysis with all features
- `entity_extraction`: Focus on entity identification
- `sentiment_analysis`: Sentiment and tone analysis
- `credibility_check`: Source credibility evaluation

## Configuration

### Basic Configuration
```python
from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig

config = MCPDashboardConfig(
    host="0.0.0.0",
    port=8080,
    mcp_server_port=8001,
    enable_graphrag=True,
    enable_analytics=True,
    enable_rag_query=True,
    enable_investigation=True,
    enable_real_time_monitoring=True
)

dashboard = MCPDashboard()
dashboard.configure(config)
dashboard.start()
```

### Environment Variables
```bash
export MCP_DASHBOARD_HOST=0.0.0.0
export MCP_DASHBOARD_PORT=8080
export MCP_DASHBOARD_BLOCKING=1  # For blocking mode
```

## API Endpoints

### Core MCP Endpoints
- `GET /api/mcp/status` - Comprehensive system status
- `GET /api/mcp/tools` - Available MCP tools
- `POST /api/mcp/tools/{category}/{tool}/execute` - Execute tool

### GraphRAG Endpoints
- `POST /api/mcp/graphrag/process` - Start GraphRAG processing
- `GET /api/mcp/graphrag/sessions` - List processing sessions
- `GET /api/mcp/graphrag/sessions/{id}` - Get session status

### Analytics Endpoints
- `GET /api/mcp/analytics/metrics` - Current analytics metrics
- `GET /api/mcp/analytics/history` - Metrics history

### RAG Query Endpoints
- `POST /api/mcp/rag/query` - Execute RAG query

### Investigation Endpoints
- `POST /api/mcp/investigation/analyze` - Start content investigation

## JavaScript SDK

The enhanced MCP JavaScript SDK provides convenient access to all features:

```javascript
// Initialize client
const client = new MCPClient('http://localhost:8080/api/mcp');

// Start GraphRAG processing
const session = await client.startGraphRAGProcessing('https://example.com', 'comprehensive');

// Execute RAG query
const result = await client.executeRAGQuery('What are the main topics?', {domain: 'technology'});

// Start investigation
const investigation = await client.startInvestigation('https://example.com/article', 'comprehensive');

// Real-time monitoring
const stopPolling = client.startStatusPolling(5000, (error, status) => {
    if (error) {
        console.error('Status update failed:', error);
    } else {
        console.log('System status:', status);
    }
});
```

## Web Interface

### Main Dashboard (`/mcp`)
- **System Status Overview**: Real-time status monitoring
- **Feature Navigation**: Quick access to all dashboard sections
- **Tool Discovery**: Browse and execute MCP tools
- **Execution History**: View recent tool executions

### GraphRAG Dashboard (`/mcp/graphrag`)
- **Processing Interface**: Start new GraphRAG processing sessions
- **Session Management**: Monitor active and completed sessions
- **Progress Tracking**: Real-time progress updates
- **Results Visualization**: View processing results and insights

### Analytics Dashboard (`/mcp/analytics`)
- **Performance Metrics**: Key performance indicators
- **Trend Analysis**: Historical performance trends
- **Interactive Charts**: Real-time updating visualizations
- **Export Capabilities**: Download reports and metrics

### RAG Query Dashboard (`/mcp/rag`)
- **Query Interface**: Execute natural language queries
- **Context Management**: Specify query context and parameters
- **Result Display**: Formatted query results with confidence scores
- **Query History**: Track previous queries and results

### Investigation Dashboard (`/mcp/investigation`)
- **Content Analysis**: Analyze URLs and content
- **Investigation Types**: Choose analysis focus
- **Results Summary**: Comprehensive investigation findings
- **Export Reports**: Download investigation results

## Integration with Previous Prototypes

This implementation integrates features from:

1. **Complete Advanced GraphRAG** (`complete_advanced_graphrag.py`)
   - Advanced web archiving and processing
   - Multi-service support and optimization
   - Comprehensive reporting capabilities

2. **Enhanced GraphRAG Integration** (`enhanced_graphrag_integration.py`)
   - Advanced knowledge extraction
   - Performance optimization
   - Quality assessment and monitoring

3. **Advanced Analytics Dashboard** (`advanced_analytics_dashboard.py`)
   - Real-time monitoring
   - Performance analytics
   - Quality metrics and trending

4. **RAG Query Dashboard** (`rag/rag_query_dashboard.py`)
   - Interactive query interface
   - Visualization capabilities
   - Real-time updates

5. **Investigation Dashboard** (`mcp_investigation_dashboard.py`)
   - Content analysis tools
   - Investigation workflows
   - Results reporting

## Deployment

### Development Mode
```bash
python -m ipfs_datasets_py.mcp_dashboard
```

### Production Mode
```bash
export MCP_DASHBOARD_BLOCKING=1
python -m ipfs_datasets_py.mcp_dashboard
```

### Docker Deployment
```bash
# Build image
docker build -f ipfs_datasets_py/mcp_server/Dockerfile -t ipfs-datasets-mcp .

# Run dashboard
docker run -d -p 8080:8080 \
  -e MCP_DASHBOARD_HOST=0.0.0.0 \
  -e MCP_DASHBOARD_PORT=8080 \
  ipfs-datasets-mcp python -m ipfs_datasets_py.mcp_dashboard
```

## Screenshots and Examples

The dashboard provides a modern, responsive interface with:
- **Unified navigation** between all features
- **Real-time status indicators** with live updates
- **Interactive visualizations** using Plotly and Bootstrap
- **Mobile-responsive design** for all screen sizes
- **Comprehensive tool discovery** with search and filtering
- **Detailed execution results** with JSON formatting

## Troubleshooting

### Common Issues

1. **Import Errors**: Some GraphRAG components may not be available if dependencies are missing. The system gracefully falls back to mock implementations.

2. **Port Conflicts**: Ensure ports 8080 (dashboard) and 8001 (MCP server) are available.

3. **Performance**: For large-scale GraphRAG processing, consider adjusting resource limits in the configuration.

### Debug Mode
```bash
export MCP_DASHBOARD_BLOCKING=1
python -m ipfs_datasets_py.mcp_dashboard
```

This will run the dashboard in blocking mode with detailed error messages.

## Next Steps

This comprehensive dashboard provides a foundation for:
- **Enhanced visualization** with more advanced charting
- **Workflow automation** for common processing tasks
- **Advanced reporting** with custom report generation
- **Multi-user support** with authentication and permissions
- **Integration with external systems** via webhooks and APIs

The dashboard is designed to be extensible and can be enhanced with additional GraphRAG features as they are developed.