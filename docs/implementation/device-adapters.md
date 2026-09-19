# Production Device Adapters

The production adapter package implements the typed SSH, command, SFTP
managed-file, and remote Run Infrastructure capabilities accepted for M3. It
is deliberately not wired into `bootstrap.py` or any installed command.

Sessions resolve secret values only at the composition seam, load exactly one
reviewed pinned host key, disable agent and ambient-key discovery, and reject
unknown or changed keys. Diagnostics contain only closed failure codes and
safe messages. Command stdout and stderr remain uninterpreted bytes, and every
command channel, SFTP session, and SSH client is closed deterministically.

Managed-file observation uses no-follow `lstat`, accepts only regular-file
reads, enforces a byte bound, and rejects incomplete reads. Replacement uses
only Paramiko's OpenSSH `posix_rename` extension. If that extension is absent,
mutation is unsupported; there is no ordinary rename or remove-plus-rename
fallback. Every mutating primitive returns an applied,
definitely-not-applied, or ambiguous receipt.

Remote Run Infrastructure is confined to
`/storage/.coreelec-reconciler/`. Fixed repository-owned helper operations
provide exclusive ownership creation, marker compare-and-swap, synchronization,
immediate reread verification, release, and quarantine conversion. Unsupported
durability fails closed. Cleanup accepts only exact manifest-owned leaves below
the Run Infrastructure runs root; it never discovers, expands, or recursively
deletes paths.

These adapters create no persistent helper, perform no retry or Effect, expose
no controller-private path or secret, and contact no Device during offline
acceptance.
