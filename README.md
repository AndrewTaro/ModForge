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
- [What gets a mod refused](#what-gets-a-mod-refused)
- [Converting a ModsInstaller 4.3.1 mod](#converting-a-modsinstaller-431-mod)
- [Silent failures the client will not report](#silent-failures-the-client-will-not-report)
- [Working on ModForge](#working-on-modforge)

## What it does, in order

1. **Discover** every blueprint directly in `res_mods/ForgeBlueprints/` (subfolders are not
   searched) and every `res_mods/PnFMods/*/manifest.xml`.
2. **Check each mod** — installer version, mod dependencies, and that it does not write a file
   [Unbound owns](#the-primitives). A mod that fails a check is skipped alone.
3. **Order** by dependency, then `priority`, then filename.
4. **Merge each Unbound 1 definition** every blueprint names — one document per `<block>` or
   `<css>`, sliced from the current build and carrying every mod's edits to it — then compile one
   shared `.swf`, [lint](#what-gets-a-mod-refused) what it merged, and register what passed.
5. **Check file references** — a mod whose payload names an `<xmlfile>` or `<swffile>` that is
   not on disk is skipped alone.
6. **Fetch the pristine original** of each target file (from `res/`, or unpacked from the `.pkg`).
7. **Apply every mod's edits** and write the merged files.

It skips the rest of the run when the blueprints are byte for byte the same, the game build is the
same, and the compiled output is the same. A file it wrote that something else changed is
repaired either way.

## Features

- **Non-destructive.** Edits stack on the untouched original, so mods share a file instead of
  overwriting each other. Removing a blueprint reverts its edits.
- **Atomic.** All files commit together or roll back — never a half-written state.
- **Isolated failure.** A mod whose edit throws, or whose markup would throw or hang the client,
  is left out whole; the rest still install. So are the mods that depend on it.
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
  copy, and the baseline is re-cut from each new game build — no re-diffing after a patch.
- **No build step.** ModForge decides the files, compiles the `.swf` the client needs, and writes
  the `uss_settings.xml` entries. Nothing to rebuild by hand when you edit an expression.
- **Checks what the client will not.** Every merged definition goes through an Unbound 1 linter
  built from the client's own code: a `bind` name that does not exist, a style value that hangs the
  load, a controller class that is not there. What would throw or hang refuses the mod; what is
  merely dead is a line in `python.log`.

## Writing a blueprint

Ship it as `res_mods/PnFMods/<YourMod>/manifest.xml`, or drop it directly in
`res_mods/ForgeBlueprints/` — not in a subfolder, which is never searched. Ship your own art and
sound; the XML ModForge can build for you.

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

A `<build>` names one game file and lists the edits to make to it.

Paths (`file=`, and `from=` on `<copy>`) name a game file the way the game does:
`gui/battle_elements.xml`. The original is read from `res/` or the `.pkg`, and the result is
written under `res_mods/`. `\` is read as `/`, and `./` and doubled slashes are dropped. An
absolute path or one containing `..` makes the blueprint invalid.

### Schema reference

Every element a blueprint may contain at the top level; the five actions that go *inside* them
are in [Actions](#actions). An unknown **element** and an unknown **attribute** are both ignored
with an info line and nothing else — a typo is quiet, so read the log after a change. The
exception is `<ubBuild>`, `<ubCompile>` and `<ubRegister>`, verbs from before 1.0.0: any of them
makes the whole blueprint invalid, with a message naming the verb to use.

| Element | Attributes | Notes |
|---|---|---|
| `<mod>` | `name`\*, `version`\*, `priority` | one per file. `priority` defaults to 0; higher applies **earlier** |
| `<requires installer=>` | `installer`\* | version constraint, e.g. `>=1.0.0`. **This installer is 1.0.0.** An unmet constraint skips your mod |
| `<requires mod=>` | `mod`\*, `version` | matches another blueprint's `<mod name=>` — so `name` is an identity key, not a label: keep it stable across renames. Enforces order, and skips your mod if that one is absent. One `<requires>` takes `installer=` or `mod=`, not both |
| `<ubBuildBlock>` | `name`\* | a `<block className=>` in `gui/unbound/markup.xml` |
| `<ubBuildStyle>` | `name`\* | a `<css name=>` in `gui/unbound/styles.xml` |
| `<ubMountInBattle>` | `unbound`\*, `rootElementId`\*, `name`, `hitTest`, `url`, `before` \| `after` | writes the `battle_elements.xml` entries |
| `<build>` | `file`\*, `root` | edit a vanilla file; with `root=` generate a new one |
| `<guard>` | `ifExists` \| `ifNotExists` | inside a `<build>` with no `root=`; position does not matter |

\* required. `A` \| `B` means one or the other; giving both makes the blueprint invalid.

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
  the mod still applies. The action is replayed to tell this apart from your own errors: a
  selector that matches nothing in vanilla either, or a node your own earlier action removed.
  Those fail your mod — not just that definition, but every definition it names, and its other
  edits in the same run.

The baseline is sliced out of the build the player is running, every launch, so nothing in your
mod is a frozen copy of vanilla.

A name vanilla does not define is **created from empty** rather than refused — it has to be, since
a new definition of your own is the same thing from the outside. So the run counts the two
separately (`4 overridden, 1 created`), and that count is your only signal for a misspelt name or
one the game renamed in the last patch: both show up as `created` where you meant `overridden`,
and the definition then renders nothing at all.

If your markup will not compile, your mod is left out whole and the reason is in `python.log`,
for the same reason a [lint refusal](#what-gets-a-mod-refused) takes the whole mod.

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
- The **first step** of `select=` has to match exactly one node; a first step that matches
  none or several is refused rather than guessed at. The steps after it may match any number:
  `block[@className='X']/*` copies every child.
- In `markup.xml` and `styles.xml`, `block[@className='X']` is a child step of `<ui>`, so it
  names a **top-level** definition — one of the 1,744 blocks or 286 presets the build declares
  there. `.//block[@className='X']` also matches nested blocks, so it is refused for the 95
  top-level names build 13187581 also uses nested.
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
| controller | written — without it the element is created empty and its markup is never built | none |

There is no default and no guess. ModForge cannot tell the two apart from the id: an Unbound 1
root is a `<block>` in a definition that has not been merged yet when the macro expands.
`unbound="2"` naming an id no `.unbound` file defines is reported at install time. The reverse,
`unbound="1"` naming an Unbound 2 view, produces a well-formed entry that never renders, and
nothing reports it.

`name=` is the instance name the client uses internally and defaults to `rootElementId`. Vanilla
gives every entry a distinct instance name (`ubMarkersContainer`, `unboundShipStateBars`), so a
name of your own is worth setting.

`hitTest=` takes `true` or `false` and **defaults to `false`**. An element that hit-tests takes
every click over its area, including clicks the game itself needs, so turn it on only for
something the player interacts with. Any other value is read as `false` and logged.

`url=` is passed through. Vanilla's Unbound 1 entries carry none. 8 of its 18 Unbound 2 entries
do, to load art embedded in a `.swf`; set it only if your view uses such assets.

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
one of those use `<build file="gui/battle_elements.xml">` directly. An anchor that matches no
entry is an error: your mod's edits to `battle_elements.xml` are dropped and the log names the
anchor.

### The primitives

`<ubMountInBattle>` is written for you as a `<build>`, the one primitive a blueprint edits files
with:

| Element | Does |
|---|---|
| `<build file="…">` | Edit a vanilla file, starting from its pristine copy. |
| `<build file="…" root="ui">` | Generate a new file, starting from an empty `<ui>` document. |

`<build file=>` is for the vanilla files no definition-keyed verb covers — `gui/battle_layout.xml`
and the like. `<ubBuildBlock>` and `<ubBuildStyle>` are not built on it: they have a pipeline of
their own, and they write the `uss_settings.xml` registration that a `<build>` is refused.

**It will not write what Unbound owns.** `gui/uss_settings.xml`, `gui/unbound/markup.xml`,
`gui/unbound/styles.xml`, anything else vanilla lists in that file's `<default>` block, and
ModForge's own output directory `gui/unbound/mods/` are all refused, and the mod is skipped with a
message naming the verb to use instead. ModForge is the only writer of those, which is what lets
it guarantee that every registered entry names a file it just wrote. A registered-but-missing
entry hangs the client at boot, and the only trace is the client's own
`ERROR: [Scaleform] Error: … missing xml from url:…` line in `python.log`.

If you ship a prebuilt `.xml`/`.swf` pair today, declare its definitions with `<ubBuildBlock>` /
`<ubBuildStyle>` instead and drop the `.swf` — ModForge compiles one for everything it emits.

### Selectors

A subset of XPath 1.0, and **everything in it means exactly what XPath means** — checked
expression-by-expression against a real XPath engine. Anything outside the subset is refused with
an error, never quietly misread. One deliberate exception: `..` from a file's root element matches
nothing, where XPath would return the document node, because no action can edit that.

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

Seven things that bite if you assume otherwise:

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
one stands. The [conflict rule](#an-unbound-1-mod-whole) is between *different* mods, not within
one.

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
- **Two mods setting the same attribute: the higher `priority` wins, in every file.** The first
  write stands, the later one is refused, and the loser is named in `python.log`.
- **Failures are contained, not silent.** In a `<build file=>` edit, a selector that matches
  nothing (or any other error) reverts your mod's edits to that one file, and the rest still
  install. A failure in a `root=` build or a definition verb drops your mod from the whole run.
  Unknown attributes and elements are info lines, not fatal. Watch `python.log` for `[ModForge]`
  lines.
- **The summary line is worth reading** — see [Reading the log](#reading-the-log).
- `file=` is relative to `res_mods/`. ModForge fetches the original even if the game only ships it
  packed, so you can target any vanilla UI file, not just already-unpacked ones.

## Reading the log

Every line is prefixed `[ModForge]` in `python.log`. The ones worth reacting to:

| Line | Means | Do |
|---|---|---|
| `created <ubBuildBlock name='X'>` where you meant to override | the build has no `X` | check the spelling, or whether the patch renamed it |
| `'A' cannot set v on <bind> in …: 'B' set it first` | two mods want the same attribute, in a definition or a file | raise your `priority`, or accept B's value |
| `… skipped -- a mod applied before it changed what that names` | a peer removed what your selector named | usually fine; your other edits landed |
| `'A' failed on <ubBuildBlock name='X'>: ActionError: … matched nothing` | your selector matches nothing in vanilla either | fix the selector — your mod was dropped from the run |
| the same, ending `(an earlier action of this mod changed what it names)` | one of your own earlier actions removed or changed the node | reorder or fix your own actions |
| `the first step of '…' matches N nodes in …` | a `<copy from=>` selector is ambiguous | add a predicate or `[1]` to the first step |
| `'A' references missing file: …` | a payload names an `<xmlfile>`/`<swffile>` that is not on disk | ship the file or fix the path — the mod was skipped |
| `<ubMountInBattle hitTest='…'> is not true or false; using false` | a typo in `hitTest=` | write `true` or `false` |
| `<ubBuildBlock name='X'> would throw (C1 at …): …; not installing 'A'` | your edit adds markup the client throws on (or `would stall`: hangs at login) | fix what it names — mod `A` was not installed. See [below](#what-gets-a-mod-refused) |
| `<ubBuildBlock name='X'>: dead D1 at …: …` | your edit adds markup the client silently ignores | nothing was refused; fix it or delete it |
| `X does not compile; not installing 'A'` | an expression in the definition does not compile | the reason is logged above it; mod `A` was not installed |
| `'N' requires mod 'M', which failed; skipping` | `M` was refused at build time | fix `M`; `N` comes back on its own |
| `cannot check names against gui/unbound/…: …` | a vanilla source could not be read | the name checks were skipped for this run; everything else ran |
| `read N classes from gui/flash/consumer_main_scene.swf` | the first run on a new build read the client's classes for C10 | expected, once per build |
| `cannot inflate …` / `cannot read the classes of …` / `… yielded N classes and no UbController` | the client's class list could not be read | C10 is skipped for this run; nothing was refused for it |
| `the Unbound 1 lint failed (…); the definitions install unchecked` / `… could not be linted …` | the linter itself broke | nothing was refused; report it, with the log |
| `manifests unchanged but the definitions were re-linted; re-applying` | ModForge was updated | expected, once |
| `the definitions did not settle (…)` | an internal inconsistency; nothing was registered | report it, with the log |
| `<styleClass value='$X'> names no preset …` | silent in game | define `$X` with `<ubBuildStyle>`, or fix the name |
| `<block className='X'> is declared by a.xml, b.xml` | two emitted files declare one name | whichever loads last wins; nothing is logged in game |
| `'A' writes gui/uss_settings.xml, which Unbound owns` | the mod was skipped entirely | use the verb the message names |
| `'X' changed on disk since our last run (…)` | something else overwrote or deleted a file a `<build file=>` wrote | an overwritten copy is kept under `.installer_cache/drift_backups/`; a deleted one has nothing to keep. A changed compiled definition is rewritten without this line |
| `no manifest changes since last run; nothing to do` | the whole run was skipped | expected. Touching a blueprint does not force a run — the check reads content, not timestamps. Change the blueprint, or delete `.installer_cache/installed.xml` |

The run ends with two summary lines:

```
done in 0.21s: discovered=5 installed=4 updated=0 unchanged=0 noop=1 skipped=0 failed=0 removed=0 conflicts=1
definitions: 4 registered (1 created, 3 overridden), 0 dropped
```

On a run that completes, every discovered mod lands in exactly one of `installed`, `updated`,
`unchanged`, `noop`, `skipped` and `failed`. `noop` is a mod that ran without error and changed nothing: every edit
was guard-blocked, already present, or lost a conflict. A mod left out because one it requires
failed counts as `skipped`. `dropped` counts definitions that would have been registered but for a
mod that failed.

## What gets a mod refused

A mod is refused when an edit it makes to a definition would make the client **throw** or
**stall** — and only for faults whose effect was measured in the client or read from its code.
The whole mod goes, never one definition: its other definitions may name what that one added,
and would throw without it. Then, in turn:

- **A mod that requires it** is skipped.
- **A mod that names a definition only it created** — `child`, `instance`, `tooltip` and the like
  pointing at it — is refused too, since that name no longer exists.

**Only what your edit introduces counts.** Vanilla carries a few latent faults of its own; a mod
that overrides one of those blocks inherits them and is not held responsible. Copied into a
definition of your own name, they count as yours, since there is no vanilla definition of that
name to inherit from — on build 13187581 that is two blocks, `ShipRowSelectableElement` and
`BattlePassRewardBannerTooltipWrapper`, each naming a definition that does not exist. When several
mods edit one definition, the fault is traced to the mod whose edit added it, and the others keep
theirs.

The faults that refuse, by code as the log names them:

| Code | Refused | Why |
|---|---|---|
| C1 | `bind name=` that is neither a verb nor a writable property of the block | `#1056` / `#1074` when the block is built |
| C2 | `<param name=>` the block class has no writable property for | `#1056` at construction |
| C4 | a property `bind` with no value | `#1125` |
| C5 | a binding with fewer `;` parts than its verb reads | `#1125` |
| B4 | a `;` inside a string literal in a binding | the compiler and the runtime split it differently: `#1006` |
| C6 | a `child`-style index past its list of names | builds a block named `null` |
| C8 | a `style` binding naming no style property | `#1006` |
| C10 | `controller` naming a class the scene lacks, or one that is not a controller | `#1065` / `#1034` |
| C13 | a verb that needs an Unbound block, on a native block | `#1009` |
| E2 | a name nothing defines, where the binding constructs it | `missing construction plan` |
| F1 | `flow`, `position`, `overflow`, `backgroundSize`, `textAlign`, `scrollbarAlign` outside their values | hangs at login |
| F6 | `background9Slice` / `userData` reading an identifier | hangs at login |
| F7 | an `aw`/`ah` size without its two breakpoints | hangs at login |

C10 checks against the classes of the build the player is running, read out of the client's own
`consumer_main_scene.swf` once per build. If that cannot be read, C10 is skipped, not guessed.

## Converting a ModsInstaller 4.3.1 mod

`ConvertV4.py` translates a v4 instruction file. It runs outside the game on plain CPython 2.7 or
3.x, stdlib only. It lives in the author's private notes repo, not in this
repository (paths below are relative to that repo):

```bash
py -3 ModForge/payload_tools/ConvertV4.py <v4-file-or-dir> <output-dir>
```

v4 files come in two main shapes. Which one dominates depends on the mod set: across one
author's own 26, 22 were battle mounts; across a 110-mod third-party corpus, most were payload
registrations. Check before assuming. A few edit other vanilla files (4 of the 110 edit
`gui/battle_layout.xml`); those convert to a plain `<build file=>`.

**Shape one: a `battle_elements.xml` insert.** Converts to a `<ubMountInBattle>` when the
result installs byte for byte what the v4 insert did:

| v4 | blueprint |
|---|---|
| `<check name="X" version="Y"/>` | `<mod name="X" version="Y">` — the only place a v4 file carries its identity |
| `<element class="lesta.unbound2.UbElement" elementName="X">` | `<ubMountInBattle unbound="2" rootElementId="X">` |
| `<element class="lesta.libs.unbound.UnboundElement">` + a `<controller>` | `<ubMountInBattle unbound="1" …>` — it writes the controller too |
| `name="unbound2MyThing"` on the element | `name="unbound2MyThing"` — **carry it over.** Omitted, it defaults to `rootElementId`, silently changing the client-internal instance name |
| `<properties hitTest="true"/>` | `hitTest="true"` — always written, since the verb defaults to `false` |
| `url="x.swf"` on the element | `url="x.swf"` |
| `<position insert="after_node" … value_1="MainHud"/>` | `after="MainHud"` |
| `<do_if_not_exist …/>` | drop it — re-applying is idempotent |

Anything the verb cannot express keeps the insert as a `<build file="gui/battle_elements.xml">`:
an anchor on `name` rather than `elementName`, extra attributes or children, a real `<guard>`,
or an Unbound 1 element without its controller. Across the 110-mod corpus, 26 of the 47
`battle_elements.xml` mods convert to mounts.

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
registers only what it just wrote. The `tpyo`, `verticle` and null-scope rows
[refuse the mod](#what-gets-a-mod-refused) at install time, and the silent rows are reported
without refusing. Uncaught AS3 errors *do* reach `python.log` as `ERROR: [Scaleform] Error: …`, so
silence there is evidence.

## Working on ModForge

```
PnFMods/ModForge/*.py      36 modules; the installer itself
PnFMods/ModForge/Main.py   entry point, run once at game start
ForgeBlueprints/           where blueprints are dropped at runtime
```

The test suite, mutation harness, ConvertV4 and the linter's sources live in the author's
private notes repo, not here. The commands below are relative to it and find this repo on
their own.

| Command | Does |
|---|---|
| `py -2.7 ModForge/tools/run_tests.py` | the whole suite |
| `py -2.7 ModForge/tools/run_tests.py merge` | one module (substring match) |
| `py -2.7 ModForge/tools/mutate_merge.py` | break each load-bearing rule in turn; the suite must go red every time |
| `py -2.7 ModForge/tools/dry_run_corpus.py` | install 110 real converted mods against a fake game tree |
| `py -2.7 ModForge/tools/audit_sandbox_names.py` | every global the installer names, against the v1 sandbox vocabulary |
| `py -3 ModForge/tools/stage_uss.py --check` | the shipped compiler and linter modules match their commented sources |
| `py -2.7 ModForge/lint/test_ub1lint.py --staged` | the linter's fixtures, against the shipped copy |
| `py -2.7 ModForge/lint/mutate_lint.py` | the linter's mutation run |

**Python 2.7 only, by design** — that is the interpreter the game runs the installer on, and
`PkgMgr` and `Paths.hashBytes` are Python 2 code. The suite refuses to run on 3.x rather than
report a green run from the wrong interpreter.

Constraints that come from the v1 mod sandbox, not from taste:

- **`Exception` is the only exception class you can name.** A v1 mod's `__builtins__` is a fixed
  dict; the other 48 are absent. `except (TypeError, ValueError):` sits dormant until the error
  path runs and then *replaces* the real error with a `NameError`. Catch `Exception` and
  discriminate inside the handler.
- `eval`, `globals`, `locals` and `compile` are absent too.
- `open` is mod-scoped, and outside the mod's own directory it returns `None` rather than raising —
  the failure surfaces later as `'NoneType' object has no attribute …`. Every file the installer
  touches is outside it, so all I/O goes through `Paths.openRead` / `Paths.openWrite`.
- `.func_name`, not `.__name__`; `class Foo(Base, object):` for new-style inheritance.
- `audit_sandbox_names.py` checks all of this by reading the source AST — run it, do not eyeball
  it. A bytecode scan misses class bases, which Python 2 compiles as `LOAD_NAME` at module scope.

**The mutation harness is the standard for "tested".** A rule nothing can break is a rule nothing
pins: a surviving mutant once exposed a test that had been passing for the wrong reason. If you
add a rule, add the mutant that proves it.
