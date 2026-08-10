<section class="hero">
  <div class="hero-mark">
    <img src="assets/spurline-logo.svg" alt="Spurline logo">
  </div>
  <div class="hero-copy">
    <p class="eyebrow">Local relay infrastructure</p>
    <h1>Spurline</h1>
    <p class="lede">A local-first relay for individuals and communities.</p>
    <p>
      Spurline is a lightweight Python relay for local development, private
      infrastructure, and durable evidence stores that stay connected to the
      broader relay network and local mesh without needing to duplicate all of it.
    </p>
  </div>
</section>

<section class="statement">
  <p>A local-first relay for individuals and communities.</p>
  <p>Built for local continuity and control. Works with the network and the mesh.</p>
</section>

<section class="grid">
  <article>
    <h2>Local First</h2>
    <p>
      Run a first-class Nostr relay on your own machine or inside a local
      application stack.
    </p>
  </article>
  <article>
    <h2>Selective</h2>
    <p>
      A spur line carries the traffic that matters for its destination. Spurline
      is designed around the same idea.
    </p>
  </article>
  <article>
    <h2>Durable</h2>
    <p>
      Events are validated, stored in SQLite, and replayed to matching
      subscriptions.
    </p>
  </article>
</section>

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,docs]"
spurline --host 127.0.0.1 --port 8080 --database ./data/spurline.sqlite3
```

Connect a Nostr client to:

```text
ws://127.0.0.1:8080
```

## Build The Site

```bash
mkdocs serve
```
