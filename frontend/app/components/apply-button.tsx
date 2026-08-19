"use client";

import { useState } from "react";

import { applyToListing, setOutcome } from "../lib/api";

export type OutcomeValue = "response" | "interview" | "silence" | "";

const OUTCOME_LABELS: Record<string, string> = {
  response: "response",
  interview: "interview",
  silence: "silence",
};

type Props = {
  listingId: number;
  applied: boolean;
  outcome: string | null;
  onApplied: (listingId: number) => void;
  onOutcome: (listingId: number, outcome: OutcomeValue) => void;
};

export default function ApplyButton({
  listingId,
  applied,
  outcome,
  onApplied,
  onOutcome,
}: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (applied) {
    return (
      <span className="inline-flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200">
          Applied{outcome ? ` · ${outcome}` : ""}
        </span>
        {(["response", "interview", "silence"] as const).map((value) => (
          <button
            key={value}
            type="button"
            disabled={pending}
            onClick={async () => {
              setPending(true);
              setError(null);
              const next = outcome === value ? "" : value;
              const result = await setOutcome(listingId, next);
              if (result.ok) {
                onOutcome(listingId, next);
              } else {
                setError(result.error);
              }
              setPending(false);
            }}
            className={
              outcome === value
                ? "rounded-md border border-zinc-400 px-2 py-0.5 text-xs font-medium hover:bg-zinc-100 disabled:cursor-wait disabled:opacity-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
                : "rounded-md border border-zinc-300 px-2 py-0.5 text-xs text-zinc-500 hover:bg-zinc-100 disabled:cursor-wait disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            }
          >
            {OUTCOME_LABELS[value]}
          </button>
        ))}
        {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
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