import type { AgentDetail, LeaderboardRow, StatusResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function apiPost<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { method: "POST", cache: "no-store" });
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function getStatus(): Promise<StatusResponse> {
  return apiGet<StatusResponse>("/api/status");
}

export function getLeaderboard(): Promise<LeaderboardRow[]> {
  return apiGet<LeaderboardRow[]>("/api/leaderboard");
}

export function getAgentDetail(name: string): Promise<AgentDetail> {
  return apiGet<AgentDetail>(`/api/agents/${encodeURIComponent(name)}`);
}

export function activateKillSwitch(): Promise<{ active: boolean }> {
  return apiPost<{ active: boolean }>("/api/kill-switch/activate");
}

export function deactivateKillSwitch(): Promise<{ active: boolean }> {
  return apiPost<{ active: boolean }>("/api/kill-switch/deactivate");
}

export function unfreezeAgent(name: string): Promise<{ agent: string; status: string }> {
  return apiPost(`/api/agents/${encodeURIComponent(name)}/unfreeze`);
}

export { API_BASE_URL };
