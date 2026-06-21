---
title: "AI Agent Workflows"
tags:
  - ai-agents
  - local-llm
  - tool-use
  - automation
  - workflow-design
created: 2026-06-21
folder: Reference
---

## Summary
AI agents extend base models by linking reasoning to external tools and autonomous action loops. They parse goals, select functions, execute tasks, observe results, and self-correct to solve multi-step workflows locally.

## Core Agent Anatomy
- **Reasoning Core:** Local [[llm wiki]] (Qwen, Llama, Mistral) handles planning, tool routing, and reflection
- **Tool Registry:** Executable functions (code runner, file I/O, web search, vector DB query, API calls)
- **Action Loop:** Continuous `think → act → observe → adjust` cycle until completion or stop condition
- **Memory Layers:** 
  - Short-term: Conversation buffer & tool outputs
  - Long-term: [[Retrieval Augmented Generation]]-backed vector DB for persistent knowledge
- **Guardrails:** Step limits, output validation, rate caps, safety filters, deterministic fallbacks

## How Agent Workflows Operate
- **1. Intent Parsing:** Breaks user prompt into discrete subtasks & dependencies
- **2. Tool Routing:** Matches subtasks to available function schemas
- **3. Execution:** Runs selected tool, captures stdout/stderr or structured response
- **4. Observation & Reflection:** LLM reads output, checks for errors, decides to retry, pivot, or finalize
- **5. State Update:** Appends result to context window, updates task queue
- **6. Delivery:** Returns final artifact, summary, or hands off to human approval

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Agent as Agent Orchestrator
    participant LLM as Local LLM
    participant Tools as Tool Executor
    participant DB as Vector/State DB

    User->>Agent: Multi-step request
    Agent->>LLM: Parse intent + route tools
    LLM-->>Agent: Tool call(s) + reasoning
    Agent->>Tools: Execute function(s)
    Tools-->>Agent: Output / Error
    alt Error / Incomplete
        Agent->>LLM: Reflect + retry/adjust
        LLM-->>Agent: Revised tool call
        Agent->>Tools: Execute again
    else Success
        Agent->>DB: Cache context / update memory
        Agent->>User: Final result
    end

    classDef neutral fill:#ADD8E6,stroke:#00008B,stroke-width:2px
    classDef success fill:#90EE90,stroke:#228B22,stroke-width:2px
    classDef warning fill:#FFD700,stroke:#B8860B,stroke-width:2px
    classDef danger fill:#FFB6C1,stroke:#DC143C,stroke-width:2px
    class Agent,LLM neutral
    class Tools warning
    class DB success
    class User danger
```

## Key Workflow Patterns
- **ReAct (Reason + Act):** Interleaves explicit thought steps with tool calls; ideal for debugging & transparent tracing
- **Plan-and-Execute:** Generates full task roadmap first, then executes sequentially; reduces context thrashing
- **Multi-Agent Orchestration:** Manager agent delegates to specialized workers (coder, reviewer, tester, formatter); scales complexity but increases overhead
- **Human-in-the-Loop:** Blocks execution at critical decision points; adds latency but prevents irreversible actions
- **Tool-Heavy vs Reason-Heavy:** Balance based on task. Code repos = tool-heavy. Strategy/writing = reason-heavy.

| Pattern | Complexity | Best For | Local Viability |
|:---|:---|:---|:---|
| ReAct | Low-Medium | Debugging, exploratory tasks, transparent workflows | High (fits 8B-13B models) |
| Plan-and-Execute | Medium | Pipelines, batch processing, reproducible runs | High (predictable context usage) |
| Multi-Agent | High | Large codebases, cross-domain projects | Medium-High (requires RAM/[[VRAM with models in the ollama list]] headroom) |
| Human-in-the-Loop | Variable | Security, compliance, irreversible actions | High (async approval queues) |

## Local Stack & Integration
- **Inference Runtime:** [[Ollama]], vLLM, llama.cpp (ensure JSON/tool-calling support enabled)
- **Orchestration Frameworks:** LangChain, CrewAI, AutoGen, Open WebUI (built-in agent plugins)
- **Tool Integration:** 
  - Custom Python/JS scripts with strict JSON schemas
  - `exec` or `docker run` for isolated environments
  - Playwright/PyAutoGUI for browser/desktop automation
  - SQLite/Chroma/Qdrant for state & RAG queries
- **Context Management:** 
  - Sliding window + summarization fallback
  - Separate tool output buffers from conversation history
  - Pre-filter retrieved chunks before injection

> [!TIP] Keep tool outputs under 1-2K tokens. Strip stack traces, compress logs, and return only actionable diffs or status codes.

> [!WARNING] Unbounded agent loops will silently exhaust context windows, RAM, and rate limits. Always hard-cap max iterations and implement deterministic timeouts.

## Pitfalls & Optimization
| Pitfall | Symptom | Fix |
|:---|:---|:---|
| Context Bloat | Degrading reasoning, truncated prompts, OOM crashes | Implement history summarization, chunk RAG results, use separate tool-output buffers |
| Tool Hallucination | Calls non-existent functions, malformed JSON | Enforce strict function schemas, validate outputs with Pydantic/JSON schema, retry with temperature=0.1 |
| Infinite Loops | Agent repeats same tool call endlessly | Add step counters, state hashing to detect cycles, inject deterministic fallback responses |
| Latency Drag | Slow iteration despite fast model | Run I/O tools asynchronously, cache frequent results, route simple decisions to smaller models |
| Environment Drift | Scripts fail due to missing deps/paths | Containerize tools, use virtual environments, pass absolute paths, validate permissions upfront |

> [!NOTE] Excalidraw: Sketch a circular agent loop with labeled segments (Parse → Plan → Act → Observe → Reflect), external tool nodes branching out, and a dashed "Context Window" boundary showing how memory shrinks/expands during execution.

> [!IMPORTANT] Local agents thrive on constraint. Define narrow tool boundaries, cap iterations, and prioritize reliable I/O over complex reasoning. A simple, robust loop beats a fragile, feature-heavy one.
