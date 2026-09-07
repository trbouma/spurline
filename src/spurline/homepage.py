"""Server-rendered public home page for a Spurline relay."""

from __future__ import annotations

from html import escape


def render_homepage(
    *,
    version: str,
    relay_url: str,
    verify_signatures: bool,
    supported_nips: list[int],
    service_npub: str | None,
    service_fips_ipv6_address: str | None,
) -> str:
    """Render a browser-facing relay overview with escaped configuration."""

    values = {
        "version": escape(version),
        "relay_url": escape(relay_url),
        "signature_status": "Enabled" if verify_signatures else "Disabled",
        "supported_nips": escape(", ".join(f"NIP-{nip:02d}" for nip in supported_nips)),
        "service_npub": escape(service_npub or "Not configured"),
        "service_fips_ipv6_address": escape(
            service_fips_ipv6_address or "Not configured"
        ),
    }

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Spurline local-first Nostr relay">
  <meta name="color-scheme" content="light dark">
  <link rel="icon" href="/assets/spurline-logo.svg" type="image/svg+xml">
  <title>Spurline | Local-first Nostr relay</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f4f7fb;
      --surface: #ffffff;
      --surface-soft: #eaf0fb;
      --ink: #101d3c;
      --muted: #59667e;
      --line: #d7deeb;
      --navy: #162a63;
      --blue: #1c65d8;
      --amber: #d99021;
      --green: #237a4b;
      --shadow: 0 18px 45px rgba(22, 42, 99, 0.09);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}

    a {{ color: var(--navy); }}

    .shell {{
      width: min(100% - 2rem, 68rem);
      margin: 0 auto;
      padding: 1.25rem 0 3rem;
    }}

    .topbar {{
      display: flex;
      min-height: 2.75rem;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1rem;
    }}

    .brand {{
      display: flex;
      align-items: center;
      gap: 0.7rem;
      color: var(--navy);
      font-size: 0.82rem;
      font-weight: 760;
      text-transform: uppercase;
    }}

    .brand svg {{ width: 2rem; height: 2rem; flex: 0 0 auto; }}

    .online {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      color: var(--green);
      font-size: 0.82rem;
      font-weight: 720;
    }}

    .online::before {{
      width: 0.55rem;
      height: 0.55rem;
      border-radius: 50%;
      background: var(--green);
      content: "";
      box-shadow: 0 0 0 0.22rem rgba(35, 122, 75, 0.12);
    }}

    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(17rem, 0.65fr);
      gap: 1.5rem;
      align-items: stretch;
      padding: clamp(1.5rem, 5vw, 3.5rem);
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }}

    .eyebrow {{
      margin: 0 0 0.8rem;
      color: var(--amber);
      font-size: 0.78rem;
      font-weight: 800;
      text-transform: uppercase;
    }}

    h1 {{
      margin: 0;
      color: var(--navy);
      font-size: clamp(3rem, 8vw, 5.4rem);
      line-height: 0.98;
      overflow-wrap: anywhere;
    }}

    .lede {{
      max-width: 39rem;
      margin: 1.2rem 0 1.5rem;
      color: var(--muted);
      font-size: clamp(1rem, 2vw, 1.18rem);
      line-height: 1.65;
    }}

    .relay-address {{
      display: flex;
      max-width: 40rem;
      align-items: center;
      gap: 0.75rem;
      padding: 0.7rem 0.75rem 0.7rem 1rem;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface-soft);
    }}

    .relay-address code {{
      min-width: 0;
      flex: 1;
      overflow-wrap: anywhere;
      color: var(--navy);
      font-size: 0.86rem;
    }}

    button {{
      flex: 0 0 auto;
      min-height: 2.35rem;
      padding: 0.55rem 0.8rem;
      border: 0;
      border-radius: 5px;
      background: var(--navy);
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-size: 0.78rem;
      font-weight: 720;
    }}

    button:focus-visible, a:focus-visible {{
      outline: 3px solid rgba(217, 144, 33, 0.48);
      outline-offset: 3px;
    }}

    .signal {{
      display: grid;
      min-height: 18rem;
      place-items: center;
      align-content: center;
      gap: 1rem;
      border-left: 1px solid var(--line);
      text-align: center;
    }}

    .signal svg {{ width: min(12rem, 65%); height: auto; }}
    .signal strong {{ display: block; color: var(--navy); font-size: 1.1rem; }}
    .signal span {{ display: block; margin-top: 0.25rem; color: var(--muted); font-size: 0.84rem; }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
      margin-top: 1rem;
    }}

    .panel {{
      padding: 1.35rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }}

    .panel h2 {{ margin: 0 0 1rem; color: var(--navy); font-size: 1rem; }}
    dl {{ margin: 0; }}

    .row {{
      display: grid;
      grid-template-columns: minmax(7.5rem, 0.4fr) minmax(0, 1fr);
      gap: 1rem;
      padding: 0.72rem 0;
      border-top: 1px solid var(--line);
    }}

    .row:first-child {{ padding-top: 0; border-top: 0; }}
    dt {{ color: var(--muted); font-size: 0.82rem; }}
    dd {{ margin: 0; overflow-wrap: anywhere; font-size: 0.86rem; font-weight: 650; }}

    .features {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.7rem;
      margin: 0;
      padding: 0;
      list-style: none;
    }}

    .features li {{
      display: flex;
      align-items: flex-start;
      gap: 0.55rem;
      color: var(--muted);
      font-size: 0.84rem;
      line-height: 1.45;
    }}

    .features li::before {{ color: var(--green); content: "\\2713"; font-weight: 850; }}

    .about {{
      margin-top: 1rem;
      padding: 1.2rem 1.35rem;
      border-left: 0.28rem solid var(--amber);
      background: #fff8ec;
      color: #5f4b29;
      font-size: 0.9rem;
      line-height: 1.6;
    }}

    .links {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.85rem 1.25rem;
      margin-top: 1rem;
      padding: 0 0.2rem;
      font-size: 0.82rem;
    }}

    .links a {{ font-weight: 680; text-decoration-thickness: 1px; }}
    .links .version {{ margin-left: auto; color: var(--muted); }}

    @media (max-width: 47rem) {{
      .shell {{ width: min(100% - 1.2rem, 68rem); }}
      .hero {{ grid-template-columns: 1fr; padding: 1.4rem; }}
      .signal {{ min-height: auto; padding-top: 1.5rem; border-top: 1px solid var(--line); border-left: 0; }}
      .signal svg {{ width: 7rem; }}
      .grid {{ grid-template-columns: 1fr; }}
      .relay-address {{ align-items: stretch; flex-direction: column; }}
      button {{ width: 100%; }}
      .links .version {{ width: 100%; margin-left: 0; }}
    }}

    @media (prefers-color-scheme: dark) {{
      :root {{
        color-scheme: dark;
        --page: #0d1322;
        --surface: #151e34;
        --surface-soft: #1d2945;
        --ink: #eef3ff;
        --muted: #afbdd8;
        --line: #33415e;
        --navy: #94b7ff;
        --amber: #efb756;
        --green: #76c794;
        --shadow: none;
      }}
      .about {{ background: #2a2318; color: #ead5ae; }}
      button {{ background: #94b7ff; color: #101a31; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        {_spurline_logo()}
        <span>Spurline relay</span>
      </div>
      <div class="online">Online</div>
    </header>

    <section class="hero">
      <div>
        <p class="eyebrow">Local-first Nostr infrastructure</p>
        <h1>Spurline</h1>
        <p class="lede">
          A lightweight relay that keeps important events close while remaining
          connected to the wider Nostr network.
        </p>
        <div class="relay-address">
          <code id="relay-url">{values['relay_url']}</code>
          <button id="copy-relay" type="button" aria-label="Copy relay URL">
            Copy relay URL
          </button>
        </div>
      </div>
      <div class="signal" aria-label="Relay identity">
        {_spurline_logo()}
        <div>
          <strong>Nostr relay</strong>
          <span>WebSocket event service</span>
        </div>
      </div>
    </section>

    <div class="grid">
      <section class="panel">
        <h2>Relay details</h2>
        <dl>
          <div class="row"><dt>Status</dt><dd>Online</dd></div>
          <div class="row"><dt>Protocol</dt><dd>Nostr over WebSockets</dd></div>
          <div class="row"><dt>Supported NIPs</dt><dd>{values['supported_nips']}</dd></div>
          <div class="row"><dt>Signatures</dt><dd>{values['signature_status']}</dd></div>
          <div class="row"><dt>Service identity</dt><dd><code>{values['service_npub']}</code></dd></div>
          <div class="row"><dt>FIPS IPv6 address</dt><dd><code>{values['service_fips_ipv6_address']}</code></dd></div>
        </dl>
      </section>

      <section class="panel">
        <h2>What this relay provides</h2>
        <ul class="features">
          <li>Signed event acceptance</li>
          <li>Stored event replay</li>
          <li>Live subscription fan-out</li>
          <li>NIP-01 filter matching</li>
          <li>Durable SQLite storage</li>
          <li>Local continuity</li>
        </ul>
      </section>
    </div>

    <aside class="about">
      Spurline is local-first, not local-only. It gives individuals,
      applications and communities a durable nearby relay while standard Nostr
      events preserve interoperability with other relays and future mesh
      synchronization.
    </aside>

    <nav class="links" aria-label="Relay resources">
      <a href="/info">Relay information</a>
      <a href="/health">Health</a>
      <a href="/docs">API documentation</a>
      <a href="https://trbouma.github.io/spurline/">About Spurline</a>
      <span class="version">Spurline {values['version']}</span>
    </nav>
  </main>
  <script>
    const button = document.getElementById("copy-relay");
    button.addEventListener("click", async () => {{
      try {{
        const relayUrl = document.getElementById("relay-url").textContent;
        await navigator.clipboard.writeText(relayUrl);
        button.textContent = "Copied";
      }} catch (_error) {{
        button.textContent = "Select URL to copy";
      }}
      window.setTimeout(() => {{ button.textContent = "Copy relay URL"; }}, 1800);
    }});
  </script>
</body>
</html>"""


def _spurline_logo() -> str:
    return """<svg viewBox="0 0 512 512" role="img" aria-label="Spurline">
      <defs>
        <linearGradient id="spur-body" x1="92" y1="70" x2="374" y2="430" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#162a63"/><stop offset="1" stop-color="#07112e"/>
        </linearGradient>
        <linearGradient id="spur-blue" x1="218" y1="108" x2="404" y2="206" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#1c65d8"/><stop offset="1" stop-color="#0f3c94"/>
        </linearGradient>
      </defs>
      <path fill="url(#spur-body)" d="M96 132c0-42 34-76 76-76h110c14 0 26 12 26 26v30c0 14-12 26-26 26H172c-22 0-40 18-40 40v54c0 22 18 40 40 40h172c42 0 76 34 76 76v82c0 14-12 26-26 26h-36c-14 0-26-12-26-26v-72c0-12-10-22-22-22H172c-42 0-76-34-76-76z"/>
      <path fill="url(#spur-body)" d="M96 354c0-14 12-26 26-26h110c14 0 26 12 26 26v48c0 14-12 26-26 26H122c-14 0-26-12-26-26z"/>
      <path fill="url(#spur-blue)" d="M210 142c0-14 12-26 26-26h128v-34c0-14 12-26 26-26h36c14 0 26 12 26 26v126c0 14-12 26-26 26H236c-14 0-26-12-26-26z"/>
      <rect x="292" y="342" width="68" height="86" rx="16" fill="#d99021"/>
    </svg>"""
