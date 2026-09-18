# Python 3.14 foundation candidates

## Purpose

This note resolves [Research the Python 3.14
foundation](https://github.com/jbruns/tv/issues/36) by narrowing the candidates
for the later human decision [Choose the foundational Python
toolchain](https://github.com/jbruns/tv/issues/37). It does not select that
toolchain.

The accepted architecture fixes the important boundaries: an on-demand,
controller-only Python 3.14 CLI over a reusable synchronous library; YAML
Profiles validated before contacting a Device; pure domain and planning
layers; SSH/SFTP behind typed adapters; canonical JSON as the stable automation
interface; no third-party plugin framework; a unit suite under 10 seconds; and
a complete offline suite under 60 seconds (accepted constraints supplied by
the Wayfinder ticket).

The comparison therefore favors explicit Python 3.14 evidence, deterministic
environments, small dependency surfaces, strict boundary behavior, easy use
with fakes, and tools that do not force asynchronous or plugin-oriented
architecture.

## Evidence standard

Compatibility evidence is strongest when a project both declares Python 3.14
support in package metadata and exercises 3.14 in first-party CI. A classifier
alone is weaker than CI; passing CI is still not a substitute for a
repository-specific locked install and smoke test. All links below are
first-party documentation, package metadata, or project source/CI.

The evidence snapshot was checked on **2026-09-18** against these current
releases: uv 0.12.17, PDM 2.29.2, Poetry 2.4.3, PyYAML 6.0.3, ruamel.yaml
0.19.1, Pydantic 2.13.5, msgspec 0.21.1, Paramiko 5.0.0, AsyncSSH 2.24.0,
Click 8.5.0, Typer 0.27.2, pytest 9.1.1, mypy 2.3.1, Ruff 0.16.8, and Black
26.5.1. PyPI's per-project JSON API is the first-party source behind the
version, classifier, and dependency checks represented by each linked project
page.

## Decision matrix

Ratings are relative to this repository:

- **Low maintenance** means one tool or dependency with a narrow role and
  little project-specific integration.
- **Medium maintenance** means configuration, adapters, or more transitive
  dependencies are expected.
- **High maintenance** means a second runtime ecosystem or an execution-model
  mismatch.

| Area | Candidate | Python 3.14 and maturity evidence | Reproducibility and testability | Fit and maintenance |
|---|---|---|---|---|
| Project and package management | **uv** | Current metadata declares Python 3.14 and Production/Stable maturity ([PyPI](https://pypi.org/project/uv/)); uv also documents managed Python installation and its project workflow ([Python versions](https://docs.astral.sh/uv/concepts/python-versions/), [projects](https://docs.astral.sh/uv/guides/projects/)). | `uv.lock` is a cross-platform lockfile intended to be checked in; `uv sync` performs exact syncing by default; `--locked` checks freshness and `--frozen` uses the lock without updating it ([lockfile](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile), [sync](https://docs.astral.sh/uv/concepts/projects/sync/)). It can also export the standardized `pylock.toml` format ([export](https://docs.astral.sh/uv/concepts/projects/export/)). | **Low.** One tool can provision Python, resolve, lock, sync, and run commands. This is the smallest operator surface, but it concentrates environment behavior in a comparatively new all-in-one tool. |
|  | **PDM** | Current metadata declares Python 3.14; it does not publish a Development Status classifier ([PyPI](https://pypi.org/project/pdm/)). | PDM records exact resolved versions and hashes in `pdm.lock`, supports lock targets and dependency groups, and supports PEP 751 `pylock.toml` export/use ([lockfile](https://pdm-project.org/latest/usage/lockfile/)). Its documented lock strategies and group-selection semantics provide control but create more policy choices for the repository. | **Medium.** Established Python-native workflow with strong lock behavior. The manager itself has a sizeable dependency graph and exposes more lock/group modes than this small project appears to require. |
|  | **Poetry** | Current metadata declares Python 3.14; it does not publish a Development Status classifier ([PyPI](https://pypi.org/project/poetry/)). | Poetry commits `poetry.lock`; installation uses the locked versions when the lock is present, and `poetry sync` removes packages not represented by the lock ([basic usage](https://python-poetry.org/docs/basic-usage/), [managing dependencies](https://python-poetry.org/docs/managing-dependencies/)). Poetry intentionally does not manage Python installation ([managing environments](https://python-poetry.org/docs/managing-environments/)). | **Medium.** Established baseline with a sizeable manager dependency graph and a separate responsibility for installing Python 3.14. Retain as a maturity comparator, not an automatic finalist. |
| YAML parsing | **PyYAML** | Current metadata declares Python 3.14 and Production/Stable maturity, and the 6.0.3 release publishes CPython 3.14 wheels ([PyPI](https://pypi.org/project/PyYAML/)). | `safe_load` limits construction to standard YAML tags ([API](https://pyyaml.org/wiki/PyYAMLDocumentation#loading-yaml)). PyYAML's mapping constructor assigns keys into a dictionary, so a repeated key replaces the earlier value rather than failing ([constructor](https://github.com/yaml/pyyaml/blob/main/lib/yaml/constructor.py#L132-L145)). Profile requirements therefore need a small repository-owned safe loader that rejects duplicate keys and multiple documents, with direct boundary tests. | **Low to medium.** Small, familiar parsing dependency; required strictness must be added explicitly at the adapter boundary. No round-trip editing cost. |
|  | **ruamel.yaml** | Current metadata declares Python 3.14 support and Beta maturity ([PyPI](https://pypi.org/project/ruamel.yaml/)). | Duplicate keys are rejected by default, and the project documents safe and round-trip APIs ([duplicate keys and API](https://yaml.dev/doc/ruamel.yaml/api/#duplicate-keys)). The documentation recommends pinning the version tested by an application because API evolution can affect callers ([API](https://yaml.dev/doc/ruamel.yaml/api/)). | **Medium.** Stronger duplicate-key behavior without a custom constructor, but round-trip/comment-preservation capabilities are outside the current read-and-validate requirement. |
| Strict model validation | **Pydantic** | Current metadata declares Python 3.14 and Production/Stable maturity ([PyPI](https://pypi.org/project/pydantic/)); the project includes 3.14 in supported metadata and CI configuration ([source](https://github.com/pydantic/pydantic/blob/main/pyproject.toml), [CI](https://github.com/pydantic/pydantic/tree/main/.github/workflows)). | Pydantic supports strict validation, but strictness must be enabled ([strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)). Unknown fields are ignored by default, so Profile models need shared `extra="forbid"` configuration; immutable value models can use `frozen=True` ([configuration](https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict)). Models are straightforward to construct in unit tests, and validation errors are structured. | **Medium.** Most mature and documented option, but safe repository defaults must override permissive library defaults consistently. The validation adapter should prevent Pydantic types from becoming infrastructure dependencies of pure planning logic. |
|  | **msgspec** | Current metadata declares Python 3.14 support and Beta maturity ([PyPI](https://pypi.org/project/msgspec/)); first-party CI includes Python 3.14 ([CI](https://github.com/jcrist/msgspec/blob/main/.github/workflows/ci.yml)). | Decoding is typed and rejects unsafe implicit conversions by default ([validation](https://github.com/jcrist/msgspec/blob/main/docs/usage.rst#L134-L158)). Struct decoding ignores unknown fields by default unless `forbid_unknown_fields=True`; structs can also be frozen ([unknown fields](https://github.com/jcrist/msgspec/blob/main/docs/structs.rst#L710-L742), [frozen structs](https://github.com/jcrist/msgspec/blob/main/docs/structs.rst#L434-L454)). The package has no required Python runtime dependencies ([package metadata](https://github.com/jcrist/msgspec/blob/main/pyproject.toml)). | **Low runtime cost, medium adoption risk.** Attractive small dependency surface and immutable data support, but lower maturity classification and a smaller ecosystem than Pydantic. |
| SSH/SFTP | **Paramiko** | Paramiko's current metadata is Production/Stable but does not declare a Python 3.14 classifier ([PyPI](https://pypi.org/project/paramiko/)). Its first-party CI explicitly includes Python 3.14, which is stronger compatibility evidence than the metadata alone ([CI](https://github.com/paramiko/paramiko/blob/main/.circleci/config.yml)). | `SSHClient` is synchronous, rejects unknown host keys by default, executes commands, and opens SFTP sessions ([SSHClient](https://docs.paramiko.org/en/stable/api/client.html)); `SFTPClient` exposes file transfer, rename, stat, and filesystem operations suitable for a narrow typed adapter ([SFTP](https://docs.paramiko.org/en/stable/api/sftp.html)). Tests can replace the repository adapter with a fake instead of mocking Paramiko internals. | **Medium.** Direct match for the accepted synchronous boundary and broad protocol surface. The missing 3.14 classifier warrants a locked install and disposable-Device smoke test before selection. |
|  | **AsyncSSH** | Current metadata declares Python 3.14 and Production/Stable maturity ([PyPI](https://pypi.org/project/asyncssh/)); first-party CI includes Python 3.14 on multiple operating systems ([CI](https://github.com/ronf/asyncssh/blob/master/.github/workflows/run_tests.yml)). | AsyncSSH supplies SSH and SFTP through asyncio APIs ([documentation](https://asyncssh.readthedocs.io/en/latest/)). It is testable behind the same transport ports, but production wiring must own an event loop or repeatedly bridge async calls into the synchronous application. | **High for the accepted design.** Strong explicit compatibility, but choosing it would add an asynchronous boundary solely for transport. Keep only if the human decision intentionally revisits the synchronous constraint. |
| CLI construction | **argparse** | `argparse` is part of the Python 3.14 standard library and is documented as a parser for user-friendly command-line interfaces ([Python 3.14 docs](https://docs.python.org/3.14/library/argparse.html)). | `ArgumentParser.parse_args()` accepts an explicit argument sequence, enabling deterministic parser tests without patching process arguments ([parse_args](https://docs.python.org/3.14/library/argparse.html#argparse.ArgumentParser.parse_args)). | **Low.** No dependency or framework lifecycle. Best fit if explicit command wiring and stable machine output matter more than decorator ergonomics. |
|  | **Click** | Current metadata is Production/Stable but does not declare a Python 3.14 classifier; first-party test configuration explicitly includes CPython 3.14 and free-threaded 3.14 ([PyPI](https://pypi.org/project/click/), [source](https://github.com/pallets/click/blob/main/pyproject.toml#L147-L150)). | `CliRunner` provides isolated in-process CLI invocation, but Click documents that it changes interpreter-wide state and is not thread-safe ([testing](https://click.palletsprojects.com/en/stable/testing/)). Click has no required runtime dependencies ([PyPI](https://pypi.org/project/click/)). | **Low to medium.** Mature command composition and testing with little dependency cost. The metadata/CI mismatch warrants a locked 3.14 smoke test. Adds framework conventions; canonical JSON must remain repository-owned rather than coupled to Click's presentation helpers. |
|  | **Typer** | Current metadata declares Python 3.14 but Beta maturity ([PyPI](https://pypi.org/project/typer/)). | Typer builds on Click and adds annotation-driven command generation; its default dependencies include Rich and Shellingham ([source](https://github.com/fastapi/typer/blob/master/pyproject.toml)). It uses Click's testing facilities ([testing](https://typer.tiangolo.com/tutorial/testing/)). | **Medium.** Pleasant annotations and rich help, but more packages and presentation behavior without a current architectural requirement. Keep as a comparator only if generated help and Rich output become explicit goals. |
| Testing | **pytest** | Current metadata declares Python 3.14 and Mature maturity ([PyPI](https://pypi.org/project/pytest/)); first-party CI tests Python 3.14 across operating systems ([CI](https://github.com/pytest-dev/pytest/blob/main/.github/workflows/test.yml)). | Built-in fixtures, parametrization, markers, `tmp_path`, and plain assertions cover pure planning tests, fake-client contracts, CLI boundaries, and opt-in live tests without a project-specific plugin ([fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html), [parametrize](https://docs.pytest.org/en/stable/how-to/parametrize.html), [markers](https://docs.pytest.org/en/stable/how-to/mark.html), [tmp_path](https://docs.pytest.org/en/stable/how-to/tmp_path.html)). | **Low.** Strongest fit for concise matrix and contract tests. Keep the initial suite plugin-free and measure collection/startup time against the budgets. |
|  | **unittest** | `unittest` is Python 3.14's standard-library unit-testing framework ([Python 3.14 docs](https://docs.python.org/3.14/library/unittest.html)). | It provides discovery, subtests, mocks, and temporary resources through the standard library, with no environment dependency ([unittest](https://docs.python.org/3.14/library/unittest.html), [unittest.mock](https://docs.python.org/3.14/library/unittest.mock.html)). | **Low dependency cost, medium test-authoring cost.** Viable baseline, but generally more ceremony for the parameterized pure-function and adapter-contract suite described by the architecture. |
| Type checking | **mypy** | Current metadata declares Python 3.14 and Production/Stable maturity ([PyPI](https://pypi.org/project/mypy/)); first-party CI exercises Python 3.14 in multiple configurations ([CI](https://github.com/python/mypy/blob/master/.github/workflows/test.yml)). | Runs entirely in the Python tool environment and supports incremental caches ([running mypy](https://mypy.readthedocs.io/en/stable/running_mypy.html#incremental-mode)). Pydantic works without a plugin, while its optional mypy plugin adds stricter generated-model checks at the cost of tool coupling ([Pydantic integration](https://docs.pydantic.dev/latest/integrations/mypy/)). | **Low to medium.** Mature, one-ecosystem choice. Start with strict project code and no model plugin unless a measured gap justifies it. |
|  | **Pyright** | Pyright's source defines Python 3.14 as a supported language version ([source](https://github.com/microsoft/pyright/blob/main/packages/pyright-internal/src/common/pythonVersion.ts)); releases are distributed through the official npm package ([package](https://github.com/microsoft/pyright/blob/main/packages/pyright/package.json)). | Fast incremental analysis and editor integration are strengths documented by the project ([README](https://github.com/microsoft/pyright#readme)). The official distribution requires Node/npm, so reproducibility must cover a second lockfile/runtime or a separately maintained wrapper. | **High operationally, low analysis friction.** Strong checker, but the second package ecosystem conflicts with the goal of a small locked toolchain unless its analysis behavior is materially better for this codebase. |
| Linting and formatting | **Ruff for both** | Current metadata declares Python 3.14 and Production/Stable maturity ([PyPI](https://pypi.org/project/ruff/)); Ruff's configuration model includes `py314` as a target version ([settings](https://docs.astral.sh/ruff/settings/#target-version)). | One executable performs linting, import sorting, and formatting. Ruff intentionally does not support custom lint plugins ([FAQ](https://docs.astral.sh/ruff/faq/#does-ruff-support-plugins)). Its formatter targets Black compatibility while documenting intentional deviations ([formatter](https://docs.astral.sh/ruff/formatter/)). | **Low.** Smallest tool count and aligns with the no-plugin direction. The human decision must accept Ruff's documented formatting differences rather than assume byte-for-byte Black output. |
|  | **Ruff lint plus Black format** | Current Black metadata declares Python 3.14 and Production/Stable maturity ([PyPI](https://pypi.org/project/black/)); first-party CI includes Python 3.14 ([CI](https://github.com/psf/black/blob/main/.github/workflows/test.yml)). | Ruff can lint and sort imports while Black owns formatting. Both support explicit target-version configuration ([Ruff settings](https://docs.astral.sh/ruff/settings/#target-version), [Black target versions](https://black.readthedocs.io/en/stable/usage_and_configuration/the_basics.html#t-target-version)). | **Medium.** Separates responsibilities and preserves Black as the formatting reference, but adds another executable, dependency graph, configuration surface, and CI step. |

## Cross-cutting tradeoffs

### Lockfiles and Python itself

A reproducible dependency graph is insufficient if CI and operator machines
silently use different Python patch releases. The later decision should define
both the committed dependency lock and how Python 3.14 is provisioned or
verified. uv can manage Python installations directly
([uv Python versions](https://docs.astral.sh/uv/concepts/python-versions/));
PDM can use installed interpreters and documents interpreter selection
([PDM environments](https://pdm-project.org/latest/usage/venv/)); Poetry
explicitly expects Python to be installed separately
([Poetry environments](https://python-poetry.org/docs/managing-environments/)).

### Validation belongs at the boundary

Neither finalist pairing is strict enough by default without repository policy:
PyYAML needs duplicate-key rejection; ruamel.yaml's API/version needs pinning;
Pydantic needs strict mode and forbidden extras; msgspec needs forbidden unknown
fields. Tests should prove that duplicate keys, multiple YAML documents,
unknown keys, type coercion, missing references, dependency cycles, and
unsupported schema versions all fail before a transport is constructed
(accepted Wayfinder constraints,
[PyYAML constructor](https://github.com/yaml/pyyaml/blob/main/lib/yaml/constructor.py#L132-L145),
[ruamel.yaml API](https://yaml.dev/doc/ruamel.yaml/api/),
[Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/),
[msgspec Struct options](https://github.com/jcrist/msgspec/blob/main/docs/structs.rst#L710-L742)).

### Canonical JSON should remain repository-owned

No CLI or model framework should define the stable automation format. Python
3.14's `json` encoder exposes the required controls for sorted keys, compact
separators, Unicode handling, and rejection of non-finite floats; the
repository should wrap those settings and test byte-for-byte golden fixtures
([Python 3.14 `json`](https://docs.python.org/3.14/library/json.html)).
Domain and Plan models should convert to plain canonical data before encoding,
so replacing a validation or CLI library does not change the versioned Plan
contract.

### Adapter seams contain dependency cost

Paramiko or AsyncSSH should implement repository-owned synchronous transport
ports; YAML and model libraries should be confined to configuration loading;
CLI frameworks should only parse input and present application results. This
keeps pure domain and planning tests independent of network, filesystem,
subprocess, parser, and presentation implementations
(accepted Wayfinder constraints).

## Focused shortlist for the human decision

Carry these bounded choices into **Choose the foundational Python toolchain**:

1. **Environment:** uv versus PDM. Keep Poetry only as the mature,
   higher-overhead baseline.
2. **Profiles:** PyYAML with a narrow strict loader versus ruamel.yaml safe
   parsing.
3. **Models:** strictly configured Pydantic versus msgspec Structs with unknown
   fields forbidden.
4. **Transport:** Paramiko as the synchronous candidate. Retain AsyncSSH only
   if changing the accepted execution model is itself in scope.
5. **CLI:** argparse versus Click. Retain Typer only if annotation-generated,
   Rich-oriented help becomes a stated requirement.
6. **Tests:** pytest without project-specific plugins versus the standard
   library's unittest baseline.
7. **Types:** mypy versus deliberately accepting Node/npm for official
   Pyright.
8. **Code quality:** Ruff for linting and formatting versus Ruff plus Black.

This is a recommendation about what to evaluate, not which combination to
choose.

## Required decision-ticket evidence

Before the human selects a combination, require:

1. A clean Python 3.14 environment created twice from the committed lock, with
   a locked/frozen CI check that fails when project metadata and lock state
   disagree.
2. A small Profile spike proving duplicate-key, multi-document, unknown-key,
   strict-type, missing-reference, dependency-cycle, and schema-version
   failures occur before any Device connection.
3. A disposable-Device transport spike proving host-key verification, command
   execution, upload, download, metadata inspection, atomic rename, timeout,
   ambiguous disconnect, and clean close behavior.
4. Canonical Plan/result JSON golden fixtures, including stable ordering,
   compact encoding, explicit Unicode behavior, and rejection of NaN and
   Infinity.
5. A representative pure planning benchmark and adapter-contract suite,
   measured with a cold unit-suite target below 10 seconds and a complete
   offline target below 60 seconds.
6. A dependency inventory for both application and development groups,
   including licenses, compiled wheels on the controller platforms, and the
   number of separately updated runtimes and lockfiles.

These checks turn upstream compatibility claims into repository-specific
evidence while preserving the maintainer's final choice.
