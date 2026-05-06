# Agent CLI Architecture

The Rotunda agent CLI is designed for shell-native agents that need a browser
they can control across multiple command invocations. A command like
`rotunda agent click <ref>` may run in a different process from the command that
created the browser, so the CLI has to keep a small control plane alive between
calls.

The current design has three goals:

- exactly one Rotunda agent daemon per host/user
- durable browser profiles without leaking stale pages or element refs
- deterministic discovery from short-lived CLI processes

## Components

### CLI process

Every `rotunda agent ...` invocation starts as a short-lived Python process in
`rotunda.__main__`.

The CLI is responsible for:

- resolving profile, context, page, element, and download refs
- discovering or starting the host daemon
- sending authenticated HTTP requests to the daemon
- recording returned resource indexes for later commands

The CLI should not keep browser objects in memory. Anything that must survive
between command invocations is either durable profile data or daemon-owned
runtime data.

### Agent daemon

The daemon runs as:

```text
python -m rotunda.agent.daemon
```

It owns the Playwright runtime, Rotunda browser process, persistent browser
context, pages, dialog state, DOM serializers, and captured downloads. The CLI
talks to it through a small localhost HTTP API.

The daemon exposes two classes of endpoints:

- `/identity`, unauthenticated and minimal, used only to identify Rotunda agents
  during port discovery
- authenticated control endpoints such as `/ping`, `/new-context`, `/new-page`,
  `/describe`, `/click`, `/fill`, `/shutdown`, and related browser actions

### Browser process

The daemon launches the installed Rotunda Firefox build through Playwright's
Firefox/Juggler path. For each active profile it opens one persistent context
using that profile's `user_data_dir`.

The daemon may know multiple pages, but the host singleton rule means only one
agent daemon is active at a time for the local user.

## Files Under `~/.rotunda/agent`

The agent CLI intentionally separates durable and runtime state.

Durable state:

- `profiles/<profile-id>/profile.json`
- `profiles/<profile-id>/browser-data/`
- `auth.json`

Runtime state:

- `daemon.json`
- `sessions/<profile-id>.json`
- non-profile entries in `resources.json`
- `logs/*.ready.json`
- `logs/<profile-id>.log`

Profiles are meant to survive daemon restarts. Contexts, pages, element refs,
downloads, and daemon sessions are not. If the daemon is gone or stale, those
runtime resources are discarded.

## Host Singleton And Discovery

The daemon binds to a deterministic localhost port range:

```text
127.0.0.1:51240-51271
```

Startup uses an exclusive `startup.lock` file so concurrent CLI calls do not
race into multiple daemon launches. Inside that lock, the CLI:

1. Loads or creates the stable per-user auth token.
2. Checks `daemon.json` for a fresh heartbeat and tries that port first.
3. Scans the fixed port range for `/identity`.
4. Accepts only responses with `service: "rotunda-agent"`.
5. Confirms control by calling authenticated `/ping`.
6. Reuses the daemon if it is already serving the requested profile.
7. If a daemon is active for another profile, asks it to shut down and waits for
   the port to clear.
8. Clears runtime state and starts a fresh daemon for the requested profile.

This gives us deterministic discovery without relying on stale random-port
session files. It also lets ordinary commands recover after a crash: if no live
daemon responds, stale runtime state is removed before a new daemon is started.

## Authentication

`auth.json` stores a stable per-user token and is created with `0600`
permissions. The CLI launches the daemon with `--token-file` so the token does
not appear in the process command line.

Discovery uses unauthenticated `/identity`, but that endpoint only returns
metadata needed to decide whether the process is a Rotunda agent. All control
endpoints require:

```text
Authorization: Bearer <token>
```

If the CLI finds a Rotunda agent on the port range but the token is rejected, it
treats that as a hard error instead of silently attaching to an unknown process.

## Heartbeat And Stale Cleanup

The daemon writes `daemon.json` and `sessions/<profile-id>.json` when it starts.
It then updates `update_tick` every few seconds.

`AgentStore` treats daemon state as stale when `update_tick` is older than the
configured threshold. On stale state it removes:

- session JSON files
- context/page/element/download resources
- `daemon.json`

It keeps profiles intact.

This is the minimum guardrail that prevents previous-run state from leaking into
fresh CLI sessions. A stale page index should never resolve after the daemon that
owned that page has disappeared.

## Resource Indexes

`resources.json` maps short numeric indexes and labels to concrete IDs:

```text
[1] profile prof_...
[2] context ctx_...
[3] page page_...
[4] element abc123 button "Submit"
```

Profile resources are durable. Runtime resources carry the daemon
`runtime_id`, which is the daemon `instance_id` that produced them.

The common flow is:

1. `new-profile` creates and registers a durable profile.
2. `new-context` starts or attaches to the daemon, creates/adopts the persistent
   browser context, and registers the context plus current pages.
3. `describe` serializes the page DOM and replaces that page's element refs.
4. Action commands resolve refs from `resources.json`, call the daemon, then
   refresh page and element resources from the response.

Element refs are intentionally scoped to the latest `describe` for a page. When
a page is described again, old element children for that page are removed before
new refs are stored.

## Lifecycle Examples

### First command for a profile

```text
CLI -> startup lock
CLI -> scan port range
CLI -> no daemon found
CLI -> clear runtime state
CLI -> spawn daemon
daemon -> bind first free port in range
daemon -> write session and daemon heartbeat
CLI -> authenticated command request
```

### Reusing the same profile

```text
CLI -> startup lock
CLI -> read fresh daemon.json
CLI -> /identity on daemon port
CLI -> authenticated /ping
CLI -> profile matches
CLI -> reuse daemon
```

### Switching profiles

```text
CLI -> startup lock
CLI -> find active daemon
CLI -> active profile differs
CLI -> authenticated /shutdown
CLI -> wait for daemon to exit
CLI -> clear runtime state
CLI -> spawn daemon for requested profile
```

### Stale daemon files

```text
CLI -> AgentStore startup
CLI -> daemon.json update_tick is stale
CLI -> remove sessions and runtime resources
CLI -> keep profiles
```

## Failure Modes

Port occupied by another service:

- `/identity` will not match `service: "rotunda-agent"`, so the CLI skips it and
  tries the next port.

Daemon crashed:

- heartbeat stops, daemon state becomes stale, runtime resources are pruned.

Daemon alive but wrong auth token:

- discovery succeeds, authenticated `/ping` fails, and the CLI raises an error.
  This avoids controlling a process owned by a different user/configuration.

CLI interrupted while daemon is starting:

- startup is protected by `startup.lock`; later commands rediscover the daemon
  through the port range or prune stale state after the heartbeat expires.

Browser process crashed:

- daemon commands return an error through the HTTP API. A later daemon restart
  clears runtime refs before rebuilding the browser context.

## Implementation Map

- `pythonlib/rotunda/__main__.py`: user-facing `rotunda agent` commands and
  resource registration
- `pythonlib/rotunda/agent/client.py`: daemon discovery, startup lock, daemon
  launch, authenticated HTTP client
- `pythonlib/rotunda/agent/daemon.py`: HTTP server, Playwright/Rotunda runtime,
  heartbeat writer, browser actions
- `pythonlib/rotunda/agent/store.py`: profile/session/resource/auth/daemon
  state storage and stale cleanup
- `pythonlib/rotunda/agent/paths.py`: agent state paths
- `pythonlib/rotunda/agent/runtime.py`: shared host, port range, service name,
  and heartbeat constants
- `pythonlib/rotunda/agent/dom_serializer.py`: page DOM snapshotting and stable
  element refs

