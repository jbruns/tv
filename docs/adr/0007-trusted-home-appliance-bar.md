---
status: accepted
---

# Build to a trusted home-appliance bar, not an audit bar

The Reconciler manages home streaming appliances on a trusted single-user home
network, so its quality bar is Wife Acceptance Factor: the Device just works,
the code and configuration stay easy to maintain, and each Device is easy to
snap to its Desired State. Disaster recovery is reprovisioning from scratch,
and no irrecoverable data lives on a Device. Adversarial concerns — malicious
local processes, a compromised transport, tamper-evident evidence — are
explicitly out of scope, as are compliance and audit obligations of any kind.

Edge cases are therefore weighed rather than exhaustively handled. Before a
mechanism that exists only to handle a failure is written, it must name the
failure it prevents, how likely that failure is, and what recovery costs
without it; an unlikely or cheaply-recoverable failure does not justify
significant machinery. Machinery must not dwarf the domain logic it serves,
and no design document may specify a mechanism before a slice actually needs
it. This decision supersedes the audit-grade posture that governed milestones
M0 through M3.
