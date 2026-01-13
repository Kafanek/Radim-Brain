#!/usr/bin/env node

/**
 * Radim Brain MCP Server
 * Kompletní integrace Radim Brain API pro Claude Desktop
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool
} from '@modelcontextprotocol/sdk/types.js';
import axios, { AxiosInstance } from 'axios';

const RADIM_BRAIN_URL = process.env.RADIM_BRAIN_URL || 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com';
const API_TIMEOUT = 30000;

class RadimBrainClient {
  private client: AxiosInstance;

  constructor(baseURL: string) {
    this.client = axios.create({
      baseURL,
      timeout: API_TIMEOUT,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  async getHealth() {
    const response = await this.client.get('/health');
    return response.data;
  }

  async listSeniors(params?: any) {
    const response = await this.client.get('/api/seniors', { params });
    return response.data;
  }

  async getSenior(seniorId: string) {
    const response = await this.client.get(`/api/seniors/${seniorId}`);
    return response.data;
  }

  async getVitalsSummary(seniorId: string) {
    const response = await this.client.get(`/api/iot/sensors/${seniorId}/vitals`);
    return response.data;
  }

  async getIoTSystemStatus() {
    const response = await this.client.get('/api/iot/system/status');
    return response.data;
  }

  async smartChat(message: string, userId: string = 'claude-desktop') {
    const response = await this.client.post('/kal/gemini/smart-chat', { message, user_id: userId });
    return response.data;
  }

  async predictHealthCrisis(seniorId: string) {
    const response = await this.client.post('/api/radim/predict/health-crisis', { senior_id: seniorId });
    return response.data;
  }
}

const tools: Tool[] = [
  {
    name: 'radim_list_seniors',
    description: 'Seznam všech seniorů v systému',
    inputSchema: {
      type: 'object',
      properties: {
        status: { type: 'string', enum: ['ok', 'warning', 'critical'] },
        room: { type: 'string' }
      }
    }
  },
  {
    name: 'radim_get_senior',
    description: 'Detail konkrétního seniora',
    inputSchema: {
      type: 'object',
      properties: {
        senior_id: { type: 'string' }
      },
      required: ['senior_id']
    }
  },
  {
    name: 'radim_get_vitals',
    description: 'Vitální funkce seniora',
    inputSchema: {
      type: 'object',
      properties: {
        senior_id: { type: 'string' }
      },
      required: ['senior_id']
    }
  },
  {
    name: 'radim_iot_status',
    description: 'Status IoT systému',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'radim_smart_chat',
    description: 'Inteligentní chat s Radimem',
    inputSchema: {
      type: 'object',
      properties: {
        message: { type: 'string' }
      },
      required: ['message']
    }
  },
  {
    name: 'radim_predict_crisis',
    description: 'Predikce zdravotní krize',
    inputSchema: {
      type: 'object',
      properties: {
        senior_id: { type: 'string' }
      },
      required: ['senior_id']
    }
  },
  {
    name: 'radim_health_check',
    description: 'Health check Radim Brain',
    inputSchema: { type: 'object', properties: {} }
  }
];

const server = new Server(
  { name: 'radim-brain-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

const client = new RadimBrainClient(RADIM_BRAIN_URL);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    let result: any;

    switch (name) {
      case 'radim_list_seniors':
        result = await client.listSeniors(args);
        break;
      case 'radim_get_senior':
        result = await client.getSenior((args as any).senior_id);
        break;
      case 'radim_get_vitals':
        result = await client.getVitalsSummary((args as any).senior_id);
        break;
      case 'radim_iot_status':
        result = await client.getIoTSystemStatus();
        break;
      case 'radim_smart_chat':
        result = await client.smartChat((args as any).message);
        break;
      case 'radim_predict_crisis':
        result = await client.predictHealthCrisis((args as any).senior_id);
        break;
      case 'radim_health_check':
        result = await client.getHealth();
        break;
      default:
        return {
          content: [{ type: 'text', text: `Neznámý nástroj: ${name}` }],
          isError: true
        };
    }

    return {
      content: [{ type: 'text', text: JSON.stringify(result, null, 2) }]
    };
  } catch (error: any) {
    return {
      content: [{ type: 'text', text: `Chyba: ${error.message}` }],
      isError: true
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('🧠 Radim Brain MCP Server spuštěn');
  console.error(`📡 Připojeno k: ${RADIM_BRAIN_URL}`);
}

main().catch((error) => {
  console.error('❌ Chyba:', error);
  process.exit(1);
});
