---
status: accepted
---

# Use exclusive Resource ownership and verified rollback

Each managed State Address will have exactly one owning Resource, and duplicate ownership will fail Profile validation rather than being resolved by precedence. Atomicity and rollback are promised only at the Resource boundary where rollback is explicitly implemented, tested, and independently verified; Runs may partially converge and report every original and recovery outcome. This trades whole-Run transactional appearance for ownership clarity and truthful failure semantics across operations that are not uniformly reversible.
