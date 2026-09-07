# Unverified: never built — Docker is not installed on the development machine.
# Placeholder until the Next.js app exists; `compose build web` will fail until then.
FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev || true
COPY . .
RUN npm run build || true
EXPOSE 3000
CMD ["npm", "start"]
