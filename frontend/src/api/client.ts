import type { NaturalTripResponse, TripPlan, TripPlanRequest } from "@/types/trip";

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

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

/** Convert a sentence into a validated request and generate a plan. */
export class TripRequestError extends Error {
  missingFields: string[];

  constructor(message: string, missingFields: string[] = []) {
    super(message);
    this.name = "TripRequestError";
    this.missingFields = missingFields;
  }
}

/** Convert natural language plus optional date-picker values into a validated plan. */
export async function createTripPlanFromText(
  query: string,
  dates?: { startDate?: string; endDate?: string }
): Promise<NaturalTripResponse> {
  const resp = await fetch(`${API_BASE}/api/trip-plan/from-text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      start_date: dates?.startDate || null,
      end_date: dates?.endDate || null,
    }),
  });
  if (!resp.ok) {
    let body: any = null;
    try {
      body = await resp.json();
    } catch {
      throw new TripRequestError(`HTTP ${resp.status}`);
    }
    const message = detailFromBody(body, `HTTP ${resp.status}`);
    throw new TripRequestError(message, Array.isArray(body?.missing_fields) ? body.missing_fields : []);
  }
  return (await resp.json()) as NaturalTripResponse;
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
  return detailFromBody(body, fallback);
}

function detailFromBody(body: any, fallback: string): string {
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
