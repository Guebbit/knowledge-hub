---
title: "Vue 3 Server Rendering"
tags:
  - vue3
  - ssr
  - hydration
  - performance
created: 2026-06-21
folder: Reference
---

## Summary
Vue 3 SSR renders components to HTML on the server before sending the response, reducing time-to-first-byte and boosting SEO. You must ensure the server-generated HTML matches the client-side state to avoid hydration crashes.

## Request Lifecycle

```mermaid
sequenceDiagram
    Client->>Server: Request URL
    Server->>Server: createSSRApp()
    Server->>Server: renderToString()
    Server-->>Client: HTML String + Script Tags
    Client->>Client: Parse HTML & Display
    Client->>Client: Download JS Bundles
    Client->>Client: Hydrate (Bind Events)
    class Server,Client success;
    class Client warning;
```

- **Server Phase**
    - Creates Vue app instance.
    - Resolves async `setup()` hooks.
    - Converts virtual DOM to static HTML string.
    - Sends HTML + JS assets to client.
- **Client Phase**
    - Browser parses HTML and renders immediately.
    - Downloads JS bundles.
    - Vue creates client app and **hydrates** existing DOM.
    - Vue attaches event listeners to existing nodes (no re-render).

## Implementation Steps

- **Install dependencies**
    - `npm i @vue/server-renderer vue`
- **Split entry points**
    - `client.ts`: Uses `createSSRApp`, calls `app.mount('#app')`.
    - `server.ts`: Uses `createSSRApp`, calls `renderToString(app)`.
- **Bundle configuration**
    - Vite/Rollup must output separate server chunks.
    - Server bundle uses `ssr` format; client uses `esm`/`iife`.
- **Framework integration**
    - Nuxt 3 handles this automatically.
    - Vanilla setup requires Node.js server boilerplate or Edge function wrapper.

## Rendering APIs

| API | Streaming | Best For | Notes |
|---|---|---|---|
| `renderToString` | ❌ | Simple APIs, Vercel, Netlify | Returns Promise<string>. Easiest to use. |
| `renderToNodeStream` | ✅ | Node.js backends | Improves TTFB. Pipes HTML chunks. |
| `renderToWebStream` | ✅ | Edge, Bun, Cloudflare | Standard web streams. Portable. |

> [!TIP] Prerendering
> Static routes can be rendered once at build time using `renderToString` and saved as `.html` files for zero-runtime cost.

## Data & State Synchronization

- **Async Setup**
    - `async setup()` works out-of-the-box in SSR.
    - Vue waits for promises to resolve before rendering HTML.
- **Passing Data Down**
    - Use `useSSRContext()` inside components to attach data to the context.
    - Access context in server entry to serialize state.
    ```typescript
    // Component
    const ctx = useSSRContext();
    ctx.myData = await fetchData();

    // Server Entry
    const ctx = {};
    const html = await renderToString(app, ctx);
    // Inject ctx.myData into page metadata or window object
    ```
- **State Management (Pinia)**
    - Pinia supports SSR natively.
    - Call `pinia.state` on server to get JSON state.
    - Inject state into client HTML before hydration.
    - Client initializes Pinia with this state to match server.

> [!WARNING] State Serialization
> Always strip sensitive data (passwords, tokens) from the SSR context before serializing to the client. The client receives all context data unless filtered.

## Hydration Safety

- **Mismatches Cause Errors**
    - HTML from server **must** match client virtual DOM exactly.
    - Differences trigger hydration warnings or crashes.
- **Common Triggers**
    - Time-based rendering (`Date.now()`).
    - Random numbers (`Math.random()`).
    - Browser-only APIs (`window`, `localStorage`) in setup without guards.
- **Fixes**
    - Use `onServerPrefetch` for server-only logic.
    - Wrap client-only code in `onMounted`.
    - Check `isServer` from `vue` utility.

> [!DANGER] Client-Only Components
> Components using browser APIs must be loaded asynchronously to prevent SSR crashes.
> - Wrap in `defineAsyncComponent`.
> - Load only when `onServerPrefetch` is available or inside `onMounted`.

> [!NOTE] Excalidraw: Sketch a split view showing Server DOM vs Client Virtual DOM with red highlights on mismatched text nodes and event listener bindings.

## Optimization Checklist

- **Chunk Splitting**
    - Split JS by route to reduce client bundle size.
    - Use `<script type="module">` for eager loading.
- **Caching**
    - Cache rendered HTML for static pages.
    - Reuse app instances for concurrent requests (if stateless).
- **SEO Meta Tags**
    - Inject `<title>` and `<meta>` via SSR context before rendering.
    - Ensure social cards and OpenGraph tags are in the initial HTML.