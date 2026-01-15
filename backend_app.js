// app/backend/src/index.js
const express = require('express');
const cors = require('cors');
const prometheus = require('prom-client');

const app = express();
const PORT = process.env.PORT || 3000;

// Prometheus metrics
const register = new prometheus.Registry();
prometheus.collectDefaultMetrics({ register });

const httpRequestDuration = new prometheus.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register]
});

const httpRequestTotal = new prometheus.Counter({
  name: 'http_requests_total',
  help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register]
});

// Middleware
app.use(cors());
app.use(express.json());

// Metrics middleware
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = (Date.now() - start) / 1000;
    httpRequestDuration.labels(req.method, req.route?.path || req.path, res.statusCode).observe(duration);
    httpRequestTotal.labels(req.method, req.route?.path || req.path, res.statusCode).inc();
  });
  next();
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
    environment: process.env.NODE_ENV || 'development',
    version: process.env.APP_VERSION || '1.0.0'
  });
});

// Readiness check endpoint
app.get('/ready', (req, res) => {
  // Add database connectivity check here if needed
  res.status(200).json({
    status: 'ready',
    timestamp: new Date().toISOString()
  });
});

// Metrics endpoint for Prometheus
app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

// API Routes
app.get('/api/status', (req, res) => {
  res.json({
    message: 'DevOps Automation Platform API',
    status: 'running',
    timestamp: new Date().toISOString()
  });
});

// Sample data endpoint
let deployments = [
  { id: 1, environment: 'dev', status: 'success', timestamp: new Date().toISOString() },
  { id: 2, environment: 'staging', status: 'success', timestamp: new Date().toISOString() },
  { id: 3, environment: 'production', status: 'success', timestamp: new Date().toISOString() }
];

app.get('/api/deployments', (req, res) => {
  res.json(deployments);
});

app.post('/api/deployments', (req, res) => {
  const { environment, status } = req.body;
  const newDeployment = {
    id: deployments.length + 1,
    environment,
    status,
    timestamp: new Date().toISOString()
  };
  deployments.push(newDeployment);
  res.status(201).json(newDeployment);
});

app.get('/api/deployments/:id', (req, res) => {
  const deployment = deployments.find(d => d.id === parseInt(req.params.id));
  if (!deployment) {
    return res.status(404).json({ error: 'Deployment not found' });
  }
  res.json(deployment);
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({
    error: 'Internal Server Error',
    message: process.env.NODE_ENV === 'development' ? err.message : undefined
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Route not found' });
});

// Start server
const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`🚀 Server running on port ${PORT}`);
  console.log(`📊 Metrics available at http://localhost:${PORT}/metrics`);
  console.log(`💚 Health check at http://localhost:${PORT}/health`);
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM signal received: closing HTTP server');
  server.close(() => {
    console.log('HTTP server closed');
    process.exit(0);
  });
});

module.exports = app;