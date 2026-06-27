export const runtime = "nodejs";
export const maxDuration = 60;

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();
  console.log("[proxy] API_BASE =", API_BASE);

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : String(e);
    const msg = `data: ${JSON.stringify({ type: "done", answer: `연결 실패: ${errMsg} | API_BASE: ${API_BASE}`, map_points: [] })}\n\n`;
    return new Response(msg, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
