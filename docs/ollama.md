# Ollama: containerized, driven from the host

Ollama runs **only** inside the `ollama` container (image `ollama/ollama:latest`). No Ollama is installed on the host. Models live in `~/.ollama` on the host and are bind-mounted into the container, so they survive any container update or recreate.

Everything below goes through one script: `scripts/ollama.sh`. It reads `CONTAINER_ENGINE` from `.env` (docker or podman).

## One-time setup

1. **Remove any host Ollama** (the upstream `install.sh` one). It conflicts with the container on port 11434 and the GPU:

   ```bash
   sudo systemctl disable --now ollama
   sudo rm -rf /etc/systemd/system/ollama.service /usr/local/bin/ollama /usr/local/lib/ollama
   sudo userdel ollama
   ```
   This does **not** touch `~/.ollama` (your models).

2. **Install the host `ollama` command** — a tiny shim in `~/.local/bin/ollama` that forwards every call into the container:

   ```bash
   scripts/ollama.sh install
   ```

   From now on `ollama list`, `ollama pull x`, `ollama run x`, `ollama ps`, `ollama rm x` work exactly as before. If the container is down, the shim starts it first.

## Updating Ollama

`docker compose up -d` / `build` **never** re-download an `image:`-only service — you will silently sit on an old image forever. Use:

```bash
scripts/ollama.sh update
```

It pulls the newest image, force-recreates the container, prints the new version, and prunes the old image. Models are untouched.

## Checking state

```bash
scripts/ollama.sh status     # container, server version, host shim, GPU, models
```

## GPU warning: `Could not locate device 507:1 on host`

The NVIDIA `nvidia-uvm` device gets a *dynamic* major number; after a driver update or reboot it can change, and the CDI spec in `/etc/cdi/nvidia.yaml` still points at the old number. Regenerate it (needs sudo):

```bash
scripts/ollama.sh fix-gpu
```

## If podman commands hang forever

A podman process that got killed mid-run (e.g. a `timeout`) can leave the libpod lock stuck. Containers keep running; only the CLI hangs. Recover with:

```bash
rm -f /dev/shm/libpod_rootless_lock_$(id -u)
podman system renumber      # "layer is in use" message at the end is harmless
```
