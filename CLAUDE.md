## Function design

- MUST apply SOLID principles.
- MUST keep functions focused — one responsibility each.
- MUST keep nesting ≤ 3 levels; extract a helper for anything deeper. `max-depth` enforces the
  block half of this (4 in tests, where an exhaustive table walk is the clearest form). Nested
  callbacks are not counted by a rule — chain, or name the step.
- MUST prefer pure functions and shared abstractions over duplicated inline logic.

## Scope

- MUST NOT preserve backward compatibility (old field names, deprecated endpoints, legacy code
  paths, dual-write transitions) unless the user explicitly asks for it. Replace, don't shim.
- MUST NOT leave deprecated code in place — no `@deprecated` tag kept "for later." When a change
  supersedes something, remove it in the same change.

## Comments

Every comment answers up to two questions, in this order, and nothing else:

1. **What does this do** — only if the name doesn't already say it.
2. **Why is it shaped this way** — the one non-obvious reason, or its place in the larger flow.

**The budget is prose, and structure is nearly free.** This is the whole rule, and it is not about
brevity — a comment that needs more room is allowed it. What is capped is the FORM that room takes.
A seventh consecutive sentence is where a reader loses the thread; a seventh labelled row is still
scannable. So running out of budget means **change form**, never delete the content.

Count the PROSE only. A list item, a `Label:` row and its indented continuations, a table rule, a
fenced block and a JSDoc tag are all nearly free:


## Code layout

Orderly, scannable files. Two rules, always:

- **Every top-level declaration gets a comment**, within the caps above. Top-level means the
  outermost body of the file — and also the outermost body of whatever construct owns most of the
  file (a composable, a store definition, a factory, a class body, a `setup()`). Constants, types,
  helpers, refs, computeds, actions, exported and internal alike: each one carries its own block.
- **One blank line between them.** Every top-level declaration is separated from its neighbours by
  a single empty line — Prettier's formatting has no way to preserve more than one, so this is the
  enforced ceiling, not just the floor — so the comment visually belongs to the thing below it.
  Inside a declaration, blank lines are fine as needed.

```ts
/**
 * Rows currently visible after the active filter.
 */
const visibleRows = computed(() => rows.value.filter(isVisible))

/**
 * Reloads the table, discarding any optimistic edits.
 * @throws {FetchError}
 */
const reload = () => fetchRows().then(applyRows)
```

## Commenting third-party / unowned code

Every call into code you didn't write — a library, a framework, a generated client — gets a
comment, even where it looks obvious today. State, in 1-3 lines:

- what the call does,
- what each non-obvious parameter means (magic numbers, bare booleans, option objects,
  positional args whose meaning only comes from that library's docs — skip the self-evident ones),
- a link to the relevant doc page, when one exists.
- Prefer more comments over fewer. When in doubt, write it.

Link out for anything longer. Don't paraphrase the library's own docs into the comment.

```ts
/**
 * Sharp: resize to a fixed box, letterboxed rather than cropped.
 * https://sharp.pixelplumbing.com/api-resize
 */
sharp(buffer).resize(1200, 630, { fit: 'contain', background: '#00000000' })
```

All of it ADHD-friendly: short lines, one idea per line, plain language, the "why" before the
"how". No paragraphs, no restating the code.