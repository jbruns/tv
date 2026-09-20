# Production Device Adapters

The production adapter package implements the typed SSH, command, SFTP
managed-file, and remote Run Infrastructure capabilities accepted for M3.
The single production `bootstrap.py` owns their lazy construction and builds
the concrete application workflow and execution dependency graph. The
installed CLI uses only that bootstrap; neither CLI nor application code
imports or constructs concrete adapters.
The shared remote ownership objects, backend port, and typed authority failures
live below both orchestration and production code in
`transports.remote_ownership`; adapters never import execution modules.

Sessions resolve secret values only at the composition seam, load exactly one
reviewed pinned host key, disable agent and ambient-key discovery, and reject
unknown or changed keys. Diagnostics contain only closed failure codes and
safe messages. Command stdout and stderr remain uninterpreted bytes, and every
command channel, SFTP session, and SSH client is closed deterministically.
The raw command runner remains private. A session exposes only requested typed
views: read-only managed files, managed-file mutation, or remote ownership.

Managed-file observation uses no-follow `lstat`, accepts only regular-file
reads through a fixed ephemeral server operation. It opens the absolute root,
walks every parent relative to pinned directory descriptors using
`O_DIRECTORY | O_NOFOLLOW`, and opens the final regular file relative to the
verified parent using `O_NOFOLLOW`. It rejects empty, dot, and dot-dot
components, enforces a byte bound on the opened descriptor, rejects incomplete
reads, and closes every descriptor. If those flags or `dir_fd` support are
unavailable, the read capability is unavailable.

Managed-file mutation is not exposed through pathname-based SFTP methods.
A fixed ephemeral server helper receives a canonical encoded request on
standard input, walks every parent with pinned no-follow directory descriptors,
and compares the final regular-file type, mode, and content digest (or exact
absence) immediately before mutation. Stage, chmod, remove, same-directory
atomic replacement, restoration, and cleanup all use that helper. Stage paths
are bound to the Run and their regular-file digest and mode are revalidated
before replacement. Changed targets, substituted stages, symlinks, and unsafe
ancestors fail closed without a success-shaped fallback; lost acknowledgements
remain ambiguous and are followed by fresh observation. The helper command is
fixed, and paths and payloads exist only in canonical standard-input data.
`tests/unit/adapters/test_managed_mutation_helper.py` exercises the real helper
against ancestor and final symlinks, changed pre-images, stage substitution,
lost acknowledgements, and command-shaped path/content values.

Remote Run Infrastructure is confined to
`/storage/.coreelec-reconciler/`. Fixed repository-owned helper operations
provide exclusive ownership creation, marker compare-and-swap, synchronization,
immediate reread verification, release, and quarantine conversion. Unsupported
durability fails closed. Every staged payload is scoped beneath the owning
opaque `runs/<key>/stage/` root, including identical payloads from concurrent
Runs. Cleanup accepts only exact manifest-owned leaves below that same Run
root, re-inspects ambiguous deletion through the fixed helper, and never
discovers, expands, or recursively deletes paths.

These adapters create no persistent helper, perform no retry or Effect, expose
no controller-private path or secret, and contact no Device during offline
acceptance.
