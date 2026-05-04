# Images

The README references `architecture.png` in this folder. The source diagram
lives next to it as `architecture.mmd` (Mermaid).

## Rendering

The fastest path is the Makefile target at the repo root:

```bash
make diagram
```

That requires the Mermaid CLI:

```bash
npm install -g @mermaid-js/mermaid-cli
```

You can also render online by pasting the contents of `architecture.mmd` into
[mermaid.live](https://mermaid.live) and exporting a PNG. Save the result here
as `architecture.png`.

Recommended export size: **1600 × 900** with a transparent background.

## Other assets

Additional screenshots referenced from the README (Kibana alerts, Cases view,
etc.) should also live in this folder.
