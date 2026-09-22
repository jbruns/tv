---
status: accepted
---

# The Reconciler owns First Contact

CoreELEC's first-boot wizard offers to enable SSH, and its final step offers to
change the root password — an offer that is easy to accept as-is. A freshly
imaged Device therefore sits on the home network with SSH open on a default
password, and closing that window is the first thing anyone would want to do.
The ownership ledger recorded `SSH-001` and `SSH-002` as
`unmanaged-inventory-fact` owned by the operator, which read as a decision that
the Reconciler would inherit key access rather than establish it. That is not
what the Recovery Baseline does: `provision-coreelec.sh:5988-6015` installs the
administrator key over a temporary password session and then proves key-only
authentication before hardening anything.

The Reconciler takes the same job. `SSH-002` becomes a Reconciler-owned
Resource, and `SSH-001` — the controller-local private key — stays with the
operator, who supplies the key the Devices share.

## First Contact is a separate entry point, not a fallback

A `bootstrap` entry point uses a password-authenticating transport arm; the
ordinary Run stays key-only. The rejected alternative was to have the ordinary
Run fall back to password authentication when key authentication fails. In
steady state, password authentication is disabled — so every genuine key
failure, such as a moved key file or a wrong identity path, would turn into
three password prompts against a daemon that will refuse all of them, and the
operator would get a confusing timeout in place of a clear error. Making First
Contact its own entry point also matches what it is: a once-per-Device act, not
a converging one.

The password arm costs almost nothing. Like the shell's `ssh_password`
(`:5954`), it is the system `ssh` client with `PubkeyAuthentication=no`, and the
client prompts the operator on the terminal. There is no `sshpass`, no stored
password, and no new `.env` key for one.

`StrictHostKeyChecking=accept-new` belongs to this entry point alone
(`SSH-004`). Trust-on-first-use is correct for the connection that *is* first
use; on an ordinary Run a changed host key means the Device was reimaged or
something is wrong, and failing is the right answer.

## `authorized_keys` is declared whole

The file holds two different keys: the administrator's, and a Home Assistant
lifecycle key carried by a `restrict,command="/storage/.config/kodi-lifecycle"`
entry (`LIFE-002`). The shell appends each one if absent, which means a revoked
key is never actually revoked — the file only grows. Declaring the whole
document instead makes "the keys that may log in" a single statement that can
remove as well as add, which is what reconciling the address means.

The administrator entry is not declared. It is derived from the public half of
the identity the Run is already authenticating with, because a Profile that can
name an administrator key is a Profile that can name the wrong one and lock the
Reconciler out of its own Device. The lifecycle key is named as a `.env` key
through the existing `from_env` arm. It is a public key and therefore not a
secret, so this widens `.env` slightly beyond ADR 0014's framing: `.env` holds
per-deployment values, and secrecy is a property of some of them rather than
the reason the file exists.

Declaring the whole document pulls `LIFE-002` into this slice ahead of the rest
of the lifecycle gateway. `LIFE-001`, the forced-command wrapper the entry
names, stays with the shell for now, so between First Contact and the lifecycle
installer that key can authenticate but its forced command fails. A key that
can log in and run nothing is safer than one that can run anything, and the
alternative — omitting the entry until `LIFE-001` is owned — would mean
shipping a declaration we already know to be incomplete and re-planning the
address in the next slice.

Only the `restrict` form is declared. `lib/coreelec-lifecycle.sh:77-85` also
renders a spelled-out fallback for OpenSSH releases older than 7.2; the Device
runs OpenSSH 9.9 and CoreELEC 21 is the only platform the Profile names, so
that fallback guards a failure that cannot occur here.

## Hardening restarts the daemon, and failing is the point

`SSH-003` writes CoreELEC's own two keys. `service.coreelec.settings` sets them
from its "Disable SSH password" toggle, and its `defaults.py:57` defines
`OPT_SSH_NOPASSWD` as `-o 'PasswordAuthentication no'` — byte-identical to what
the shell writes, so for once the shell is using upstream's string rather than
inventing one. `oe.py`'s `set_service` writes the file with a plain `open` and
no `chmod`, which is why its four siblings are all 0644; the shell's 0600 is the
departure, and the declaration keeps the mode CoreELEC gives it.

`EFFECT-003` restarts `sshd.service`, which drops the connection issuing it:
`ExecStart` is `/usr/sbin/sshd -D $SSH_ARGS`, so the new option only takes at
start, `ExecReload`'s SIGHUP replays the original argv and would not pick it up,
and the daemon is not socket-activated, so our session is a child in the unit's
cgroup. The Run therefore reconnects and verifies afterwards, as the shell does.

If that reconnect fails, the Run fails hard and points at the local console. We
deliberately do not reorder the Run to leave Kodi playing in that case, and we
do not build a revert path — a revert would have to travel over the connection
that just died. A Device that cannot be reached after its own sshd restarted is
evidence of something wrong with the Device, the storage media, or the way it
was imaged, and that diagnosis should be forced rather than softened.
