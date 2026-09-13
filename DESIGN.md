---
name: ConnectSphere
description: A calm operations atlas for planning and delivering events with clarity.
colors:
  mineral-teal: "oklch(43% 0.09 190)"
  mineral-teal-hover: "oklch(38% 0.085 190)"
  mineral-teal-active: "oklch(34% 0.078 190)"
  ink-navy: "oklch(27% 0.055 252)"
  muted-slate: "oklch(48% 0.035 248)"
  atlas-paper: "oklch(98% 0.008 210)"
  mist-surface: "oklch(96% 0.012 210)"
  raised-surface: "oklch(99% 0.006 210)"
  blueprint-line: "oklch(86% 0.02 220)"
  on-accent: "oklch(98% 0.008 190)"
  focus: "oklch(57% 0.16 235)"
  refusal-red: "oklch(42% 0.14 25)"
  refusal-surface: "oklch(95% 0.025 25)"
typography:
  display:
    fontFamily: '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
    fontSize: "clamp(2rem, 6vw, 3.75rem)"
    fontWeight: 700
    lineHeight: 1.02
    letterSpacing: "-0.05em"
  headline:
    fontFamily: '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
    fontSize: "clamp(2rem, 7vw, 2.75rem)"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-0.045em"
  body:
    fontFamily: '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 650
    lineHeight: 1.45
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  base: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "48px"
  3xl: "64px"
  4xl: "96px"
components:
  button-primary:
    backgroundColor: "{colors.mineral-teal}"
    textColor: "{colors.on-accent}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "12px 24px"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.mineral-teal-hover}"
    textColor: "{colors.on-accent}"
  button-primary-active:
    backgroundColor: "{colors.mineral-teal-active}"
    textColor: "{colors.on-accent}"
  input:
    backgroundColor: "{colors.atlas-paper}"
    textColor: "{colors.ink-navy}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "48px"
  form-error:
    backgroundColor: "{colors.refusal-surface}"
    textColor: "{colors.refusal-red}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
---

# Design System: ConnectSphere

## 1. Overview

**Creative North Star: "Operations Atlas"**

ConnectSphere feels like a well-made operational map: composed at first glance, precise under inspection, and useful while several people coordinate time-sensitive work. The governing scene is an event professional at a large monitor in a bright shared office, moving between schedules, approvals, venues, equipment, and responsibilities without losing context.

The interface is light, flat, and orderly at rest. Structure comes from a self-adjusting grid, semantic spacing, tonal surfaces, and fine dividers. The responsive shell changes composition at 48rem: a split operational canvas on larger screens becomes a single reading sequence on narrow screens. Motion uses a 160ms ease-out transition for state feedback only.

Stripe Dashboard informs trustworthy hierarchy, Skedda informs scheduling clarity, and Linear informs workflow speed. Cvent informs domain breadth, not interface density. Festival advertising, dark developer consoles, and sprawling configuration tools are explicit anti-references.

**Key Characteristics:**

- Light, calm, and operational
- Restrained mineral-teal emphasis
- Ink-like typography and precise alignment
- Clear roles, statuses, ownership, and next actions
- Dense when useful, spacious when comprehension needs it
- Familiar controls with complete accessible states

## 2. Colors

The palette uses cool teal-tinted neutrals, one mineral accent, and a tightly controlled error pair. OKLCH values in the frontmatter and CSS are canonical.

### Primary

- **Mineral Teal** (`mineral-teal`): Primary actions, current navigation, route lines, and selected controls. Hover and active variants darken perceptually without shifting hue.

### Secondary

- **Ink Navy** (`ink-navy`): Strong text, structural icons, and high-trust anchors.
- **Focus Blue** (`focus`): The three-pixel external focus outline. It is deliberately distinct from both the surface and Mineral Teal.

### Tertiary

- **Refusal Red** (`refusal-red`): Invalid, denied, and destructive outcomes.
- **Refusal Surface** (`refusal-surface`): A quiet error background that preserves readable dark-red text.

### Neutral

- **Atlas Paper** (`atlas-paper`): The primary canvas and input background.
- **Mist Surface** (`mist-surface`): Context panels and secondary regions.
- **Raised Surface** (`raised-surface`): The sign-in work area and other foreground task surfaces.
- **Blueprint Line** (`blueprint-line`): Borders, dividers, and code-native map geometry.
- **Muted Slate** (`muted-slate`): Supporting copy and inactive information.

### Named Rules

**The Ten Percent Rule.** Mineral Teal occupies no more than ten percent of an operational screen. Its rarity preserves meaning.

**The Status Needs Two Signals Rule.** Status is always communicated by text or icon as well as colour.

