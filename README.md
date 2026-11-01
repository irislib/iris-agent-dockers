# Iris agent containers

Run persistent Hermes and OpenClaw agents with a local Ollama model, and talk to
both through separate encrypted Iris chats. No hosted model account is needed.
The adapter invokes the agents' supported CLIs and preserves their sessions.
It does not replace either agent with a simple chatbot.

## Start

Requirements: Docker Compose, a running local Ollama server, and an installed
model with at least 65,536 tokens of context (Hermes requires 64K minimum). Inference is capped at 4,096 output tokens per call. These defaults target Docker Desktop on Apple Silicon. Iris currently
uses the released Linux x86_64 CLI under Docker's emulation; both agents run
natively on ARM64. Other hosts need Docker's equivalent emulation or a matching
released Iris binary, and a reachable Ollama host alias.

```sh
cp .env.example .env
# Set KAT_MODEL to the exact installed tag shown by `ollama list`.
./iris-agents build
./iris-agents up
./iris-agents pair hermes --owner YOUR_NPUB
./iris-agents pair openclaw --owner YOUR_NPUB
```

Pairing asks for your private Iris invite without echoing it. Use the same
personal invite for both agents. The returned direct-chat identity must exactly
match `--owner`, or pairing fails. No person's keys or existing Iris profile
are imported. Each agent's transport creates its own identity once and retains
it in a Docker volume. Each agent sends a short introduction automatically. Send a message in either chat to run a task.

```sh
./iris-agents status
./iris-agents shell hermes
./iris-agents shell openclaw
./iris-agents logs hermes
./iris-agents stop
./iris-agents up
./iris-agents check
```

Closing a shell does not stop the agents. `stop` preserves containers and volumes.
`up` resumes them. Rebuilding and `up` preserve workspaces, conversations and
identities. Do not remove volumes unless you intend to lose that state.
Do not use `docker compose down -v` as a restart command.

## Boundaries

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
./iris-agents check
```

`check` probes live network isolation and allowed internet/model access from
both agents, then inspects mounts, capabilities, privileges and port bindings.
It does not run model inference or send messages. For an inference/tool smoke
test, run `/opt/iris-agent/worker.py probe` with Python inside either agent and
pipe a task on stdin; the output stays in the terminal rather than being sent.

The portable [Iris skill](https://github.com/irislib/iris-chat-rs/tree/main/plugins/iris-chat)
is useful for agents with direct CLI access. These containers deliberately keep
the CLI and credentials in the transport, so their agent-facing instruction is
simply to complete the task and return the reply. This is a standalone adapter,
not an upstream-maintained Hermes or OpenClaw channel plugin.

References: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[Hermes Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker),
[OpenClaw agent CLI](https://docs.openclaw.ai/cli/agent),
[OpenClaw Ollama](https://docs.openclaw.ai/providers/ollama),
[Iris CLI workflow](https://github.com/irislib/iris-chat-rs/blob/main/docs/agents.md).
