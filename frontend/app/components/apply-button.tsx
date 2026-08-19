"use client";

import { useState } from "react";

import { applyToListing } from "../lib/api";

type Props = {
  listingId: number;
  applied: boolean;
  onApplied: (listingId: number) => void;
};

export default function ApplyButton({ listingId, applied, onApplied }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (applied) {
    return (
      <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200">
        Applied
      </span>
    );
  }

  async function onApply() {
    setPending(true);
    setError(null);
    const result = await applyToListing(listingId);
    if (result.ok) {
      onApplied(listingId);
    } else {
      setError(result.error);
    }
    setPending(false);
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={pending}
        onClick={onApply}
        className="rounded-md border border-zinc-300 px-2.5 py-0.5 text-xs font-medium hover:bg-zinc-100 disabled:cursor-wait disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        {pending ? "Applying…" : "Mark as applied"}
      </button>
      {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
    </span>
  );
}