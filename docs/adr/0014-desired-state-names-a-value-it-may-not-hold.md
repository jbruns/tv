---
status: accepted
---

# Desired State names a value it may not hold

Six State Addresses on the theater Ugoos resolve from the shared `.env` file:
`weather.ha`'s `ha_server` and `ha_key`, `pvr.nextpvr`'s `host` and `pin`, and
TMDb Helper's `mdblist_apikey` and `omdb_apikey`. Four are credentials. The
other two are the endpoints those credentials authenticate to, and
`provision.conf` rejects both keys naming them — the shell treats the whole of
`.env` as one boundary rather than sorting it into credentials and addresses
([`config/README.md`](../../config/README.md)).

A Profile is committed. It therefore cannot carry any of the six, and the
first question this slice had to answer was whether declaring the two
endpoints in a Profile would be a reasonable way to move that boundary.

It would not, and nothing moves. **Desired State names a `.env` key rather
than holding a value, and the boundary stays exactly where the shell put it.**
A setting states `value` or `from_env`, never both:

```yaml
- setting: ha_server
  from_env: HOME_ASSISTANT_URL
```

Three consequences follow, and each is the point of the decision.

**The value is read before Device contact.** A named key that `.env` does not
hold — or holds empty, which is what `.env.example` ships — is an error naming
the key, raised while the configuration is read and before anything is
observed, let alone stopped or written. A Run cannot get as far as the Device
and discover there that it has nothing to write.

**The value is never printed.** `plan` and `apply` report a named address as
`named by HOME_ASSISTANT_URL` and print neither the desired value nor the
Observation. The Observation matters here: what the Device holds for `ha_key`
*is* the token, so reporting drift the ordinary way would print the credential
while reporting that it was wrong. One rule covers all six rather than a list
of which are sensitive, because the boundary is the file and not a judgement
about each key.

**The file is read only when something names it.** A Run that names nothing
never opens `.env`, so the Reconciler still plans and applies on a checkout
that holds no secrets at all.

## Why the Reconciler reads `.env` itself

`.env` is bash: the shell entry points `source` it, and `.env.example`
documents shell quoting rules. The Reconciler reads it instead with a strict
`KEY=value` grammar that accepts a bare, single-quoted, or double-quoted
scalar and rejects everything else naming the file and the line — the posture
`provision.conf` already takes, where a value is data and never shell syntax.

The grammar is deliberately narrower than bash's. A line outside it is
rejected rather than guessed at, because the failure being avoided is a value
*misread*: a credential that parses as something plausible and different is
written to the Device, and the Verification that follows compares the same
wrong value against itself and reports Convergence. A rejected line costs an
operator one edit; a misread one costs a broken add-on that looks converged.

The alternative was for the Reconciler to read its process environment and
leave the operator to `set -a && . ./.env && set +a`, which is the pattern
hardware acceptance already documents. It needs no grammar and lets bash stay
the only reader, but it makes every Run carry a preamble that is silent when
forgotten in one direction — a stale exported value from an earlier shell is
indistinguishable from a fresh one — and it moves a step out of the tool and
into an operator's memory. The command in
[reconciling the theater Ugoos](../operations/reconcile-theater.md) stays one
line.

## Considered and rejected

**Declaring the two endpoints in the Profile and keeping only the four
credentials named.** It reads as the honest split: a hostname is not a secret,
and `NEXTPVR_HOST` in a committed file would document the deployment. But the
repository has one boundary, not two, and `provision.conf` enforces it by
rejecting all seven keys. Committing two of them would leave the rule "a
Profile never carries a secret" needing a second sentence about which
non-secrets from `.env` are allowed, and that sentence is what future slices
would argue about. Naming costs the same for all six.

**Redacting only the four credentials in output.** Printing `ha_server` in
full is genuinely more diagnosable, and it is the cheaper choice today. It
also means the redaction rule is a list, and a list acquires an entry every
time a key is added — eventually by someone who does not know which side of it
a new key belongs on. A named value is never printed; the key is always
printed, and a wrong endpoint is diagnosed by looking at `.env`, which the
operator has.

**A secret store.** Nothing on this network has one, `.env` is what the shell
reads, and both engines must agree on the value or they revert each other
forever ([ADR 0012](0012-shadow-the-shell-and-retire-it-wholesale.md)). A
second source of truth for the same six values is the one change guaranteed to
break that agreement.

## What this unblocks

[ADR 0012](0012-shadow-the-shell-and-retire-it-wholesale.md) defers
`CORE-020`–`CORE-027`, the Kodi remote-control service cohort, on "a secrets
mechanism" because it contains `services.webserverpassword`. This is that
mechanism, and `KODI_WEB_PASSWORD` is already in `.env`. That cohort is a
slice of its own and is not taken here; it is no longer blocked.
