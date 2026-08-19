import BucketToggle from "./components/bucket-toggle";
import ListingsView, { type ListingItem } from "./components/listings-view";
import PaginationControls from "./components/pagination";
import RefreshButton from "./components/refresh-button";
import SearchBox from "./components/search-box";
import { API_URL } from "./lib/api";

type ListingsData = {
  items: ListingItem[];
  page: number;
  has_next: boolean;
  total: number;
  last_sweep_at: string | null;
};

type ListingsResponse =
  | { ok: true; data: ListingsData; error: null }
  | { ok: false; error: string };

function formatRelative(iso: string | null): string {
  if (!iso) return "never";
  const diffSeconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffSeconds < 60) return "just now";
  const minutes = Math.round(diffSeconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString();
}

async function fetchListings(
  page: number,
  keyword: string,
  bucket: "new" | "all",
): Promise<ListingsResponse> {
  const params = new URLSearchParams();
  params.set("bucket", bucket);
  if (page > 1) params.set("page", String(page));
  if (keyword) params.set("keyword", keyword);
  const qs = params.toString();
  const url = `${API_URL}/api/listings/${qs ? `?${qs}` : ""}`;
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    return { ok: false, error: `The API responded with HTTP ${response.status}` };
  }
  return response.json();
}

function parseBucket(value: string | string[] | undefined): "new" | "all" {
  return typeof value === "string" && value === "all" ? "all" : "new";
}

export default async function HomePage(props: {
  searchParams: Promise<{
    page?: string | string[];
    keyword?: string | string[];
    bucket?: string | string[];
  }>;
}) {
  const searchParams = await props.searchParams;
  const rawPage = searchParams.page;
  const page =
    typeof rawPage === "string" && /^\d+$/.test(rawPage) ? Math.max(1, Number(rawPage)) : 1;
  const rawKeyword = searchParams.keyword;
  const keyword = typeof rawKeyword === "string" ? rawKeyword.trim() : "";
  const bucket = parseBucket(searchParams.bucket);

  let data: ListingsData | null = null;
  let error: string | null = null;
  try {
    const result = await fetchListings(page, keyword, bucket);
    if (result.ok) {
      data = result.data;
    } else {
      error = result.error;
    }
  } catch {
    error = `Could not reach the backend at ${API_URL}. Is Django running?`;
  }

  return (
    <div className="flex min-h-full flex-col">
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <h1 className="text-3xl font-semibold tracking-tight">Job Listings</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Last sweep: {data ? formatRelative(data.last_sweep_at) : "never"} <RefreshButton />
          </p>
        </header>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-4">
            <SearchBox key={`${keyword}-${bucket}`} keyword={keyword} bucket={bucket} />
            <BucketToggle bucket={bucket} keyword={keyword} page={page} />
          </div>
          {data && (
            <PaginationControls
              page={data.page}
              hasNext={data.has_next}
              keyword={keyword}
              bucket={bucket}
            />
          )}
        </div>

        {error ? (
          <div className="mt-8 rounded-lg border border-red-300 bg-red-50 p-6 text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
            <h2 className="font-semibold">Could not load listings</h2>
            <p className="mt-1 text-sm">{error}</p>
          </div>
        ) : data ? (
          <ListingsView
            key={`${bucket}-${keyword}-${data.page}`}
            initialItems={data.items}
            bucket={bucket}
            keyword={keyword}
            page={data.page}
          />
        ) : null}
      </main>
    </div>
  );
}