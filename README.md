# Local agent containers

Manage persistent OpenCode, Hermes and OpenClaw containers with one `agents` command.
Hermes and OpenClaw use a local Ollama model and separate encrypted Iris chats. No hosted model account is needed.
The adapter invokes the agents' supported CLIs and preserves their sessions.
It does not replace either agent with a simple chatbot.

## Start

Requirements: Docker Compose, a running local Ollama server, and an installed
model with at least 65,536 tokens of context (Hermes requires 64K minimum). Inference is capped at 4,096 output tokens per call. These defaults target Docker Desktop on Apple Silicon. Iris currently
uses the released Linux x86_64 CLI under Docker's emulation; both agents run
natively on ARM64. Other hosts need Docker's equivalent emulation or a matching
released Iris binary, and a reachable Ollama host alias.

```sh
./agents setup --owner YOUR_NPUB
```

Setup detects a single installed KAT model, builds missing images, starts both
chat agents, and asks for your private Iris invite once without echoing it.
It does not download models. To select a different installed tag on first setup,
add `--model MODEL`; use `setup hermes` or `setup openclaw` to set up just one.
Existing `.env` model and network settings are preserved.

The returned direct-chat identity must exactly
match `--owner`, or pairing fails. No person's keys or existing Iris profile
are imported. Each agent's transport creates its own identity once and retains
it in a Docker volume. Each agent sends a short introduction automatically. Send a message in either chat to run a task.

Rerun `agents setup` at any time to start or finish setup. It reuses the approved
contact, retains existing containers and sessions, and does not pair again or
send another introduction for an already-paired agent. It does not create or
change OpenCode containers. An existing agent's contact policy cannot be changed
through setup.

```sh
./agents status
./agents chat-status
./agents hermes
./agents openclaw
./agents logs hermes
./agents stop
./agents up
./agents check
```

Run the script from this directory, or symlink `agents` into a directory on your
`PATH`. It resolves its own location, so you can call it from any working directory.

```sh
agents opencode                  # OpenCode's persistent tmux terminal
agents hermes                    # Hermes container shell
agents openclaw                  # OpenClaw container shell
agents status                    # All three and their helpers
agents chat-status               # Iris readiness, task counts and last reply receipt
agents setup                     # Start/resume chat setup; preserve existing pairing
agents stop hermes               # Only Hermes and its private helpers
agents up hermes                 # Start Hermes; retain its existing container
agents opencode --workspace demo # Separate OpenCode workspace
agents check opencode            # OpenCode/Ollama checks
agents check hermes              # Hermes isolation checks
```

`status`, `up`, `stop` and `check` accept an agent name or `all` (the default).
`build` builds Hermes/OpenClaw images; `pair` applies only to those two agents.
OpenCode uses its pinned upstream image. Existing container names and volume names
are deliberately retained, including names beginning `oc-local` and `iris-agents`.
The previous launcher names are replaced by `agents`.

Closing a shell does not stop the agents. `stop` preserves containers and volumes.
`up` resumes them without replacing existing containers. `build` prepares new
images but does not deploy them. To apply an image update, wait until tasks are
idle and explicitly recreate the affected services with Docker Compose; their
named volumes retain workspaces, conversations and identities. Do not remove volumes unless you intend to lose that state.
Do not use `docker compose down -v` as a restart command.

## OpenCode

`agents opencode` reconnects to the existing `work` tmux session. Inside it, run
`opencode`; choose the local model using `/models`. Detach with Ctrl+B, then D.
OpenCode, its installed tools and tmux stay in the persistent container. A stop
ends running processes but preserves the container and its named volumes.

**OpenCode keeps its existing networking; it does not inherit the stricter chat-agent
firewall.** It can reach host Ollama and private networks. Its launcher retains
NET_ADMIN and TUN access for existing VPN setups, but does not install or enroll a
VPN in a new workspace. Existing VPN configuration stays in its separate named
volume. No host directories or Docker socket are mounted, and privileged mode
is disabled. The terminal runs as root with four CPUs and 6 GB RAM.

## Hermes and OpenClaw boundaries

- No host directories, Docker socket, published host ports, privileged mode,
  host networking, NVPN software, or VPN membership.
- The two agents have independent filesystems, workspaces and Iris identities.
- Each agent's network namespace has a separate firewall container. Only that
  container has `NET_ADMIN`; agents have no network-admin, raw-network or mount capabilities, and messaging services have none.
  Agents cannot change its rules or read its processes/filesystem.
