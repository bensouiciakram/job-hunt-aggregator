# Job Hunt Aggregator — Frontend

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4 frontend for the
Job Hunt Aggregator. It renders the listings stored by the Django backend
(`backend/`) via `GET /api/listings/`.

## Install

```bash
npm.cmd install
```

## Run

```bash
npm.cmd run dev
```

Open [http://localhost:3000](http://localhost:3000).

The Django backend must be running on port 8000 (see `backend/README.md`):

```bash
cd ../backend
uv run python manage.py runserver 8000
```

## Backend URL

The frontend reads the API base URL from the `NEXT_PUBLIC_API_URL` environment
variable and falls back to `http://127.0.0.1:8000`:

```bash
# .env.local (not committed) — override if the backend runs elsewhere
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Copy `.env.example` to `.env.local` to opt in explicitly.

## Scripts

- `npm.cmd run dev` — development server (port 3000)
- `npm.cmd run build` — production build
- `npm.cmd run start` — serve the production build
- `npm.cmd run lint` — ESLint

## Structure

- `app/page.tsx` — home page; a Server Component that fetches the listings API
  server-side (`cache: "no-store"`) and renders the list, the last-sweep stamp,
  an empty state, and a friendly error block when the backend is unreachable.
- `app/components/pagination.tsx` — client prev/next controls (URL-driven).
- `app/components/refresh-button.tsx` — client button re-fetching the current page.
- `app/components/search-box.tsx` — client keyword search (`&keyword=`).