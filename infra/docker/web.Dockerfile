# Static dashboard image. Build context: repo root. Built OK locally (run 20261010T154653Z).
FROM node:22-slim AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web apps/web
COPY packages/contracts packages/contracts
RUN npm ci --workspace @archipelago/web --workspace @archipelago/contracts --include-workspace-root \
 && npm run build -w @archipelago/web

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY infra/proxy/web-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
