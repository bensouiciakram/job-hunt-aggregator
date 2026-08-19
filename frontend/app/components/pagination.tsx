"use client";

import { useRouter } from "next/navigation";

type Props = { page: number; hasNext: boolean; keyword: string; bucket: "new" | "all" };

export default function PaginationControls({ page, hasNext, keyword, bucket }: Props) {
  const router = useRouter();

  function href(targetPage: number) {
    const params = new URLSearchParams();
    if (bucket !== "new") params.set("bucket", bucket);
    if (targetPage > 1) params.set("page", String(targetPage));
    if (keyword) params.set("keyword", keyword);
    const qs = params.toString();
    return `/${qs ? `?${qs}` : ""}`;
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-zinc-500 dark:text-zinc-400">Page {page}</span>
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => router.push(href(page - 1))}
        className="rounded-md border border-zinc-300 px-3 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700"
      >
        Prev
      </button>
      <button
        type="button"
        disabled={!hasNext}
        onClick={() => router.push(href(page + 1))}
        className="rounded-md border border-zinc-300 px-3 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700"
      >
        Next
      </button>
    </div>
  );
}