# Deployment Container — Implementation Plan (Phase B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A private repository that builds the helpmate dashboard into a hardened container, deploys it through Coolify behind Cloudflare at `helpmate-tb.semantcon.org`, and records what it actually does under concurrent load.

**Architecture:** One service, no database. A multi-stage image compiles the C++ extension in a builder stage and ships only wheels in a runtime stage; the 350 GB corpus is never baked, arriving as a read-only bind mount at `/tables`. Coolify's own proxy terminates TLS — there is no nginx in this design.

**Tech Stack:** Docker (multi-stage), Docker Compose / Coolify, Python 3.12 slim, uvicorn, Cloudflare.

Implements Phase B of `docs/superpowers/specs/2026-08-13-deployment-and-search-off-design.md`.

## Prerequisites — do not start without these

1. **Phase A is merged.** `docs/superpowers/plans/2026-08-13-search-off-by-default.md` must be on `main` and tagged, because this image pins a git ref and the whole point is that the deployed build has search off. Building against a pre-0.14.0 ref deploys the endpoint this work exists to close.
2. **The private repository exists.** Creating it is the user's decision and the user's account — do not create it unprompted. Suggested name `helpmate-deploy`; visibility **private**.
3. **The table subset is chosen.** The corpus is 350 GB and the target volume will not hold it. Pick the materials to serve — the 23 puzzle materials are the floor, since the puzzle screen filters its session to what the server has.

## Global Constraints

- **Max 4 cores.** Every build/test/benchmark command runs under `taskset -c 0-3`. A Docker build is the heaviest thing here; `--cpuset-cpus=0-3` on `docker build` as well.
- **Never write to `~/tb` or `~/tb/raw`.** A 6-piece generation run is live there. Every mount of it is `:ro`. Table subsets are *copied* to a scratch directory, never moved.
- **Never `rm -rf /tmp/tmp.*`.**
- Bracket any process pattern (`helpmate[-]server`).
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

All paths are in the **private** repository, not `8pieces-helpmate`.

| File | Responsibility |
|---|---|
| `Dockerfile` | Two stages: compile wheels, then a runtime with no toolchain |
| `.dockerignore` | Keep the build context small — `build/_deps` alone is multi-GB |
| `docker-compose.yml` | The Coolify service: read-only mount, limits, healthcheck |
| `.env.example` | `HELPMATE_REF`, `TABLES_DIR`, `CORS_ORIGIN` — committed; real `.env` never is |
| `bench/concurrent_moves.py` | The 30-concurrent `/v1/moves` measurement |
| `README.md` | Runbook: build, deploy, roll back, choose the table subset |

---

### Task 1: The image

**Files:** Create `Dockerfile`, `.dockerignore`, `.env.example`

**Interfaces:**
- Consumes: the public repo at a git ref, passed as build arg `HELPMATE_REF`.
- Produces: an image exposing 8642, entrypoint `helpmate-server`, tables expected at `/tables`.

- [ ] **Step 1: Write `.dockerignore` first**

Before any build, or the context upload will be multi-gigabyte:

```
.git
.env
bench/
README.md
```

- [ ] **Step 2: Write the Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1

# ---- builder: compiles the C++ extension, then is thrown away -------------
FROM python:3.12-slim-bookworm AS builder

# ChessMG, Catch2 and nlohmann/json are fetched by CMake FetchContent at
# configure time, all public and all pinned to exact refs in CMakeLists.txt,
# so this needs network but is reproducible. git is required for that fetch.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG HELPMATE_REF=main
WORKDIR /src
RUN git clone --filter=blob:none https://github.com/osick/8pieces-helpmate.git . \
    && git checkout "${HELPMATE_REF}"

# Build all three wheels. The core wheel carries the compiled module; the
# other two are pure Python and cheap.
RUN pip wheel --no-deps -w /wheels . \
    && pip wheel --no-deps -w /wheels ./src/packages/api \
    && pip wheel --no-deps -w /wheels ./src/packages/web

