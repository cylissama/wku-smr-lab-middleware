#!/bin/sh
# Builds the architecture site (architecture/ -> arch-dist/) for /architecture/.
# Never fails the image build: an invalid model prints an error to the build
# log and arch-dist/ gets a page showing it instead of the diagrams.
# shortcut: errors are only seen in the build log or on the page; add CI if that's missed.
set -u
cd "$(dirname "$0")/.."
log=$(mktemp)

if npm run --silent arch:check >"$log" 2>&1 && npm run --silent arch:build >>"$log" 2>&1; then
  echo "Architecture site built."
  exit 0
fi

esc=$(printf '\033')
echo "ERROR: the architecture model (web/architecture/) is invalid; /architecture/ will show this error." >&2
sed "s/${esc}\[[0-9;]*m//g" "$log" >&2

rm -rf arch-dist && mkdir -p arch-dist
{
  echo '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Architecture: build error</title>'
  echo '<meta name="viewport" content="width=device-width, initial-scale=1">'
  echo '<style>body{font:15px system-ui,sans-serif;margin:2rem;max-width:60rem}pre{background:#f4f4f5;padding:1rem;overflow:auto;white-space:pre-wrap}</style></head><body>'
  echo '<h1>The architecture diagram failed to build</h1>'
  echo '<p>The model in <code>web/architecture/</code> has errors. Fix them (<code>npm run arch:check</code> in <code>web/</code>), then rebuild the <code>web</code> image.</p><pre>'
  sed -e "s/${esc}\[[0-9;]*m//g" -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' "$log"
  echo '</pre></body></html>'
} > arch-dist/index.html
exit 0
