FROM node:22-alpine AS build
WORKDIR /srv/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

# Runtime image carries production dependencies only: dev/build tooling
# (vitest, vite, playwright, typescript) never ships to deployed containers.
FROM node:22-alpine
WORKDIR /srv/apps/web
ENV NODE_ENV=production
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /srv/apps/web/.next ./.next
COPY --from=build /srv/apps/web/next.config.mjs ./next.config.mjs
EXPOSE 3000
CMD ["npm", "start"]
