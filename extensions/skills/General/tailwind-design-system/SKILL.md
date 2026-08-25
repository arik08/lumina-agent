---
name: tailwind-design-system
description: Use this skill when building design systems with Tailwind CSS v4, configuring CSS-first themes, creating variant-based components, or migrating from Tailwind v3 to v4.
license: Complete terms in LICENSE.txt
---

# Tailwind Design System (v4)

## When to Use

Apply this skill when the agent needs to:

- Configure Tailwind CSS v4 with the new CSS-first `@theme` syntax
- Build component libraries with CVA on top of Tailwind v4
- Implement dark mode with `@custom-variant`
- Use OKLCH colors for perceptually uniform palettes
- Create responsive grid systems with Tailwind utilities
- Migrate an existing project from Tailwind v3 to v4

## Key Concepts

### CSS-First Configuration

Tailwind v4 replaces `tailwind.config.ts` with native CSS `@theme` blocks. Configuration lives in your CSS file, not JavaScript.

```css
@import "tailwindcss";

@theme {
  --color-brand-50: oklch(0.97 0.01 250);
  --color-brand-100: oklch(0.93 0.02 250);
  --color-brand-200: oklch(0.87 0.04 250);
  --color-brand-300: oklch(0.78 0.08 250);
  --color-brand-400: oklch(0.68 0.12 250);
  --color-brand-500: oklch(0.55 0.16 250);
  --color-brand-600: oklch(0.47 0.16 250);
  --color-brand-700: oklch(0.4 0.14 250);
  --color-brand-800: oklch(0.33 0.11 250);
  --color-brand-900: oklch(0.25 0.08 250);
  --color-brand-950: oklch(0.18 0.06 250);

  --color-surface: oklch(0.99 0 0);
  --color-surface-alt: oklch(0.96 0 0);
  --color-on-surface: oklch(0.15 0 0);
  --color-on-surface-muted: oklch(0.45 0 0);

  --color-danger: oklch(0.55 0.2 25);
  --color-success: oklch(0.6 0.18 145);
  --color-warning: oklch(0.75 0.15 80);

  --font-family-sans: "Inter Variable", ui-sans-serif, system-ui, sans-serif;
  --font-family-mono: "JetBrains Mono Variable", ui-monospace, monospace;

  --spacing-content: 1rem;
  --spacing-section: 3rem;

  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --radius-xl: 1rem;
  --radius-full: 9999px;

  --shadow-sm: 0 1px 2px oklch(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px oklch(0 0 0 / 0.07), 0 2px 4px oklch(0 0 0 / 0.05);
  --shadow-lg: 0 10px 15px oklch(0 0 0 / 0.1), 0 4px 6px oklch(0 0 0 / 0.05);

  --animate-fade-in: fade-in 0.3s ease-out;
  --animate-slide-up: slide-up 0.3s ease-out;
}

@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(0.5rem);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

### OKLCH Color Space

OKLCH provides perceptual uniformity — equal steps in lightness look equal to the human eye, unlike HSL.

```
oklch(L C H)
  L = Lightness (0–1): 0 is black, 1 is white
  C = Chroma (0–0.4): saturation intensity
  H = Hue (0–360): color wheel angle
```

Generate a palette by varying lightness while keeping chroma and hue constant:

```css
@theme {
  --color-accent-100: oklch(0.93 0.1 300);
  --color-accent-300: oklch(0.78 0.15 300);
  --color-accent-500: oklch(0.55 0.2 300);
  --color-accent-700: oklch(0.4 0.15 300);
  --color-accent-900: oklch(0.25 0.08 300);
}
```

### Dark Mode with @custom-variant

```css
@custom-variant dark (&:where(.dark, .dark *));
```

This enables `dark:` utilities without additional JavaScript configuration. Toggle the `.dark` class on `<html>` to switch themes.

## Patterns

### Complete Entry Point (app.css)

```css
@import "tailwindcss";

@custom-variant dark (&:where(.dark, .dark *));

