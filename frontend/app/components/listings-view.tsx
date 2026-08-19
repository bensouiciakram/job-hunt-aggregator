"use client";

import { useState } from "react";

import ApplyButton, { type OutcomeValue } from "./apply-button";

export type ListingItem = {
  id: number;
  title: string;
  company: string;
  url: string;
  published_at: string | null;
  source: { name: string; adapter_key: string } | null;
  status: string;
  keywords: string[];
  interest_score: number;
  signals: {
    cross_posted: boolean;
    churn_possible: boolean;
    growth_possible: boolean;
  };
};

type Props = {
  initialItems: ListingItem[];
  bucket: "new" | "all";
  keyword: string;
  page: number;
};

export default function ListingsView({ initialItems, bucket, keyword, page }: Props) {
  const [items, setItems] = useState(initialItems);
  const [outcomes, setOutcomes] = useState<Record<number, string>>({});

  function onApplied(listingId: number) {
    setItems((current) =>
      bucket === "new"
        ? current.filter((item) => item.id !== listingId)
        : current.map((item) =>
            item.id === listingId ? { ...item, status: "applied" } : item,
          ),
    );
  }

  function onOutcome(listingId: number, outcome: OutcomeValue) {
    setOutcomes((current) => ({ ...current, [listingId]: outcome }));
  }

  const emptyCopy = keyword
    ? "No listings match your search."
    : bucket === "new"
      ? "No new listings in the last 24 hours."
      : page > 1
        ? "No more pages."
        : "No listings yet. The collector has not found any postings.";

  if (items.length === 0) {
    return (
      <div className="mt-8 rounded-lg border border-zinc-200 bg-zinc-50 p-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-400">
        {emptyCopy}
      </div>
    );
  }

  return (
    <ul className="mt-8 divide-y divide-zinc-200 dark:divide-zinc-800">
      {items.map((item) => {
        const href = /^https?:$/i.test(new URL(item.url).protocol)
          ? item.url
          : undefined;
        return (
          <li key={item.id} className="py-5" data-row="listing">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="break-words text-lg font-medium">{item.title}</h2>
              <ScoreChip score={item.interest_score} />
              {item.source && (
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {item.source.name}
                </span>
              )}
              <SignalChips signals={item.signals} />
            </div>
            <p className="mt-1 break-words text-sm text-zinc-600 dark:text-zinc-400">
              {item.company} · {formatRelative(item.published_at)}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  Open posting
                </a>
              ) : (
                <span className="inline-block break-words text-sm text-zinc-500 dark:text-zinc-400">
                  {item.url}
                </span>
              )}
              <ApplyButton
                listingId={item.id}
                applied={item.status === "applied"}
                outcome={outcomes[item.id] ?? null}
                onApplied={onApplied}
                onOutcome={onOutcome}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ScoreChip({ score }: { score: number }) {
  if (typeof score !== "number") return null;
  const tone =
    score >= 70
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
      : score < 40
        ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200"
        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span
      title="Interest score"
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}
    >
      {score}
    </span>
  );
}

function SignalChips({
  signals,
}: {
  signals: ListingItem["signals"];
}) {
  const labels: [keyof ListingItem["signals"], string][] = [
    ["cross_posted", "cross-posted"],
    ["churn_possible", "churn?"],
    ["growth_possible", "growth?"],
  ];
  return (
    <>
      {labels.map(([key, label]) =>
        signals[key] ? (
          <span
            key={key}
            data-signal={key}
            className="rounded-full border border-zinc-300 px-2 py-0.5 text-xs text-zinc-500 dark:border-zinc-700 dark:text-zinc-400"
          >
            {label}
          </span>
        ) : null,
      )}
    </>
  );
}

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