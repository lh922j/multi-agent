export interface MapPoint {
  apt_name: string;
  dong_name: string;
  area_exclusive: number;
  deal_amount: number;
  latitude: number;
  longitude: number;
  type: "trade" | "rent" | "commercial" | "location" | "station";
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  mapPoints?: MapPoint[];
  agentName?: string;
  streaming?: boolean;
}

export interface Session {
  id: string;
  title: string;
  updatedAt: Date;
  messages: Message[];
}

export interface SSEEvent {
  type: "token" | "agent" | "done" | "error";
  token?: string;
  agent?: string;
  answer?: string;
  map_points?: MapPoint[];
}
