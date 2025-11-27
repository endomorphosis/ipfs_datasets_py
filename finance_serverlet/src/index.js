/**
 * Finance Data Serverlet
 * 
 * A self-contained lightweight Node.js server for financial data collection
 * with multi-source integrity validation.
 * 
 * Features:
 * - SQLite local storage for persistence
 * - HTTP REST API for data access
 * - Multiple data sources (Yahoo Finance, Binance, TradingView, Webull)
 * - Cross-source data integrity validation
 */

import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { initDatabase, closeDatabase } from './db/index.js';
import routes from './api/routes.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Configuration
const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '0.0.0.0';
const DB_PATH = process.env.DB_PATH || path.join(__dirname, '..', 'data', 'finance.db');

// Create Express app
const app = express();

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// CORS middleware (permissive for development)
app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
    if (req.method === 'OPTIONS') {
        return res.sendStatus(200);
    }
    next();
});

// Request logging
app.use((req, res, next) => {
    const start = Date.now();
    res.on('finish', () => {
        const duration = Date.now() - start;
        console.log(`${req.method} ${req.path} ${res.statusCode} ${duration}ms`);
    });
    next();
});

// API routes
app.use('/api', routes);

// Root endpoint with API documentation
app.get('/', (req, res) => {
    res.json({
        name: 'Finance Data Serverlet',
        version: '1.0.0',
        description: 'Lightweight financial data server with multi-source integrity validation',
        endpoints: {
            health: 'GET /api/health',
            symbols: {
                list: 'GET /api/symbols',
                create: 'POST /api/symbols',
                get: 'GET /api/symbols/:symbol'
            },
            sources: 'GET /api/sources',
            data: {
                ohlcv: 'GET /api/ohlcv/:symbol',
                fetch: 'POST /api/fetch/:symbol',
                price: 'GET /api/price/:symbol'
            },
            integrity: {
                validate: 'POST /api/validate/:symbol',
                history: 'GET /api/integrity/:symbol',
                validateAndFetch: 'POST /api/validate-and-fetch/:symbol'
            },
            search: 'GET /api/search?q=query'
        },
        dataSources: ['yahoo_finance', 'binance', 'tradingview', 'webull']
    });
});

// Error handling middleware
app.use((err, req, res, _next) => {
    console.error('Error:', err);
    res.status(500).json({
        success: false,
        error: err.message || 'Internal server error'
    });
});

// 404 handler
app.use((req, res) => {
    res.status(404).json({
        success: false,
        error: 'Not found',
        path: req.path
    });
});

// Graceful shutdown
function shutdown() {
    console.log('\nShutting down gracefully...');
    closeDatabase();
    process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// Initialize and start server
async function start() {
    try {
        // Initialize database
        console.log('Initializing database...');
        initDatabase(DB_PATH);
        
        // Start server
        app.listen(PORT, HOST, () => {
            console.log(`
╔════════════════════════════════════════════════════════════╗
║           Finance Data Serverlet v1.0.0                    ║
╠════════════════════════════════════════════════════════════╣
║  Server running at http://${HOST}:${PORT}                      ║
║                                                            ║
║  Data Sources:                                             ║
║    • Yahoo Finance                                         ║
║    • Binance                                               ║
║    • TradingView                                           ║
║    • Webull                                                ║
║                                                            ║
║  Endpoints:                                                ║
║    GET  /api/health            - Health check              ║
║    GET  /api/symbols           - List symbols              ║
║    POST /api/symbols           - Add symbol                ║
║    GET  /api/ohlcv/:symbol     - Get OHLCV data           ║
║    POST /api/fetch/:symbol     - Fetch from sources        ║
║    GET  /api/price/:symbol     - Current prices            ║
║    POST /api/validate/:symbol  - Validate integrity        ║
║    POST /api/validate-and-fetch/:symbol - Full pipeline    ║
║                                                            ║
║  Database: ${DB_PATH.substring(0, 40)}...
╚════════════════════════════════════════════════════════════╝
            `);
        });
    } catch (error) {
        console.error('Failed to start server:', error);
        process.exit(1);
    }
}

start();

export default app;
