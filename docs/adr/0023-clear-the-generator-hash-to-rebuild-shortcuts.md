---
status: accepted
---

# Clear the generator hash to rebuild shortcuts

The skin shows what `script-skinvariables-generator-includes-.xml` holds, and
`script.skinvariables` compiles that include from the Shortcut Nodes when the
Home window loads. `ShortcutsTemplate.update_xml` (`template.py:283-330`)
skips the compile when the Skin String `script-skinvariables-generator-hash`
matches a hash of its kwargs, the profile name and the skin's
`skinvariables-generator.json`. The node files are not in that hash, so a
changed Shortcut Node never reached the skin on a Device already in service
(#169).

**When a Run changes a Shortcut Node, it clears the generator hash in the
skin's Settings Document during the Kodi stop it already takes, and waits for
the include to be recompiled.** This is a Rebuild Trigger on a Contested
Address. The Run writes the hash once, and the skin disarms the trigger by
storing a fresh hash after it compiles. The Reconciler declares no value
there. This follows [ADR 0015](0015-trigger-the-view-rebuild-the-way-the-skin-does.md):
a file write while Kodi is stopped, fired by the restart the Run was already
taking.

Clearing an absent hash creates nothing. A fresh Device holds no hash and
compiles on its first load anyway.

The Run waits until the include differs from what it held when Kodi was
stopped and parses as XML. Checking for the declared guids was rejected
because removing or relabelling a shortcut leaves every remaining guid in the
old include, so the check would pass before any rebuild.

## Considered options

- **Stamp `Shortcuts.RebuildDateTime`**, the skin editor's own signal. The
  skin also writes `FirstRun` and editor timestamps there, so a declared value
  would fight it.
- **Leave it manual.** Without the fix, every Shortcut Node change needs a
  step nobody is prompted for, and skipping it produces no error.
