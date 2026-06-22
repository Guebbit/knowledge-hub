---
title: "Container Runtime Comparison"
tags:
  - containers
  - docker
  - podman
  - devops
  - linux
created: 2026-06-21
folder: Inbox
---

## Summary
Docker and Podman are container runtimes that package applications with dependencies for consistent deployment. Docker relies on a central daemon for management, while Podman runs containers directly without a background service. Both use standard OCI images but differ in security defaults, networking, and ecosystem tools.

## Core Concepts
- **Containers**: Isolated processes sharing the host kernel, lightweight alternative to VMs
- **Images**: Read-only blueprints built from `Dockerfile` or `Containerfile`
- **Storage Drivers**: Overlay2 (Docker) vs vfs/storage overlay (Podman rootless)
- **Networking**: Bridge networks, host mode, port mapping, DNS resolution
- **Orchestration**: Docker Compose vs Podman Pods / Kompose / Kubernetes integration
- **OCI Compliance**: Both produce/run standard Open Container Initiative images

## Docker vs Podman
| Feature | Docker | Podman |
|---|---|---|
| Architecture | Client → Daemon → Runtime | Daemonless → Conmon → Runtime |
| Default Execution | Root required | Rootless by default |
| Network Setup | Docker bridge/CNI | CNI plugins (host/networkmanager) |
| Compose Tool | Docker Compose (official) | Podman Compose (community) |
| Systemd Integration | Requires third-party generators | Native `generate systemd` support |
| Ecosystem | Mature, broad plugin support | Linux-native, Kubernetes-friendly |
| CLI Compatibility | `docker` commands | `podman` aliases (`docker` → `podman`) |

## Architecture Flow
```mermaid
flowchart TD
  classDef success fill:#90EE90,stroke:#228B22,stroke-width:2px;
  classDef danger fill:#FFB6C1,stroke:#DC143C,stroke-width:2px;
  classDef warning fill:#FFD700,stroke:#B8860B,stroke-width:2px;
  classDef neutral fill:#ADD8E6,stroke:#00008B,stroke-width:2px;

  CLI[User CLI] --> D_Daemon[Docker Daemon]:::warning
  D_Daemon --> C_Containerd[containerd]:::neutral
  C_Containerd --> D_Runt[runc]:::neutral
  D_Runt --> D_Cont[Container]:::success

  CLI --> P_Conmon[conmon]:::success
  P_Conmon --> P_Runt[crun/runc]:::success
  P_Runt --> P_Cont[Container]:::success

  style CLI fill:#f9f9f9,stroke:#333,stroke-width:2px
```

## Command Cheat Sheet
- `docker/podman run -d -p 8080:80 --name web nginx` → Run detached container with port mapping
- `docker/podman build -t myapp:latest .` → Build image from current directory
- `docker/podman compose up -d` → Start multi-container stack
- `podman system migrate` → Fix storage issues after rootless setup
- `alias docker=podman` → Drop-in CLI compatibility layer

> [!TIP] best practices
> - Always pin image tags to specific versions or digests
> - Use `--read-only` and `--tmpfs` for writable layers
> - Prefer named volumes over bind mounts for database state
> - Run containers as non-root with `--userns=keep-id` (Podman)

> [!WARNING] gotchas
> - Docker daemon blocks port 2375/2376; conflicts with other services
> - Podman rootless requires `fuse-overlayfs` or `userxattr` kernel options
> - Docker Compose v3+ drops support for `network_mode: host` on some platforms
> - Volume permissions break when UID/GID differs between host and container

> [!DANGER] critical issues
> - Never expose Docker socket (`-v /var/run/docker.sock`) to untrusted containers
> - Rootless Podman fails silently if subuid/subgid ranges are misconfigured in `/etc/subuid`
> - Running privileged containers bypasses all isolation; audit before use

## Quick Debugging Flow
- `docker/podman logs <container>` → View stdout/stderr
- `docker/podman exec -it <container> /bin/sh` → Drop into running process
- `docker/podman inspect <container>` → JSON metadata & mount/network details
- `podman info` → Runtime config, storage driver, CNI networks
- `journalctl -u docker.service` / `systemctl status docker` → Daemon health

> [!NOTE] Excalidraw: Sketch host kernel → storage driver → network bridge → container process lifecycle with arrow flow

> [!IMPORTANT] key takeaways
> Podman wins on security and systemd integration; Docker wins on ecosystem maturity and Windows/Mac desktop support. Choose based on target environment, not features.