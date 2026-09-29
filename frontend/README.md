# Carbon Copilot dashboard

React 19 + TypeScript + Vite front end for the Carbon Copilot API. In production the
built files are served by the FastAPI backend; in development Vite proxies `/api` to
port 8000.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Vite dev server on port 5173 with the API proxy |
| `npm run typecheck` | `tsc -b` over the app and config projects |
| `npm run lint` | oxlint (React hooks and TypeScript rules) |
| `npm test` | Vitest, single run |
| `npm run test:watch` | Vitest in watch mode |
| `npm run test:coverage` | Vitest with V8 coverage and the thresholds in `vite.config.ts` |
| `npm run build` | Typecheck, then a production bundle in `dist/` |

Dependencies are pinned to exact versions (`.npmrc` sets `save-exact`), so `npm install <pkg>`
records the resolved version rather than a range.

## Structure

- `src/store.ts`: Zustand store for the application shell. It owns the session, the
  inventory list, the open run and workspace, the factor catalogue, navigation and
  request state, and exposes the actions that load or change them (`bootstrap`,
  `loadInventories`, `open`, `importFiles`, `demo`, `logout`, ...). Components subscribe
  to slices with `useStore(selector)`; panel-local form state stays in the component.
- `src/workspace.ts`: typed `request`/`send` helpers (CSRF header, JSON errors) and the
  workspace types.
- `src/api.ts`: ledger and report types plus display labels.
- `src/App.tsx`: layout, navigation and lazy-loaded page panels.
- `src/components/`: overview, ledger table, review editor, compliance panels.
- `src/test/`: Vitest suites. `fixtures.ts` provides data builders and `mockFetch`, a
  route-based `fetch` stub keyed as `"METHOD /path"`; `setup.ts` registers jest-dom
  matchers and resets the store between tests.

## Testing conventions

Tests run in jsdom with Testing Library. Mock the API with `mockFetch({...})` rather than
mocking modules, so the real `request` wrapper, headers and error handling are exercised.
Reset happens automatically after each test (DOM cleanup, global stubs, store state).
