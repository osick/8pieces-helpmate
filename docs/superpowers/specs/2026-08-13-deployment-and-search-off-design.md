# Search off by default, and a deployable dashboard

Status: proposed
Follows `2026-08-13-puzzles-and-polish-design.md` (v0.13.0).

Two changes that serve one goal: make the dashboard something that can be
handed to other people without the operator holding their breath.

## Why

The dashboard is finished enough to show. What is not finished is the one
endpoint that can hurt the machine serving it.

`/v1/mine` scans a material plane. Three properties make it unsafe to expose:
`SIGTERM` does not stop a running scan; the timeout is non-deterministic under
load because the `ThreadPoolExecutor` worker outlives the HTTP response that
gave up on it; and nothing bounds how many scans run at once. None of that
matters for a single local user and all of it matters for thirty. The load
work was deferred deliberately — this spec does not do it. It removes the
exposure until it is done.

Everything else here is packaging: a container, a mount, and the smallest set
of hardening that the app's own shape does not already provide.

## What the corpus forces

Measured, not estimated:

| | tables | size |
|---|---|---|
| 2-4 pieces | 66 | 0.44 GB |
| 5 pieces | 220 | 147 GB |
| 6 pieces | 9 | 202 GB |
| **total** | **295** | **350 GB** |

The tables are the state. There is no database, but there are 350 GB that a
container must reach, and that number — not CPU, not RAM — decides where this
can be hosted and what it costs.

It also constrains the puzzle screen, which filters its session to materials
the server actually has: **730 of the 930 shipped puzzles are 5- or 6-piece**,
and the 23 puzzle materials total 214 GB. A deployment carrying only the
image-sized 0.44 GB slice would still work, but it would quietly lose the hard
end of the difficulty ladder — most of what makes the screen worth opening.

So tables are mounted, never baked. Locally that mount is `~/tb/raw`
read-only. In production it is a compressed copy: at the measured ~6.5x
(`docs/USAGE.md`, `KRvkbn` 462 MiB raw -> 70.8 MiB compressed) the corpus
becomes roughly 45-55 GB, which fits on a cheap VPS. `tools/compress-corpus.sh`
writes into a *different* directory, so producing that copy never touches the
source corpus.

**Turning search off is what makes compression free.** The 6.5x slowdown
recorded against compressed tables was `mine --count` specifically — random
enumeration probing. Single-probe cost is +9%. A dashboard without search only
ever probes.

## Search off by default

`helpmate-server` gains `--enable-mine`. Mining is off unless asked for,
everywhere — including for anyone who runs the public API themselves.

**The endpoint.** With mining off, `/v1/mine` returns **503 `mining_disabled`**,
with a hint naming the flag. Not 404: the route exists, and claiming otherwise
would mislead a client probing the API surface. 503 says "this server is not
offering that right now", which is exactly true and exactly reversible.

**The dashboard does not guess.** `/v1/health` already reports `mine_timeout`;
it gains `mining_enabled`. On boot, when mining is off, the UI **removes
`#panel-mine` and the Search nav button from the DOM** and never calls
`initMine()`. This costs no extra request: `chip.js` already fetches
`/v1/health` at boot, and the capability rides that response.

Removal, not hiding. Round 1 established the failure mode: hiding the Search
button left the Enter key submitting the form, and the orphaned `setInterval`
went on overwriting `#mine-status` forever. With the form absent from the
document there is no key path, no poll, and no timer to orphan.

**Nothing is deleted.** `mine.js`, the endpoint, and the CLI `mine` command all
remain, tested, behind one flag. When the concurrency work lands, the flag
turns it back on.

## The container

Two stages, no state, no database.

**builder** — `python:3.12-slim` plus build-essential, cmake and git; builds the
`helpmate` wheel. `FetchContent` pulls ChessMG (`efbe11d`), Catch2 (`v3.5.4`)
and nlohmann/json (`v3.11.3`) — all public repositories pinned to exact refs,
so the build is reproducible. (The project's standing "no GitHub clones during
build" rule is specific to the development machine, whose gitconfig rewrites
HTTPS to SSH and then blocks on a passphrase prompt. A container has no such
rewrite.)

**runtime** — `python:3.12-slim` with the wheels installed. No compiler, no git,
non-root user, read-only root filesystem, tmpfs for `/tmp`.

