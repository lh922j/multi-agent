export const runtime = "edge";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    const msg = `data: ${JSON.stringify({ type: "done", answer: "서버에 연결할 수 없습니다.", map_points: [] })}\n\n`;
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
