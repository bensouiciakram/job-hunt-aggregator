"use client";

import { useRouter } from "next/navigation";
import { useState, type FocusEvent, type FormEvent } from "react";

export default function SearchBox({
  keyword,
  bucket,
}: {
  keyword: string;
  bucket: "new" | "all";
}) {
  const router = useRouter();
  const [value, setValue] = useState(keyword);

  function pushKeyword(next: string) {
    const params = new URLSearchParams();
    if (bucket !== "new") params.set("bucket", bucket);
    if (next) params.set("keyword", next);
    const qs = params.toString();
    router.push(`/${qs ? `?${qs}` : ""}`);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    pushKeyword(value.trim());
  }

  function onBlur(event: FocusEvent<HTMLInputElement>) {
    const next = event.target.value.trim();
    if (next !== keyword) {
      pushKeyword(next);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex items-center gap-2">
      <input
        type="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onBlur={onBlur}
        placeholder="Search by title or company"
        className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
      />
      <button
        type="submit"
        className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        Search
      </button>
    </form>
  );
}