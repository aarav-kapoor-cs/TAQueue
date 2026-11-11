# Dev image. A production image would run `npm run build` and serve dist/ with nginx.
FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
