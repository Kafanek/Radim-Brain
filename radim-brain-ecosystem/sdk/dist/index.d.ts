/// <reference types="node" />
import { AxiosInstance } from 'axios';
import * as Types from './types.js';
export * from './types.js';
export declare class SeniorManagement {
    private client;
    constructor(client: AxiosInstance);
    list(): Promise<Types.Senior[]>;
    get(seniorId: string): Promise<Types.Senior>;
    create(senior: Types.SeniorCreateRequest): Promise<Types.Senior>;
    update(seniorId: string, updates: Partial<Types.SeniorCreateRequest>): Promise<Types.Senior>;
    getVitals(seniorId: string): Promise<Types.VitalsSummary>;
    addSensorReading(seniorId: string, reading: Omit<Types.SensorReading, 'senior_id' | 'timestamp'>): Promise<void>;
}
export declare class IoTManagement {
    private client;
    constructor(client: AxiosInstance);
    getSystemStatus(): Promise<Types.IoTSystemStatus>;
    getMeshStatus(): Promise<Types.MeshStatus>;
    detectPatterns(seniorId: string): Promise<Types.PatternDetection>;
}
export declare class TherapyManagement {
    private client;
    constructor(client: AxiosInstance);
    getAdvice(seniorId: string, context: string): Promise<Types.TherapyAdvice>;
    getEmpatheticResponse(message: string): Promise<Types.EmpatheticResponse>;
    getExercises(seniorId: string): Promise<Types.ExerciseRoutine>;
}
export declare class AIManagement {
    private client;
    constructor(client: AxiosInstance);
    smartChat(message: string, userId?: string): Promise<Types.ChatResponse>;
    quantumAnalysis(input: any): Promise<Types.QuantumAnalysis>;
}
export declare class ScenarioManagement {
    private client;
    constructor(client: AxiosInstance);
    fallDetection(seniorId: string, sensorData: any): Promise<Types.FallDetection>;
    medicationReminder(seniorId: string): Promise<Types.MedicationReminder>;
    nightMonitoring(seniorId: string): Promise<any>;
}
export declare class PredictionManagement {
    private client;
    constructor(client: AxiosInstance);
    healthCrisis(seniorId: string): Promise<Types.HealthCrisisPrediction>;
}
export declare class ContentManagement {
    private client;
    constructor(client: AxiosInstance);
    fetchNews(category?: string): Promise<Types.NewsResponse>;
    generateQuiz(topic: string, difficulty: 'easy' | 'medium' | 'hard'): Promise<Types.QuizResponse>;
    listBooks(): Promise<Types.Book[]>;
    getBook(bookId: string): Promise<Types.Book>;
}
export declare class MemoryManagement {
    private client;
    constructor(client: AxiosInstance);
    getUserHistory(userId: string): Promise<Types.UserHistory>;
    getBreakthroughs(userId: string): Promise<Types.Breakthrough[]>;
    saveConversation(userId: string, message: string, response: string, sentiment?: string): Promise<void>;
}
export declare class VoiceManagement {
    private client;
    constructor(client: AxiosInstance);
    synthesize(request: Types.VoiceSynthesisRequest): Promise<Blob>;
    synthesizeElevenLabs(text: string, voiceId?: string): Promise<Blob>;
}
export interface RadimBrainConfig {
    baseURL?: string;
    timeout?: number;
    headers?: Record<string, string>;
}
export declare class RadimBrain {
    private client;
    seniors: SeniorManagement;
    iot: IoTManagement;
    therapy: TherapyManagement;
    ai: AIManagement;
    scenarios: ScenarioManagement;
    predictions: PredictionManagement;
    content: ContentManagement;
    memory: MemoryManagement;
    voice: VoiceManagement;
    constructor(config?: RadimBrainConfig);
    health(): Promise<Types.HealthStatus>;
    windsurfHealth(): Promise<any>;
}
export default RadimBrain;
//# sourceMappingURL=index.d.ts.map