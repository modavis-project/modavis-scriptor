# syntax=docker/dockerfile:1.7

FROM node:22.20.0-bookworm-slim@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:22.20.0-bookworm-slim@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e AS runtime

LABEL org.opencontainers.image.title="MODAVIS Scriptor" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.source="https://github.com/modavis-project/modavis-scriptor" \
      org.opencontainers.image.documentation="https://doi.org/10.5281/zenodo.22284008"

ENV NODE_ENV=production \
    NO_UPDATE_NOTIFIER=1

RUN npm install --global --omit=optional wrangler@4.128.0 \
    && mkdir -p /app /data \
    && chown -R node:node /app /data

WORKDIR /app
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/LICENSE /app/THIRD_PARTY_NOTICES.md ./
COPY --from=build --chown=node:node /app/LICENSES ./LICENSES

USER node
EXPOSE 3000
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["wrangler", "dev", "--config", "dist/server/wrangler.json", "--ip", "0.0.0.0", "--port", "3000", "--persist-to", "/data"]