- Internet IPv4 is allowed. Private, shared, link-local, reserved and multicast
  IPv4 destinations are blocked. IPv6 is blocked except within the container's
  own loopback. Direct access to host Ollama is blocked too.
- The sole private-network exception is port 11434 on the model gateway. It
  exposes only discovery and inference for the configured installed model.
  Pull, delete, create, other models and arbitrary URL forwarding are rejected.
  Inference is serialized between these two agents to limit GPU contention.
- Additional public host/WAN IPv4 addresses can be placed in `BLOCK_HOST_IPS`
  (space separated). Keep that list current if your host has public addresses
  or your router forwards public ports to it. Private-network blocks are static.
- Iris keys, pairing policy and the message queue live in separate transport
  containers. Agents see only the fixed-owner reply API. There is no API to
  change the owner, accept invites, join groups or choose a recipient.
- This is an Iris contact boundary, not a ban on all communication software an
  agent could install through its general internet access. Do not give these
  agents unrelated account credentials.

The user can manage software as root inside the agent containers. Network and mount
capabilities are removed, so operations such as mounting, changing network rules
and raw network access remain unavailable. No permissions are granted on the host.

## Messages and recovery

Only authenticated incoming messages in the approved direct chat become tasks.
Outgoing messages, other chats, groups, empty messages and deleted messages do
not trigger the agent. The broker persists processed message IDs; restarts do
not replay completed tasks. Replies can only go to the paired owner.

A task interrupted during execution is not automatically replayed because it may
already have changed files or contacted a website. The worker reports the
interruption and waits for a new instruction. Reply intent is recorded before
sending; retries inspect Iris history to avoid duplicate sends.

`sent` is not recipient delivery confirmation. Iris reports `received` or `seen`
when the recipient acknowledges a message. Text tasks and replies are supported;
attachments are not downloaded or executed automatically.

`agents chat-status [hermes|openclaw|all]` reports readiness, completed and active
task counts (including the introduction), recorded task errors, and the latest
outgoing reply receipt. This is read-only operator access: it does not print
message contents, keys or invites, and does not add an agent-accessible API.

For diagnostics, the agent's `iris-bridge/last-error.log` and
`iris-bridge/last-turn.jsonl` live in its private home volume. The transport's
`/state/transport.log` stays in its own volume. Never publish those files,
`.env`, the pairing file, or Iris profiles.

## Pinned inputs

- Hermes official image: v0.22.5, source `bf0203a794a07aac3ff764972ab9087baa4e4f4e`.
- OpenClaw official image: 2026.10.9, source `8b18b5578f66eab1501cba4cef2310d88bfb9a41`.
- Both upstream images and the Debian support image are pinned by OCI digest in
  the Dockerfiles. Support packages use the signed Debian snapshot from
  2026-10-25. Iris v2026.10.30 is pinned by archive SHA-256 and checked before use.
- The agent images are upstream artifacts, not independently reproduced builds.
  Docker layer hashes verify those downloads; they do not prove binary/source
  equivalence. Local images add only this repository's adapter files.

## Development

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
./agents check
```

`check hermes` and `check openclaw` probe live network isolation and allowed internet/model access from
both agents, then inspects mounts, capabilities, privileges and port bindings.
It does not run model inference or send messages. For an inference/tool smoke
test, run `/opt/iris-agent/worker.py probe` with Python inside either agent and
pipe a task on stdin; the output stays in the terminal rather than being sent.

The portable [Iris skill](https://github.com/irislib/iris-chat-rs/tree/main/plugins/iris-chat)
is useful for agents with direct CLI access. These containers deliberately keep
the CLI and credentials in the transport, so their agent-facing instruction is
simply to complete the task and return the reply. This is a standalone adapter,
not an upstream-maintained Hermes or OpenClaw channel plugin.

Native channel plugins are not required for this text-task workflow. They would
be a useful next step for attachments, typing indicators, and scheduled messages
through the agents' gateway delivery systems. Both
[Hermes platform plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/adding-platform-adapters)
and [OpenClaw channel plugins](https://docs.openclaw.ai/plugins/building-plugins)
can ship independently; no core pull request is needed for the current adapter.

References: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[Hermes Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker),
[OpenClaw agent CLI](https://docs.openclaw.ai/cli/agent),
[OpenClaw Ollama](https://docs.openclaw.ai/providers/ollama),
[Iris CLI workflow](https://github.com/irislib/iris-chat-rs/blob/main/docs/agents.md).
