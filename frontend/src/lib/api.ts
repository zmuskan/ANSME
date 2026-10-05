const API_BASE = "http://127.0.0.1:8000";

export interface ProductAnalysis {
  sentiment_score: number;
  requirement_match: number;
  pros: string[];
  cons: string[];
  risk_flags: string[];
  explanation: string;
}

export interface SuccessfulProduct {
  status: "success";
  url: string;
  title: string;
  brand: string | null;
  price: number | null;
  rating: number | null;
  image_url: string | null;
  description: string | null;
  overall_score: number;
  verdict: string;
  metrics: Record<string, number>;
  analysis: ProductAnalysis;
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
  verdict: string;
  created_at: string;
}

export async function analyzeProduct(
  url: string,
  budget?: number,
  requirements?: string
): Promise<AnalyzeProductResponse> {
  const response = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      urls: [url],
      budget,
      requirements,
    }),
  });

  if (!response.ok) {
    throw new Error("Analysis failed");
  }

  return response.json() as Promise<AnalyzeProductResponse>;
}
export async function getHistory(limit = 50): Promise<HistoryRecord[]> {
  const response = await fetch(
    `http://127.0.0.1:8000/history?limit=${limit}`
  );

  if (!response.ok) {
    throw new Error("Failed to load history");
  }

  return response.json() as Promise<HistoryRecord[]>;
}

export async function getHistoryItem(id: number) {
  const response = await fetch(
    `http://127.0.0.1:8000/history/${id}`
  );

  if (!response.ok) {
    throw new Error("Failed to load analysis");
  }

  return response.json();
}

export async function deleteHistoryItem(
  id: number
): Promise<{ status: string; message: string }> {
  const response = await fetch(
    `http://127.0.0.1:8000/history/${id}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    throw new Error("Delete failed");
  }

  return response.json() as Promise<{ status: string; message: string }>;
}