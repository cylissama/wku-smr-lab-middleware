# SOP: Mockup to Production Cutover

## Purpose
This SOP explains how to move the current mockup into the live dashboard and connect it to the real backend API without leaving placeholder behavior behind.

## What This Mockup Uses Today
- The Info page loads documents from `public/info/manifest.json`.
- The API Explorer uses `VITE_API_URL` as the backend base URL.
- The frontend build derives API and service URLs from the shared environment configuration.
- The saved endpoint list in `src/Home.jsx` is a hand-maintained endpoint catalog.

## Production Cutover Steps

## 1. Point the frontend to the live API
- Set `VITE_API_URL` to the real backend base URL in the live dashboard environment.
- Make sure the URL includes the correct protocol and host, for example `https://dashboard-api.example.com`.
- Confirm the live API supports the same routes used by the app:
  - `GET /session`
  - `GET /sessions`
  - `GET /session/start/<label>`
  - `GET /session/stop/`
  - `POST /send/<dest>`

## 2. Confirm live API routing
- Make sure `HOST_IP` and `FASTAPI_PORT` in the shared `.env` file point at the production backend.
- If you need an override, provide `VITE_API_URL` or `VITE_WS_URL` during the frontend build.
- Rebuild the frontend whenever those values change because Vite bakes them into the static bundle.

## 3. Replace placeholder endpoint definitions
- Review the saved API endpoint catalog in `src/Home.jsx`.
- Replace demo paths like `"/session/start/demo-session"` with real examples that make sense for operators.
- Add any missing live endpoints that users should be able to inspect from the Info page.
- If the real system exposes API documentation, consider loading endpoint metadata from the backend instead of hardcoding it in the UI.

## 4. Keep service links environment-driven
- Move AI, Twins, camera, database GUI, and any other service URLs into environment variables.
- Avoid leaving IP addresses directly in component files.
- Prefer names such as:
  - `VITE_AI_URL`
  - `VITE_TWINS_URL`
  - `VITE_ROBOT_CAMERA_URL`
  - `VITE_DB_GUI_URL`

## 5. Review CORS and authentication
- Confirm the live API allows requests from the dashboard frontend origin.
- If the real API requires authentication, update `apiRequest()` to send the correct headers or credentials.
- If tokens or cookies are required, test session expiration and unauthorized responses.
- Make sure the UI shows useful error messages when authentication fails.

## 6. Make the document library production-ready
- Replace sample files in `public/info/` with real SOPs, manuals, safety documents, and reference files.
- Keep filenames stable and update `manifest.json` whenever files are added, renamed, or removed.
- For PDFs, verify they open correctly in the embedded viewer and in a new tab.
- For sensitive operational documents, decide whether these files should remain public static assets or come from a protected backend source.

## 7. Improve safety for live API actions
- Be careful with endpoints that start or stop sessions.
- For production, add confirmation prompts before any action that changes system state.
- Consider separating read-only API inspection from write actions.
- Log operator actions if the live dashboard needs traceability.

## 8. Test the cutover
- Run the frontend against a staging or test API before production.
- Verify:
  - Info documents load
  - Search works
  - Markdown, text, JSON, CSV, and PDF previews work
  - API requests return real data
  - Errors display clearly when the backend is unavailable
- Run `npm run build` before deployment.

## Recommended Code Changes Before Production
- Move hardcoded external URLs into environment variables.
- Remove or isolate mock-only endpoint examples.
- Add confirmation UI for state-changing API requests.
- Add loading and error handling for any new authenticated endpoints.
- Decide whether the Info file manifest should stay static or come from a backend content service.
- Remove unused commented code once the live integration is settled.

## Suggested Environment Variables
```env
HOST_IP=192.168.1.76
FASTAPI_PORT=8000
VITE_API_URL=https://your-live-api.example.com
VITE_AI_URL=https://your-ai-service.example.com
VITE_TWINS_URL=https://your-twins-service.example.com
VITE_ROBOT_CAMERA_URL=https://your-camera-service.example.com
VITE_DB_GUI_URL=https://your-db-gui.example.com
```

## Final Pre-Deployment Checklist
- Live API URL is configured correctly.
- External service links are not hardcoded.
- Sample documents are replaced with real documents.
- Production-only authentication behavior is tested.
- State-changing actions are protected with confirmation.
- Build completes successfully.
- Staging test results look clean before release.

## Notes
- Right now this mockup is a good UI shell, but production readiness mainly depends on environment configuration, authentication, safety around write actions, and removing hardcoded placeholders.
- If the live dashboard has stricter access control requirements, the biggest architectural decision will be whether Info documents remain static files or move behind the authenticated API.
