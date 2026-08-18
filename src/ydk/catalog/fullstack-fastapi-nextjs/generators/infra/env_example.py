#!/usr/bin/env python3
"""Generator: produces .env.example for fullstack project.

Reads config component for project settings.
Outputs .env.example with all required environment variables.
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

# Check if an OpenAPI artifact path was passed
openapi_artifact = os.environ.get("YDK_ARTIFACT_OPENAPI", "")

env_content = f"""\
# {project_name} — Environment Variables
# Copy this file to .env and fill in the values.

# Database
POSTGRES_DB={db_name}
POSTGRES_USER={db_user}
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://{db_user}:changeme@localhost:{db_port}/{db_name}

# Backend
BACKEND_PORT={backend_port}
ENVIRONMENT=development
SECRET_KEY=changeme-generate-a-real-secret

# Frontend
FRONTEND_PORT={frontend_port}
NEXT_PUBLIC_API_URL=http://localhost:{backend_port}
"""

if openapi_artifact:
    env_content += f"""
# OpenAPI (generated)
OPENAPI_SPEC_PATH={openapi_artifact}
"""

output = [{"path": ".env.example", "content": env_content}]
print(json.dumps(output))
