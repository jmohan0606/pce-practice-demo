import type { ApiEnvelope, HealthStatus } from "@/lib/types/api";

/** Base URL for the backend API (FastAPI on port 8001). */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001";

export class ApiClient {
  constructor(private readonly baseUrl = API_BASE_URL) {}

  async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    return this.unwrap<T>(response);
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    return this.unwrap<T>(response);
  }

  private async unwrap<T>(response: Response): Promise<T> {
    if (!response.ok) throw new Error(`API error ${response.status}: ${await response.text()}`);
    const payload = (await response.json()) as ApiEnvelope<T> | T;
    if (typeof payload === "object" && payload !== null && "success" in payload && "data" in payload) {
      const envelope = payload as ApiEnvelope<T>;
      if (!envelope.success) throw new Error(envelope.error || envelope.message || "API returned failure");
      return envelope.data;
    }
    return payload as T;
  }
}

export const apiClient = new ApiClient();

/** Typed helper: backend + TigerGraph health for the top-bar status pill. */
export async function getHealth(): Promise<HealthStatus> {
  return apiClient.get<HealthStatus>("/api/health");
}
