import { getAccessToken } from "@/lib/auth";
import { fetchAllHistoryPages } from "@/lib/history-actions";

const API_BASE =
  import.meta.env["VITE_API_URL"] ??
  "http://127.0.0.1:8000";

async function authenticatedHeaders(): Promise<Headers> {
  const accessToken = await getAccessToken();
  const headers = new Headers();
  headers.set("Authorization", `Bearer ${accessToken}`);
  return headers;
}


async function getApiError(response: Response, fallback: string): Promise<Error> {
  let detail = "";

  try {
    const body = await response.json();
    detail =
      typeof body.detail === "string"
        ? body.detail
        : typeof body.message === "string"
          ? body.message
          : "";
  } catch {
    // The response may not contain JSON.
  }

  return new Error(
    `${fallback} (HTTP ${response.status})${detail ? `: ${detail}` : ""}`,
  );
}

export interface ProductAnalysis {
  sentiment_score: number;
  requirement_match: number;
  pros: string[];
  cons: string[];
  risk_flags: string[];
  explanation: string;
}

export interface EvidenceResponse {
  title: string;
  url: string;
  source: string;
  score: number;
  snippet: string;
  quality_score: number;
}

export interface SuccessfulProduct {
  status: "success";
  url: string;
  title: string;
  brand: string | null;
  price: number | null;
  price_raw?: string | null;
  price_currency?: string | null;
  rating: number | null;
  image_url: string | null;
  description: string | null;
  overall_score: number;
  verdict: string;
  metrics: Record<string, number>;
  score_breakdown: Record<string, number>;
  processing_time_ms: number | null;
  sources_analyzed: number;
  evidence: EvidenceResponse[];
  category: string;
  review_count: number | null;
  price_history?: {
    history: Array<{
      price: number;
      price_raw?: string | null;
      price_currency?: string | null;
      captured_at: string | null;
    }>;
    lowest_seen: number | null;
    highest_seen: number | null;
    common_currency?: string | null;
  };
  similar_products?: Array<{
    id: number;
    title: string | null;
    url: string;
    price: number | null;
    overall_score: number;
    verdict: string;
  }>;
  analysis: ProductAnalysis;
  history_saved?: boolean;
  history_save_error?: string;
}

export interface FailedProduct {
  status: "error";
  url: string;
  error: string;
}

export interface AnalyzeProductResponse {
  status: string;
  processed_count: number;
  successful_count: number;
  failed_count: number;
  budget: number | null;
  products: Array<SuccessfulProduct | FailedProduct>;
}

export interface HistoryRecord {
  id: number;
  url: string;
  title: string | null;
  price: number | null;
  price_raw?: string | null;
  price_currency?: string | null;
  verdict: string;
  created_at: string;
  overall_score: number;
}

export interface AnalyticsSummary {
  total_analyses: number;
  sources_analyzed: number;
  avg_score: number;
  worth_it_count: number;
  consider_count: number;
  skip_count: number;
  history: Array<{ date: string; score: number }>;
  categories: Array<{ category: string; count: number; avg_score: number }>;
  most_analyzed_category: { category: string; count: number; avg_score: number } | null;
  top_sources: Array<{ domain: string; count: number }>;
}

export interface HistoryAnalysis extends HistoryRecord {
  brand: string | null;
  price_raw?: string | null;
  price_currency?: string | null;
  rating: number | null;
  image_url: string | null;
  description: string | null;
  overall_score: number;
  sentiment_score: number | null;
  requirement_match: number | null;
  pros: string[] | null;
  cons: string[] | null;
  risk_flags: string[] | null;
  explanation: string | null;
  metrics: Record<string, number>;
  score_breakdown: Record<string, number>;
  processing_time_ms: number | null;
  sources_analyzed: number;
  evidence: EvidenceResponse[];
  category: string;
  review_count: number | null;
  price_history: {
    history: Array<{
      price: number;
      price_raw?: string | null;
      price_currency?: string | null;
      captured_at: string | null;
    }>;
    lowest_seen: number | null;
    highest_seen: number | null;
    common_currency?: string | null;
  };
  similar_products: Array<{
    id: number;
    title: string | null;
    url: string;
    price: number | null;
    overall_score: number;
    verdict: string;
  }>;
}

