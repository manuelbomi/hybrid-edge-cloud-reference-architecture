# Dashboard UI image: builds the Vite React-TS app, then serves the
# static bundle with nginx. Build context for this Dockerfile is
# `frontend/` (see the `dashboard-ui` service in
# ../docker-compose.cloud.yml), so paths below are relative to that dir.
#
# The cloud ingest API and edge local API URLs are baked into the JS
# bundle at build time (Vite inlines `import.meta.env.VITE_*` at build
# time, it cannot read them from the container at runtime), via build
# args. Defaults match the host-published ports used throughout
# README.md, since this static bundle runs in the *browser*, not inside
# the Docker network -- it must reach the APIs the same way your browser
# does, via localhost's published ports.

FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

ARG VITE_INGEST_API_URL=http://localhost:8080
ARG VITE_EDGE_API_URL=http://localhost:8000
ENV VITE_INGEST_API_URL=$VITE_INGEST_API_URL
ENV VITE_EDGE_API_URL=$VITE_EDGE_API_URL

RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