**The Tinted Canvas Rule.** Pure black and pure white are prohibited. Every neutral belongs to the Atlas family.

## 3. Typography

**Display Font:** Segoe UI Variable (with Segoe UI and system sans fallbacks)

**Body Font:** Segoe UI Variable (with Segoe UI and system sans fallbacks)

**Character:** One humanist family keeps forms, schedules, tables, and role-heavy workflows coherent. Tight display spacing creates map-title authority; body copy remains conventional and readable.

### Hierarchy

- **Display** (700, responsive 2rem to 3.75rem, 1.02): Entry-surface statements only.
- **Headline** (700, responsive 2rem to 2.75rem, 1.08): Page purpose and current workspace context.
- **Title** (700, 1.125rem): Product identity and important component titles.
- **Body** (400, 1rem, 1.6): Instructions and prose, limited to 65 to 75 characters per line.
- **Label** (650, 0.875rem, sentence case): Form labels, metadata, buttons, and status messages.
- **Eyebrow** (700, 0.75rem, 0.14em tracking, uppercase): Rare operational context above a major title.

### Named Rules

**The One Working Voice Rule.** One sans family carries the product. Display faces, decorative italics, and monospace styling are prohibited in ordinary interface copy.

**The Hierarchy Before Colour Rule.** Size, weight, and spacing establish reading order before accent colour is introduced.

## 4. Elevation

ConnectSphere uses no resting shadows. Tonal layers and one-pixel full borders establish structure. Shadows are reserved for future transient surfaces that genuinely move above the page, such as menus and popovers.

### Named Rules

**The Atlas Lies Flat Rule.** Permanent page regions do not float. If every surface casts a shadow, the hierarchy has failed.

**The State Motion Rule.** State transitions use the 160ms ease-out token. Reduced-motion preferences collapse them to effectively immediate feedback.

## 5. Components

Components are refined and restrained. Their shapes are gently squared, their labels are persistent, and their interaction states are unmistakable.

### Buttons

- **Shape:** Gently squared (8px) with a 48px minimum height.
- **Primary:** Mineral Teal with Atlas-tinted near-white text and 12px by 24px padding.
- **Hover / Focus:** Perceptually darker teal on hover, a one-pixel downward response when active, and a three-pixel Focus Blue outline offset by three pixels.
- **Disabled / Loading:** The control remains in place, reduces opacity, blocks repeat actions, and changes its label to the action in progress.

### Cards / Containers

- **Corner Style:** Containers are square by default; bounded messages and controls may use the 8px radius.
- **Background:** Atlas Paper, Mist Surface, or Raised Surface according to hierarchy.
- **Shadow Strategy:** No resting shadow.
- **Border:** One-pixel Blueprint Line around a real grouping boundary, never a coloured side stripe.
- **Internal Padding:** Select from the documented 4px spacing scale according to content density.

### Inputs / Fields

- **Style:** Persistent label, Atlas Paper background, one-pixel Blueprint Line border, 8px radius, and a 48px minimum height.
- **Focus:** Three-pixel Focus Blue external outline plus a Mineral Teal border.
- **Error / Disabled:** Authentication errors remain form-level because they must not identify which credential failed. Error text uses Refusal Red on Refusal Surface and includes an icon.

### Navigation

- **Style:** Product identity remains compact. Active destinations use Mineral Teal only when navigation exists; text and landmark semantics carry meaning at every width.
- **Mobile treatment:** The content order becomes linear. The approved Operations Atlas background crops toward its text-safe region so decorative geometry never obscures copy.

## 6. Do's and Don'ts

### Do:

- **Do** make the active role, owner, state, and next action visible wherever they affect a decision.
- **Do** use the documented 4px spacing scale and the 8px standard control radius.
- **Do** maintain WCAG 2.2 Level AA contrast and the three-pixel visible keyboard focus treatment.
- **Do** use status text or icons alongside semantic colour.
- **Do** let spacing, tonal surfaces, and fine full dividers organise dense information.
- **Do** use the approved Operations Atlas background only as decorative imagery; keep all interface copy and meaningful controls as semantic HTML.

### Don't:

- **Don't** use a colourful festival or ticket-sales aesthetic for internal operations.
- **Don't** imitate Jira's configuration overload, visual clutter, or deeply nested settings.
- **Don't** inherit the dense legacy-enterprise character associated with large event-management suites.
- **Don't** use generic purple SaaS gradients, glassmorphism, neon decoration, confetti, or stock event photography as product identity.
- **Don't** make the entire application resemble a dark developer tool or depend on keyboard-first interaction.
- **Don't** add decorative dashboards, cards, charts, or motion that do not help a user complete a task.
- **Don't** use coloured side-stripe borders, gradient text, nested cards, or modals as a first response to layout problems.
