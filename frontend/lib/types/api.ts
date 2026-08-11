/** Standard envelope the backend may wrap responses in. */
export type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  error?: string;
  message?: string;
};

/** Shape of GET /api/health — mirrors the backend graph client's health dict. */
export type HealthStatus = {
  healthy: boolean;
  mode?: "real" | "mock" | string;
  graph?: string;
  error?: string;
};
