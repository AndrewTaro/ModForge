# ModForge

A mod installer for World of Warships. It patches the game's own UI files from small XML
**blueprints**, so several mods can edit the same vanilla file — or the same Unbound 1
definition — without overwriting each other, and builds their payloads out of the current
build's markup.

Usually bundled inside other mods' packs, not installed on its own. It runs once at game start,
has no UI, and reverts every file to stock when removed.

Writing a mod: start at [Writing a blueprint](#writing-a-blueprint).
Porting one from ModsInstaller 4.3.1: start at
[Porting a ModsInstaller 4.3.1 mod](#porting-a-modsinstaller-431-mod).
Either way, read [Silent failures the client will not report](#silent-failures-the-client-will-not-report)
before writing markup — most Unbound 1 mistakes have no symptom at all.

## Contents

- [What it does, in order](#what-it-does-in-order)
- [Features](#features)
- [Writing a blueprint](#writing-a-blueprint) — [schema reference](#schema-reference), [conditions on other mods](#conditions-on-other-mods), [selectors](#selectors), [actions](#actions)
- [An Unbound 1 mod, whole](#an-unbound-1-mod-whole)
- [Optional integration with another mod](#optional-integration-with-another-mod)
- [Reading the log](#reading-the-log)
- [What gets a mod refused](#what-gets-a-mod-refused)
- [Porting a ModsInstaller 4.3.1 mod](#porting-a-modsinstaller-431-mod)
- [Silent failures the client will not report](#silent-failures-the-client-will-not-report)

## What it does, in order

1. **Discover** every blueprint directly in `res_mods/ForgeBlueprints/` (subfolders are not
   searched) and every `res_mods/PnFMods/*/manifest.xml`.
2. **Check each mod** — installer version, its [`<requires mods=>`](#conditions-on-other-mods)
   condition, and that it does not write a file [Unbound owns](#the-primitives). A mod that fails a
   check is skipped alone.
3. **Order** by dependency, then `priority`, then filename.
4. **Merge each Unbound 1 definition** every blueprint names — one document per `<block>` or
   `<css>`, sliced from the current build and carrying every mod's edits to it, less the blocks
   whose own `<requires mods=>` does not hold and the edits an earlier mod
   [already made](#an-unbound-1-mod-whole) — then compile one shared `.swf`,
   [lint](#what-gets-a-mod-refused) what it merged, and register what passed.
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
<mod name="MyMod" version="1.0.0" priority="0">
  <requires installer=">=1.1.0"/>            <!-- and: <requires mods="Other>=2.0"/> -->
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
with an info line and nothing else — a typo is quiet, so read the log after a change. Two
exceptions make the whole blueprint invalid, with a message showing what to write instead:
`<ubBuild>`, `<ubCompile>` and `<ubRegister>`, verbs from before 1.0.0; and `mod=` or `version=`
on a `<requires>`, which ignored would install the mod with no requirement at all.

| Element | Attributes | Notes |
|---|---|---|
| `<mod>` | `name`\*, `version`\*, `priority` | one per file. `name` is an identifier — letters, digits and `_`, not starting with a digit, and not `and`, `or` or `not` in any letter case; anything else makes the blueprint invalid. It is what another blueprint's `mods=` names, case-sensitively, so keep it stable. `version` has to start with a number (`1.2`, not `v1.2`) or every constraint on it fails. Use `major.minor.patch`: more numbers still work but are logged. `priority` defaults to 0; higher applies **earlier** |
| `<requires installer=>` | `installer`\* | version constraint, e.g. `>=1.1.0`. An unmet constraint skips your mod. Directly under `<mod>` only; inside a block it makes the blueprint invalid |
| `<requires mods=>` | `mods`\* | a [condition on other mods](#conditions-on-other-mods). Under `<mod>` it skips your mod when it does not hold, and enforces order. Also a direct child of `<build file=>` (not with `root=`), `<ubBuildBlock>`, `<ubBuildStyle>` and `<ubMountInBattle>`, where it skips that block alone. One `<requires>` takes `installer=` or `mods=`, not both |
| `<ubBuildBlock>` | `name`\* | a `<block className=>` in `gui/unbound/markup.xml` |
| `<ubBuildStyle>` | `name`\* | a `<css name=>` in `gui/unbound/styles.xml` |
| `<ubMountInBattle>` | `unbound`\*, `rootElementId`\*, `name`, `hitTest`, `url`, `before` \| `after` | writes the `battle_elements.xml` entries |
| `<build>` | `file`\*, `root`, `restartOnChange` | edit a vanilla file; with `root=` generate a new one. `restartOnChange="true"`: see [Files the client reads before mods load](#files-the-client-reads-before-mods-load) |
| `<guard>` | `ifExists` \| `ifNotExists` | inside a `<build>` with no `root=`; position does not matter |

\* required. `A` \| `B` means one or the other; giving both makes the blueprint invalid.

Definition names are **opaque and verbatim**. `$Foo` and `Foo` are different presets; nothing
normalises the `$`, because the client does not either — it is convention, not grammar.

A definition verb may not carry a `<guard>`, and neither may a `root=` build. Both are refused
outright rather than treated as a condition that is always false: a guard reads the document it
edits, and those two start from a definition or from nothing.

### Conditions on other mods

`mods=` is an expression over other blueprints' `<mod name=>`:

```xml
<requires mods="ModA"/>
<requires mods="ModA>=1.2 and not ModB"/>
<requires mods="(ModA&lt;2.0 or ModB) and !ModC"/>
```

| | |
|---|---|
| a name | true when that mod is installed |
| `Name>=1.2` | installed, and its `<mod version=>` meets the constraint: `>=`, `<=`, `==`, `>`, `<` |
| `not X`, `!X` | the same thing |
| `X and Y`, `X or Y` | `and` binds tighter: `A or B and C` is `A or (B and C)` |
| `( … )` | grouping |

- **`<` is `&lt;`** in an XML attribute; written raw, the file is not XML and the whole blueprint
  is invalid.
- **Anything else is an error, and an error makes the blueprint invalid**: a lone `=`, `!=`, `&&`,
  `||`, a comma, `AND` in capitals, a version with anything but digits and dots.
- **`not ModA>=2.0` is also true when ModA is absent.** For "ModA is here and older than 2.0"
  write `ModA<2.0`.
- **Several `<requires mods=>` in one place all have to hold.**
- **It has to be a direct child.** Inside an `<insert>` or `<replace>` it is payload, and is
  written into the game file.

**Installed** means the mod passed its own checks in this run. A mod that is on disk but was
itself skipped is not installed, so `not X` holds for it.

**Under `<mod>`** an unmet condition skips your whole mod, and your mod is ordered after every mod
the condition names outside a `not`, whatever the priorities. With `A or B` that is after each of
the two that is present. Mods whose conditions name each other in a circle — `A` needs `B` and
`B` needs `A`, or each says `not` the other — are all skipped, and the log names them.

**Inside a block** it skips that block and the rest of your mod installs. It never changes the
order. To put one action under a condition, give it a block of its own: a mod may name the same
definition, or the same file, in several blocks. A `root=` build takes none: it is written before
any mod can be refused, so put the condition under `<mod>`, in a blueprint of its own.

```xml
<ubBuildBlock name="PortSwitcher">
  <setAttribute select=".//bind[@name='text']" attribute="value" to="'Hello'"/>
</ubBuildBlock>
<ubBuildBlock name="PortSwitcher">
  <requires mods="not OtherSwitcher"/>
  <insert into="."><bind name="alpha" value="0.8"/></insert>
</ubBuildBlock>
```

A mod [refused](#what-gets-a-mod-refused) after the checks, while the definitions are built,
splits the two scopes. Inside a definition verb, a `<ubMountInBattle>` or a `<build file=>` edit it
counts as absent: a block under `mods="X"` drops out and one under `mods="not X"` comes in. A mod
already skipped under `<mod>` for `not X` stays skipped.

**Carry `<requires installer=">=1.1.0"/>` in any blueprint that uses `mods=`.** ModForge 1.0.x
reads `mods=` and a `<requires>` inside a block as unknown, logs an info line, and installs
everything unconditionally.

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
<mod name="MyMod" version="1.0.0">
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

- **Same attribute of the same element, different values.** The higher `priority` wins; the loser
  is named in `python.log` and its *other* edits still land. Nothing is silently overwritten. Two
  mods writing the same value agree: no line, and not counted in `conflicts=`.
- **One mod removes what another edits.** That one selector is skipped, reported, and the rest of
  the mod still applies. The action is replayed to tell this apart from your own errors: a
  selector that matches nothing in vanilla either, or a node your own earlier action removed.
  Those fail your mod — not just that definition, but every definition it names, and its other
  edits in the same run.
- **Two mods make the same edits.** When everything a later mod does to a definition, applied
  alone to vanilla, gives what an earlier mod's edits give, the later mod is skipped for that
  definition, said in an info line, and still counts as installed. This is what lets two mods ship
  the same shared block. It compares the whole contribution, so a mod that does more is not a
  match and merges as usual. It also covers edits by position: two mods each removing `./x[1]`
  remove one node, not two.

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

### Optional integration with another mod

A bind that constructs a block by name is [refused (E2)](#what-gets-a-mod-refused) when nothing
defines that name — so a reference to another mod's block refuses *your* mod on every client
without that mod. Three ways to write it:

- **Put the bind in a block of its own, under a condition.** It is only merged, and only linted,
  when the other mod is installed:
  ```xml
  <ubBuildBlock name="Host">
    <requires mods="Port_Interface_MainCrew"/>
    <insert into=".">
      <bind name="instance" value="'ON_MainCrewIcon'; {}"/>
    </insert>
  </ubBuildBlock>
  ```
- **Let the other mod do it.** Its blueprint names your block and inserts the bind itself; yours
  never mentions it.
- **"Theirs if present, else vanilla's"** is two blocks, one under `mods="X"` and one under
  `mods="not X"`.

A name the lint cannot read as a literal — `flag ? 'ON_MainCrewIcon' : null` — is not checked at
all. It installs, and throws in the client when the other mod is missing.

This is not what a [`<guard>`](#actions) is for. A guard reads the document being edited;
`<requires mods=>` reads which mods are installed.

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

### Files the client reads before mods load

ModForge runs after the client has already read some files, among them `engine_config.xml` and
`camerasConsumer.xml`. An edit to one of those takes effect only on the next start. Mark its `<build>` with `restartOnChange="true"` and ModForge restarts the client itself:

```xml
<requires installer=">=1.2.0"/>
<build file="engine_config.xml" restartOnChange="true">
  ...
</build>
```

- It restarts only when the bytes of that file actually change: on install, on an update that
  changes the file, and when removing the blueprint restores the stock file. A run that leaves the
  file as it was does not restart.
- Before restarting it shows a Windows notification that the game is restarting. The text is
  translated through [LocalizationLoader](https://github.com/AndrewTaro/LocalizationLoader);
  without it, the notification shows its key, `IDS_MODFORGE_RESTARTING`.
- If something else rewrites the file before every start, ModForge restarts for that content once,
  then logs an error instead of restarting on every boot.

An older ModForge ignores the attribute with an info line, so carry the `<requires installer=>`.

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
| `<insert into="sel">…</insert>` | Add children into the parent. `before=`/`after=` place them, and that selector is evaluated **with the `into=` node as its root** — so a bare step like `bind[@name='x']` means a *child* of it, and `.//bind[…]` is needed for anything deeper. Without either, children are appended. A child identical to one already in that parent is skipped, whichever mod put it there. |
| `<remove select="sel"/>` | Delete matched nodes. |
| `<replace select="sel">…</replace>` | Swap matched nodes for the supplied elements. |
| `<setAttribute select="sel" attribute="a" to="v"/>` | Set attribute `a`, adding it if absent. With `from="old"` it replaces **every** occurrence of that substring instead, and does nothing at all where the substring is absent — silently, so check your result. `select=` may be omitted, which targets the node the action is scoped to. |
| `<copy select="sel" into="sel">…</copy>` | Clone nodes, from this file or from `from="…"`. Children are actions on the clone. A clone identical to a node another mod already put in the same parent is skipped; a mod's own repeated copies are kept. |

A `<guard ifExists="sel"/>` or `<guard ifNotExists="sel"/>` anywhere inside a `<build>` skips the
whole build unless the condition holds. Reach for a guard only for real conditional logic on the
file's content (e.g. patch differently depending on what an earlier mod left in it). Whether
another mod is *installed* is a [`<requires mods=>`](#conditions-on-other-mods) inside the build,
not a guard. You don't need one to avoid installing twice: re-applying is idempotent —
identical inserts are skipped, and an unchanged run is a no-op — so the old "skip if my element
already exists" guard is unnecessary.

A guard reads the document it edits, so two places refuse one outright rather than quietly
treating every condition as false: a `root=` build, which starts from an empty document, and
`<ubBuildBlock>` / `<ubBuildStyle>`, which are assembled from the vanilla definition when there
is one and from nothing when there is not.

Worth knowing:

- **Edits stack on the pristine original, in order.** Each file starts from the vanilla copy;
  mods apply one after another. A higher `priority` runs earlier, so a later mod's selectors can
  match — and edit — what an earlier one added. Use `<requires mods=…>` under `<mod>` when you
  truly depend on another mod: it both enforces order and skips your mod if that mod is absent.
- **Two mods setting the same attribute to different values: the higher `priority` wins, in every
  file.** The first write stands, the later one is refused, and the loser is named in
  `python.log`.
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
| `invalid manifest …: <mod name='X'>: a mod name is letters, digits and _ only, and does not start with a digit` | the name is not an identifier (or: `'and', 'or' and 'not' are reserved`) | rename it, and every `mods=` that names it — the blueprint was not read |
| `invalid manifest …: <requires mod=> and version= are gone; write <requires mods='Other>=2.0'/>` | the two attributes are refused | write what the message shows — the blueprint was not read. For a name that is not an identifier it shows `Name` and says to rename that mod |
| `invalid manifest …: <requires mods='…'> in <mod>: …` | the expression does not parse; the end says why, and `in …` names the block | fix it — the blueprint was not read |
| `'N' requires mods 'A>=2.0 and B and C', which does not hold (A 1.0 is installed; B is not installed; C is present but was itself skipped); skipping` | your `<mod>`-level condition is not met; the brackets give what was found for each name | install what is missing, or it is working as written |
| `'A': <requires mods='X'> does not hold; skipping its edits to <ubBuildBlock name='P'>` (or `… to gui/file.xml`) | a block's own condition is not met | expected; the rest of `A` installed. Printed on a run that rebuilds, not on a `nothing to do` one |
| `'B': its edits to <ubBuildBlock name='P'> are the ones 'A' already made; skipped` | both mods make the same edits to `P` | expected; `B` counts as installed |
| `'A', 'B' name each other in <requires mods=>, in a circle; skipping them` | each waits for the other, or each says `not` the other | drop one of the conditions |
| `B: <style> is already in <block>, from 'A'; skipped` | a `<copy>` would add a node `A` already added | expected |
| `'A' cannot set v on <bind> in …: 'B' set it first` | two mods want different values for the same attribute, in a definition or a file | raise your `priority`, or accept B's value |
| `… skipped -- a mod applied before it changed what that names` | a peer removed what your selector named | usually fine; your other edits landed |
| `'A' failed on <ubBuildBlock name='X'>: ActionError: … matched nothing` | your selector matches nothing in vanilla either | fix the selector — your mod was dropped from the run |
| the same, ending `(an earlier action of this mod changed what it names)` | one of your own earlier actions removed or changed the node | reorder or fix your own actions |
| `the first step of '…' matches N nodes in …` | a `<copy from=>` selector is ambiguous | add a predicate or `[1]` to the first step |
| `'A' references missing file: …` | a payload names an `<xmlfile>`/`<swffile>` that is not on disk | ship the file or fix the path — the mod was skipped |
| `X: version='24.3.1.2.50' has 5 numbers; use major.minor.patch, like 1.2.0` | the version has more than three numbers | nothing was refused, and it still compares; shorten it |
| `<ubMountInBattle hitTest='…'> is not true or false; using false` | a typo in `hitTest=` (or in `restartOnChange=`) | write `true` or `false` |
| `X changed; restarting the client so it takes effect` | a `restartOnChange` file was written | expected; the client comes back on its own |
| `X changed again to the content the client was already restarted for; not restarting again` | something else rewrites `X` before every start | find what writes it; ModForge will not loop |
| `<ubBuildBlock name='X'> would throw (C1 at …): …; not installing 'A'` | your edit adds markup the client throws on (or `would stall`: hangs at login) | fix what it names — mod `A` was not installed. See [below](#what-gets-a-mod-refused) |
| `<ubBuildBlock name='X'>: dead D1 at …: …` | your edit adds markup the client silently ignores | nothing was refused; fix it or delete it |
| `X does not compile; not installing 'A'` | an expression in the definition does not compile | the reason is logged above it; mod `A` was not installed |
| `'N' requires mod 'M', which failed; skipping` | `M` was refused at build time, and `N`'s condition does not hold without it | fix `M`; `N` comes back on its own |
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
was guard-blocked, already present, lost a conflict, or sat in a block whose `<requires mods=>` did not hold. A mod left out because one it requires
failed counts as `skipped`. `dropped` counts definitions that would have been registered but for a
mod that failed.

## What gets a mod refused

A mod is refused when an edit it makes to a definition would make the client **throw** or
**stall** — and only for faults whose effect was measured in the client or read from its code.
The whole mod goes, never one definition: its other definitions may name what that one added,
and would throw without it. Then, in turn:

- **A mod that requires it** is skipped, unless its condition still holds without it
  (`mods="It or Other"`).
- **A block conditioned on it** drops out, or under `not` comes in, and the definitions are merged
  again. See [Conditions on other mods](#conditions-on-other-mods).
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
| E2 | a name nothing defines, where the binding constructs it. For a name another mod defines, see [Optional integration with another mod](#optional-integration-with-another-mod) | `missing construction plan` |
| F1 | `flow`, `position`, `overflow`, `backgroundSize`, `textAlign`, `scrollbarAlign` outside their values | hangs at login |
| F6 | `background9Slice` / `userData` reading an identifier | hangs at login |
| F7 | an `aw`/`ah` size without its two breakpoints | hangs at login |

C10 checks against the classes of the build the player is running, read out of the client's own
`consumer_main_scene.swf` once per build. If that cannot be read, C10 is skipped, not guessed.

## Porting a ModsInstaller 4.3.1 mod

A v4 file is usually one of two shapes. One that edits some other vanilla file becomes a plain
`<build file=>`.

**Shape one: a `battle_elements.xml` insert.** It becomes a `<ubMountInBattle>`:

| v4 | blueprint |
|---|---|
| `<check name="X" version="Y"/>` | `<mod name="X" version="Y">`, with `X` made an identifier |
| `<element class="lesta.unbound2.UbElement" elementName="X">` | `<ubMountInBattle unbound="2" rootElementId="X">` |
| `<element class="lesta.libs.unbound.UnboundElement">` + a `<controller>` | `<ubMountInBattle unbound="1" …>` — it writes the controller too |
| `name="unbound2MyThing"` on the element | `name="unbound2MyThing"` — omitted, it defaults to `rootElementId` and silently renames the instance |
| `<properties hitTest="true"/>` | `hitTest="true"` |
| `url="x.swf"` on the element | `url="x.swf"` |
| `<position insert="after_node" … value_1="MainHud"/>` | `after="MainHud"` |
| `<do_if_not_exist …/>` | drop it |

- **Keep the `<position>`.** It is render order, and losing it is silent.
- **`<check name=>` rarely survives verbatim.** A mod name is letters, digits and `_`, so
  `Move Port Clock` becomes `Move_Port_Clock`. `<requires mods=>` resolves against the new
  spelling, case-sensitively, so every blueprint that names the mod has to use the same one.
- Several `<insert>`s become several `<ubMountInBattle>` in one `<mod>`.
- The verb cannot express an anchor on `name` instead of `elementName`, extra attributes or
  children, a `<guard>`, or an Unbound 1 element without its controller. Keep those as a
  `<build file="gui/battle_elements.xml">`.

**Shape two: a `uss_settings.xml` registration.** Drop the registration: ModForge registers what
it emits. What you port is the payload's content, as definitions.

1. Open the payload the v4 file registered, e.g. `res_mods/gui/unbound/mods/my_mod.xml`.
2. Every **top-level** `<block className="X">` becomes `<ubBuildBlock name="X">`, and every
   top-level `<css name="$Y">` becomes `<ubBuildStyle name="$Y">`. Nested ones come along with
   their parent.
3. **Diff each one against the current `markup.xml`.** A v4 payload is normally a copy of the
   vanilla definition with a few lines changed, so the diff is the mod:

   | the payload's definition is | write |
   |---|---|
   | vanilla's, with edits | `<ubBuildBlock name="TheVanillaName">` + just those edits |
   | vanilla's, under a different name | a verb with the new name + the [`/*` copy form](#pulling-in-another-definition), then the edits |
   | entirely the mod's own | a verb with that name + `<insert into=".">` of its children |

4. **Treat drift as deletion.** The payload froze vanilla at the build it was made on, so a
   difference may be the author's intent or markup the game has since removed. Check that the
   surrounding block still exists in current vanilla before carrying it forward. (Seen in the
   wild: a payload still carrying an `isEventShip` branch and an
   `IDS_STEQ_EQUIPMENT_NOT_AVAILABLE` window that appear nowhere in either of the last two builds.)
5. Delete the `.swf`. ModForge compiles one shared SWF for everything it emits.

A v4 file that assembled its payload instead of shipping one maps the same way:

| v4 | blueprint |
|---|---|
| `<copy_past>` of a vanilla block, plus edits | `<ubBuildBlock name="X">` plus those edits, one per copied block |
| `<rename attr_rename="className">` over a copy | the `/*` copy form, under the new name |
| a root-level op that searched the whole payload with `.//` | repeat it only in the definitions it matches — an action that matches nothing refuses the mod |

**Checking your work.** Boot the client and read `python.log`: see [Reading the log](#reading-the-log).

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
