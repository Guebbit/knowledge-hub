---
title: "NestJS Core Patterns"
tags:
  - nestjs
  - nodejs
  - typescript
  - backend
  - server
created: 2026-06-22
folder: Inbox
---

## Summary
NestJS is a structured framework for Node.js that helps you build scalable server-side apps using TypeScript. It organizes code into modules with dependency injection, making your backend easier to maintain and test. Think of it as adding strict architecture and enterprise features on top of Express or Fastify.

## Architecture Flow

````mermaid
sequenceDiagram
    participant Client
    participant NestApp
    participant Middleware
    participant Guard
    participant Pipe
    participant Controller
    participant Service
    participant Filter

    Client->>NestApp: HTTP Request
    NestApp->>Middleware: Intercept
    Middleware-->>NestApp: Pass/Modify
    NestApp->>Guard: Auth Check
    alt Unauthorized
        Guard-->>Client: 401 Error
    end
    NestApp->>Pipe: Validate/Transform
    Pipe-->>Controller: Clean Data
    Controller->>Service: Business Logic
    Service-->>Controller: Result
    Controller-->>Client: Response
    opt Error
        Controller-->>Filter: Handle Error
        Filter-->>Client: Formatted Error
    end
````

````mermaid
flowchart TD
    classDef green fill:#90EE90,stroke:#228B22,stroke-width:2px;
    classDef red fill:#FFB6C1,stroke:#DC143C,stroke-width:2px;
    classDef yellow fill:#FFD700,stroke:#B8860B,stroke-width:2px;
    classDef blue fill:#ADD8E6,stroke:#00008B,stroke-width:2px;

    Request([Request Arrives]):::blue --> Middleware
    Middleware --> Guard
    Guard --> Pipe
    Pipe --> Controller:::green
    Controller --> Service:::green
    Service --> Response([Response Sent]):::green

    Guard -- Fail --> Error401([401 Unauthorized]):::red
    Pipe -- Fail --> Error400([400 Bad Request]):::red
    Controller -- Exception --> ExceptionFilter([Exception Filter]):::yellow

    subgraph NestCore
        Middleware:::yellow
        Guard:::yellow
        Pipe:::yellow
        Controller:::green
        ExceptionFilter:::yellow
    end
````

> [!IMPORTANT] NestJS runs on Express by default but supports Fastify. You can import raw Express/Fastify packages, but using NestJS abstractions keeps your code framework-agnostic.

## Core Building Blocks

*   **Modules:** Logical boundaries that group related controllers and providers.
*   **Controllers:** Handle incoming requests and return responses to clients.
*   **Providers:** Injectables like services, repositories, factories, and helpers.
*   **Dependency Injection:** Built-in system to manage object creation and relationships.

````mermaid
mindmap
  root((NestJS))
    Modules
      Controllers
      Providers
      Services
      Repositories
    Dependency Injection
      Classes
      Tokens
    Request Lifecycle
      Middleware
      Interceptors
      Guards
      Pipes
      Filters
````

## Dependency Injection

*   Use `@Injectable()` on classes to make them providers.
*   Define providers in the module's `providers` array.
*   Inject via constructor parameters.

| Scope | Lifecycle | Use Case |
| :--- | :--- | :--- |
| **Singleton** | Created once on app startup | Default services, DB connections |
| **Request** | Created per HTTP request | Request-scoped data, logging |
| **Transient** | Created every time injected | Fresh state per injection point |

> [!WARNING] Cyclic dependencies break the build. Use `forwardRef(() => ClassName)` if modules/classes depend on each other.

## Best Practices

*   Keep controllers thin; move business logic to services.
*   Use DTOs (Data Transfer Objects) with `class-validator` for request validation.
*   Group features by domain, not by technical type (Feature-based modules).
*   Use the CLI to generate code: `nest g <type> <name>`.

> [!TIP] Use `ValidationPipe` globally in `main.ts` to auto-validate all incoming request bodies using DTO decorators.

## Comparison

| Feature | NestJS | Express | Fastify |
| :--- | :--- | :--- | :--- |
| **Structure** | Opinionated / Modular | Unopinionated | Unopinionated |
| **DI** | Built-in | Manual / Third-party | Manual / Third-party |
| **Performance** | High | Good | Very High |
| **Learning Curve** | Steeper | Low | Medium |
| **TypeScript** | First-class | Good | Good |
| **Best For** | Large teams, enterprise | Simple APIs, prototyping | High-throughput microservices |

## Quick Start

```bash
npm i -g @nestjs/cli
nest new project-name
cd project-name
nest start
```

> [!NOTE] Excalidraw: Sketch the relationship between Modules, Providers, and the DI Container showing injection arrows.