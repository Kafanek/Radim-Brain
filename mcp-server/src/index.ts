#!/usr/bin/env node

/**
 * 🎭 Radim Brain MCP Server v2.0
 * Orchestrátor + Seniors + IoT + Consciousness
 * Pro Claude Desktop
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

// ============================================
// RADIM BRAIN CLIENT
// ============================================

class RadimBrainClient {
  private client: AxiosInstance;

  constructor(baseURL: string) {
    this.client = axios.create({
      baseURL,
      timeout: API_TIMEOUT,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  // --- Health & System ---
  async getHealth() {
    const response = await this.client.get('/health');
    return response.data;
  }

  async getHealthReady() {
    const response = await this.client.get('/health/ready');
    return response.data;
  }

  // --- Orchestrator ---
  async orchestrate(action: string, target?: string, params?: any) {
    const response = await this.client.post('/api/orchestrator/orchestrate', {
      action,
      target,
      params: params || {},
      user_id: 'claude-desktop'
    });
    return response.data;
  }

  async getOrchestratorHealth() {
    const response = await this.client.get('/api/orchestrator/health');
    return response.data;
  }

  async getSystemsStatus() {
    const response = await this.client.get('/api/orchestrator/systems');
    return response.data;
  }

  // --- Seniors ---
  async listSeniors(params?: any) {
    const response = await this.client.get('/api/seniors', { params });
    return response.data;
  }

  async getSenior(seniorId: string) {
    const response = await this.client.get(`/api/seniors/${seniorId}`);
    return response.data;
  }

  // --- IoT & Vitals ---
  async getVitalsSummary(seniorId: string) {
    const response = await this.client.get(`/api/iot/sensors/${seniorId}/vitals`);
    return response.data;
  }

  async getIoTSystemStatus() {
    const response = await this.client.get('/api/iot/system/status');
    return response.data;
  }

  // --- Chat ---
  async smartChat(message: string, userId: string = 'claude-desktop') {
    const response = await this.client.post('/kal/gemini/smart-chat', { message, user_id: userId });
    return response.data;
  }

  async radimChat(message: string, mode: string = 'senior') {
    const response = await this.client.post('/api/radim/chat', {
      message,
      user_id: 'claude-desktop',
      mode
    });
    return response.data;
  }

  // --- Consciousness ---
  async getConsciousnessState() {
    const response = await this.client.get('/api/consciousness/state');
    return response.data;
  }

  // --- Agents ---
  async getAgentHealth() {
    const response = await this.client.get('/kal/agent/health');
    return response.data;
  }

  async getAgentCapabilities() {
    const response = await this.client.get('/kal/agent/capabilities');
    return response.data;
  }

  // --- Crisis ---
  async predictHealthCrisis(seniorId: string) {
    const response = await this.client.post('/api/radim/predict/health-crisis', { senior_id: seniorId });
    return response.data;
  }
}

// ============================================
// TOOLS DEFINITION
// ============================================

const tools: Tool[] = [
  // === ORCHESTRATOR TOOLS ===
  {
    name: 'orchestrate',
    description: '🎭 Hlavní orchestrační nástroj. Akce: health_all (kontrola všech systémů), analyze (AI analýza), monitor (real-time monitoring), chat (orchestrovaný chat), fix (návrh opravy), logs (Heroku logy)',
    inputSchema: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['health_all', 'analyze', 'monitor', 'chat', 'fix', 'logs'],
          description: 'Orchestrační akce'
        },
        target: {
          type: 'string',
          enum: ['backend', 'wordpress', 'frontend', 'all'],
          description: 'Cílový systém (volitelné)'
        },
        params: {
          type: 'object',
          description: 'Parametry akce (message pro chat, problem pro fix, lines pro logs)'
        }
      },
      required: ['action']
    }
  },
  {
    name: 'check_health',
    description: '❤️ Rychlý health check Heroku backendu',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'get_systems_status',
    description: '📊 Přehled stavu všech systémů (backend, WordPress, consciousness, agents)',
    inputSchema: { type: 'object', properties: {} }
  },

  // === CONSCIOUSNESS TOOLS ===
  {
    name: 'get_consciousness_state',
    description: '🧠 Stav Consciousness Engine (harmony, empathy, φ direction)',
    inputSchema: { type: 'object', properties: {} }
  },

  // === AGENT TOOLS ===
  {
    name: 'get_agent_health',
    description: '🎭 Health status AI Rodiny Kafánků (všichni agenti)',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'get_agent_capabilities',
    description: '🤖 Seznam schopností všech agentů',
    inputSchema: { type: 'object', properties: {} }
  },

  // === CHAT TOOLS ===
  {
    name: 'radim_chat',
    description: '💬 Chat s Radimem (WhatsApp styl). Režimy: senior, rodina, technik',
    inputSchema: {
      type: 'object',
      properties: {
        message: { type: 'string', description: 'Zpráva pro Radima' },
        mode: { type: 'string', enum: ['senior', 'rodina', 'technik'], description: 'Režim chatu' }
      },
      required: ['message']
    }
  },
  {
    name: 'radim_smart_chat',
    description: '🧠 Inteligentní chat s kontextem a pamětí',
    inputSchema: {
      type: 'object',
      properties: {
        message: { type: 'string', description: 'Zpráva' }
      },
      required: ['message']
    }
  },

  // === SENIOR TOOLS ===
  {
    name: 'radim_list_seniors',
    description: '👴 Seznam seniorů v systému',
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
    description: '👤 Detail konkrétního seniora',
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
    description: '💓 Vitální funkce seniora (HR, SpO2, teplota)',
    inputSchema: {
      type: 'object',
      properties: {
        senior_id: { type: 'string' }
      },
      required: ['senior_id']
    }
  },

  // === IoT TOOLS ===
  {
    name: 'radim_iot_status',
    description: '🏠 Status IoT systému (senzory, Zigbee)',
    inputSchema: { type: 'object', properties: {} }
  },

  // === CRISIS TOOLS ===
  {
    name: 'radim_predict_crisis',
    description: '🚨 Predikce zdravotní krize seniora',
    inputSchema: {
      type: 'object',
      properties: {
        senior_id: { type: 'string' }
      },
      required: ['senior_id']
    }
  }
];

// ============================================
// SERVER SETUP
// ============================================

const server = new Server(
  { name: 'radim-orchestrator', version: '2.0.0' },
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
      // Orchestrator
      case 'orchestrate':
        result = await client.orchestrate(
          (args as any).action,
          (args as any).target,
          (args as any).params
        );
        break;
      case 'check_health':
        result = await client.getHealth();
        break;
      case 'get_systems_status':
        result = await client.getSystemsStatus();
        break;

      // Consciousness
      case 'get_consciousness_state':
        result = await client.getConsciousnessState();
        break;

      // Agents
      case 'get_agent_health':
        result = await client.getAgentHealth();
        break;
      case 'get_agent_capabilities':
        result = await client.getAgentCapabilities();
        break;

      // Chat
      case 'radim_chat':
        result = await client.radimChat(
          (args as any).message,
          (args as any).mode || 'senior'
        );
        break;
      case 'radim_smart_chat':
        result = await client.smartChat((args as any).message);
        break;

      // Seniors
      case 'radim_list_seniors':
        result = await client.listSeniors(args);
        break;
      case 'radim_get_senior':
        result = await client.getSenior((args as any).senior_id);
        break;
      case 'radim_get_vitals':
        result = await client.getVitalsSummary((args as any).senior_id);
        break;

      // IoT
      case 'radim_iot_status':
        result = await client.getIoTSystemStatus();
        break;

      // Crisis
      case 'radim_predict_crisis':
        result = await client.predictHealthCrisis((args as any).senior_id);
        break;

      default:
        return {
          content: [{ type: 'text', text: `❌ Neznámý nástroj: ${name}` }],
          isError: true
        };
    }

    return {
      content: [{ type: 'text', text: JSON.stringify(result, null, 2) }]
    };
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || error.message || 'Unknown error';
    return {
      content: [{ type: 'text', text: `❌ Chyba: ${errorMsg}` }],
      isError: true
    };
  }
});

// ============================================
// START
// ============================================

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('🎭 Radim Orchestrator MCP Server v2.0 spuštěn');
  console.error(`📡 Backend: ${RADIM_BRAIN_URL}`);
  console.error(`🔧 Tools: ${tools.length} nástrojů`);
}

main().catch((error) => {
  console.error('❌ Fatální chyba:', error);
  process.exit(1);
});
