# ModForge

A mod installer for World of Warships. It patches the game's own UI files from small XML
**blueprints**, so several mods can edit the same vanilla file without overwriting each other,
and builds a mod's own Unbound 1 payload out of the current build's markup.

Usually bundled inside other mods' packs, not installed on its own. It runs once at game start,
has no UI, and reverts every file to stock when removed.

## What it does, in order

1. **Discover** every blueprint under `res_mods/ForgeBlueprints/` and `res_mods/PnFMods/*/manifest.xml`.
2. **Check requirements** — installer version and mod dependencies; unmet ones skip that mod only.
3. **Build** any Unbound 1 payload a blueprint declares — generate the markup from vanilla,
   compile the `.swf`.
4. **Order** by dependency, then `priority`, then filename.
5. **Fetch the pristine original** of each target file (from `res/`, or unpacked from the `.pkg`).
6. **Apply every mod's edits** and write the merged files.

It skips the whole run if no blueprint, mod set, or game build changed since last launch.

## Features

- **Non-destructive.** Edits stack on the untouched original, so mods share a file instead of
  overwriting each other. Removing a blueprint reverts its edits.
- **Atomic.** All files commit together or roll back — never a half-written state.
- **Isolated failure.** A mod whose edit throws is reverted alone; the rest still install.
- **Crash-safe.** A reference that would hard-crash the client at boot is redirected to a stub, so
  only that one mod goes inert.
- **Incremental.** Tracks what it wrote; rebuilds a file if something else overwrote it, and
  re-fetches originals when the game updates.
- **Builds Unbound 1 payloads.** Ship the `.xml`; ModForge compiles the `.swf` the client needs,
  so there is no build tool to run and nothing to rebuild by hand when you edit an expression.
- **Tracks vanilla markup and styles.** Describe your changes to a vanilla `<block>` or `<css>`
  instead of copying it, and the copy is re-cut from the current build every launch — no
  re-diffing after a patch.
- **Handles the boilerplate.** One element registers your payload in `uss_settings.xml`;
  another mounts an element in battle, both entries it needs.

## Writing a blueprint

Ship it as `res_mods/PnFMods/<YourMod>/manifest.xml`, or drop it in `res_mods/ForgeBlueprints/`.
Ship your own art and sound; the XML ModForge can build for you.

```xml
<mod name="My Mod" version="1.0.0" priority="0">
  <requires installer=">=1.0.0"/>            <!-- or: <requires mod="Other" version=">=2.0"/> -->
  <build file="gui/battle_elements.xml">
    <insert into="elementList">
      <element name="myClip" class="MyClip"/>
    </insert>
  </build>
</mod>
```

A `<build>` names one game file and lists the edits to make to it. Every path is relative to
`res_mods/` and must stay inside it.

### An Unbound 1 mod, whole

An Unbound 1 mod is three things: a markup `.xml`, a `.swf` holding every `value=` expression in
that markup compiled, and an entry in `gui/uss_settings.xml` so the client loads the pair.
`<ubBuild>` is all three:

```xml
<mod name="My Mod" version="1.0.0">
  <ubBuild name="MyMod">
    <copy from="gui/unbound/markup.xml" select="block[@className='PortSwitcher']" into=".">
      <setAttribute attribute="className" to="MyPortSwitcher"/>
    </copy>
  </ubBuild>
</mod>
```

That writes `gui/unbound/mods/MyMod.xml`, compiles `gui/unbound/mods/MyMod.swf` from it, and
registers both. `name` fixes all three paths, so there is nothing to keep in sync. Add
`autoCompile="false"` if your mod is markup only — the `<swffile>` line then goes away too, which
matters: a registration naming a file nothing produces hangs the client at boot.

Ship only what is yours. The build is cached on its inputs, so it runs once and then only when
something it reads changes; the outputs are deleted when the mod is removed.