# ---- runtime: no compiler, no git, no source ------------------------------
FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 10001 helpmate
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

USER helpmate
EXPOSE 8642

# Tables are mounted read-only at /tables, never baked: the corpus is 350 GB.
# Search is off because --enable-mine is absent, which is the whole point of
# this deployment -- do not add it here.
ENTRYPOINT ["helpmate-server", "--host", "0.0.0.0", "--port", "8642", \
            "--tables", "/tables"]
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Git ref of osick/8pieces-helpmate to build. Use a tag, never a branch:
# a branch makes "what is deployed" unanswerable after the fact.
HELPMATE_REF=v0.14.0

# Host directory holding the table subset to serve. Mounted READ-ONLY.
# Never point this at a directory a generation run is writing into.
TABLES_DIR=/srv/helpmate/tables

# Origin allowed to make cross-origin GETs. Leave empty for same-origin only,
# which is what the dashboard needs.
CORS_ORIGIN=
```

- [ ] **Step 4: Build it**

```bash
taskset -c 0-3 docker build --cpuset-cpus=0-3 \
  --build-arg HELPMATE_REF=v0.14.0 -t helpmate-web:v0.14.0 .
```

Expected: success. The C++ compile is the slow part — several minutes on four cores.

- [ ] **Step 5: Verify the runtime layer is actually clean**

```bash
docker run --rm helpmate-web:v0.14.0 --help | head -5
docker run --rm --entrypoint sh helpmate-web:v0.14.0 -c 'id -u'
docker run --rm --entrypoint sh helpmate-web:v0.14.0 -c 'which gcc cc g++ git || echo "no toolchain — correct"'
docker images helpmate-web:v0.14.0 --format '{{.Size}}'
```

Expected: the usage text lists `--enable-mine`; uid `10001`, not 0; `no toolchain — correct`; size well under 1 GB.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore .env.example
git commit -m "$(cat <<'EOF'
feat: multi-stage image for the helpmate dashboard

Builder compiles the C++ extension and is discarded; the runtime carries
wheels only -- no compiler, no git, no source -- and runs as uid 10001.

Tables are never baked. The corpus is 350 GB and the entrypoint expects a
read-only mount at /tables. --enable-mine is deliberately absent: search is
the endpoint this deployment exists to keep closed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The stack, with the hardening in it

**Files:** Create `docker-compose.yml`

**Interfaces:**
- Consumes: the image from Task 1, `.env`.
- Produces: a Coolify-deployable service.

- [ ] **Step 1: Write the compose file**

```yaml
services:
  helpmate:
    build:
      context: .
      args:
        HELPMATE_REF: ${HELPMATE_REF}
    restart: unless-stopped

    # The corpus is months of CPU. Read-only is structural, not a promise.
    volumes:
      - ${TABLES_DIR}:/tables:ro

    command:
      - --host=0.0.0.0
      - --port=8642
      - --tables=/tables
      # Bounded connections: without this, connection count grows until the
      # box does. No --enable-mine, deliberately.
      - --limit-concurrency=64

    # Nothing is written anywhere. Anything that tries is a bug worth failing.
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"

    # No `ports:` — Coolify's proxy reaches this over its own network. A
    # published port would bypass both Coolify and Cloudflare.
    expose:
      - "8642"

    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8642/v1/health',timeout=5).status==200 else 1)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
```

`--limit-concurrency` is added to `helpmate-server` in Phase A Task 2. Confirm it exists before relying on it — `helpmate-server --help | grep limit-concurrency` — because a flag argparse rejects will crash the container on start, and a flag that is accepted but ignored is worse.

- [ ] **Step 2: Prepare a scratch table subset**

Never mount `~/tb/raw` itself — a generation run is writing there.

```bash
d=$(mktemp -d)
for m in KQvk Kvk KRvk KBvk; do
  cp ~/tb/raw/$m.hm ~/tb/raw/$m.stats.json "$d/" 2>/dev/null
