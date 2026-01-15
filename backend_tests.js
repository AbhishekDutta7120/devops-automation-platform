// app/backend/tests/api.test.js
const request = require('supertest');
const app = require('../src/index');

describe('API Endpoints', () => {
  describe('GET /health', () => {
    it('should return 200 and health status', async () => {
      const res = await request(app).get('/health');
      expect(res.statusCode).toBe(200);
      expect(res.body).toHaveProperty('status', 'healthy');
      expect(res.body).toHaveProperty('timestamp');
      expect(res.body).toHaveProperty('uptime');
    });
  });

  describe('GET /ready', () => {
    it('should return 200 and ready status', async () => {
      const res = await request(app).get('/ready');
      expect(res.statusCode).toBe(200);
      expect(res.body).toHaveProperty('status', 'ready');
    });
  });

  describe('GET /api/status', () => {
    it('should return API status', async () => {
      const res = await request(app).get('/api/status');
      expect(res.statusCode).toBe(200);
      expect(res.body).toHaveProperty('message');
      expect(res.body).toHaveProperty('status', 'running');
    });
  });

  describe('GET /api/deployments', () => {
    it('should return list of deployments', async () => {
      const res = await request(app).get('/api/deployments');
      expect(res.statusCode).toBe(200);
      expect(Array.isArray(res.body)).toBe(true);
    });
  });

  describe('POST /api/deployments', () => {
    it('should create a new deployment', async () => {
      const newDeployment = {
        environment: 'test',
        status: 'success'
      };
      const res = await request(app)
        .post('/api/deployments')
        .send(newDeployment);
      expect(res.statusCode).toBe(201);
      expect(res.body).toHaveProperty('id');
      expect(res.body).toHaveProperty('environment', 'test');
      expect(res.body).toHaveProperty('status', 'success');
    });
  });

  describe('GET /metrics', () => {
    it('should return Prometheus metrics', async () => {
      const res = await request(app).get('/metrics');
      expect(res.statusCode).toBe(200);
      expect(res.text).toContain('http_requests_total');
    });
  });

  describe('GET /nonexistent', () => {
    it('should return 404 for unknown routes', async () => {
      const res = await request(app).get('/nonexistent');
      expect(res.statusCode).toBe(404);
      expect(res.body).toHaveProperty('error', 'Route not found');
    });
  });
});