If your markup will not compile, that mod alone is skipped and the reason is in `python.log`. One
error is worth knowing about in advance: the client blanks six identifiers in the constant pool of
any unsigned `.swf`, so an expression containing `ExternalInterface`, `GameDelegate`,
`GameInfoHolder`, `InputDelegate`, `gameInfoHolder`, `getDefinitionByName` — **or any leading part
of one**, down to a single letter — is refused rather than shipped in a form that would silently
misbehave.

### Copying vanilla instead of pasting it

An Unbound 1 mod normally works by redefining a vanilla `<block className="…">` — which means
pasting the whole block into your markup and changing a line or two. That copy is frozen at the
version you pasted it from, and every game update silently stales it.

`<copy from="…">` takes the block out of the build the player is running, every launch:

```xml
<ubBuild name="MyMod">
  <copy from="gui/unbound/markup.xml" select="block[@className='PortSwitcher']" into=".">
    <setAttribute attribute="className" to="MyPortSwitcher"/>
    <setAttribute select="block/block[@type='text']/bind[@name='text']"
                  attribute="value" to="'Hello'"/>
  </copy>
  <copy from="gui/unbound/styles.xml" select="css[@name='PortSwitcherPreset']" into="."/>
</ubBuild>
```

Nothing in the mod is a copy of vanilla any more. After a game update the block is re-cut and the
`.swf` rebuilt on the next launch, and if the block — or anything your selectors name — is gone,
that mod is skipped with the reason in `python.log` rather than shipping a stale duplicate.

- `from=` is any vanilla file. `gui/unbound/markup.xml` holds the `<block className=>`
  definitions, `gui/unbound/styles.xml` the `<css name=>` ones; the two are disjoint.
- The first step of `select=` names a **top-level** definition — one of the ~1,700 the build
  declares directly under `<ui>`. A name that only exists nested inside another is not
  addressable, and if a build ever declares the same one twice the copy is refused rather than
  guessing between them. Further steps reach inside it: `block[@className='X']/style`.
- `into="."` puts the copy at the root of the file being built. Children of `<copy>` are actions
  on the copy itself, so a `<setAttribute>` with no `select=` renames its root — which is how you
  publish vanilla's definition under your own name instead of overriding the original.
- Without `from=`, `<copy>` clones from the file being edited rather than another one.

### Showing it in battle

Registering a payload makes the client load it; it does not put anything on screen in battle.
`<ubMountInBattle>` writes the `battle_elements.xml` entries that do:

```xml
<ubMountInBattle unbound="1" rootElementId="MyModContainer"/>
```

`rootElementId` is the element your markup defines. `unbound=` says which framework defines it,
and is **required** — the two are written differently in all three places that matter:

| | `unbound="1"` | `unbound="2"` |
|---|---|---|
| class | `lesta.libs.unbound.UnboundElement` | `lesta.unbound2.UbElement` |
| root id | inside `<properties>` | `elementName=` on the element |
| controller | written — without it the element is listed and never constructed | none |

There is no default and no guess. ModForge cannot tell the two apart from the id: an Unbound 1
root is a `<block>` in your own payload, which for a `<ubBuild>` mod does not exist yet when the
macro expands. Naming the wrong one produces a well-formed entry that simply never renders.

`name=` is the instance name the client uses internally and defaults to `rootElementId`;
`hitTest="false"` opts out of mouse hit-testing, worth doing for anything purely decorative.
`url=` is accepted and passed through, but an Unbound element does not need one — vanilla's own
Unbound 1 entries carry none — so leave it out unless you know otherwise.

### Registering a payload you already built

If you ship a precompiled `.xml`/`.swf` pair, put it in `gui/unbound/mods/` and register it:

```xml
<ubRegister name="MyMod"/>            <!-- swf="false" for markup only -->
```

`<ubBuild>` does this for you; `<ubRegister>` is for the mods that do not use it.

### The primitives

`<ubBuild>`, `<ubRegister>` and `<ubMountInBattle>` are shorthand. Underneath there are two:

