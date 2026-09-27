import fs from "node:fs/promises";
import path from "node:path";

const WEB_ROOT = process.cwd();
const INFO_DIR = path.join(WEB_ROOT, "public", "info");
const MANIFEST_PATH = path.join(INFO_DIR, "manifest.json");

const CATEGORY_BY_TYPE = {
  md: "SOP",
  txt: "Guide",
  json: "Reference",
  csv: "Reference",
  pdf: "PDF",
  png: "Diagram",
  jpg: "Diagram",
  jpeg: "Diagram",
  gif: "Diagram",
  webp: "Diagram",
  svg: "Diagram",
};

function toSlug(value) {
  return value
    .toLowerCase()
    .replace(/\.[a-z0-9]+$/i, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function toTitle(fileName) {
  const noExt = fileName.replace(/\.[a-z0-9]+$/i, "");
  return noExt
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function defaultDescription(fileName, type) {
  const title = toTitle(fileName);

  if (type === "md") {
    return `${title} document.`;
  }

  if (type === "pdf") {
    return `${title} PDF document.`;
  }

  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(type)) {
    return `${title} image file.`;
  }

  return `${title} reference file.`;
}

function encodePathForPublic(fileName) {
  return `/info/${encodeURIComponent(fileName)}`;
}

async function readExistingManifest() {
  try {
    const raw = await fs.readFile(MANIFEST_PATH, "utf8");
    const parsed = JSON.parse(raw);
    const docs = Array.isArray(parsed.documents) ? parsed.documents : [];

    const byPath = new Map();

    for (const doc of docs) {
      if (!doc || typeof doc !== "object") {
        continue;
      }

      if (typeof doc.path !== "string") {
        continue;
      }

      byPath.set(doc.path, doc);
    }

    return byPath;
  } catch {
    return new Map();
  }
}

async function generateManifest() {
  const existingByPath = await readExistingManifest();
  const names = await fs.readdir(INFO_DIR);

  const fileNames = names
    .filter((name) => name !== "manifest.json")
    .sort((a, b) => a.localeCompare(b));

  const documents = fileNames.map((fileName) => {
    const typeMatch = fileName.toLowerCase().match(/\.([a-z0-9]+)$/);
    const type = typeMatch ? typeMatch[1] : "file";
    const encodedPath = encodePathForPublic(fileName);

    const existing =
      existingByPath.get(encodedPath) ||
      existingByPath.get(`/info/${fileName}`) ||
      null;

    const fallbackId = toSlug(fileName) || `file-${Math.random().toString(36).slice(2, 8)}`;

    return {
      id: existing?.id || fallbackId,
      title: existing?.title || toTitle(fileName),
      description: existing?.description || defaultDescription(fileName, type),
      category: existing?.category || CATEGORY_BY_TYPE[type] || "Reference",
      type: existing?.type || type,
      path: encodedPath,
      tags: Array.isArray(existing?.tags)
        ? existing.tags
        : [type, (CATEGORY_BY_TYPE[type] || "reference").toLowerCase()],
      ...(existing?.notes ? { notes: existing.notes } : {}),
    };
  });

  const manifest = {
    documents,
  };

  await fs.writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}

generateManifest()
  .then(() => {
    console.log("Info manifest generated: public/info/manifest.json");
  })
  .catch((error) => {
    console.error("Failed to generate info manifest:", error);
    process.exitCode = 1;
  });
