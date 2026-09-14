to fail gracefully — 401/404/empty-reply must surface as a tool error, not an
# hermes-chathub-connector

Hermes Agent plugin that exposes two static meta-tools for the ChatHub
connector platform. The plugin discovers and invokes the user's registered
connector tools through the ChatHub gateway; it does not connect to upstream
MCP servers or hold user OAuth tokens.

## Tools

Both tools belong to the `chathub` toolset:

- `list_chathub_tools`: list the available, fully prefixed connector tool names; accepts an optional `query` (space-separated keywords, grep-style OR matching against names/descriptions, case-insensitive).
- `exec_chathub_tools`: invoke one tool by its prefixed name and JSON arguments.

The entry-point name is `chathub-connector`, matching existing Hermes profiles.

## Gateway endpoints

Both calls go to the ChatHub gateway under the `be-api/` prefix — the only
`/api` family the ChatHub ingress routes to the API host:

- `GET  {gateway}/be-api/connectors/tools`
- `POST {gateway}/be-api/connectors/tools:call`

Every request carries `X-Turn-Secret` (re-read per call).

## Installation

Preferred installation is the pip package in the Hermes environment:

```bash
pip install hermes-chathub-connector
```

For local development, the directory form remains supported:

```bash
cp -R hermes-chathub-connector "$HERMES_HOME/plugins/chathub-connector"
```

The directory must contain `plugin.yaml` and the top-level `__init__.py`.

## Configuration

Enable the plugin and its toolset in Hermes `config.yaml`:

```yaml
plugins:
  enabled:
    - chathub-connector
platform_toolsets:
  cli:
    - chathub
  api_server:
    - chathub
connector:
  gateway_url: "http://127.0.0.1:44340"
```

`CHATHUB_GATEWAY_URL` overrides `connector.gateway_url`; otherwise the plugin
uses its built-in local gateway default. Each active turn must provide the
short-lived `CHATHUB_TURN_SECRET`, which is read again for every tool call.

The package intentionally declares no runtime dependencies. Hermes provides
`requests` in its environment, so installing this plugin does not change that
shared dependency.

## Development checks

```bash
python3 -m venv /tmp/plugvenv
/tmp/plugvenv/bin/pip install --no-deps .
/tmp/plugvenv/bin/pip install pytest   # optional; tests also run under unittest
/tmp/plugvenv/bin/python -m pytest tests/
/tmp/plugvenv/bin/python tests/test_register.py
python3 scripts/smoke_chathub_tools.py --help
```

`tests/test_endpoint_paths.py` pins both handlers to the `be-api/` endpoints
(the ingress routes only that prefix to the API host).
