// Vercel Edge Function: forwards every /api/* call to the backend on Render.
// The backend address lives in the private Vercel variable BACKEND_URL (e.g. https://rafiq-xxxx.onrender.com),
// so it never appears in the website's code. vercel.json rewrites /api/<path> -> /api/proxy?path=<path>.
export const config = { runtime: "edge" };

export default async function handler(req) {
  const base = (process.env.BACKEND_URL || "").replace(/\/+$/, "");
  if (!base) {
    return new Response(JSON.stringify({ detail: "BACKEND_URL is not set in Vercel environment variables" }),
      { status: 500, headers: { "content-type": "application/json" } });
  }
  const url = new URL(req.url);
  const path = url.searchParams.get("path") || "";
  url.searchParams.delete("path");
  const target = `${base}/api/${path}${url.search}`;

  const headers = new Headers(req.headers);
  ["host", "connection", "content-length", "x-forwarded-host"].forEach((h) => headers.delete(h));
  const init = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") { init.body = req.body; init.duplex = "half"; }

  try {
    const r = await fetch(target, init);
    const out = new Headers(r.headers);
    ["content-encoding", "content-length", "transfer-encoding", "connection"].forEach((h) => out.delete(h));
    if ((r.headers.get("content-type") || "").includes("text/event-stream")) {
      out.set("cache-control", "no-cache, no-transform");
      out.set("x-accel-buffering", "no");
    }
    return new Response(r.body, { status: r.status, statusText: r.statusText, headers: out });
  } catch (e) {
    // Render free plan: the first request after a sleep can take ~1 minute. The app retries on its own.
    return new Response(JSON.stringify({ detail: "Backend is waking up or unreachable, try again in a moment" }),
      { status: 502, headers: { "content-type": "application/json" } });
  }
}
