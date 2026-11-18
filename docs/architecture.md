# Architecture, Licensing, and Hosting

This page records how optodraw is structured for an **open-core** model: the
library and the editor are open-source; a future hosted service keeps only its
business layer (accounts, storage, billing) private. It is the reference for
contributors and for anyone deploying optodraw as a website.

## Open-core model

optodraw follows the same pattern as Tidy3D (open client, proprietary cloud) and
tools like GitLab / Sentry / PostHog (open core, private "cloud" layer):

- **Open-source (this repo, BSD-3-Clause):** the full tool a researcher can
  `pip install` and run locally — including the visual editor.
- **Private (a separate deployment repo, not shipped to PyPI):** only the
  multi-tenant SaaS plumbing. It depends on `optodraw` and composes on top of it.

### What lives where

| Open-source (`optodraw`, pip/conda) | Private (hosted-deployment repo) |
| --- | --- |
| Core library: scene graph, components, renderers, schema, registry, GDS | Accounts / auth / SSO |
| The editor: frontend + local single-tenant FastAPI app (`optodraw/app`) | User project storage (database), cloud save/load |
| `optodraw-gui` launcher and desktop bundling | Billing, quotas, rate limiting, multi-tenant sessions |
| Downloadable desktop app archives (built from this code) | Collaboration/sharing, marketing site, deploy infra |

**Rule of thumb:** never put accounts, SSO, a database, or billing logic in the
open package. The shared-token lock for `--hosted` stays in the open app so a
public bind is not anonymous by default. Distributing prebuilt executables does
not require closing the source (KLayout, Inkscape, Blender all ship binaries
and full source).

## The deployment seam

The open app serves a single tenant. Local use (`optodraw-gui` on 127.0.0.1)
needs no auth by design; public hosting does. Two levels exist:

1. **Built-in token auth** — `optodraw-gui --hosted` requires a shared editor
   token (`--auth-token`, else `OPTODRAW_AUTH_TOKEN`, else an ephemeral
   generated one). Every `/api` route demands it via `Authorization: Bearer`,
   the `X-Optodraw-Token` header, or the cookie set by one-time browser login
   at `/auth/login?token=...`. Pass `--allow-anonymous-hosted` to opt out
   explicitly.
2. **Custom auth** — `create_app(hosted=True, auth_dependency=...)`. The
   `auth_dependency` is a FastAPI dependency applied to every `/api` route; a
   hosted repo passes its own per-user check (cookie/JWT/session).
3. **Sessions** — the open app uses one in-memory `SessionStore` and one
   "default" session. A custom authentication dependency does not isolate
   users. Use one instance per tenant until a hosted layer supplies a
   request-scoped session store and persistent storage.

```python
# In a private hosted repo (illustrative):
from optodraw.app.server import create_app

async def require_user(...):       # validate cookie/JWT, raise 401 otherwise
    ...

app = create_app(hosted=True, auth_dependency=require_user)
# This app still has one shared editor session; run one instance per tenant.
```

## Building native desktop apps

The same editor packages as native `.exe` / `.dmg` / `.appimage` from one
codebase. The bundle entry point is `packaging/desktop_main.py` (opens a
PyWebView window around the local server). A shared PyInstaller spec and per-OS
wrapping instructions live in [`packaging/README.md`](https://github.com/Acceluma/optodraw/blob/HEAD/packaging/README.md):

```bash
pip install "optodraw[desktop]" pyinstaller
cd packaging && pyinstaller optodraw.spec   # -> dist/optodraw/ (+ optodraw.app on macOS)
```

A conda recipe starter is in `conda/meta.yaml`. Native installers must be built
per-OS on CI — they cannot be cross-built.

## Deploying as a website

For a single-tenant hosted editor, use the launcher. It generates a token when
none is configured and prints a browser login URL:

```bash
optodraw-gui --hosted --host 0.0.0.0 --no-browser
```

Notes:

- Put it behind a reverse proxy (nginx/Caddy) for TLS and static caching.
- `hosted=True` enables CORS and requires `auth_token` or `auth_dependency`.
  Same-origin local use (`optodraw-gui` without `--hosted`) does not authenticate.
- `--allow-anonymous-hosted` explicitly disables the hosted authentication
  requirement. Do not use it on a public server.
- The in-memory session store is per-process and shared by all requests.
  Multi-worker and multi-user hosting needs a separate session design.

## Licensing

- The **library and editor stay BSD-3-Clause** — permissive licensing maximizes
  adoption, citation, and contribution, which matters most for a research tool.
- Permissive licensing lets anyone rehost the open code; the protection is simply
  that the **monetizable layer (accounts, storage, compute, collaboration) is
  private**, not visible to clone.
- AGPL-3.0 on the app (to force hosted forks to publish changes) is an option but
  usually overkill here and can deter corporate users; prefer BSD + a private
  hosted layer.
- Integrations respect upstream licenses: the gdsfactory ecosystem comes with a
  plain install; BlenderGDS (GPL) is interoperated with, never vendored.
