---
name: frontend-ui-tests
description: Write and maintain focused frontend unit and UI tests for React applications. Use when adding tests for components, forms, panels, request flows, loading/error/result states, accessibility behavior, or when setting up Vitest, Testing Library, user-event, jsdom, and frontend test scripts.
---

# Frontend UI Tests

## Goal

Write tests that verify user-visible behavior and frontend contracts without testing backend internals, rendering implementation details, or fragile CSS.

Prefer React Testing Library, Vitest, `user-event`, and jsdom when the repo already uses React. If the repo has an existing test framework, follow it instead of replacing it.

## Workflow

1. Inspect existing test setup: `package.json`, Vite/Vitest config, setup files, and nearby tests.
2. Identify the user behavior to protect before writing code.
3. Write the failing test first. Confirm it fails for the intended reason.
4. Add the smallest production change needed: accessible labels, roles, request extraction, or state handling.
5. Run the targeted test, then the full frontend test command and build/typecheck command.
6. Report exact commands and pass/fail counts.

## What To Test

Prioritize behavior over structure:

- Opening, closing, tab switching, menus, dialogs, and mode selection.
- Form inputs, toggles, selects, file inputs, validation, and disabled states.
- Request contracts: endpoint, method, JSON body, FormData fields, and headers.
- Loading, success, empty, and error states.
- Result rendering: images, links, metrics, alerts, modals, and previews.
- Accessibility semantics needed by users and tests: `role`, accessible names, `aria-label`, `aria-pressed`, `role="alert"`, `role="dialog"`.

Avoid testing:

- CSS implementation details unless layout behavior is the feature.
- Backend algorithms, generated image contents, or network availability.
- Internal React state directly.
- Mock calls that do not correspond to a user-visible behavior or contract.

## Test Shape

Use queries that match how users find UI:

```tsx
render(<Panel />);
await user.click(screen.getByRole('button', { name: /open panel/i }));
await user.selectOptions(screen.getByLabelText('Mode'), 'gps_n');
await user.click(screen.getByRole('button', { name: /run/i }));

await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/run', expect.any(Object)));
expect(JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body))).toMatchObject({
  mode: 'gps_n',
});
```

Prefer:

- `getByRole` for buttons, tabs, dialogs, links, alerts, images.
- `getByLabelText` for inputs, selects, textareas.
- `findBy...` for async result appearance.
- `waitFor` for async state transitions.
- `userEvent` for realistic interaction.
- `fireEvent.change` only when number inputs or low-level events are unstable in jsdom.

## Mock Boundaries

Mock browser/network edges, not component behavior:

- Mock `globalThis.fetch` with successful, failed, and pending responses.
- Mock `URL.createObjectURL` for Blob image results.
- Use deferred promises for loading-state tests.
- Return real `Blob`, `FormData`, and JSON-shaped objects when possible.

Example helpers:

```tsx
function pngResponse() {
  return Promise.resolve({
    ok: true,
    blob: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })),
  } as Response);
}

function failedJsonResponse(message: string) {
  return Promise.resolve({
    ok: false,
    json: () => Promise.resolve({ detail: message }),
  } as Response);
}
```

## Accessibility As Test Contract

When a test cannot find a control by role or label, improve the UI instead of using `querySelector` or `data-testid`, unless the element genuinely has no semantic role.

Use:

- Buttons: visible text or `aria-label`.
- Icon-only close buttons: `aria-label="Close ..."`.
- Error messages: `role="alert"`.
- Modal previews: `role="dialog"`, `aria-modal="true"`, accessible name.
- Toggles: `aria-pressed` and an accessible name.

Only use `data-testid` for non-interactive visual containers or unavoidable third-party widgets.

## Suggested Test Batches

First batch:

- Opens and closes the component/panel.
- Switches major modes or tabs.
- Submits key request flows with edited inputs.
- Verifies each endpoint or `map_type` route.
- Verifies upload/FormData modes when present.

Second batch:

- Shows loading state while pending.
- Renders success result after response.
- Renders backend error message.
- Opens and closes preview/dialog/modal.

Later batches:

- Keyboard behavior.
- File input behavior.
- Empty states.
- Guarded/disabled controls.
- Regression tests for bugs found during manual QA.

## Verification

Run the narrow test first, then the full frontend checks used by the repo. Common commands:

```powershell
npm test -- ComponentName.test.tsx
npm test
npm run build
```

If Vite/Vitest needs `esbuild` and sandbox blocks process spawn, rerun with the required approval instead of skipping verification.
