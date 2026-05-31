# nextjs-fsd-shadcn

Ignition pack for Next.js 16 frontends using Feature-Sliced Design (FSD),
ShadCN v4, TanStack Query v5, SSE real-time events, Cognito PKCE auth,
react-hook-form + Zod forms, and MSW testing.

Native ODK ignition pack with component-driven generation.

## Generators

| ID                 | Description                                                |
|--------------------|------------------------------------------------------------|
| derive-features    | Derive frontend-features.yaml from openapi.json + pages   |
| typescript-types   | Entity types from OpenAPI spec components                  |
| openapi-sdk        | Typed SDK via @hey-api/openapi-ts                          |
| nextjs-features    | FSD feature slices from frontend-features                  |
| page-scaffolding   | 3-tier page scaffold (shell + container + hook)            |
| query-hooks        | TanStack Query hooks from openapi-spec                     |
| page-shells        | Next.js App Router routing shells                          |
| page-containers    | Smart container components                                 |
| widget-stubs       | Typed widget shells from frontend-features                 |
| navigation-config  | Navigation config and ROUTES constants                     |
| auth-provider      | Cognito PKCE auth provider                                 |
| msw-handlers       | MSW mock API handlers                                      |
| nextjs-api-client  | Typed API client from api-contracts                        |

## Templates

Jinja2 templates in `templates/` are consumed by the generators above:

- `entities/types.ts.j2` -- re-export types from generated SDK
- `features/query-hook.ts.j2` -- TanStack Query hook per domain
- `shared/query-keys.ts.j2` -- centralised query key factory
- `shared/navigation.ts.j2` -- navigation config and ROUTES
- `pages/page-shell.tsx.j2` -- thin App Router shell
- `pages/page-container.tsx.j2` -- smart container with Suspense
- `pages/page-hook.ts.j2` -- page-level data hook
