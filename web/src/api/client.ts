// Minimal typed fetch client for the read-only API.
// Errors surface as ApiError with the server's generic envelope — the UI
// never shows raw stack traces because the API never sends them.

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const BASE = "/api/v1";

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export async function get<T>(path: string, params: Record<string, unknown> = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}${qs(params as Record<string, string>)}`, {
    headers: { Accept: "application/json" },
  });
  let body: unknown = null;
  try {
    body = await resp.json();
  } catch {
    /* non-JSON body */
  }
  if (!resp.ok) {
    const envelope = body as { error?: string; message?: string } | null;
    throw new ApiError(
      resp.status,
      envelope?.error ?? "http_error",
      envelope?.message ?? `Request failed (${resp.status})`,
    );
  }
  return body as T;
}