The entrypoint runs `helpmate-server --host 0.0.0.0 --tables /tables` and does
not pass `--enable-mine`. `/tables` is a read-only bind mount, so one image
serves the raw corpus locally and a compressed one in production with only the
mount differing.

A `.dockerignore` is required, not optional: `build/_deps` alone would push a
multi-gigabyte build context.

## Stack: Cloudflare, Coolify, and no nginx

Cloudflare -> Coolify's proxy -> the container. One service.

Coolify already runs a reverse proxy that terminates TLS and routes by domain
label. Cloudflare already caches and compresses static assets at the edge. An
nginx inside the stack would be a third hop performing no function that the
other two are not already performing. It is not in this design. If a specific
caching or compression policy is wanted later, it can be added then, with a
reason.

## Hardening

The app's shape does most of the work: no database, no writes, no auth, no
cookies, no user-supplied content stored anywhere, and — after this spec — no
search. Access is gated by Cloudflare to selected users. What remains:

**Two items that are genuinely wrong today.**

- `CORSMiddleware(allow_origins=["*"])` (`app.py:56`) is wide open. It becomes
  a repeatable `--cors-origin ORIGIN` flag. With none given the middleware is
  not installed at all, which leaves same-origin requests working — the
  dashboard is served from the same origin as the API — and cross-origin
  browser requests blocked. The wildcard becomes something an operator opts
  into, per origin, rather than the default.
- The table mount is `:ro`. The corpus represents months of CPU; a bug must be
  structurally unable to write to it, not merely expected not to.

**Container hygiene, cheap and standard.** Non-root user; `cap_drop: ALL`;
`no-new-privileges`; explicit memory and CPU limits; the container port
published only to the proxy network, never the host; uvicorn
`--limit-concurrency` so connection count cannot grow without bound.

**Deliberately not done.** Application-level authentication (Cloudflare Access
gates it), application-level rate limiting (Cloudflare does it at the edge, and
better), a WAF, CSRF protection (nothing mutates).

**One unknown, stated rather than assumed.** With mining gone, the most
expensive remaining endpoint is `/v1/moves`, which probes every legal move — up
to roughly 200 cold probes on a 6-piece table. Its behaviour under concurrency
has not been measured. Verification below measures it; the result decides
whether the deferred load work is still safely deferrable.

## Production hosting

Requirements: ~50-60 GB of disk for a compressed corpus, 2-4 GB RAM, two cores,
Docker, EU.

| option | spec | ~cost/month | note |
|---|---|---|---|
| **Hetzner CX23 + volume** | 4 GB RAM / 40 GB + 60 GB volume | ~EUR 8 | storage grows independently |
| netcup VPS 1000 ARM G11 | 8 GB RAM / 256 GB NVMe | ~EUR 6.53 ex VAT | most disk per euro; needs an arm64 build |
| Contabo VPS S | 8 GB RAM / 200 GB | ~USD 11 | most variable performance of the three |

**Recommended: Hetzner CX23 with a block volume.** Seven-piece generation is on
the roadmap and will dwarf the current corpus, so the ability to grow storage
without replacing the server is worth more than netcup's larger included disk.
Block storage is billed per GB per month, so the volume tracks the corpus
rather than being sized for a guess. Choose netcup instead if the lowest
current bill matters more and an arm64 image build is acceptable.

**None of these hosts the raw 350 GB.** Production requires the compressed
corpus, and producing it is a long streaming job over every table. It is a work
item, not a footnote.

### What a deployment serves is not what generation produces

The stated goal is the full 6-piece closure. That is **715 materials, 41.2 TB
raw, roughly 4.5-6.3 TB compressed** — derived from
`size = KK x prod(48 for pawns, 64 otherwise)` per `slice_index.cpp:14-18`, and
checked against disk (predicted 28.88 GiB for a pawnless 6-piece table, measured
29G).

| pawns | tables | per table | subtotal | share |
|---|---|---|---|---|
| 0 | 330 | 31.0 GB | 10.2 TB | 24.8% |
| 1 | 240 | 90.9 GB | 21.8 TB | 52.9% |
| 2 | 108 | 68.2 GB | 7.4 TB | 17.9% |
| 3 | 32 | 51.1 GB | 1.6 TB | 4.0% |
| 4 | 5 | 38.3 GB | 0.2 TB | 0.5% |

