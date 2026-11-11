# DEMO ONLY: this runs the Vite dev server. A production image would run
# `npm run build` and serve the dist/ folder with nginx.
FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