| Element | Does |
|---|---|
| `<build file="…">` | Edit a vanilla file, starting from its pristine copy. |
| `<build file="…" root="ui">` | Generate a new file, starting from an empty `<ui>` document. |
| `<ubCompile out="…" source="…"/>` | Compile markup into a `.swf`. Repeat `<source file="…"/>` as children to compile several files into one. |

### Selectors

A subset of XPath 1.0, and **everything in it means exactly what XPath means** — checked
expression-by-expression against a real XPath engine. Anything outside the subset is refused with
an error, never quietly misread.

| | |
|---|---|
| steps | `a/b/c`, `.`, `..`, `*` |
| descendant | `.//b`, `a//b` |
| attribute | `[@n='x']`, `[@n!='x']`, `[@n]` |
| text | `[text()='x']`, `[text()]`, `[.='x']` |
| position | `[1]`, `[last()]` |

Not supported, and refused: `//` from the root (there are no absolute paths — use `.//`), `|`,
`position()>1`, `@a` as a step, and any value containing `]`.

Four things that bite if you assume otherwise:

- **A predicate takes either quote style.** An Unbound `value=` is built out of single-quoted
  strings, so selecting a `<bind>` by its expression needs the double-quoted form:
  ```xml
  <setAttribute select="bind[@value=&quot;isEnemy ? '-1' : '1'&quot;]" attribute="value" to="'1'"/>
  ```
- **A position indexes what the predicates before it selected**, not the raw sibling list.
  `b[@n='x'][2]` is the second `x`-named `b`; `b[2][@n='x']` is the second `b`, kept only if it is
  `x`-named. Positions are 1-based, so `[0]` matches nothing.
- **A position applies per context node.** `a/b[1]` is the first `b` of *each* `a`. If you mean
  the first one anywhere, that is `.//b[1]`.
- **`[text()='x']` tests each text child separately**; `[.='x']` compares the whole string value.
  Neither trims whitespace.

Prefer a path plus a stable `@name` over a long value or an index where you have the choice —
both of the latter break on the next patch, an index silently.

**Actions** inside a `<build>`:

| Action | Does |
|---|---|
| `<insert into="sel">…</insert>` | Add children into the parent (`before=`/`after=` for placement). Identical re-inserts are skipped. |
| `<remove select="sel"/>` | Delete matched nodes. |
| `<replace select="sel">…</replace>` | Swap matched nodes for the supplied elements. |
| `<setAttribute select="sel" attribute="a" to="v"/>` | Set attribute `a`, adding it if absent; with `from="old"`, replaces that substring instead and does nothing where it is not found. |
| `<copy select="sel" into="sel">…</copy>` | Clone nodes, from this file or from `from="…"`. Children are actions on the clone. |

A `<guard ifExists="sel"/>` or `<guard ifNotExists="sel"/>` at the top of a `<build>` skips it
unless the condition holds. Reach for a guard only for real conditional logic (e.g. patch differently
depending on another mod). You don't need one to avoid installing twice: re-applying is idempotent —
identical inserts are skipped, and an unchanged run is a no-op — so the old "skip if my element
already exists" guard is unnecessary. A `root=` build has nothing to test, so it takes no guard.

Worth knowing:

- **Edits stack on the pristine original, in order.** Each file starts from the vanilla copy;
  mods apply one after another. A higher `priority` runs earlier, so a later mod's selectors can
  match — and edit — what an earlier one added. Use `<requires mod=…>` when you truly depend on
  another mod: it both enforces order and skips your mod if that mod is absent.
- **Failures are contained, not silent.** A selector that matches nothing (or any error) reverts
  just your mod's edits to that file and moves on — the rest still install. Unknown attributes and
  elements are warnings, not fatal. Watch `python.log` for `[ModForge]` lines.
- `file=` is relative to `res_mods/`. ModForge fetches the original even if the game only ships it
  packed, so you can target any vanilla UI file, not just already-unpacked ones.