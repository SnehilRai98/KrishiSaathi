import { vi } from "vitest";

type Route = (url: string, init?: RequestInit) => unknown;

/** Replace global fetch with a router: the first matching [substring, handler] wins. */
export function mockFetch(routes: [string, Route][], status = 200) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const match = routes.find(([part]) => url.includes(part));
    let body = match ? match[1](url, init) : { detail: `no mock for ${url}` };
    let code = match ? status : 404;
    // A handler can set its own status: return { __status: 422, body: {...} }.
    if (body && typeof body === "object" && "__status" in body) {
      code = Number((body as { __status: number }).__status);
      body = (body as unknown as { body: unknown }).body;
    }
    return { ok: code < 400, status: code, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Minimal XMLHttpRequest stand-in that answers every upload with `response`. */
export function mockUpload(response: unknown, status = 200): string[] {
  const opened: string[] = [];
  class FakeXHR {
    upload: { onprogress: ((e: unknown) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    status = status;
    responseText = JSON.stringify(response);
    open(_method: string, url: string) {
      opened.push(url);
    }
    send() {
      queueMicrotask(() => this.onload?.());
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return opened;
}