export async function analyzeProduct(
  url: string,
  budget?: number,
  requirements?: string,
  saveHistory = true,
): Promise<AnalyzeProductResponse> {
  const headers = await authenticatedHeaders();
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      urls: [url],
      budget,
      requirements,
      save_history: saveHistory,
    }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error(
        "Your sign-in session is missing or expired. Please sign in again and retry the analysis."
      );
    }
    throw new Error("Analysis failed");
  }

  return response.json() as Promise<AnalyzeProductResponse>;
}
export async function getHistory(limit = 50): Promise<HistoryRecord[]> {
  const headers = await authenticatedHeaders();
  const response = await fetch(`${API_BASE}/history?limit=${limit}`, {
    headers,
  });

  if (!response.ok) {
    throw await getApiError(response, "Failed to load history");
  }

  return response.json() as Promise<HistoryRecord[]>;
}

export async function getAllHistory(): Promise<HistoryRecord[]> {
  return fetchAllHistoryPages(async (offset, limit) => {
    const headers = await authenticatedHeaders();
    const response = await fetch(
      `${API_BASE}/history?limit=${limit}&offset=${offset}`,
      { headers },
    );
    if (!response.ok) {
      throw new Error(`Failed to load analysis history (HTTP ${response.status}).`);
    }

    return (await response.json()) as HistoryRecord[];
  });
}

export async function getHistoryItem(id: number): Promise<HistoryAnalysis> {
  const headers = await authenticatedHeaders();
  const response = await fetch(`${API_BASE}/history/${id}`, { headers });

  if (!response.ok) {
    throw new Error("Failed to load analysis");
  }

  return response.json() as Promise<HistoryAnalysis>;
}

export async function getAnalytics(days?: number): Promise<AnalyticsSummary> {
  const params = days ? `?days=${days}` : "";
  const headers = await authenticatedHeaders();
  const response = await fetch(`${API_BASE}/analytics${params}`, { headers });

  if (!response.ok) {
    throw await getApiError(response, "Failed to load analytics");
  }

  return response.json() as Promise<AnalyticsSummary>;
}

export interface LeaderboardItem {
  title: string;
  url: string | null;
  overall_score: number;
  verdict: string;
  category: string;
}

export async function getLeaderboard(limit = 10): Promise<{
  highest: LeaderboardItem[];
  lowest: LeaderboardItem[];
}> {
  const response = await fetch(`${API_BASE}/leaderboard?limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Failed to load leaderboard (HTTP ${response.status}).`);
  }
  return response.json();
}

export async function getLeaderboardParticipation(): Promise<boolean> {
  const headers = await authenticatedHeaders();
  const response = await fetch(`${API_BASE}/leaderboard/participation`, {
    headers,
  });
  if (!response.ok) {
    throw new Error(`Failed to load leaderboard preference (HTTP ${response.status}).`);
  }
  const data = (await response.json()) as { enabled: boolean };
  return data.enabled;
}

export async function setLeaderboardParticipation(
  enabled: boolean,
): Promise<void> {
  const headers = await authenticatedHeaders();
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}/leaderboard/participation`, {
    method: "PUT",
    headers,
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) {
    throw new Error(`Failed to update leaderboard preference (HTTP ${response.status}).`);
  }
}

export async function deleteHistoryItem(
  id: number
): Promise<{ status: string; message: string }> {
  const headers = await authenticatedHeaders();
  const response = await fetch(`${API_BASE}/history/${id}`, {
    method: "DELETE",
    headers,
  });

  if (!response.ok) {
    throw new Error("Delete failed");
  }

  return response.json() as Promise<{ status: string; message: string }>;
}