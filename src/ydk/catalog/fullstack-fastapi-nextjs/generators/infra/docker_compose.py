#!/usr/bin/env python3
"""Generator: produces docker-compose.yml for fullstack project.

Reads config component for project name and database settings.
Outputs a docker-compose.yml with backend, frontend, and postgres services.
"""

import json
import os

import yaml

# Read config component
config_path = os.environ.get("YDK_COMPONENT_CONFIG", "")
config = {}
if config_path:
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

# Read init answers for project name fallback
init_answers = json.loads(os.environ.get("YDK_INIT_ANSWERS", "{}"))
project_name = config.get("project_name", init_answers.get("project_name", "myapp"))
db_name = config.get("database_name", f"{project_name}_db")
db_user = config.get("database_user", "postgres")
db_port = config.get("database_port", 5432)
backend_port = config.get("backend_port", 8000)
frontend_port = config.get("frontend_port", 3000)

compose = f"""\
version: "3.9"

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "{backend_port}:{backend_port}"
    environment:
      - DATABASE_URL=postgresql://{db_user}:${{POSTGRES_PASSWORD}}@db:{db_port}/{db_name}
      - ENVIRONMENT=development
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port {backend_port} --reload

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "{frontend_port}:{frontend_port}"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:{backend_port}
    volumes:
      - ./frontend:/app
      - /app/node_modules
    command: npm run dev

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB={db_name}
      - POSTGRES_USER={db_user}
      - POSTGRES_PASSWORD=${{POSTGRES_PASSWORD}}
    ports:
      - "{db_port}:{db_port}"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U {db_user}"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:

networks:
  default:
    name: {project_name}-network
"""

output = [{"path": "docker-compose.yml", "content": compose}]
print(json.dumps(output))
