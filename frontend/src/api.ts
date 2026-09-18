export type ApiRequest = (path: string, init?: RequestInit) => Promise<Response>;

export function defaultRequest(token: string): ApiRequest {
  return (path, init = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init.headers },
  });
}

export async function responseError(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({}));
  return body.error || fallback;
}
