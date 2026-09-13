# ModForge

A mod installer for World of Warships. It patches the game's own UI files from small XML
**blueprints**, so several mods can edit the same vanilla file — or the same Unbound 1
definition — without overwriting each other, and builds their payloads out of the current
build's markup.

Usually bundled inside other mods' packs, not installed on its own. It runs once at game start,
has no UI, and reverts every file to stock when removed.

Writing a mod: start at [Writing a blueprint](#writing-a-blueprint).
Porting one from ModsInstaller 4.3.1: start at
[Converting a ModsInstaller 4.3.1 mod](#converting-a-modsinstaller-431-mod).
Either way, read [Silent failures the client will not report](#silent-failures-the-client-will-not-report)
before writing markup — most Unbound 1 mistakes have no symptom at all.

## Contents

- [What it does, in order](#what-it-does-in-order)
- [Features](#features)
- [Writing a blueprint](#writing-a-blueprint) — [schema reference](#schema-reference), [selectors](#selectors), [actions](#actions)
- [An Unbound 1 mod, whole](#an-unbound-1-mod-whole)
- [Reading the log](#reading-the-log)
- [Converting a ModsInstaller 4.3.1 mod](#converting-a-modsinstaller-431-mod)
- [Silent failures the client will not report](#silent-failures-the-client-will-not-report)
- [Working on ModForge](#working-on-modforge)

## What it does, in order

1. **Discover** every blueprint under `res_mods/ForgeBlueprints/` and `res_mods/PnFMods/*/manifest.xml`.
2. **Check requirements** — installer version and mod dependencies; unmet ones skip that mod only.
3. **Order** by dependency, then `priority`, then filename.
4. **Merge each Unbound 1 definition** every blueprint names — one document per `<block>` or
   `<css>`, sliced from the current build and carrying every mod's edits to it — then compile one
   shared `.swf` and register what it wrote.
5. **Fetch the pristine original** of each target file (from `res/`, or unpacked from the `.pkg`).
6. **Apply every mod's edits** and write the merged files.

It skips the whole run if no blueprint, mod set, or game build changed since last launch.

## Features

- **Non-destructive.** Edits stack on the untouched original, so mods share a file instead of
  overwriting each other. Removing a blueprint reverts its edits.
- **Atomic.** All files commit together or roll back — never a half-written state.
- **Isolated failure.** A mod whose edit throws is reverted alone; the rest still install.
- **Crash-safe by construction.** The entry that hangs the client at boot is one registered against
  a file that is missing or will not parse. ModForge is the only writer of `uss_settings.xml` and
  registers only what it staged in the same commit, so that entry cannot arise — it is not a check
  that might miss a case.
- **Incremental.** Tracks what it wrote; rebuilds a file if something else overwrote it, and
  re-fetches originals when the game updates.
- **Merges Unbound 1 definitions across mods.** Name the `<block>` or `<css>` you change, not a
  file. Two mods changing the same one contribute to a single document instead of shipping rival
  files where the last loaded wins; `priority` settles a real collision and the run reports it.
- **Tracks vanilla markup and styles.** Your mod describes its changes rather than carrying a
  copy, and the baseline is re-cut from the current build every launch — no re-diffing after a
  patch.
- **No build step.** ModForge decides the files, compiles the `.swf` the client needs, and writes
  the `uss_settings.xml` entries. Nothing to rebuild by hand when you edit an expression.
- **Checks what the client will not.** An expression key the compiled `.swf` lacks, a
  `styleClass` that resolves to nothing, a definition two files declare — each is silent in game
  and each is an install-time line in `python.log`.

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

### Schema reference

Every element a blueprint may contain at the top level; the five actions that go *inside* them
are in [Actions](#actions). An unknown **element** and an unknown **attribute** are both ignored
with an info line and nothing else — a typo is quiet, so read the log after a change.

| Element | Attributes | Notes |
|---|---|---|
| `<mod>` | `name`\*, `version`\*, `priority` | one per file. `priority` defaults to 0; higher applies **earlier** |
| `<requires installer=>` | `installer`\* | version constraint, e.g. `>=1.0.0`. **This installer is 1.0.0.** An unmet constraint skips your mod |
| `<requires mod=>` | `mod`\*, `version` | matches another blueprint's `<mod name=>` — so `name` is an identity key, not a label: keep it stable across renames. Enforces order, and skips your mod if that one is absent |
| `<ubBuildBlock>` | `name`\* | a `<block className=>` in `gui/unbound/markup.xml` |
| `<ubBuildStyle>` | `name`\* | a `<css name=>` in `gui/unbound/styles.xml` |
| `<ubMountInBattle>` | `unbound`\*, `rootElementId`\*, `name`, `hitTest`, `url`, `before` \| `after` | writes the `battle_elements.xml` entries |
| `<build>` | `file`\*, `root` | edit a vanilla file; with `root=` generate a new one |
| `<guard>` | `ifExists` \| `ifNotExists` | inside a `<build>` with no `root=`; position does not matter |

\* required.

Names are **opaque and verbatim**. `$Foo` and `Foo` are different presets; nothing normalises the
`$`, because the client does not either — it is convention, not grammar.

A definition verb may not carry a `<guard>`, and neither may a `root=` build. Both are refused
outright rather than treated as a condition that is always false: a guard reads the document it
edits, and those two start from a definition or from nothing.

### An Unbound 2 mod, whole

Unbound 2 is the current standard, and it needs almost nothing from ModForge. A view at
`gui/unbound2/PnFMods/<YourMod>.unbound` is found by the client on its own — **no registration, no
compile, no `.swf`, and none of the `ubBuild*` verbs**. All ModForge does is put it on screen in
battle:

```xml
<mod name="MyMod" version="1.0.0">
  <requires installer=">=1.0.0"/>
  <ubMountInBattle unbound="2" rootElementId="MyMod_Container" after="MainHud"/>
</mod>
```

`rootElementId` is the name of the `(def element …)` your `.unbound` declares. That is the whole
blueprint for a typical Unbound 2 mod.

Everything below about `<ubBuildBlock>`, `<ubBuildStyle>`, SWF compilation and `markup.xml` is
**Unbound 1** — the older framework. You need it only if you are changing the game's own Unbound 1
markup.

### An Unbound 1 mod, whole

An Unbound 1 mod redefines a **definition** — a `<block className=>` in
`gui/unbound/markup.xml`, or a `<css name=>` in `gui/unbound/styles.xml`. Name the one you edit
and list the changes:

```xml
<mod name="My Mod" version="1.0.0">
  <ubBuildBlock name="PortSwitcher">
    <setAttribute select=".//bind[@name='text']" attribute="value" to="'Hello'"/>
  </ubBuildBlock>

  <ubBuildStyle name="$TextHeaderBold">
    <setAttribute select="./fontSize" attribute="value" to="19"/>
    <setAttribute select="./textColor" attribute="value" to="0xFFCC66"/>
  </ubBuildStyle>
</mod>
```

You name the definition; ModForge decides the file, the compile and the registration. Selectors
inside are written against the definition itself: `.` is it, `./x` its own children, `.//x`
anything inside it.

The point of naming the definition rather than a file: **two mods editing the same one merge.**
Each contributes its own edits to one document, so you get both, instead of two files racing to
define the same name with the last one loaded winning.

Where they genuinely collide, `priority` decides and the run says so:

- **Same attribute of the same element.** The higher `priority` wins; the loser is named in
  `python.log` and its *other* edits still land. Nothing is silently overwritten.
- **One mod removes what another edits.** That one selector is skipped, reported, and the rest of
  the mod still applies. A selector that never matched anything in vanilla is still your own
  error and still reverts your whole contribution to that definition — the two cases are told
  apart by replaying the action against the untouched definition.

The baseline is sliced out of the build the player is running, every launch, so nothing in your
mod is a frozen copy of vanilla.

A name vanilla does not define is **created from empty** rather than refused — it has to be, since
a new definition of your own is the same thing from the outside. So the run counts the two
separately (`4 overridden, 1 created`), and that count is your only signal for a misspelt name or
one the game renamed in the last patch: both show up as `created` where you meant `overridden`,
and the definition then renders nothing at all.

If your markup will not compile, that definition alone is dropped and the reason is in
`python.log`.

One refusal is worth knowing about in advance. The client blanks six identifiers in the constant
pool of any unsigned `.swf`: `ExternalInterface`, `GameDelegate`, `GameInfoHolder`,
`InputDelegate`, `gameInfoHolder`, `getDefinitionByName`. It matches by **pool entry**, not by
substring, and a pool entry that is a *prefix* of one of those is blanked too — so a bare
identifier `Game`, or even `G`, is refused, while `gameplay` (not a prefix of any of them) is
fine. Your expression's identifiers each become a pool entry; string literals and property names
count. ModForge refuses the build rather than ship something that would silently misbehave.

### Pulling in another definition

`<copy from="…">` takes an element out of a vanilla file and puts it in the one being built:

```xml
<ubBuildBlock name="MyPortSwitcher">
  <copy from="gui/unbound/markup.xml" select="block[@className='PortSwitcher']/style" into="."/>
</ubBuildBlock>
```

- `from=` is any vanilla file. `gui/unbound/markup.xml` holds the `<block className=>`
  definitions, `gui/unbound/styles.xml` the `<css name=>` ones; the two are disjoint.
- The first step of `select=` names a **top-level** definition — one of the ~1,700 the build
  declares directly under `<ui>`. A name that only exists nested inside another is not
  addressable, and if a build ever declares the same one twice the copy is refused rather than
  guessing between them. Further steps reach inside it: `block[@className='X']/style`.
- Children of `<copy>` are actions on the copy itself, with selectors relative to it, so a
  `<setAttribute>` with no `select=` rewrites its root attribute.
- Without `from=`, `<copy>` clones from the document being built rather than another file.

**To publish a vanilla definition under your own name**, copy its *children* into a definition of
the name you want — note the `/*`:

```xml
<ubBuildBlock name="MyPortSwitcher">
  <copy from="gui/unbound/markup.xml" select="block[@className='PortSwitcher']/*" into="."/>
  <setAttribute select=".//bind[@name='text']" attribute="value" to="'Mine'"/>
</ubBuildBlock>
```

Nothing is lost by taking the children rather than the block: every top-level vanilla definition
carries `className` and no other attribute, and your verb supplies the name.

Copying the block itself (`select="block[@className='PortSwitcher']"`, without `/*`) does not
rename it — it **nests** it, so your definition ends up with the vanilla block as its only child
and renders one layout level deeper than you meant. It will not error; check the emitted file if
the layout looks off by a container.

### Showing it in battle

A registered definition is loaded by the client; that alone does not put anything on screen in
battle. `<ubMountInBattle>` writes the `battle_elements.xml` entries that do:

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
root is a `<block>` in a definition that has not been merged yet when the macro expands. Naming
the wrong one produces a well-formed entry that simply never renders.

`name=` is the instance name the client uses internally and defaults to `rootElementId`. Vanilla
gives every entry a distinct instance name (`ubMarkersContainer`, `unboundShipStateBars`), so a
name of your own is worth setting.

`hitTest=` takes `true` or `false` and **defaults to `true`**; `false` opts out of mouse
hit-testing, worth doing for anything purely decorative. `url=` is accepted and passed through,
but an Unbound element does not need one — vanilla's own Unbound 1 entries carry none — so leave
it out unless you know otherwise.

**Placement is render order, so set it.** `before=` and `after=` take the `elementName` of an
existing entry:

```xml
<ubMountInBattle unbound="2" rootElementId="MyModContainer" after="MainHud"/>
<ubMountInBattle unbound="2" rootElementId="MyOverlay" before="MarkersContainer"/>
```

Without either the entry is appended, which puts it on top of everything. Give one or the other
unless last is genuinely what you want — an element anchored `before="MarkersContainer"` draws
*under* the markers, and appending it instead draws it over them, with no error either way. The
anchor matches `elementName`; six of vanilla's 24 entries have only a `name`, and to sit next to
one of those use `<build file="gui/battle_elements.xml">` directly.

### The primitives

`<ubBuildBlock>`, `<ubBuildStyle>` and `<ubMountInBattle>` sit on top of one thing:

| Element | Does |
|---|---|
| `<build file="…">` | Edit a vanilla file, starting from its pristine copy. |
| `<build file="…" root="ui">` | Generate a new file, starting from an empty `<ui>` document. |

`<build file=>` is for the vanilla files no definition-keyed verb covers — `gui/battle_layout.xml`
and the like.

**It will not write what Unbound owns.** `gui/uss_settings.xml`, `gui/unbound/markup.xml`,
`gui/unbound/styles.xml`, anything else vanilla lists in that file's `<default>` block, and
ModForge's own output directory `gui/unbound/mods/` are all refused, and the mod is skipped with a
message naming the verb to use instead. ModForge is the only writer of those, which is what lets
it guarantee that every registered entry names a file it just wrote — the registered-but-missing
entry is the one that hangs the client at boot with nothing in the log.

If you ship a prebuilt `.xml`/`.swf` pair today, declare its definitions with `<ubBuildBlock>` /
`<ubBuildStyle>` instead and drop the `.swf` — ModForge compiles one for everything it emits.

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
| substring | `[contains(@n,'x')]`, `[contains(.,'x')]`, `[contains(text(),'x')]` |
| position | `[1]`, `[last()]` |

Not supported, and refused: `//` from the root (there are no absolute paths — use `.//`), `|`,
`position()>1`, `@a` as a step, and any value containing `]`.

Five things that bite if you assume otherwise:

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
- **`.//` searches descendants, a bare step searches children.** `bind[@name='x']` only sees direct
  children; if the node is nested — a style property lives under `<style>`, for instance — you want
  `.//bind[@name='x']` or the explicit path.
- **`..` reaches the parent, and works after a descendant step.** This is how you address a
  container that has no name of its own — find the child that identifies it, then climb:
  ```xml
  <insert into=".//bind[@name='repeat']/../style"><maxHeight value="800"/></insert>
  ```
  The one restriction is that `..` may not come *immediately* after `//`.
- **Predicates chain, and mixing kinds is fine.** `bind[@name='collectionDH'][contains(@value,'ship')]`
  is how you pick one of several identically-named binds — usually better than an index, which
  breaks silently on the next patch.

Prefer a path plus a stable `@name` over a long value or an index where you have the choice —
both of the latter break on the next patch, an index silently.

One mod may `setAttribute` the same attribute repeatedly; the writes stack in order and the last
one stands. The conflict rule below is between *different* mods, not within one.

### Actions

The body of a `<build>` or either definition verb:

| Action | Does |
|---|---|
| `<insert into="sel">…</insert>` | Add children into the parent. `before=`/`after=` place them, and that selector is evaluated **with the `into=` node as its root** — so a bare step like `bind[@name='x']` means a *child* of it, and `.//bind[…]` is needed for anything deeper. Without either, children are appended. Identical re-inserts are skipped. |
| `<remove select="sel"/>` | Delete matched nodes. |
| `<replace select="sel">…</replace>` | Swap matched nodes for the supplied elements. |
| `<setAttribute select="sel" attribute="a" to="v"/>` | Set attribute `a`, adding it if absent. With `from="old"` it replaces **every** occurrence of that substring instead, and does nothing at all where the substring is absent — silently, so check your result. `select=` may be omitted, which targets the node the action is scoped to. |
| `<copy select="sel" into="sel">…</copy>` | Clone nodes, from this file or from `from="…"`. Children are actions on the clone. |

A `<guard ifExists="sel"/>` or `<guard ifNotExists="sel"/>` anywhere inside a `<build>` skips the
whole build unless the condition holds. Reach for a guard only for real conditional logic (e.g. patch differently
depending on another mod). You don't need one to avoid installing twice: re-applying is idempotent —
identical inserts are skipped, and an unchanged run is a no-op — so the old "skip if my element
already exists" guard is unnecessary.

A guard reads the document it edits, so two places refuse one outright rather than quietly
treating every condition as false: a `root=` build, which starts from an empty document, and
`<ubBuildBlock>` / `<ubBuildStyle>`, which are assembled from the vanilla definition when there
is one and from nothing when there is not.

Worth knowing:

- **Edits stack on the pristine original, in order.** Each file starts from the vanilla copy;
  mods apply one after another. A higher `priority` runs earlier, so a later mod's selectors can
  match — and edit — what an earlier one added. Use `<requires mod=…>` when you truly depend on
  another mod: it both enforces order and skips your mod if that mod is absent.
- **Failures are contained, not silent.** A selector that matches nothing (or any error) reverts
  just your mod's edits to that file and moves on — the rest still install. Unknown attributes and
  elements are warnings, not fatal. Watch `python.log` for `[ModForge]` lines.
- **The summary line is worth reading** — see [Reading the log](#reading-the-log).
- `file=` is relative to `res_mods/`. ModForge fetches the original even if the game only ships it
  packed, so you can target any vanilla UI file, not just already-unpacked ones.

## Reading the log

Every line is prefixed `[ModForge]` in `python.log`. The ones worth reacting to:

| Line | Means | Do |
|---|---|---|
| `created <ubBuildBlock name='X'>` where you meant to override | the build has no `X` | check the spelling, or whether the patch renamed it |
| `'A' cannot set v on <bind> in …: 'B' set it first` | two mods want the same attribute | raise your `priority`, or accept B's value |
| `… skipped -- a mod applied before it changed what that names` | a peer removed what your selector named | usually fine; your other edits landed |
| `'A' failed on <ubBuildBlock name='X'>: ActionError: … matched nothing` | your selector matches nothing in vanilla either | fix the selector — the whole contribution was reverted |
| `X: N expression(s) the compiled SWF does not carry` | the definition was dropped, not registered | an expression failed to compile; the reason is logged above |
| `<styleClass value='$X'> names no preset …` | silent in game | define `$X` with `<ubBuildStyle>`, or fix the name |
| `<block className='X'> is declared by a.xml, b.xml` | two emitted files declare one name | whichever loads last wins; nothing is logged in game |
| `'A' writes gui/uss_settings.xml, which Unbound owns` | the mod was skipped entirely | use the verb the message names |
| `'X' changed on disk since our last run` | something else overwrote a file ModForge wrote | the copy is kept under `.installer_cache/drift_backups/` |
| `no manifest changes since last run; nothing to do` | the whole run was skipped | expected; touch a blueprint to force one |

The run ends with two summary lines — the mod counts, then:

```
definitions: 4 registered (1 created, 3 overridden), 0 dropped, 0 conflicting write(s)
```

## Converting a ModsInstaller 4.3.1 mod

`ConvertV4.py` translates a v4 instruction file. It runs outside the game on plain CPython 2.7 or
3.x, stdlib only. It lives in the author's private notes repo, mounted at `notes/` and not part of
a public clone:

```bash
py -3 notes/ModForge/payload_tools/ConvertV4.py <v4-file-or-dir> <output-dir>
```

v4 files come in two shapes. Which one dominates depends on the mod set: across one author's
own 25, 21 were battle mounts; across a 110-mod third-party corpus, most were payload
registrations. Check before assuming.

**Shape one: a `battle_elements.xml` insert.** Converts to a single `<ubMountInBattle>`:

| v4 | blueprint |
|---|---|
| `<check name="X" version="Y"/>` | `<mod name="X" version="Y">` — the only place a v4 file carries its identity |
| `<element class="lesta.unbound2.UbElement" elementName="X">` | `<ubMountInBattle unbound="2" rootElementId="X">` |
| `<element class="lesta.libs.unbound.UnboundElement">` + a `<controller>` | `<ubMountInBattle unbound="1" …>` — it writes the controller too |
| `name="unbound2MyThing"` on the element | `name="unbound2MyThing"` — **carry it over.** Omitted, it defaults to `rootElementId`, silently changing the client-internal instance name |
| `<properties hitTest="true"/>` | `hitTest="true"` (the default) |
| `<position insert="after_node" … value_1="MainHud"/>` | `after="MainHud"` |
| `<do_if_not_exist …/>` | drop it — re-applying is idempotent |

**Do not drop the `<position>`.** It is render order, and losing it is silent.

A v4 file with several `<insert>`s becomes several `<ubMountInBattle>` in one `<mod>` — that is
fine, and better than inventing a second mod identity. Keep `<mod name=>` exactly as `<check
name=>` had it even where that disagrees with the repo or element name; it is what
`<requires mod=>` resolves against.

**Shape two: a `uss_settings.xml` registration.** A v4 file that only registers a payload and
touches nothing else maps to **no `<build>` and no mount at all** — ModForge registers what it
emits, so the registration simply disappears. What survives is the payload's *content*, as
definitions.

**What it can and cannot see.** A v4 file is an *instruction* file. Where the mod shipped a
prebuilt `.xml`/`.swf` pair and v4 merely registered it, nothing in the instruction describes what
that payload defines — so the converter emits a `TODO` naming the files instead of guessing. That
is the common case, not the exception.

Finishing such a mod by hand:

1. Open the payload the TODO names, e.g. `res_mods/gui/unbound/mods/aslain_link.xml`.
2. Every **top-level** `<block className="X">` becomes `<ubBuildBlock name="X">`; every top-level
   `<css name="$Y">` becomes `<ubBuildStyle name="$Y">`. Nested ones are not definitions — they are
   inline children, and they come along with their parent.
3. **Diff each one against the current `markup.xml`.** A v4 payload is normally a verbatim copy
   of the vanilla definition with a handful of lines changed, so the diff *is* the mod. Three
   shapes come out of it:

   | the payload's definition is | write |
   |---|---|
   | vanilla's, with edits | `<ubBuildBlock name="TheVanillaName">` + just those edits |
   | vanilla's, under a different name | a verb with the new name + the `/*` copy form, then the edits |
   | entirely the mod's own | a verb with that name + `<insert into=".">` of its children |

4. **Treat drift as deletion, not as a feature.** The payload froze vanilla at the build it was
   made on, so a hunk that differs may be the author's intent *or* markup WG has since changed or
   removed. Check whether the surrounding block still exists in current vanilla before carrying it
   forward — a mechanical port of every difference silently resurrects markup the game deleted.
   (Seen in the wild: a payload still carrying an `isEventShip` branch and an
   `IDS_STEQ_EQUIPMENT_NOT_AVAILABLE` window that appear nowhere in either of the last two builds.)
5. Delete the `.swf`. ModForge compiles one shared SWF for everything it emits.

**Checking your work.** There is no offline validator in a public clone — the test suite and the
dry-run harness live in the author's private notes repo. Your feedback loop is booting the client
and reading `python.log`, so [Reading the log](#reading-the-log) is the section to keep open.

What the converter *does* handle mechanically: a v4 payload assembly (`<copy_past>` plus edits)
becomes one definition verb per seeded block, because "copy vanilla X, edit it, register the file"
and "`<ubBuildBlock name="X">` plus those edits" are the same thing. A republish — v4's
`<rename attr_rename="className">` over a seeded copy — becomes the `/*` copy form above.

The one construct it refuses to guess at is a root-level op that searched the **whole** v4 payload
with `.//`. Each definition is its own document now, so the same action would have to be repeated
in every one and would fail in each that has nothing matching, taking the mod with it. Those become
a `TODO` naming the definitions involved.

## Silent failures the client will not report

Unbound 1 has no error reporting worth the name. These are worth knowing before you write markup,
because none of them produces a useful symptom:

| You write | What happens |
|---|---|
| `bind name="tpyo"` | `ReferenceError #1056` when that block is built. Measured: in a block the port builds, **the port never presents** — the client sits on "Logging in…" |
| `bind name="tpyo!"` (trailing `!`) | nothing at all — a missing property of a sealed class reads as `undefined` here |
| a `<styleClass>` naming no preset | ignored, no log; the element renders with inherited values |
| an unknown child tag or attribute | dead markup; tag dispatch is E4X child access, so anything unnamed is never looked at |
| `<flow value="verticle">`, and the same for `position`, `overflow`, `backgroundSize`, `textAlign`, `scrollbarAlign` | **the client hangs at login** — the parse throws inside the load queue, which then never advances |
| `<background9Slice>` / `<userData>` reading any identifier | same hang; those are evaluated with a null scope while the XML loads, so they may only contain literals |
| a registered file that is missing, empty, or malformed | the boot stalls on a countdown that never reaches zero |

ModForge removes the last row by construction — it is the only writer of `uss_settings.xml` and
registers only what it just wrote — and reports the `styleClass` and expression-key cases at
install time. The rest are the author's to avoid. Uncaught AS3 errors *do* reach `python.log` as
`ERROR: [Scaleform] Error: …`, so silence there is evidence.

## Working on ModForge

```
PnFMods/ModForge/*.py      31 modules; the installer itself
PnFMods/ModForge/Main.py   entry point, run once at game start
ForgeBlueprints/           where blueprints are dropped at runtime
notes/                     private notes repo, mounted here (gitignored)
notes/ModForge/tools/      test suite, corpus dry-run, mutation harness
notes/ModForge/payload_tools/  ConvertV4, the SWF compiler's oracle harness
```

| Command | Does |
|---|---|
| `py -2.7 notes/ModForge/tools/run_tests.py` | the whole suite |
| `py -2.7 notes/ModForge/tools/run_tests.py merge` | one module (substring match) |
| `py -2.7 notes/ModForge/tools/mutate_merge.py` | break each load-bearing rule in turn; the suite must go red every time |
| `py -2.7 notes/ModForge/tools/dry_run_corpus.py` | install 110 real converted mods against a fake game tree |
| `py -2.7 notes/ModForge/tools/audit_sandbox_names.py` | every global the installer names, against the v1 sandbox vocabulary |

**Python 2.7 only, by design** — that is the interpreter the game runs the installer on, and
`PkgMgr` and `Paths.hashBytes` are Python 2 code. The suite refuses to run on 3.x rather than
report a green run from the wrong interpreter.

Constraints that come from the v1 mod sandbox, not from taste:

- **`Exception` is the only exception class you can name.** A v1 mod's `__builtins__` is a fixed
  dict; the other 48 are absent. `except (TypeError, ValueError):` sits dormant until the error
  path runs and then *replaces* the real error with a `NameError`. Catch `Exception` and
  discriminate inside the handler.
- `eval`, `globals`, `locals` and `compile` are absent too. `open` is mod-scoped.
- `.func_name`, not `.__name__`; `class Foo(Base, object):` for new-style inheritance.
- `audit_sandbox_names.py` checks all of this against the compiled bytecode — run it, do not eyeball it.

**The mutation harness is the standard for "tested".** A rule nothing can break is a rule nothing
pins: three real problems in this codebase surfaced only because a mutant survived, including a
test that had been passing for the wrong reason. If you add a rule, add the mutant that proves it.
