import type { TripPlan, TripPlanRequest } from "@/types/trip";
import type { RagQueryResponse } from "@/types/rag";

const API_BASE = import.meta.env.VITE_API_BASE || "";

/** 调用后端 /api/trip-plan，返回完整的多智能体规划结果。 */
export async function createTripPlan(req: TripPlanRequest): Promise<TripPlan> {
  const resp = await fetch(`${API_BASE}/api/trip-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    throw new Error(await extractDetail(resp));
  }
  return (await resp.json()) as TripPlan;
}

/** 调用后端 /api/rag/query，返回带引用来源的知识库问答结果。 */
export async function queryKnowledge(
  question: string,
  topK = 4
): Promise<RagQueryResponse> {
  const resp = await fetch(`${API_BASE}/api/rag/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, top_k: topK }),
  });
  if (!resp.ok) {
    throw new Error(await extractDetail(resp));
  }
  return (await resp.json()) as RagQueryResponse;
}

/** 从 FastAPI 错误响应中提取可读错误信息。422 的 detail 是错误数组，逐项取 msg 并拼接。 */
async function extractDetail(resp: Response): Promise<string> {
  const fallback = `HTTP ${resp.status}`;
  let body: any;
  try {
    body = await resp.json();
  } catch {
    return fallback;
  }
  const detail = body?.detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => d?.msg ?? (typeof d === "string" ? d : JSON.stringify(d)))
      .filter(Boolean)
      .join("；") || fallback;
  }
  if (typeof detail === "string") return detail;
  if (detail) return JSON.stringify(detail);
  return fallback;
}
