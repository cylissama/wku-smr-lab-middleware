import DataDashboard from "./DataDashboard.jsx";
import { Route, Routes } from "react-router-dom";
import "./App.css";

const AI_URL = import.meta.env.VITE_AI_URL;
const TWINS_URL = import.meta.env.VITE_TWINS_URL;

// Every nav item shares one size; only the colors differ for the current page.
const NAV_ITEM =
  "inline-flex h-9 w-36 items-center justify-center rounded-md border text-sm font-medium transition";
const NAV_ACTIVE = "border-cyan-500 bg-cyan-600 text-white shadow-sm";
const NAV_IDLE =
  "border-slate-600 bg-slate-800 text-slate-100 hover:border-cyan-500 hover:bg-slate-700";

function App() {
  function topBar() {
    return (
      <nav className="fixed top-0 left-0 z-40 w-full border-b border-slate-700/40 bg-slate-950/90 px-6 py-3 text-white shadow backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-row items-center justify-between">
          <h2 className="text-lg font-semibold tracking-wide">Smart Manufacturing Research</h2>

          <div className="flex items-center gap-3">
            <a href="/" aria-current="page" className={`${NAV_ITEM} ${NAV_ACTIVE}`}>
              Data Dashboard
            </a>

            <a href="/docs/" className={`${NAV_ITEM} ${NAV_IDLE}`}>
              Documentation
            </a>

            {AI_URL ? (
              <a
                href={AI_URL}
                target="_blank"
                rel="noreferrer"
                className={`${NAV_ITEM} ${NAV_IDLE}`}
              >
                AI
              </a>
            ) : null}

            {TWINS_URL ? (
              <a
                href={TWINS_URL}
                target="_blank"
                rel="noreferrer"
                className={`${NAV_ITEM} ${NAV_IDLE}`}
              >
                Twins
              </a>
            ) : null}
          </div>
        </div>
      </nav>
    );
  }

  return (
    <div className="min-h-screen bg-transparent">
      {topBar()}

      <Routes>
        <Route path="/" element={<DataDashboard />} />
      </Routes>
    </div>
  );
}

export default App;
