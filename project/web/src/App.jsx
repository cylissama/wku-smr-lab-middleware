import DataDashboard from "./DataDashboard.jsx";
import { Route, Routes } from "react-router-dom";
import "./App.css";

const AI_URL = import.meta.env.VITE_AI_URL;
const TWINS_URL = import.meta.env.VITE_TWINS_URL;

function App() {
  function topBar() {
    return (
      <nav className="fixed top-0 left-0 z-40 w-full border-b border-slate-700/40 bg-slate-950/90 px-6 py-3 text-white shadow backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-row items-center justify-between">
          <h2 className="text-lg font-semibold tracking-wide">Smart Manufacturing Research</h2>

          <div className="flex items-center gap-4">

            <button
              className="flex items-center gap-1 rounded bg-cyan-600 px-3 py-2 text-white transition hover:bg-cyan-500"
              onClick={() => {
                window.location.href = "/docs/";
              }}
            >
              Documentation
            </button>

            {AI_URL ? (
              <a
                href={AI_URL}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 rounded bg-cyan-600 p-2 text-white transition hover:bg-cyan-500"
              >
                AI
              </a>
            ) : null}

            {TWINS_URL ? (
              <a
                href={TWINS_URL}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 rounded bg-cyan-600 p-2 text-white transition hover:bg-cyan-500"
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
