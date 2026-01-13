import axios from 'axios';
export * from './types.js';
export class SeniorManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async list() {
        const { data } = await this.client.get('/api/radim/seniors');
        return data.seniors || [];
    }
    async get(seniorId) {
        const { data } = await this.client.get(`/api/radim/seniors/${seniorId}`);
        return data.senior || data;
    }
    async create(senior) {
        const { data } = await this.client.post('/api/radim/seniors', senior);
        return data.senior || data;
    }
    async update(seniorId, updates) {
        const { data } = await this.client.put(`/seniors/${seniorId}`, updates);
        return data;
    }
    async getVitals(seniorId) {
        const { data } = await this.client.get(`/seniors/${seniorId}/vitals`);
        return data;
    }
    async addSensorReading(seniorId, reading) {
        await this.client.post(`/seniors/${seniorId}/sensors`, reading);
    }
}
export class IoTManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async getSystemStatus() {
        const { data } = await this.client.get('/iot/status');
        return data;
    }
    async getMeshStatus() {
        const { data } = await this.client.get('/iot/mesh');
        return data;
    }
    async detectPatterns(seniorId) {
        const { data } = await this.client.get(`/iot/patterns/${seniorId}`);
        return data;
    }
}
export class TherapyManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async getAdvice(seniorId, context) {
        const { data } = await this.client.post('/therapy/advice', { senior_id: seniorId, context });
        return data;
    }
    async getEmpatheticResponse(message) {
        const { data } = await this.client.post('/therapy/empathy', { message });
        return data;
    }
    async getExercises(seniorId) {
        const { data } = await this.client.get(`/therapy/exercises/${seniorId}`);
        return data;
    }
}
export class AIManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async smartChat(message, userId) {
        const { data } = await this.client.post('/ai/chat', { message, user_id: userId });
        return data;
    }
    async quantumAnalysis(input) {
        const { data } = await this.client.post('/quantum/analyze', input);
        return data;
    }
}
export class ScenarioManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async fallDetection(seniorId, sensorData) {
        const { data } = await this.client.post(`/scenarios/fall/${seniorId}`, sensorData);
        return data;
    }
    async medicationReminder(seniorId) {
        const { data } = await this.client.get(`/scenarios/medication/${seniorId}`);
        return data;
    }
    async nightMonitoring(seniorId) {
        const { data } = await this.client.get(`/scenarios/night/${seniorId}`);
        return data;
    }
}
export class PredictionManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async healthCrisis(seniorId) {
        const { data } = await this.client.get(`/predictions/crisis/${seniorId}`);
        return data;
    }
}
export class ContentManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async fetchNews(category) {
        const { data } = await this.client.get('/news', { params: { category } });
        return data;
    }
    async generateQuiz(topic, difficulty) {
        const { data } = await this.client.post('/quiz/generate', { topic, difficulty });
        return data;
    }
    async listBooks() {
        const { data } = await this.client.get('/kal/library/books');
        return data;
    }
    async getBook(bookId) {
        const { data } = await this.client.get(`/kal/library/books/${bookId}`);
        return data;
    }
}
export class MemoryManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async getUserHistory(userId) {
        const { data } = await this.client.get(`/radim/memory/${userId}`);
        return data;
    }
    async getBreakthroughs(userId) {
        const { data } = await this.client.get(`/radim/breakthroughs/${userId}`);
        return data;
    }
    async saveConversation(userId, message, response, sentiment) {
        await this.client.post('/radim/conversation', { user_id: userId, message, response, sentiment });
    }
}
export class VoiceManagement {
    client;
    constructor(client) {
        this.client = client;
    }
    async synthesize(request) {
        const { data } = await this.client.post('/tts-proxy/azure', request, {
            responseType: 'blob',
        });
        return data;
    }
    async synthesizeElevenLabs(text, voiceId) {
        const { data } = await this.client.post('/tts-proxy/elevenlabs', { text, voice_id: voiceId }, {
            responseType: 'blob',
        });
        return data;
    }
}
export class RadimBrain {
    client;
    seniors;
    iot;
    therapy;
    ai;
    scenarios;
    predictions;
    content;
    memory;
    voice;
    constructor(config = {}) {
        this.client = axios.create({
            baseURL: config.baseURL || (typeof globalThis !== 'undefined' &&
                typeof globalThis.window !== 'undefined' &&
                globalThis.window.location?.hostname === 'localhost'
                ? 'http://localhost:8002'
                : 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com'),
            timeout: config.timeout || 30000,
            headers: {
                'Content-Type': 'application/json',
                ...config.headers,
            },
        });
        // Initialize modules
        this.seniors = new SeniorManagement(this.client);
        this.iot = new IoTManagement(this.client);
        this.therapy = new TherapyManagement(this.client);
        this.ai = new AIManagement(this.client);
        this.scenarios = new ScenarioManagement(this.client);
        this.predictions = new PredictionManagement(this.client);
        this.content = new ContentManagement(this.client);
        this.memory = new MemoryManagement(this.client);
        this.voice = new VoiceManagement(this.client);
    }
    async health() {
        const { data } = await this.client.get('/health');
        return data;
    }
    async windsurfHealth() {
        const { data } = await this.client.get('/api/windsurf/health');
        return data;
    }
}
export default RadimBrain;
//# sourceMappingURL=index.js.map