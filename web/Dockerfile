FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev=false

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_BFF_URL=http://localhost:8080
ENV NEXT_PUBLIC_BFF_URL=$NEXT_PUBLIC_BFF_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