@theme {
  --color-brand-500: oklch(0.55 0.16 250);
  --color-brand-600: oklch(0.47 0.16 250);
  --color-surface: oklch(0.99 0 0);
  --color-surface-alt: oklch(0.96 0 0);
  --color-on-surface: oklch(0.15 0 0);
  --color-on-surface-muted: oklch(0.45 0 0);
  --color-border: oklch(0.9 0 0);

  --color-dark-surface: oklch(0.15 0 0);
  --color-dark-surface-alt: oklch(0.2 0 0);
  --color-dark-on-surface: oklch(0.93 0 0);
  --color-dark-on-surface-muted: oklch(0.6 0 0);
  --color-dark-border: oklch(0.3 0 0);

  --font-family-sans: "Inter Variable", system-ui, sans-serif;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
}

@layer base {
  :root {
    --background: var(--color-surface);
    --foreground: var(--color-on-surface);
    --muted: var(--color-on-surface-muted);
    --border: var(--color-border);
  }

  .dark {
    --background: var(--color-dark-surface);
    --foreground: var(--color-dark-on-surface);
    --muted: var(--color-dark-on-surface-muted);
    --border: var(--color-dark-border);
  }

  body {
    background-color: var(--background);
    color: var(--foreground);
  }
}
```

### CVA Button Component

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:
          "bg-brand-500 text-white hover:bg-brand-600 active:bg-brand-700",
        secondary:
          "bg-surface-alt text-on-surface border border-border hover:bg-surface-alt/80",
        ghost: "text-on-surface hover:bg-surface-alt",
        danger: "bg-danger text-white hover:opacity-90",
        link: "text-brand-500 underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
```

### CVA Card Component

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const cardVariants = cva("rounded-lg border transition-shadow", {
  variants: {
    variant: {
      default: "bg-[var(--background)] border-[var(--border)]",
      elevated: "bg-[var(--background)] border-transparent shadow-md",
      outlined: "bg-transparent border-[var(--border)]",
    },
    padding: {
      none: "",
      sm: "p-4",
      md: "p-6",
      lg: "p-8",
    },
  },
  defaultVariants: {
    variant: "default",
    padding: "md",
  },
});

interface CardProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

export function Card({ className, variant, padding, ...props }: CardProps) {
  return (
    <div
      className={cn(cardVariants({ variant, padding }), className)}
      {...props}
    />
  );
}

export function CardHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1.5", className)} {...props} />;
}

export function CardTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-lg font-semibold leading-tight", className)}
      {...props}
    />
  );
}

export function CardContent({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("text-sm text-[var(--muted)]", className)} {...props} />
  );
}
```

### CVA Input and Label

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const inputVariants = cva(
  "w-full rounded-md border bg-transparent px-3 py-2 text-sm transition-colors placeholder:text-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      state: {
        default: "border-[var(--border)]",
        error: "border-danger text-danger",
        success: "border-success",
      },
    },
    defaultVariants: {
      state: "default",
    },
  },
);

interface InputProps
  extends
    React.InputHTMLAttributes<HTMLInputElement>,
    VariantProps<typeof inputVariants> {}

export function Input({ className, state, ...props }: InputProps) {
  return (
    <input className={cn(inputVariants({ state }), className)} {...props} />
  );
}

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("text-sm font-medium text-[var(--foreground)]", className)}
      {...props}
    />
  );
}
```

### Responsive Grid System

```tsx
import { cn } from "@/lib/utils";

interface ContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: "sm" | "md" | "lg" | "xl" | "full";
}

const containerSizes = {
  sm: "max-w-screen-sm",
  md: "max-w-screen-md",
  lg: "max-w-screen-lg",
  xl: "max-w-screen-xl",
  full: "max-w-full",
};

export function Container({
  size = "xl",
  className,
  ...props
}: ContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-4 sm:px-6 lg:px-8",
        containerSizes[size],
        className,
      )}
      {...props}
    />
  );
}

interface GridProps extends React.HTMLAttributes<HTMLDivElement> {
  cols?: 1 | 2 | 3 | 4 | 6 | 12;
  gap?: "sm" | "md" | "lg";
}

const gapSizes = { sm: "gap-4", md: "gap-6", lg: "gap-8" };

export function Grid({ cols = 3, gap = "md", className, ...props }: GridProps) {
  const colClasses: Record<number, string> = {
    1: "grid-cols-1",
    2: "grid-cols-1 sm:grid-cols-2",
    3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
    4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4",
    6: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-6",
    12: "grid-cols-4 sm:grid-cols-6 lg:grid-cols-12",
  };

  return (
    <div
      className={cn("grid", colClasses[cols], gapSizes[gap], className)}
      {...props}
    />
  );
}
```

