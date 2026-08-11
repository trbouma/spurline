---
title: Spurline
description: A local-first relay for individuals and communities.
---

<section class="spurline-hero" markdown>

# Spurline

<img class="spurline-hero-mark" src="assets/spurline-logo.svg" alt="Spurline logo">

<p class="spurline-tagline">A local-first relay for individuals and communities.</p>

<p class="spurline-intro">Spurline is a lightweight Python Nostr relay built for local continuity and control. It works with the broader relay network and the local mesh without needing to duplicate all of it.</p>

[Why Spurline?](why-spurline.md){ .md-button .md-button--primary }
[Get started](getting-started.md){ .md-button }

</section>

## Local relay infrastructure

Spurline gives a person, organization, application, or community a local relay
that can preserve the events that matter nearby. Public relays remain the
mainline. Spurline is the spur: connected to the larger network, but useful in
its own local place.

<div class="spurline-grid" markdown>

<article class="spurline-card" markdown>

### Local first

Run a Nostr relay on your own machine, inside a local application stack, or
eventually as part of an appliance.

</article>

<article class="spurline-card" markdown>

### Selective

A spur line carries the traffic that matters for its destination. Spurline is
designed around local relevance rather than whole-network duplication.

</article>

<article class="spurline-card" markdown>

### Durable

Events are validated, stored in SQLite, replayed to matching subscriptions, and
served through a FastAPI runtime.

</article>

</div>

## Built for the Acorn stack

Spurline is a sibling project in the Acorn local-first stack. Acorn coordinates
keys, signing, records, and wallet state. Safebox Web provides the human
workflow surface. Grove stores opaque encrypted blobs. Spurline provides local
relay continuity.

```text
Safebox Web -> Acorn -> Spurline
                      -> Grove
```

Spurline is independent enough to run on its own, but shaped to become part of
the future Lockbox appliance profile alongside Acorn, Safebox Web, and Grove.

[Read the rationale](why-spurline.md){ .md-button .md-button--primary }
[Review the relay API](relay-api.md){ .md-button }
