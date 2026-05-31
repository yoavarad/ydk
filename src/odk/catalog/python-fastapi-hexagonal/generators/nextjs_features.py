#!/usr/bin/env python3
"""Generate FSD feature slices from frontend-features.yaml (Next.js App Router).

Follows Cosden pattern: short focused files, requestHandler for API calls,
typed success/error discrimination, components under 80 lines.
"""

import json
import os
from pathlib import Path

import yaml


def to_camel(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def to_pascal(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts)


def generate_api_ts(name: str, api_calls: list[str]) -> str:
    """Generate api.ts using requestHandler pattern — typed success/error."""
    if not api_calls:
        return f"""// API calls for {name} feature
// Add your requestHandler calls here:
// import {{ apiClient }} from '@/shared/api/client';
// import {{ requestHandler }} from '@/shared/api/requestHandler';
//
// export const get{to_pascal(name)} = requestHandler(
//   () => apiClient.get('/{name}'),
// );
"""

    lines = [
        f"// API calls for {name} feature",
        "import { apiClient } from '@/shared/api/client';",
        "import { requestHandler } from '@/shared/api/requestHandler';",
        "",
    ]
    for call in api_calls:
        camel_call = to_camel(call)
        lines.append(f"export const {camel_call} = requestHandler(")
        lines.append(f"  () => apiClient.get('/{call.replace('_', '-')}'),")
        lines.append(");")
        lines.append("")
    return "\n".join(lines)


def generate_component_tsx(name: str, component_name: str, description: str) -> str:
    """Generate a focused component under 80 lines."""
    return f"""'use client';
import {{ useState }} from 'react';

type Props = {{
  // TODO: add props
  onSuccess?: () => void;
}};

/**
 * {component_name} — {description or name}
 * Max 80 lines. Extract sub-components if this grows larger.
 */
export function {component_name}({{ onSuccess }}: Props) {{
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading) return <div>Loading...</div>;
  if (error) return <div className="text-red-500">{{error}}</div>;

  return (
    <div>
      {{/* TODO: implement {description or name} UI */}}
    </div>
  );
}}
"""


def _derive_domain(feature: dict) -> str:
    """Derive the domain group for a feature.

    Uses explicit 'domain' field if present, otherwise infers from
    the feature's route or API call paths.
    """
    if feature.get("domain"):
        return feature["domain"]

    # Try to infer from route
    route = feature.get("route", "")
    if route:
        parts = route.strip("/").split("/")
        # Skip 'api' prefix
        if parts and parts[0] == "api":
            parts = parts[1:]
        if parts:
            return parts[0]

    # Try to infer from api_calls
    api_calls = feature.get("api_calls", [])
    if api_calls:
        # First API call path might indicate domain
        call = api_calls[0]
        parts = call.strip("/").split("/")
        if parts and parts[0] == "api":
            parts = parts[1:]
        if parts:
            return parts[0].replace("_", "-")

    # Fall back to feature name prefix
    name = feature.get("name", "")
    parts = name.split("-")
    if len(parts) > 1:
        return parts[0]

    return "shared"


def generate_feature(feature: dict) -> list[dict]:
    name = feature["name"]
    component_name = to_pascal(name)
    api_calls = feature.get("api_calls", [])
    description = feature.get("description", "")

    # Group under domain directory
    domain = _derive_domain(feature)

    # Derive the sub-feature name (strip domain prefix if present)
    sub_name = name
    domain_prefix = domain.replace("-", "_") + "-"
    name_normalized = name.replace("-", "_") + "-"
    if name_normalized.startswith(domain_prefix.replace("-", "_")):
        sub_name = name[len(domain_prefix.rstrip("-")) :]
        sub_name = sub_name.lstrip("-").lstrip("_") or name

    base_path = f"{domain}/{sub_name}"

    files = []

    # index.ts barrel export
    files.append(
        {
            "path": f"{base_path}/index.ts",
            "content": f"""export {{ {component_name} }} from './{component_name}';
""",
        }
    )

    # api.ts — requestHandler pattern
    files.append(
        {
            "path": f"{base_path}/api.ts",
            "content": generate_api_ts(name, api_calls),
        }
    )

    # Main component (no separate model.ts — keep logic inline per Cosden pattern)
    files.append(
        {
            "path": f"{base_path}/{component_name}.tsx",
            "content": generate_component_tsx(name, component_name, description),
        }
    )

    return files


def main():
    path = os.environ.get("ODK_COMPONENTS_FRONTEND_FEATURE", "")
    if not path or not Path(path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    output = []
    for feature in data.get("features", []):
        output.extend(generate_feature(feature))
    print(json.dumps(output))


if __name__ == "__main__":
    main()
