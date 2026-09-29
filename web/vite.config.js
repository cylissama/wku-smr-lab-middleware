import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

function formatUrl(protocol, host, port, pathname = "") {
  if (!host) {
    return "";
  }

  const normalizedPath = pathname ? `/${pathname.replace(/^\/+/, "")}` : "";
  const resolvedPort = port && !["80", "443"].includes(String(port)) ? `:${port}` : "";

  return `${protocol}://${host}${resolvedPort}${normalizedPath}`;
}

function toWebSocketUrl(value) {
  if (!value) {
    return "";
  }

  return value.replace(/^http/i, "ws");
}

export default defineConfig(({ mode }) => {
  const envDir = path.resolve(__dirname, "..");
  const fileEnv = loadEnv(mode, envDir, "");
  const env = { ...fileEnv, ...process.env };

  const hostIp = env.HOST_IP || "localhost";
  const fastapiPort = env.FASTAPI_PORT || "8000";

  const apiUrl = env.VITE_API_URL || formatUrl("http", hostIp, fastapiPort);
  const wsUrl = env.VITE_WS_URL || toWebSocketUrl(apiUrl);
  const aiUrl = env.VITE_AI_URL || formatUrl("http", hostIp, "3000");
  const twinsUrl = env.VITE_TWINS_URL || formatUrl("http", hostIp, "8001");

  return {
    plugins: [react(), tailwindcss()],
    envDir,
    define: {
      "import.meta.env.VITE_API_URL": JSON.stringify(apiUrl),
      "import.meta.env.VITE_WS_URL": JSON.stringify(wsUrl),
      "import.meta.env.VITE_AI_URL": JSON.stringify(aiUrl),
      "import.meta.env.VITE_TWINS_URL": JSON.stringify(twinsUrl),
      "import.meta.env.VITE_ROBOT_CAMERA_URL": JSON.stringify(
        env.VITE_ROBOT_CAMERA_URL || env.ROBOT_CAMERA_URL || "",
      ),
      "import.meta.env.VITE_DB_GUI_URL": JSON.stringify(
        env.VITE_DB_GUI_URL || env.DB_GUI_URL || "",
      ),
      "import.meta.env.VITE_PORTAINER_URL": JSON.stringify(
        env.VITE_PORTAINER_URL || env.PORTAINER_URL || "",
      ),
    },
  };
});
