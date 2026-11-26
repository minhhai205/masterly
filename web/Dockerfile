FROM node:24-bookworm-slim AS build

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:24-bookworm-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

COPY --from=build --chown=node:node /app/package.json /app/next.config.js ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public

USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
