"use client";
import { useEffect, useRef, useState } from "react";
import { MapPoint, Message } from "@/types";

declare global {
  interface Window {
    kakao: {
      maps: {
        load: (cb: () => void) => void;
        Map: new (container: HTMLElement, opts: object) => KakaoMap;
        LatLng: new (lat: number, lng: number) => KakaoLatLng;
        Marker: new (opts: { position: KakaoLatLng; map?: KakaoMap }) => KakaoMarker;
        InfoWindow: new (opts: { content: string; removable?: boolean }) => KakaoInfoWindow;
        Polygon: new (opts: {
          map: KakaoMap;
          path: KakaoLatLng[] | KakaoLatLng[][];
          strokeWeight?: number;
          strokeColor?: string;
          strokeOpacity?: number;
          strokeStyle?: string;
          fillColor?: string;
          fillOpacity?: number;
        }) => KakaoPolygon;
      };
    };
  }
}

interface KakaoMap { setCenter(latlng: KakaoLatLng): void; }
interface KakaoLatLng { getLat(): number; getLng(): number; }
interface KakaoMarker { setMap(map: KakaoMap | null): void; addListener(event: string, cb: () => void): void; }
interface KakaoInfoWindow { open(map: KakaoMap, marker: KakaoMarker): void; }
interface KakaoPolygon { setMap(map: KakaoMap | null): void; }

interface GeoFeature {
  properties: { code: string; name: string };
  geometry: {
    type: "Polygon" | "MultiPolygon";
    coordinates: number[][][] | number[][][][];
  };
}

interface Props { messages: Message[]; }

const AGENT_COLORS: Record<string, string> = {
  DataQueryAgent: "#2563EB",
  RAGAgent: "#7C3AED",
  PredictionAgent: "#059669",
  AnomalyAgent: "#DC2626",
  OrchestratorAgent: "#D97706",
};