done
ls -la "$d"; du -sh "$d"
```

- [ ] **Step 3: Bring it up and check every hardening claim**

```bash
TABLES_DIR="$d" HELPMATE_REF=v0.14.0 docker compose up -d --build
sleep 10
curl -s localhost:8642/v1/health | python3 -m json.tool
```

Then verify each control rather than assuming it:

```bash
c=$(docker compose ps -q helpmate)
docker exec "$c" sh -c 'touch /tables/x' 2>&1 | grep -qi "read-only" && echo "mount ro — correct"
docker exec "$c" sh -c 'touch /x'        2>&1 | grep -qi "read-only" && echo "rootfs ro — correct"
docker exec "$c" id -u
docker inspect "$c" --format '{{.HostConfig.SecurityOpt}} {{.HostConfig.CapDrop}} {{.HostConfig.Memory}}'
```

Expected: both `read-only` lines, uid `10001`, `no-new-privileges` present, `ALL` dropped, memory limit non-zero.

- [ ] **Step 4: Confirm the dashboard works and search is gone**

```bash
curl -s localhost:8642/v1/health | grep -o '"mining_enabled": *[a-z]*'
curl -s -o /dev/null -w "%{http_code}\n" "localhost:8642/v1/mine?material=KQvk&dtm=4"
curl -s localhost:8642/ | grep -c 'data-panel="mine"'
curl -s "localhost:8642/v1/probe?fen=7k/8/5K2/8/8/8/8/6Q1%20w" | python3 -m json.tool | head
```

Expected: `false`; `503`; the grep count is `1` — the *markup* still ships the button and the *browser* removes it, which is correct and worth seeing rather than assuming; a real probe result.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
feat: Coolify stack with the hardening verified, not assumed

Read-only table mount, read-only rootfs with a tmpfs /tmp, all capabilities
dropped, no-new-privileges, memory and CPU limits, and no published port --
Coolify's proxy reaches the service over its own network, so publishing one
would bypass both Coolify and Cloudflare.

Every control is checked from inside the running container rather than taken
on trust: two write attempts that must fail, the uid, and the inspect output.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Measure what it does under load

**Files:** Create `bench/concurrent_moves.py`

The spec calls this a measurement, not a gate. Its purpose is to replace a guess with a number before other people use the deployment.

**Interfaces:**
- Consumes: a running container from Task 2.
- Produces: a recorded p50/p95 and a hang count in the README.

- [ ] **Step 1: Write the benchmark**

```python
"""30 concurrent /v1/moves requests — the concurrency the deferred load work
was scoped against.

/v1/moves probes every legal move, so it is the most expensive endpoint left
once search is off. Nobody has measured it under concurrency; this does.
Reports p50, p95, max and any request that failed or never returned."""
import argparse, concurrent.futures as cf, statistics, sys, time, urllib.error, urllib.request