A pawn triples a table, because `KK` goes from 462 to 1806 the moment one
appears and that outweighs the pawn's smaller 48-square radix. The 240
one-pawn materials are over half the corpus on their own; the pawnless closure
is only a quarter of it.

**No affordable host stores that, and the deployment does not need to.** These
are separate concerns and this design keeps them separate:

- **Generation and archival** target the full corpus. Its home is the Hugging
  Face dataset, not a VPS.
- **The deployment** serves a chosen subset — the 23 puzzle materials plus
  whatever else is worth exploring — sized to fit the mounted volume. Materials
  outside it already have correct behaviour: `404 unknown_material`.

Do **not** wire the deployment to `--hf-repo` as a fallback for missing
materials. `RemoteSource` caches whole files, so a probe into a one-pawn
6-piece material would trigger a 90 GB download behind a single HTTP request.
An honest 404 is better than a request that appears to hang for hours.

So the hosting recommendation above stands, scoped to a deployment subset. The
full corpus is a storage and generation question, answered on Hugging Face,
and out of scope here.

## Repositories

A new **private deployment repository** holds the `Dockerfile`, the Coolify
stack definition, `.dockerignore`, an `.env.example`, and a runbook. It builds
the public repository **at a git ref passed as a build argument**, so the
deployed version is explicit and the private repository stays small. Real
environment files are never committed.

The dashboard stays in the public monorepo for now; whether it moves is a
decision deferred until the deployment is running and has been seen. This
design does not foreclose it: the deploy stack consumes the dashboard only as a
directory, through the existing `--web-root`. If the UI later moves to its own
repository, the Dockerfile gains a second source and nothing else changes.

Note for the record: `osick/8pieces-helpmate` has been public and MIT-licensed
since 2026-07-18, and the dashboard has been in it throughout. Any future split
changes where new work happens; it cannot make past versions private, and
rewriting published history to attempt that would break every clone without
achieving it.

## Non-goals

- The concurrency and `SIGTERM` work on `mine`. Explicitly still deferred; this
  spec removes the exposure, it does not fix the endpoint.
- Deleting any search code.
- nginx, a database, application-level auth or rate limiting.
- Moving the dashboard to a private repository (deferred, not rejected).
- Multi-architecture image builds. One architecture, matching the target.
- Publishing the corpus to Hugging Face.

## Verification

**API** — `/v1/mine` returns 503 `mining_disabled` by default and 200 with
`--enable-mine`. `/v1/health` reports `mining_enabled` in both states. Existing
suites stay green.

**UI** — with mining off, `#panel-mine`, `#mine-form` and the Search nav button
are **absent from the DOM**, not hidden, and the nav has four buttons; with it
on, all return and search still works. Asserted on absence, because hiding was
the original bug.

**Container** — the image builds; it runs as a non-root user; no compiler is
present in the runtime layer; `/v1/health` answers; the dashboard loads and a
probe returns a real result; a write to `/tables` from inside the container
fails.

**Load** — **30** concurrent `/v1/moves` requests against a 6-piece material,
matching the concurrency target the deferred load work was scoped against.
Report p50, p95, and whether any request hangs or is dropped. This is a
measurement, not a pass/fail gate; its purpose is to record what the
deployment actually does before other people use it. If it is bad, that is a
finding to act on, not a reason to withhold the deployment from a
Cloudflare-gated audience of selected users.

## Operational note

`~/tb/raw` currently has a live 6-piece generation run writing into it. A
read-only mount cannot corrupt the corpus, but the server may meet a
half-written table and fail on that material — `compact --compress` already
skips files touched within the last hour for this reason. For the demo, either
exclude in-progress materials from the mount or accept transient errors on
them.

## Sources

Hosting prices checked 2026-08-13:
[Hetzner pricing](https://comparedge.com/tools/hetzner/pricing),
[Hetzner review incl. volume pricing](https://betterstack.com/community/guides/web-servers/hetzner-cloud-review/),
[netcup VPS plans](https://www.netcup.com/en/server/vps),
[netcup VPS 1000 ARM G11](https://www.vpsbenchmarks.com/hosters/netcup/plans/vps-1000-arm-g11),
[Contabo vs netcup](https://www.eucloudcost.com/compare/contabo-vs-netcup/).
