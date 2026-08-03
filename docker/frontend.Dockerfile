# ATLAS Frontend image — Next.js 16 (standalone output) with bun.
# Multi-stage: deps → build → runner. Uses oven/bun for a small, fast image.

FROM oven/bun:1-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

FROM oven/bun:1-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
# NEXT_PUBLIC_* are baked at build time. For single-VM behind nginx, the browser
# reaches the API on the same origin (/api → nginx → api), so default to the
# origin-relative form by leaving these empty; override with build args for a
# split-host deploy.
ARG NEXT_PUBLIC_API_URL=""
ARG NEXT_PUBLIC_WS_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN bun run build

FROM oven/bun:1-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001 -G nodejs
# Next standalone output copies the minimal server into .next/standalone
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["bun", "server.js"]
