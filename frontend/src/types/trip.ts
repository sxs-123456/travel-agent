// 与后端 Pydantic 模型对齐的前端类型定义。
// 后端：backend/models/trip.py  →  前端：本文件

export interface Location {
  longitude: number;
  latitude: number;
  address?: string | null;
}

export interface WeatherInfo {
  date: string;
  temperature: number;
  condition: string;
}

export interface Attraction {
  source_id?: string | null;
  name: string;
  location: Location;
  ticket_price: number;
  ticket_price_note?: string | null;
  description: string;
  recommended_duration: number;
  image_url?: string | null;
  image_source?: string | null;
}

export interface Meal {
  source_id?: string | null;
  name: string;
  location?: Location | null;
  price: number;
  cuisine: string;
  price_source?: string | null;
  price_is_estimated?: boolean;
}

export interface Hotel {
  name: string;
  location: Location;
  price_per_night: number;
  star_rating: number;
  image_url?: string | null;
  image_source?: string | null;
  level?: string | null;
  price_source?: string | null;
  price_is_estimated?: boolean;
}

export interface DayPlan {
  day: number;
  date: string;
  attractions: Attraction[];
  meals: Meal[];
  hotel?: Hotel | null;
  route_distance_km?: number | null;
  route_duration_min?: number | null;
  route_distance_source?: "amap_driving" | "straight_line";
  transit_advice?: string[];
  notes: string;
}

export interface Budget {
  ticket_total: number;
  hotel_total: number;
  meal_total: number;
  transport_total: number;
  rail_total?: number;
  taxi_total?: number;
  rail_is_estimated?: boolean;
  taxi_is_estimated?: boolean;
  transport_is_estimated?: boolean;
  total: number;
  travelers?: number;
  rooms?: number;
}

export interface TrainSeat {
  type: string;
  remain: string;
  price?: number | null;
}

export interface TrainOption {
  train_no: string;
  train_type?: string;
  from_station: string;
  to_station: string;
  depart_time: string;
  arrive_time: string;
  duration: string;
  seats: TrainSeat[];
  min_price?: number | null;
  currency?: string;
  source_note?: string;
}

export interface TrainRecommendation {
  direction: string;
  date: string;
  recommended?: TrainOption | null;
  reason: string;
  candidates: TrainOption[];
  price_per_person?: number | null;
}

export interface TripPlan {
  city: string;
  start_date: string;
  end_date: string;
  days: DayPlan[];
  weather_info: WeatherInfo[];
  budget?: Budget | null;
  train_info?: TrainRecommendation[] | null;
  train_note?: string | null;
  generation_metrics?: GenerationMetrics | null;
}

export interface GenerationMetrics {
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd?: number | null;
  usage_available: boolean;
}

export interface TripPlanRequest {
  city: string;
  start_date: string;
  end_date: string;
  preferences: string;
  budget_level: string;
  travelers: number;
  // 必须与后端 TripPlanRequest.origin_city 字段同名（同 snake_case），
  // 否则 Pydantic 接收时找不到该 key，默认置空 → 12306 车次被跳过。
  origin_city?: string;
}

export interface NaturalTripResponse {
  request: TripPlanRequest;
  plan: TripPlan;
}
