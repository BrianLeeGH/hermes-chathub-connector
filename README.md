# chathub-hermes-toolset

ChatHub connector-platform **device-side plugin** for Hermes — two static
meta-tools that bridge an agent on the Hermes device to the ChatHub connector
gateway over HTTP, authenticated per call with the current turn secret.

Design source: `chathub-connector-platform-design.md` §8 (meta-tool mode D5,
turn-secret D3, threat model §2). No Hermes source is modified — this is a
standalone **user plugin** deployed to `$HERMES_HOME/plugins/chathub-connector/`.

## Tools (toolset: `chathub`)

| Tool | Schema | Behaviour |
|---|---|---|
| `list_chathub_tools()` | no args | `get_secret("CHATHUB_TURN_SECRET")` → `GET {gateway}/api/connectors/tools` (header `X-Turn-Secret`) → returns the JSON catalog (full prefixed names, e.g. `ms365/get_current_user`) |
| `exec_chathub_tools(name, args)` | `{name: string, args: object\|string}` | same secret → `POST {gateway}/api/connectors/tools:call` with body `{name, args}` → returns the result string |

* The secret is read **on every call** (turn-level freshness, §8).
* Non-2xx responses (401/404/429/502/…) are returned to the model as tool
  error results (never raised), per design §6.5.2.
* The plugin never knows individual connectors, never connects upstream, and
  never holds user OAuth tokens (threat model §2 R1-R5).

## Gateway base URL resolution

Precedence:
1. env `CHATHUB_GATEWAY_URL` (deployment override)
2. Hermes config.yaml custom key `connector.gateway_url` (static, shared by
   every hermes process; config.yaml never holds secrets)
3. built-in default `http://127.0.0.1:44340` (local integration backend)

Rationale (recorded in `reports/t6-plugin.md`): the URL is static deployment
config, so it is resolved from plain env/config — **not** through
`get_secret()` (which is reserved for the turn secret, profile-scoped).

## Layout

```
plugin.yaml      # manifest: name chathub-connector, kind standalone
__init__.py      # register(ctx) -> registers both tools into toolset "chathub"
tools.py         # self-contained handlers (imports hermes top-level modules only)
scripts/
  smoke_chathub_tools.py   # smoke test (runs inside the Hermes venv)
```

## Deploy / enable / verify (Hermes-WSL)

```bash
# 1. push the plugin dir to the Hermes install
#    $HERMES_HOME/plugins/chathub-connector/  (HERMES_HOME=/root/.hermes)
# 2. config.yaml (same file read by gateway/serve/dashboard):
#      plugins:
#        enabled: [... existing ..., "chathub-connector"]
#      platform_toolsets:
#        cli:  [... existing ..., "chathub"]       # TUI serve sessions (chathub)
#        api_server: [... existing ..., "chathub"]
#      connector:
#        gateway_url: "http://127.0.0.1:44340"     # optional static config
# 3. restart hermes-serve + hermes-gateway
# 4. verify: hermes plugins list | grep chathub ; hermes tools | grep chathub
```

## Smoke

```bash
/usr/local/lib/hermes-agent/venv/bin/python \
  scripts/smoke_chathub_tools.py \
  --plugin-dir /root/.hermes/plugins/chathub-connector
```

The script injects a throwaway `CHATHUB_TURN_SECRET`, runs list + exec against
a local mock HTTP server (asserts `X-Turn-Secret` header + body shape + 401
passthrough), then probes the real gateway URL (old LocalSIT binary is expected
to fail gracefully — 401/404/empty-reply must surface as a tool error, not an
exception).
