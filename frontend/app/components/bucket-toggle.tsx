"use client";

import { useRouter } from "next/navigation";

type Props = { bucket: "new" | "all"; keyword: string; page: number };

export default function BucketToggle({ bucket, keyword, page }: Props) {
  const router = useRouter();

  function href(next: "new" | "all") {
    const params = new URLSearchParams();
    if (next !== "new") params.set("bucket", next);
    if (page > 1) params.set("page", String(page));
    if (keyword) params.set("keyword", keyword);
    const qs = params.toString();
    return `/${qs ? `?${qs}` : ""}`;
  }

  const base =
    "rounded-md border px-3 py-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ";
  const active =
    "border-blue-600 bg-blue-600 text-white dark:border-blue-500 dark:bg-blue-500";
  const idle =
    "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800";

  return (
    <div className="flex items-center gap-2" role="group" aria-label="Listings bucket">
      <button
        type="button"
        disabled={bucket === "new"}
        onClick={() => router.push(href("new"))}
        className={base + (bucket === "new" ? active : idle)}
      >
        New (24h)
      </button>
      <button
        type="button"
        disabled={bucket === "all"}
        onClick={() => router.push(href("all"))}
        className={base + (bucket === "all" ? active : idle)}
      >
        All
      </button>
    </div>
  );
}