### CSS Animations with @starting-style

Native CSS transitions for enter/exit animations (no JavaScript needed):

```css
.dialog-overlay {
  opacity: 1;
  transition:
    opacity 0.2s ease-out,
    display 0.2s ease-out allow-discrete;

  @starting-style {
    opacity: 0;
  }
}

.dialog-overlay[hidden] {
  opacity: 0;
  display: none;
}

.dialog-panel {
  opacity: 1;
  transform: scale(1);
  transition:
    opacity 0.2s ease-out,
    transform 0.2s ease-out,
    display 0.2s ease-out allow-discrete;

  @starting-style {
    opacity: 0;
    transform: scale(0.95);
  }
}
```

## v3 → v4 Migration Checklist

| Step | v3                                    | v4                                  |
| ---- | ------------------------------------- | ----------------------------------- |
| 1    | `@tailwind base/components/utilities` | `@import "tailwindcss"`             |
| 2    | `tailwind.config.ts` theme extend     | `@theme { }` in CSS                 |
| 3    | `darkMode: 'class'`                   | `@custom-variant dark (...)`        |
| 4    | `theme.colors.brand`                  | `--color-brand-*` in `@theme`       |
| 5    | `theme.fontFamily.sans`               | `--font-family-sans` in `@theme`    |
| 6    | `theme.borderRadius.lg`               | `--radius-lg` in `@theme`           |
| 7    | Plugin-based custom utilities         | `@utility` directive                |
| 8    | `ring-offset-2 ring-2`                | `outline-2 outline-offset-2`        |
| 9    | `bg-opacity-50`                       | `bg-brand-500/50` (modifier syntax) |
| 10   | PostCSS + autoprefixer                | Built-in; remove autoprefixer       |

### Migration Code Example

**Before (v3):**

```js
// tailwind.config.ts
export default {
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          500: "#3b82f6",
          600: "#2563eb",
        },
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
      },
    },
  },
};
```

**After (v4):**

```css
/* app.css */
@import "tailwindcss";

@custom-variant dark (&:where(.dark, .dark *));

@theme {
  --color-brand-500: oklch(0.55 0.16 250);
  --color-brand-600: oklch(0.47 0.16 250);
  --font-family-sans: "Inter Variable", system-ui, sans-serif;
}
```

## Common Pitfalls

1. **Still using `tailwind.config.ts`** — In v4, move all theme customization to `@theme` blocks in CSS. The JS config file is no longer needed for most projects.
2. **Using `@tailwind` directives** — Replace `@tailwind base; @tailwind components; @tailwind utilities;` with `@import "tailwindcss"`.
3. **HSL colors for palettes** — HSL has poor perceptual uniformity. Use OKLCH for palettes where equal lightness steps should look equal.
4. **Forgetting `@custom-variant` for dark mode** — The `darkMode` config key no longer exists in v4. Define dark mode with `@custom-variant dark (...)`.
5. **Raw color values in components** — Always reference theme tokens. Use `bg-brand-500` not `bg-[#3b82f6]`.
6. **Ignoring `@starting-style`** — v4 supports native CSS enter animations. Use them instead of JavaScript animation libraries for simple transitions.

## Do's and Don'ts

### Do

- Use `@import "tailwindcss"` as the single entry point
- Define all design tokens in `@theme` blocks
- Use OKLCH for color definitions
- Use `@custom-variant` for dark mode
- Use the `/` opacity modifier (`bg-brand-500/50`)
- Use `@starting-style` for enter animations
- Keep `@theme` blocks organized by category (colors, fonts, spacing)

### Don't

- Don't create a `tailwind.config.ts` unless you need a plugin that requires it
- Don't use `@tailwind base`, `@tailwind components`, or `@tailwind utilities`
- Don't use `bg-opacity-*` utilities (removed in v4)
- Don't use `ring-offset-*` (use `outline-offset-*` instead)
- Don't hardcode hex colors in utility classes
- Don't add autoprefixer to PostCSS (Tailwind v4 handles it)
