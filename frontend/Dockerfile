# nanoCAS frontend image: production build served by nginx.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Empty API endpoint => same-origin requests; nginx proxies /api traffic
# to the backend container (see nginx.conf).
ARG REACT_APP_API_ENDPOINT=""
ENV REACT_APP_API_ENDPOINT=${REACT_APP_API_ENDPOINT}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
