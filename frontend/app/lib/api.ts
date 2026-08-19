export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export async function applyToListing(
  listingId: number,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/listings/${listingId}/apply/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      cache: "no-store",
    });
  } catch {
    return { ok: false, error: "Could not reach the backend." };
  }
  if (!response.ok) {
    return { ok: false, error: `The API responded with HTTP ${response.status}` };
  }
  return { ok: true };
}