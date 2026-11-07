# Vendored LiveKit browser client

`livekit-client.umd.min.js` is vendored so the local demo page does not depend on a CDN.

- Package: `livekit-client@2.15.6`
- Source: `https://cdn.jsdelivr.net/npm/livekit-client@2.15.6/dist/livekit-client.umd.min.js`
- License: Apache-2.0 (LiveKit, Inc.)
- Upstream: <https://github.com/livekit/client-sdk-js>

To update it, download the same UMD bundle from the pinned version, replace the file and
re-run `make test` plus a browser smoke. The file is served at
`/static/livekit-client.umd.min.js` by `forge_voice.web.app`.

# Vendored HTMX

`htmx.min.js` is vendored so the local dashboard has no CDN dependency.

- Package: `htmx.org@2.0.4`
- Source: `https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js`
- License: BSD 2-Clause (Big Sky Software)
- Upstream: <https://github.com/bigskysoftware/htmx>

It is served at `/static/htmx.min.js` and used only by `/dashboard` filters.
