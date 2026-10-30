# syntax=docker/dockerfile:1.7

FROM node:22.23.4-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:22.23.4-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS runtime

LABEL org.opencontainers.image.title="MODAVIS Scriptor" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.source="https://github.com/modavis-project/modavis-scriptor" \
      org.opencontainers.image.documentation="https://doi.org/10.5281/zenodo.22284008"

ENV NODE_ENV=production \
    NO_UPDATE_NOTIFIER=1 \
    PATH="/app/node_modules/.bin:${PATH}"

RUN mkdir -p /app /data && chown -R node:node /app /data

WORKDIR /app
COPY --chown=node:node package.json package-lock.json ./
USER node
# Wrangler is a runtime dependency: install its complete tree from the same lock
# as the build instead of resolving a separate global dependency tree.
RUN npm ci --omit=dev --no-fund && npm cache clean --force
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/LICENSE /app/THIRD_PARTY_NOTICES.md ./
COPY --from=build --chown=node:node /app/LICENSES ./LICENSES

USER node
EXPOSE 3000
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["wrangler", "dev", "--config", "dist/server/wrangler.json", "--ip", "0.0.0.0", "--port", "3000", "--persist-to", "/data"]
