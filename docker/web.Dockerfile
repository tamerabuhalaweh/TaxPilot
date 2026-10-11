FROM node:22-alpine AS build
WORKDIR /srv/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM node:22-alpine
WORKDIR /srv/apps/web
ENV NODE_ENV=production
COPY --from=build /srv/apps/web ./
EXPOSE 3000
CMD ["npm", "start"]
