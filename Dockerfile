FROM node:24-bookworm-slim AS web
WORKDIR /app
RUN npm install -g pnpm@10.15.1
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json frontend/package.json
RUN pnpm install --frozen-lockfile
COPY frontend frontend
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
RUN pnpm build

FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.33
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend backend
COPY --from=web /app/frontend/dist frontend/dist
ENV PYTHONPATH=/app/backend
RUN useradd --create-home appuser
USER appuser
CMD ["sh", "-c", ".venv/bin/gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --access-logfile -"]
