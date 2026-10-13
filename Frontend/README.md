# KrishiSaathi – Frontend

React 18 + TypeScript + Vite + Tailwind CSS single-page app. It talks to the FastAPI backend in `../backend`.

```bash
npm install
npm run dev        # http://localhost:8080
```

The API address defaults to `http://127.0.0.1:8000`. To change it, copy `.env.example` to `.env` and edit `VITE_API_URL`.

| Command             | What it does                              |
| ------------------- | ----------------------------------------- |
| `npm run dev`       | Dev server with hot reload (port 8080)    |
| `npm run build`     | Type-check and build to `dist/`           |
| `npm run preview`   | Serve the production build on port 8080   |
| `npm run lint`      | ESLint                                    |
| `npm run typecheck` | TypeScript, no emit                       |
| `npm test`          | Vitest + Testing Library component tests  |

## Structure

```
src/
  App.tsx                      layout, navigation, routes
  pages/
    Dashboard.tsx              home
    CropHealth.tsx             leaf photo upload, result, heat-map, measured reliability, history
    FertilizerAdvisor.tsx      fertiliser plan form, saved plans
  components/
    ui.tsx                     shared notices, fields, badges, buttons
    PlanView.tsx               a fertiliser plan (table, schedule, sources, print layout)
  lib/
    api.ts                     API base URL, error-message and date helpers
    fertilizer.ts              planner form validation and request building
    crop.ts, a11y.ts           score wording, aria helper
  test/                        test setup and fetch/upload mocks
```
