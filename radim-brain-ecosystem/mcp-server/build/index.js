#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, } from '@modelcontextprotocol/sdk/types.js';
import axios from 'axios';
// Read API URL from environment or default to Heroku
const API_BASE_URL = process.env.RADIM_API_URL || 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com';
// Log which API we're using
console.error(`[Radim MCP] Connecting to: ${API_BASE_URL}`);
class RadimBrainClient {
    client;
    constructor(baseURL = API_BASE_URL) {
        this.client = axios.create({
            baseURL,
            timeout: 30000,
            headers: {
                'Content-Type': 'application/json',
            },
        });
    }
    // Seniors Management
    async listSeniors() {
        const response = await this.client.get('/api/radim/seniors');
        return response.data;
    }
    async getSenior(seniorId) {
        const response = await this.client.get(`/api/seniors/${seniorId}`);
        return response.data;
    }
    async createSenior(data) {
        // Map first_name + last_name to name if needed
        if (data.first_name && data.last_name) {
            data.name = `${data.first_name} ${data.last_name}`;
            delete data.first_name;
            delete data.last_name;
        }
        // Ensure senior_id exists
        if (!data.senior_id) {
            data.senior_id = `senior_${Date.now()}`;
        }
        const response = await this.client.post('/api/radim/seniors', data);
        return response.data;
    }
    async getVitals(seniorId) {
        const response = await this.client.get(`/api/seniors/${seniorId}/vitals`);
        return response.data;
    }
    async addSensorReading(seniorId, data) {
        const response = await this.client.post(`/api/seniors/${seniorId}/sensor`, data);
        return response.data;
    }
    // IoT Management
    async getIoTStatus() {
        const response = await this.client.get('/api/iot/system/status');
        return response.data;
    }
    async getMeshStatus() {
        const response = await this.client.get('/api/iot/mesh/status');
        return response.data;
    }
    async detectPatterns(seniorId) {
        const response = await this.client.get(`/api/iot/sensors/${seniorId}/patterns`);
        return response.data;
    }
    // Therapy & AI
    async getTherapyAdvice(seniorId, context) {
        const response = await this.client.post('/kal/therapy/advice', {
            senior_id: seniorId,
            context,
        });
        return response.data;
    }
    async getEmpatheticResponse(message) {
        const response = await this.client.post('/kal/therapy/empathy', { message });
        return response.data;
    }
    async getExercises(seniorId) {
        const response = await this.client.get(`/kal/therapy/exercises`);
        return response.data;
    }
    async smartChat(message, userId) {
        const response = await this.client.post('/kal/gemini/smart-chat', { message, user_id: userId });
        return response.data;
    }
    async quantumAnalysis(data) {
        const response = await this.client.post('/quantum/process', data);
        return response.data;
    }
    // Scenarios
    async fallDetection(seniorId, data) {
        const response = await this.client.post('/api/radim/scenarios/fall-detection', { senior_id: seniorId, ...data });
        return response.data;
    }
    async medicationReminder(seniorId) {
        const response = await this.client.get('/api/radim/scenarios/medication-reminder', { params: { senior_id: seniorId } });
        return response.data;
    }
    async nightMonitoring(seniorId) {
        const response = await this.client.get('/api/radim/scenarios/night-monitoring', { params: { senior_id: seniorId } });
        return response.data;
    }
    // Predictions
    async predictCrisis(seniorId) {
        const response = await this.client.get('/api/radim/predict/health-crisis', { params: { senior_id: seniorId } });
        return response.data;
    }
    // Content
    async fetchNews(category) {
        const response = await this.client.post('/kal/news/fetch', { category: category || 'general' });
        return response.data;
    }
    async generateQuiz(topic, difficulty) {
        const response = await this.client.post('/kal/quiz/generate', { topic, difficulty });
        return response.data;
    }
    async listBooks() {
        const response = await this.client.get('/kal/library/books');
        return response.data;
    }
    async getAcademyLesson(lessonId) {
        const response = await this.client.get('/kal/therapy/academy', { params: { lesson_id: lessonId } });
        return response.data;
    }
    // Memory
    async getUserHistory(userId) {
        const response = await this.client.get(`/kal/radim/history/${userId}`);
        return response.data;
    }
    async getBreakthroughs(userId) {
        const response = await this.client.get(`/kal/radim/breakthroughs/${userId}`);
        return response.data;
    }
    // Voice
    async synthesizeVoice(text, voice = 'cs-CZ-AntoninNeural') {
        const response = await this.client.post('/api/azure/tts', { text, voice });
        return response.data;
    }
    // System
    async healthCheck() {
        const response = await this.client.get('/health');
        return response.data;
    }
    async windsurfHealth() {
        const response = await this.client.get('/api/windsurf/health');
        return response.data;
    }
}
// MCP Tools Definition
const tools = [
    {
        name: 'radim_list_seniors',
        description: 'List all seniors in the system with their current status',
        inputSchema: {
            type: 'object',
            properties: {},
        },
    },
    {
        name: 'radim_get_senior',
        description: 'Get detailed information about a specific senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string', description: 'Senior ID' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_create_senior',
        description: 'Create a new senior profile in the Radim Brain system',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: {
                    type: 'string',
                    description: 'Unique senior ID (auto-generated if not provided)'
                },
                name: {
                    type: 'string',
                    description: 'Full name of the senior'
                },
                age: {
                    type: 'number',
                    description: 'Age of the senior (50-120)',
                    minimum: 50,
                    maximum: 120
                },
                room: {
                    type: 'string',
                    description: 'Room number (e.g., "101")'
                },
                medical_conditions: {
                    type: 'array',
                    items: { type: 'string' },
                    description: 'List of medical conditions (optional)'
                },
                medications: {
                    type: 'array',
                    items: { type: 'string' },
                    description: 'List of medications (optional)'
                },
                baselines: {
                    type: 'object',
                    description: 'Baseline vital signs (optional)',
                    properties: {
                        heart_rate: { type: 'number' },
                        blood_pressure_systolic: { type: 'number' },
                        blood_pressure_diastolic: { type: 'number' },
                        spo2: { type: 'number' }
                    }
                },
                preferences: {
                    type: 'object',
                    description: 'Senior preferences (optional)'
                }
            },
            required: ['name', 'age', 'room'],
        },
    },
    {
        name: 'radim_get_vitals',
        description: 'Get current vital signs for a senior (heart rate, blood pressure, temperature, SpO2)',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string', description: 'Senior ID' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_add_sensor_reading',
        description: 'Add a new sensor reading for a senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
                sensor_type: { type: 'string' },
                value: { type: 'number' },
                unit: { type: 'string' },
            },
            required: ['senior_id', 'sensor_type', 'value'],
        },
    },
    {
        name: 'radim_iot_status',
        description: 'Get IoT system status including connected devices',
        inputSchema: {
            type: 'object',
            properties: {},
        },
    },
    {
        name: 'radim_mesh_status',
        description: 'Get Zigbee mesh network status and topology',
        inputSchema: {
            type: 'object',
            properties: {},
        },
    },
    {
        name: 'radim_detect_patterns',
        description: 'Detect behavioral patterns for a senior based on sensor data',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_therapy_advice',
        description: 'Get therapeutic advice for a senior based on their condition',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
                context: { type: 'string', description: 'Current situation or concern' },
            },
            required: ['senior_id', 'context'],
        },
    },
    {
        name: 'radim_empathic_response',
        description: 'Generate an empathetic response to a message',
        inputSchema: {
            type: 'object',
            properties: {
                message: { type: 'string', description: 'Message to respond to' },
            },
            required: ['message'],
        },
    },
    {
        name: 'radim_get_exercises',
        description: 'Get recommended exercises for a senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_academy_lesson',
        description: 'Get a learning lesson from MyKolibri Academy',
        inputSchema: {
            type: 'object',
            properties: {
                lesson_id: { type: 'string' },
            },
            required: ['lesson_id'],
        },
    },
    {
        name: 'radim_smart_chat',
        description: 'Chat with Radim AI assistant',
        inputSchema: {
            type: 'object',
            properties: {
                message: { type: 'string' },
                user_id: { type: 'string', description: 'Optional user ID for context' },
            },
            required: ['message'],
        },
    },
    {
        name: 'radim_quantum_analysis',
        description: 'Perform quantum emotional analysis',
        inputSchema: {
            type: 'object',
            properties: {
                text: { type: 'string' },
                analysis_type: { type: 'string' },
            },
            required: ['text'],
        },
    },
    {
        name: 'radim_fall_detection',
        description: 'Process fall detection event for a senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
                sensor_data: { type: 'object' },
            },
            required: ['senior_id', 'sensor_data'],
        },
    },
    {
        name: 'radim_medication_reminder',
        description: 'Get medication reminders for a senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_night_monitoring',
        description: 'Get night monitoring data for a senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_predict_crisis',
        description: 'Predict potential health crisis for a senior',
        inputSchema: {
            type: 'object',
            properties: {
                senior_id: { type: 'string' },
            },
            required: ['senior_id'],
        },
    },
    {
        name: 'radim_fetch_news',
        description: 'Fetch news articles, optionally filtered by category',
        inputSchema: {
            type: 'object',
            properties: {
                category: { type: 'string', description: 'News category' },
            },
        },
    },
    {
        name: 'radim_generate_quiz',
        description: 'Generate a quiz on a specific topic',
        inputSchema: {
            type: 'object',
            properties: {
                topic: { type: 'string' },
                difficulty: { type: 'string', enum: ['easy', 'medium', 'hard'] },
            },
            required: ['topic', 'difficulty'],
        },
    },
    {
        name: 'radim_list_books',
        description: 'List available e-books in the library',
        inputSchema: {
            type: 'object',
            properties: {},
        },
    },
    {
        name: 'radim_user_history',
        description: 'Get conversation and interaction history for a user',
        inputSchema: {
            type: 'object',
            properties: {
                user_id: { type: 'string' },
            },
            required: ['user_id'],
        },
    },
    {
        name: 'radim_breakthroughs',
        description: 'Get therapeutic breakthroughs for a user',
        inputSchema: {
            type: 'object',
            properties: {
                user_id: { type: 'string' },
            },
            required: ['user_id'],
        },
    },
    {
        name: 'radim_synthesize_voice',
        description: 'Synthesize text to speech using Azure TTS',
        inputSchema: {
            type: 'object',
            properties: {
                text: { type: 'string' },
                voice: {
                    type: 'string',
                    description: 'Voice name (default: cs-CZ-AntoninNeural)',
                },
            },
            required: ['text'],
        },
    },
    {
        name: 'radim_health_check',
        description: 'Check Radim Brain API health status',
        inputSchema: {
            type: 'object',
            properties: {},
        },
    },
];
// MCP Server Implementation
const server = new Server({
    name: 'radim-brain-mcp',
    version: '1.0.0',
}, {
    capabilities: {
        tools: {},
    },
});
const client = new RadimBrainClient();
// Tool handlers
server.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools };
});
server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
        switch (name) {
            case 'radim_list_seniors':
                return { content: [{ type: 'text', text: JSON.stringify(await client.listSeniors(), null, 2) }] };
            case 'radim_get_senior':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getSenior(args.senior_id), null, 2) }] };
            case 'radim_create_senior':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.createSenior(args), null, 2) }] };
            case 'radim_get_vitals':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getVitals(args.senior_id), null, 2) }] };
            case 'radim_add_sensor_reading':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.addSensorReading(args.senior_id, args), null, 2) }] };
            case 'radim_iot_status':
                return { content: [{ type: 'text', text: JSON.stringify(await client.getIoTStatus(), null, 2) }] };
            case 'radim_mesh_status':
                return { content: [{ type: 'text', text: JSON.stringify(await client.getMeshStatus(), null, 2) }] };
            case 'radim_detect_patterns':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.detectPatterns(args.senior_id), null, 2) }] };
            case 'radim_therapy_advice':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getTherapyAdvice(args.senior_id, args.context), null, 2) }] };
            case 'radim_empathic_response':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getEmpatheticResponse(args.message), null, 2) }] };
            case 'radim_get_exercises':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getExercises(args.senior_id), null, 2) }] };
            case 'radim_academy_lesson':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getAcademyLesson(args.lesson_id), null, 2) }] };
            case 'radim_smart_chat':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.smartChat(args.message, args.user_id), null, 2) }] };
            case 'radim_quantum_analysis':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.quantumAnalysis(args), null, 2) }] };
            case 'radim_fall_detection':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.fallDetection(args.senior_id, args.sensor_data), null, 2) }] };
            case 'radim_medication_reminder':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.medicationReminder(args.senior_id), null, 2) }] };
            case 'radim_night_monitoring':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.nightMonitoring(args.senior_id), null, 2) }] };
            case 'radim_predict_crisis':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.predictCrisis(args.senior_id), null, 2) }] };
            case 'radim_fetch_news':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.fetchNews(args.category), null, 2) }] };
            case 'radim_generate_quiz':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.generateQuiz(args.topic, args.difficulty), null, 2) }] };
            case 'radim_list_books':
                return { content: [{ type: 'text', text: JSON.stringify(await client.listBooks(), null, 2) }] };
            case 'radim_user_history':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getUserHistory(args.user_id), null, 2) }] };
            case 'radim_breakthroughs':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.getBreakthroughs(args.user_id), null, 2) }] };
            case 'radim_synthesize_voice':
                if (!args)
                    throw new Error('Missing arguments');
                return { content: [{ type: 'text', text: JSON.stringify(await client.synthesizeVoice(args.text, args.voice), null, 2) }] };
            case 'radim_health_check':
                const health = await client.healthCheck();
                const windsurfHealth = await client.windsurfHealth();
                return { content: [{ type: 'text', text: JSON.stringify({ system: health, windsurf: windsurfHealth }, null, 2) }] };
            default:
                throw new Error(`Unknown tool: ${name}`);
        }
    }
    catch (error) {
        return {
            content: [
                {
                    type: 'text',
                    text: `Error: ${error.message}\n${error.response?.data ? JSON.stringify(error.response.data, null, 2) : ''}`,
                },
            ],
            isError: true,
        };
    }
});
// Start server
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error('Radim Brain MCP Server running on stdio');
}
main().catch((error) => {
    console.error('Fatal error:', error);
    process.exit(1);
});
//# sourceMappingURL=index.js.map