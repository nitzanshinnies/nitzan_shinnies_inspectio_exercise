"""Minimal HTML that exercises the public REST surface (exercise operational UI)."""

from __future__ import annotations

# Embedded so ``pip install`` wheels always ship the UI without extra package_data rules.
OPERATIONAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Inspectio API</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 42rem; margin: 1rem auto; padding: 0 0.5rem; }
    fieldset { margin-bottom: 1rem; }
    label { display: block; margin: 0.35rem 0; }
    input[type="text"], input[type="number"] { width: 100%; max-width: 24rem; }
    pre { background: #f0f0f0; padding: 0.6rem; overflow: auto; font-size: 0.85rem; }
    button { margin-top: 0.35rem; margin-right: 0.35rem; }
  </style>
</head>
<body>
  <h1>Inspectio — operational surface</h1>
  <p>Calls the same REST routes as the exercise: <code>POST /messages</code>,
  <code>POST /messages/repeat?count=N</code>, <code>GET /messages/success|failed?limit=…</code>.</p>

  <fieldset>
    <legend>POST /messages → messageId</legend>
    <label>to <input id="m-to" type="text" value="+10000000000" autocomplete="off"/></label>
    <label>body <input id="m-body" type="text" value="hello" autocomplete="off"/></label>
    <button type="button" id="btn-send">Send</button>
    <pre id="out-m"></pre>
  </fieldset>

  <fieldset>
    <legend>POST /messages/repeat?count=N → messageIds / summary</legend>
    <label>count <input id="r-count" type="number" value="3" min="1" step="1"/></label>
    <label>to <input id="r-to" type="text" value="+10000000000" autocomplete="off"/></label>
    <label>body <input id="r-body" type="text" value="hello" autocomplete="off"/></label>
    <button type="button" id="btn-repeat">Repeat</button>
    <pre id="out-r"></pre>
  </fieldset>

  <fieldset>
    <legend>GET /messages/success &amp; /failed?limit=100</legend>
    <label>limit <input id="lim" type="number" value="100" min="1" max="1000" step="1"/></label>
    <button type="button" id="btn-ok">Success outcomes</button>
    <button type="button" id="btn-fail">Failed outcomes</button>
    <pre id="out-g"></pre>
  </fieldset>

  <script>
    const base = '';

    document.getElementById('btn-send').onclick = async () => {
      const res = await fetch(base + '/messages', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          to: document.getElementById('m-to').value,
          body: document.getElementById('m-body').value,
        }),
      });
      document.getElementById('out-m').textContent =
        res.status + ' ' + res.statusText + '\\n' + await res.text();
    };

    document.getElementById('btn-repeat').onclick = async () => {
      const c = document.getElementById('r-count').value;
      const res = await fetch(base + '/messages/repeat?count=' + encodeURIComponent(c), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          to: document.getElementById('r-to').value,
          body: document.getElementById('r-body').value,
        }),
      });
      document.getElementById('out-r').textContent =
        res.status + ' ' + res.statusText + '\\n' + await res.text();
    };

    async function getOutcomes(kind) {
      const lim = document.getElementById('lim').value;
      const res = await fetch(base + '/messages/' + kind + '?limit=' + encodeURIComponent(lim));
      document.getElementById('out-g').textContent =
        res.status + ' ' + res.statusText + '\\n' + await res.text();
    }
    document.getElementById('btn-ok').onclick = () => getOutcomes('success');
    document.getElementById('btn-fail').onclick = () => getOutcomes('failed');
  </script>
</body>
</html>
"""
