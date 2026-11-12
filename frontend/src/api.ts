export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? undefined
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: 'The backend returned an unreadable response.',
    }));
    const message =
      typeof error.detail === 'string'
        ? error.detail
        : Array.isArray(error.detail)
          ? error.detail.map((e: { msg: string }) => e.msg).join(' ')
          : 'Request failed.';
    throw new ApiError(message, response.status);
  }
  return response.json();
}