// Ray casting — GeoJSON은 [lng, lat] 순서
function pointInPolygon(lat: number, lng: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersect = yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function ptInFeature(lat: number, lng: number, feat: GeoFeature): boolean {
  const { type, coordinates } = feat.geometry;
  if (type === "Polygon") {
    const rings = coordinates as number[][][];
    return pointInPolygon(lat, lng, rings[0]);
  }
  const polys = coordinates as number[][][][];
  return polys.some((poly) => pointInPolygon(lat, lng, poly[0]));
}

export default function MapPanel({ messages }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const kakaoMapRef = useRef<KakaoMap | null>(null);
  const markersRef = useRef<KakaoMarker[]>([]);
  const polygonsRef = useRef<KakaoPolygon[]>([]);
  const geoDataRef = useRef<GeoFeature[] | null>(null);
  const [mapStatus, setMapStatus] = useState<"loading" | "ready" | "error">("loading");
  const [mapError, setMapError] = useState("");

  const lastMsg = [...messages].reverse().find((m) => m.role === "assistant");
  const mapPoints: MapPoint[] = lastMsg?.mapPoints ?? [];
  const lastUserMsg = [...messages].reverse().find((m) => m.role === "user")?.content ?? "";

  // ── GeoJSON 로드 (최초 1회) ────────────────────────────────
  useEffect(() => {
    if (geoDataRef.current) return;
    fetch("/geodata/metro_districts.json")
      .then((r) => r.json())
      .then((json) => { geoDataRef.current = json.features as GeoFeature[]; })
      .catch(() => {});
  }, []);

  // ── 지도 초기화 ────────────────────────────────────────────
  useEffect(() => {
    const KEY = process.env.NEXT_PUBLIC_KAKAO_MAP_KEY;

    if (!KEY || KEY === "your_kakao_map_key_here") {
      setMapStatus("error");
      setMapError("NEXT_PUBLIC_KAKAO_MAP_KEY가 .env.local에 설정되지 않았습니다.");
      return;
    }

    if (window.kakao?.maps?.Map) { initMap(); return; }

    const existing = document.getElementById("kakao-sdk");
    if (existing) {
      const wait = setInterval(() => {
        if (window.kakao?.maps) { clearInterval(wait); initMap(); }
      }, 100);
      return () => clearInterval(wait);
    }

    const s = document.createElement("script");
    s.id = "kakao-sdk";
    s.src = `//dapi.kakao.com/v2/maps/sdk.js?appkey=${KEY}&libraries=services&autoload=false`;
    s.onload = initMap;
    s.onerror = () => {
      setMapStatus("error");
      setMapError("스크립트 로드 실패 — API 키 또는 등록 도메인을 확인하세요.");
    };
    document.head.appendChild(s);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function initMap() {
    window.kakao.maps.load(() => {
      if (!mapRef.current) return;
      try {
        kakaoMapRef.current = new window.kakao.maps.Map(mapRef.current, {
          center: new window.kakao.maps.LatLng(37.5665, 126.9780),
          level: 7,
        });
        setMapStatus("ready");
      } catch (e) {
        setMapStatus("error");
        setMapError(String(e));
      }
    });
  }

  // ── 마커 업데이트 ──────────────────────────────────────────
  useEffect(() => {
    if (!kakaoMapRef.current || mapStatus !== "ready") return;
    markersRef.current.forEach((m) => m.setMap(null));
    markersRef.current = [];
    if (!mapPoints.length) return;

    let sumLat = 0, sumLng = 0;
    mapPoints.forEach((pt) => {
      const pos = new window.kakao.maps.LatLng(pt.latitude, pt.longitude);
      const marker = new window.kakao.maps.Marker({ position: pos, map: kakaoMapRef.current! });
      const info = new window.kakao.maps.InfoWindow({
        content: `<div style="padding:6px 10px;font-size:12px;white-space:nowrap"><b>${pt.apt_name}</b><br/>${(pt.deal_amount / 10000).toFixed(1)}억</div>`,
      });
      marker.addListener("click", () => info.open(kakaoMapRef.current!, marker));
      markersRef.current.push(marker);
      sumLat += pt.latitude;
      sumLng += pt.longitude;
    });

    kakaoMapRef.current.setCenter(
      new window.kakao.maps.LatLng(sumLat / mapPoints.length, sumLng / mapPoints.length)
    );
  }, [mapPoints, mapStatus]);

  // ── 폴리곤 업데이트 ────────────────────────────────────────
  useEffect(() => {
    if (!kakaoMapRef.current || mapStatus !== "ready") return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];

    if (!geoDataRef.current) return;

    const matchedFeatures = new Map<string, GeoFeature>();

    // 1순위: 사용자 메시지에 명시된 구/동 이름 → 정확히 그 지역만 강조
    const userNameMatches = geoDataRef.current.filter((f) => lastUserMsg.includes(f.properties.name));
    if (userNameMatches.length > 0) {
      userNameMatches.forEach((f) => matchedFeatures.set(f.properties.code, f));
    } else {
      // 2순위: location/station 타입 포인트 이름 매칭
      for (const pt of mapPoints) {
        if (pt.type === "location" || pt.type === "station") {
          const byName = geoDataRef.current.find((f) => f.properties.name === pt.apt_name);
          if (byName) matchedFeatures.set(byName.properties.code, byName);
        }
      }
      // 3순위: 이름 매칭도 없으면 PIP (폴백)
      if (matchedFeatures.size === 0) {
        for (const pt of mapPoints.filter((p) => p.type !== "location" && p.type !== "station")) {
          for (const feat of geoDataRef.current) {
            if (matchedFeatures.has(feat.properties.code)) continue;
            if (ptInFeature(pt.latitude, pt.longitude, feat)) {
              matchedFeatures.set(feat.properties.code, feat);
              break;
            }
          }
        }
      }
    }

    if (matchedFeatures.size === 0) return;

    // 매칭된 구마다 폴리곤 생성
    const STROKE = "#2563EB";
    const FILL = "#2563EB";

    const toLatLng = (coord: number[]) =>
      new window.kakao.maps.LatLng(coord[1], coord[0]);

    for (const feat of matchedFeatures.values()) {
      const { type, coordinates } = feat.geometry;

      // outer ring만 사용 (hole 링 제외) — MultiPolygon은 각 서브폴리곤의 outer ring
      const outerRings: number[][][] =
        type === "Polygon"
          ? [(coordinates as number[][][])[0]]
          : (coordinates as number[][][][]).map((poly) => poly[0]);

      for (const ring of outerRings) {
        const path = ring.map(toLatLng);
        const polygon = new window.kakao.maps.Polygon({
          map: kakaoMapRef.current!,
          path,
          strokeWeight: 2,
          strokeColor: STROKE,
          strokeOpacity: 0.85,
          strokeStyle: "solid",
          fillColor: FILL,
          fillOpacity: 0.07,
        });
        polygonsRef.current.push(polygon);
      }
    }
  }, [mapPoints, mapStatus, lastUserMsg]);

  const stats = computeStats(mapPoints);

  return (
    <div className="flex flex-col h-full min-w-0 bg-white border-l border-slate-200" style={{ flex: 2 }}>
      {/* 지도 라벨 바 */}
      <div className="flex items-center gap-2 px-4 h-9 border-b border-slate-200 shrink-0" style={{ background: "#F8FAFC" }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#2563EB" strokeWidth="2">
          <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
          <line x1="8" y1="2" x2="8" y2="18" />
          <line x1="16" y1="6" x2="16" y2="22" />
        </svg>
        <span className="text-xs font-semibold" style={{ color: "#475569" }}>지도</span>
      </div>

      {/* 지도 영역 — 패널 높이의 50% */}
      <div className="relative w-full" style={{ flex: "0 0 50%" }}>
        <div ref={mapRef} className="w-full h-full" />
        {mapStatus === "loading" && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-100 text-sm text-slate-400">
            지도 로딩 중...
          </div>
        )}
        {mapStatus === "error" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-100 gap-2 px-6 text-center">
            <span className="text-2xl">🗺️</span>
            <p className="text-xs text-slate-500">{mapError}</p>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto min-w-0">
        {/* 통계 카드 */}
        {stats && (
          <div className="flex flex-wrap border-b border-slate-100">
            {[
              { label: "거래 건수", value: `${mapPoints.length}건`, color: "#2563EB" },
              { label: "평균 매매가", value: stats.avg, color: "#059669" },
              { label: "최고 거래가", value: stats.max, color: "#DC2626" },
              { label: "최저 거래가", value: stats.min, color: "#7C3AED" },
            ].map((card, i) => (
              <div
                key={card.label}
                className="p-3"
                style={{
                  width: "50%",
                  borderRight: i % 2 === 0 ? "1px solid #f1f5f9" : "none",
                  borderBottom: i < 2 ? "1px solid #f1f5f9" : "none",
                }}
              >
                <div className="flex items-start gap-2">
                  <div className="w-1 h-10 rounded-full mt-0.5 shrink-0" style={{ background: card.color }} />
                  <div>
                    <p className="text-sm text-slate-400">{card.label}</p>
                    <p className="text-2xl font-bold text-slate-800 leading-tight">{card.value}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 에이전트 트레이스 */}
        {messages.some((m) => m.agentName) && (
          <div>
            <p className="text-xs font-semibold text-slate-500 mb-2">에이전트 처리 흐름</p>
            <div className="space-y-2">
              {messages.filter((m) => m.role === "assistant" && m.agentName).map((m, i, arr) => (
                <div key={i} className="flex items-start gap-2.5">
                  <div className="flex flex-col items-center">
                    <div className="w-2.5 h-2.5 rounded-full mt-1 shrink-0" style={{ background: AGENT_COLORS[m.agentName!] ?? "#6B7280" }} />
                    {i < arr.length - 1 && <div className="w-0.5 bg-slate-200 mt-1" style={{ minHeight: 16 }} />}
                  </div>
                  <div>
                    <p className="text-xs font-medium" style={{ color: AGENT_COLORS[m.agentName!] ?? "#6B7280" }}>{m.agentName}</p>
                    <p className="text-[11px] text-slate-400 truncate max-w-[360px]">{m.content.slice(0, 60)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function computeStats(points: MapPoint[]) {
  if (!points.length) return null;
  const amounts = points.map((p) => p.deal_amount);
  const fmt = (v: number) => `${(v / 10000).toFixed(1)}억`;
  return {
    avg: fmt(amounts.reduce((a, b) => a + b, 0) / amounts.length),
    max: fmt(Math.max(...amounts)),
    min: fmt(Math.min(...amounts)),
  };
}
