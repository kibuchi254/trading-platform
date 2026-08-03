# ATLAS — Admin Console

Next.js 16 + shadcn UI frontend for the ATLAS trading platform. Authenticates against the
backend JWT flow and visualizes/manages every ATLAS domain: terminals, trading (the
"books"), strategies, risk, AI, analytics, and admin.

Built on the [Studio Admin](https://github.com/arhamkhnz/next-shadcn-admin-dashboard)
template (MIT).

## Run locally

```bash
# 1. Backend must be running on :8000 (see ../README.md)
uvicorn platform.main:app --port 8000        # from repo root
python -m platform.bridge.server --port 9000

# 2. Frontend
cd frontend
cp .env.example .env.local   # adjust if your backend isn't on localhost:8000
bun install
bun run dev                 # http://localhost:3000
```

First sign-in: open `/auth/v1/register` to create your organization + admin, then `/auth/v1/login`.

## Architecture

- **API client** — `src/lib/api/client.ts` reads the JWT from the `atlas_access` cookie
  (set by the BFF), sends `Authorization: Bearer`, and auto-refreshes on 401. Typed
  endpoint wrappers in `endpoints.ts`; DTOs in `types.ts`.
- **WebSocket client** — `src/lib/api/ws.ts` streams `/ws/ticks` and `/ws/terminal-events`
  with `?token=`; auto-reconnect. `useTicks` / `useTerminalEvents` hooks.
- **Auth BFF** — `src/app/api/auth/{login,register,logout,refresh}/route.ts` proxy the
  backend auth endpoints and set the cookies. `src/middleware.ts` guards `/dashboard/*`.
- **Pages** — `src/app/(main)/dashboard/<area>/` (one folder per ATLAS domain). Sidebar
  nav in `src/navigation/sidebar/sidebar-items.ts`.

## Build / lint

```bash
bun run build     # next build (Turbopack + type-check)
bun run check     # biome lint/format
bun run dev
```

## Docker

The `frontend` service (`../docker/frontend.Dockerfile`) builds a standalone Next image and
is wired into `../docker/docker-compose.yml` behind nginx. See `../docs/DEPLOYMENT.md`.