def one(url: str, timeout: float):
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read()
            return time.perf_counter() - t, r.status
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t, e.code
    except Exception as e:
        return None, repr(e)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8642")
    p.add_argument("--fen", default="7k/8/5K2/8/8/8/8/6Q1 w")
    p.add_argument("-n", type=int, default=30)
    p.add_argument("--timeout", type=float, default=60.0)
    a = p.parse_args()

    url = f"{a.base}/v1/moves?fen=" + urllib.parse.quote(a.fen)
    with cf.ThreadPoolExecutor(max_workers=a.n) as ex:
        wall = time.perf_counter()
        out = list(ex.map(lambda _: one(url, a.timeout), range(a.n)))
        wall = time.perf_counter() - wall

    ok = sorted(d for d, s in out if d is not None and s == 200)
    bad = [s for d, s in out if d is None or s != 200]
    print(f"{a.n} concurrent, wall {wall:.2f}s, {len(ok)} ok, {len(bad)} failed")
    if bad:
        print(f"  failures: {bad}")
    if ok:
        print(f"  p50 {statistics.median(ok):.3f}s  "
              f"p95 {ok[max(0, int(len(ok) * 0.95) - 1)]:.3f}s  max {ok[-1]:.3f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it against a 4-piece material first**

```bash
taskset -c 0-3 python3 bench/concurrent_moves.py -n 30
```

Record the output verbatim.

- [ ] **Step 3: Run it against a 6-piece material**

This is the case the spec actually asks about. Stage a 6-piece table **read-only from a copy** — the file is 29 GB, so copy only if there is disk, otherwise mount `~/tb/raw` read-only for this one measurement and take a material the live run is *not* writing (`KBBvkbb`, not `KBvkrbb`).

```bash
taskset -c 0-3 python3 bench/concurrent_moves.py -n 30 --fen "<a KBBvkbb position>"
```

Record p50, p95, max, failures, and whether anything hung.

- [ ] **Step 4: Write the finding into the README, honestly**

State the numbers and what they mean for exposure. If p95 is bad or anything hangs, say so plainly and say that the Cloudflare-gated audience is what makes it acceptable for now — do not round a bad number into a reassuring sentence.

- [ ] **Step 5: Commit**

```bash
git add bench/concurrent_moves.py README.md
git commit -m "$(cat <<'EOF'
test: measure 30 concurrent /v1/moves instead of guessing

With search off, /v1/moves is the most expensive endpoint left -- it probes
every legal move, up to ~200 cold probes on a 6-piece table -- and its
behaviour under concurrency had never been measured. This records p50, p95,
max and any hang, on a 4-piece and a 6-piece material.

A measurement, not a gate: the result informs how widely the deployment is
shared, and it is written into the README as measured.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The runbook

**Files:** Create `README.md`

- [ ] **Step 1: Write it**

Cover, concretely, with real commands:

1. **What this is** — the private deployment for `helpmate-tb.semantcon.org`; the application lives in the public `osick/8pieces-helpmate`.
2. **Choosing the table subset** — why the full 350 GB is not deployed, that the 23 puzzle materials are the floor because the puzzle screen filters to installed materials, and how to copy a subset without touching `~/tb`.
3. **Deploying** — set `HELPMATE_REF` to a tag, `docker compose up -d --build`, point Coolify at the repo, map the domain.
4. **Rolling back** — change `HELPMATE_REF` to the previous tag and rebuild. This is why the ref must never be a branch.
5. **Turning search back on** — add `--enable-mine` to `command:`, and the standing reason not to: `SIGTERM` does not stop a scan and concurrency is unbounded.
6. **The load measurement** — the recorded numbers from Task 3.
7. **What is deliberately absent** — nginx (Coolify's proxy and Cloudflare already do it), a database (there is none), app-level auth (Cloudflare Access) and app-level rate limiting (Cloudflare, at the edge).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: runbook for the helpmate deployment

Covers choosing a table subset, deploying by tag, rolling back, and the
standing reason search stays off. Records what is deliberately absent --
nginx, a database, app-level auth and rate limiting -- so the next person
does not add them back wondering why they were missing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage.** Multi-stage image and no baked tables → Task 1. Read-only mount, non-root, read-only rootfs, dropped capabilities, limits, no published port, `--limit-concurrency` → Task 2. No nginx → recorded in Task 4 as a deliberate absence, so it is not re-added by accident. The 30-concurrent `/v1/moves` measurement → Task 3. `--cors-origin` is plumbed as `.env` in Task 1 and left empty, matching the spec's same-origin default.

**Not covered here.** Compressing a corpus for production, choosing and provisioning a production host, and the Hugging Face dataset. All are downstream of this working locally, and the spec scopes the hosting recommendation to a *deployment subset* rather than the 4.5–6.3 TB full 6-piece closure.

**Resolved before execution, not left as a risk.** An earlier draft of this plan assumed `helpmate-server` forwards `--limit-concurrency` to uvicorn. It does not: `main.py:_run` calls `uvicorn.run(app, host=host, port=port)` and nothing else. A silently ignored limit reads exactly like a limit that works, which is the worst kind of hardening. The pass-through is therefore **added in Phase A, Task 2** — a public-repo change — and this plan consumes it. Do not add the compose line before that ships.
