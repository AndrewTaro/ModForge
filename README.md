# ModForge

A mod installer for World of Warships. It patches the game's own UI files from small XML
**blueprints**, so several mods can edit the same vanilla file without overwriting each other.

Usually bundled inside other mods' packs, not installed on its own. It runs once at game start,
has no UI, and reverts every file to stock when removed.

## What it does, in order

1. **Discover** every blueprint under `res_mods/ForgeBlueprints/` and `res_mods/PnFMods/*/manifest.xml`.
2. **Check requirements** — installer version and mod dependencies; unmet ones skip that mod only.
3. **Order** by dependency, then `priority`, then filename.
4. **Fetch the pristine original** of each target file (from `res/`, or unpacked from the `.pkg`).
5. **Apply every mod's edits** and write the merged files.

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

## Writing a blueprint

Ship it as `res_mods/PnFMods/<YourMod>/manifest.xml`, or drop it in `res_mods/ForgeBlueprints/`.
Ship your own assets — ModForge assembles the vanilla files, not your payload.

```xml
<mod name="My Mod" version="1.0.0" priority="0">
  <requires installer=">=1.0.0"/>            <!-- or: <requires mod="Other" version=">=2.0"/> -->
  <target file="gui/uss_settings.xml">
    <insert into="mods">
      <xmlfile>../unbound/mods/MyMod.xml</xmlfile>
    </insert>
  </target>
</mod>
```

**Selectors** (over the target file): child steps `a/b/c`, `.` / `..`, `*`, `[@name='x']`,
`[text()='x']`, `[1]` / `[last()]`. No recursive `//`.

**Actions** inside a `<target>`:

| Action | Does |
|---|---|
| `<insert into="sel">…</insert>` | Add children into the parent (`before=`/`after=` for placement). Identical re-inserts are skipped. |
| `<remove select="sel"/>` | Delete matched nodes. |
| `<replace select="sel">…</replace>` | Swap matched nodes for the supplied elements. |
| `<rename select="sel" attribute="a" to="v"/>` | Set attribute `a`; with `from="old"`, replaces that substring. |
| `<copy select="sel" into="sel">…</copy>` | Clone nodes elsewhere; `<override attribute="a" value="v"/>` tweaks the clone. |

A `<guard ifExists="sel"/>` or `<guard ifNotExists="sel"/>` at the top of a `<target>` skips it
unless the condition holds. Reach for a guard only for real conditional logic (e.g. patch differently
depending on another mod). You don't need one to avoid installing twice: re-applying is idempotent —
identical inserts are skipped, and an unchanged run is a no-op — so the old "skip if my element
already exists" guard is unnecessary.

Worth knowing:

- **Edits stack on the pristine original, in order.** Each target starts from the vanilla file;
  mods apply one after another. A higher `priority` runs earlier, so a later mod's selectors can
  match — and edit — what an earlier one added. Use `<requires mod=…>` when you truly depend on
  another mod: it both enforces order and skips your mod if that mod is absent.
- **Failures are contained, not silent.** A selector that matches nothing (or any error) reverts
  just your mod's edits to that file and moves on — the rest still install. Unknown attributes and
  elements are warnings, not fatal. Watch `python.log` for `[ModForge]` lines.
- `file=` is relative to `res_mods/`. ModForge fetches the original even if the game only ships it
  packed, so you can target any vanilla UI file, not just already-unpacked ones.