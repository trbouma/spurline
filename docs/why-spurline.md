---
title: Why Spurline?
description: The rationale for a local-first Nostr relay.
---

# Why Spurline?

Nostr relays are simple, replaceable infrastructure. That is their strength.
But applications, individuals, and communities still need a dependable local
place where relevant events can be preserved, queried, and replayed.

Spurline exists for that local role.

## The mainline and the spur

Public relays are the mainline. They move events across the wider network and
make discovery, publication, and synchronization possible across many
operators.

A local relay has a different job. It does not need to carry everything. It
needs to preserve the events that matter for its local destination:

- a person and their devices;
- a family or small organization;
- an application deployment;
- a community mesh;
- an appliance that must keep working when connectivity is imperfect.

That is the reason for the name. A spur line branches from a larger network,
serves a local purpose, and remains connected without becoming the whole rail
system.

## Local continuity

Spurline is for continuity close to the user. It should make local applications
less dependent on any single public relay, hosted operator, or momentary
network condition.

The goal is not isolation. The goal is a credible local base:

- preserve relevant events nearby;
- replay state to local clients quickly;
- keep working during network disruption;
- synchronize selectively when other relays or mesh peers are available;
- make local operation inspectable and boring.

## The Mainstay product family

Spurline is designed as an independently useful sibling in the Mainstay product
family:

- **Mainstay** is the future unified local-first application.
- **Safebox Web** provides the current human-facing workflows and practical
  application foundation.
- **Acorn** safeguards user-controlled keys, funds, and records, and provides
  signing and recovery below the application layer.
- **Grove** stores opaque encrypted blobs and attachments.
- **Spurline** preserves and serves Nostr events locally.
- **Clear** optionally provides bounded local currencies.

Each product should remain independently useful. Together, they form a
local-first runtime for keys, funds, records, storage, events, and continuity.

**Good boundaries, not barriers.** Spurline keeps a clear relay boundary and
failure domain, while standard Nostr events allow compatible applications and
infrastructure to publish, query, replicate, and synchronize through it.

## Toward Lockbox

The long-term packaging direction is Lockbox: the hardware-first appliance that
runs Mainstay and supporting services such as Acorn, Grove, Spurline, and
optional Clear currencies locally.

The initial appliance target is FreeBSD on Raspberry Pi 4 with a physical
keypad and TROPIC01 HSM. In that setting, Spurline becomes the local relay
surface for the appliance:

- local clients connect to Spurline first;
- relevant events stay available on the device;
- the appliance can work with public relays and local mesh peers;
- local presence and hardware-backed controls can govern sensitive authority
  elsewhere in the stack.

## Design posture

Spurline should stay small, readable, and operationally modest. A local relay
should be easy to run, easy to inspect, and easy to replace.

The first implementation is intentionally narrow: FastAPI, WebSocket relay
traffic, HTTP health and info routes, SQLite persistence, event validation, and
basic NIP-01 subscription behavior.

The larger direction is selective synchronization and local resilience without
turning the relay into a monolith.
