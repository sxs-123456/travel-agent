import type { NaturalTripResponse, TripPlan } from "@/types/trip";

export interface SavedTrip extends NaturalTripResponse {
  id: string;
  query: string;
  createdAt: string;
  updatedAt: string;
}

const HISTORY_KEY = "ai-trip-planner:history:v1";
const LEGACY_KEY = "ai-trip-planner:last-plan";
const MAX_SAVED_TRIPS = 20;

function isSavedTrip(value: unknown): value is SavedTrip {
  const item = value as SavedTrip;
  return Boolean(item?.id && item?.request?.city && Array.isArray(item?.plan?.days));
}

function write(items: SavedTrip[]): boolean {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_SAVED_TRIPS)));
    return true;
  } catch {
    return false;
  }
}

export function loadTripHistory(): SavedTrip[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) return parsed.filter(isSavedTrip);
  } catch {
    // Corrupt or unavailable browser storage is treated as an empty history.
  }
  return [];
}

export function migrateLegacyPlan(): SavedTrip[] {
  const current = loadTripHistory();
  if (current.length) return current;
  try {
    const raw = sessionStorage.getItem(LEGACY_KEY);
    if (!raw) return current;
    const legacy = JSON.parse(raw);
    if (!legacy?.request?.city || !Array.isArray(legacy?.plan?.days)) return current;
    const now = new Date().toISOString();
    const item: SavedTrip = {
      id: "trip-" + Date.now(),
      query: legacy.query || legacy.request.city + "\u65c5\u884c\u8ba1\u5212",
      request: legacy.request,
      plan: legacy.plan,
      createdAt: now,
      updatedAt: now,
    };
    write([item]);
    sessionStorage.removeItem(LEGACY_KEY);
    return [item];
  } catch {
    return current;
  }
}

export function saveTrip(response: NaturalTripResponse, query: string): SavedTrip {
  const now = new Date().toISOString();
  const item: SavedTrip = {
    id: globalThis.crypto?.randomUUID?.() || "trip-" + Date.now(),
    query,
    request: response.request,
    plan: response.plan,
    createdAt: now,
    updatedAt: now,
  };
  write([item, ...loadTripHistory()]);
  return item;
}

export function updateSavedTripPlan(id: string, plan: TripPlan): SavedTrip[] {
  const items = loadTripHistory().map((item) =>
    item.id === id ? { ...item, plan, updatedAt: new Date().toISOString() } : item
  );
  write(items);
  return items;
}

export function deleteSavedTrip(id: string): SavedTrip[] {
  const items = loadTripHistory().filter((item) => item.id !== id);
  write(items);
  return items;
}
