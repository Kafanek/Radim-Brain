export interface Senior {
    senior_id: string;
    first_name: string;
    last_name: string;
    age: number;
    room: string;
    phone?: string;
    emergency_contact_name?: string;
    emergency_contact_phone?: string;
    medical_conditions?: string[];
    medications?: string[];
    allergies?: string[];
    status: 'ok' | 'warning' | 'critical';
    is_active: boolean;
    registered_at: string;
    updated_at?: string;
    last_seen?: string;
}
export interface SeniorCreateRequest {
    first_name: string;
    last_name: string;
    age: number;
    room: string;
    phone?: string;
    emergency_contact_name?: string;
    emergency_contact_phone?: string;
    medical_conditions?: string[];
    medications?: string[];
    allergies?: string[];
}
export interface VitalsSummary {
    heart_rate?: number;
    blood_pressure_systolic?: number;
    blood_pressure_diastolic?: number;
    temperature?: number;
    spo2?: number;
    last_updated: string;
    status: 'normal' | 'warning' | 'critical';
}
export interface SensorReading {
    sensor_id: string;
    sensor_type: string;
    value: number;
    unit: string;
    timestamp: string;
    senior_id: string;
}
export interface IoTSystemStatus {
    status: 'online' | 'offline' | 'degraded';
    connected_devices: number;
    total_devices: number;
    mesh_health: number;
    last_update: string;
}
export interface MeshStatus {
    coordinator: {
        ieee_address: string;
        network_address: string;
        friendly_name: string;
    };
    devices: Array<{
        ieee_address: string;
        network_address: string;
        friendly_name: string;
        model: string;
        vendor: string;
        link_quality: number;
        last_seen: string;
    }>;
    topology: any;
}
export interface PatternDetection {
    senior_id: string;
    patterns: Array<{
        type: 'sleep' | 'activity' | 'bathroom' | 'anomaly';
        description: string;
        confidence: number;
        detected_at: string;
    }>;
}
export interface TherapyAdvice {
    advice: string;
    exercises?: string[];
    recommendations?: string[];
    urgency: 'low' | 'medium' | 'high';
}
export interface EmpatheticResponse {
    response: string;
    emotion_detected: string;
    empathy_score: number;
}
export interface ExerciseRoutine {
    senior_id: string;
    exercises: Array<{
        name: string;
        description: string;
        duration_minutes: number;
        difficulty: 'easy' | 'medium' | 'hard';
        category: string;
    }>;
}
export interface ChatResponse {
    response: string;
    model?: string;
    tokens_used?: number;
    sentiment?: string;
}
export interface QuantumAnalysis {
    emotional_state: string;
    quantum_coherence: number;
    empathy_resonance: number;
    therapeutic_insights: string[];
}
export interface FallDetection {
    senior_id: string;
    fall_detected: boolean;
    confidence: number;
    timestamp: string;
    location?: string;
    action_taken: string;
}
export interface MedicationReminder {
    senior_id: string;
    medications: Array<{
        name: string;
        dosage: string;
        time: string;
        taken: boolean;
    }>;
    next_reminder: string;
}
export interface HealthCrisisPrediction {
    senior_id: string;
    risk_level: 'low' | 'medium' | 'high' | 'critical';
    risk_factors: string[];
    recommendations: string[];
    predicted_window: string;
    confidence: number;
}
export interface NewsResponse {
    articles: Array<{
        title: string;
        summary: string;
        category: string;
        published_at: string;
        url?: string;
    }>;
}
export interface QuizResponse {
    topic: string;
    difficulty: string;
    questions: Array<{
        question: string;
        options: string[];
        correct_answer: number;
        explanation?: string;
    }>;
}
export interface Book {
    book_id: string;
    title: string;
    author: string;
    category: string;
    description?: string;
    cover_url?: string;
    content_url: string;
}
export interface UserHistory {
    user_id: string;
    conversations: Array<{
        timestamp: string;
        message: string;
        response: string;
        sentiment?: string;
    }>;
    total_interactions: number;
    last_interaction: string;
}
export interface Breakthrough {
    user_id: string;
    breakthrough_type: string;
    description: string;
    detected_at: string;
    severity_improvement?: number;
    empathy_increase?: number;
}
export interface VoiceSynthesisRequest {
    text: string;
    voice?: string;
    rate?: number;
    pitch?: number;
}
export interface HealthStatus {
    status: 'healthy' | 'degraded' | 'unhealthy';
    timestamp: string;
    version: string;
    checks: {
        redis?: {
            status: string;
            latency_ms?: number;
        };
        database?: {
            status: string;
            type?: string;
        };
        gemini_api?: {
            status: string;
        };
        agents?: {
            status: string;
            active?: number;
        };
    };
}
//# sourceMappingURL=types.d.ts.map