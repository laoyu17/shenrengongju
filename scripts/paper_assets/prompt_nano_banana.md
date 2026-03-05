# Nano Banana Pro Prompt Pack (GA1)

## Scope
- Target: single Graphical Abstract image for RTOS-Sim paper package.
- Role: visual summary only, not quantitative evidence.
- Output ratio: 16:9 preferred, 4:3 backup.

## 1) Master Prompt (English)
Create a publication-grade graphical abstract for a real-time scheduling simulation research system.
Show an evidence chain from "config + simulation engine" to "event stream" to "audit checks + compliance profiles" to "reproducible reports".
Use a clean scientific visual language: layered blocks, directional flow, concise labels, subtle icons, and disciplined white space.
The composition must look like a systems conference paper figure, not a marketing poster.
Include tiny neutral labels for: SimEngine, EventBus, Scheduler, Resource Protocol (PIP/PCP), Audit, research_v1, engineering_v1, reproducibility.
Visual hierarchy: mechanism first, evidence second, governance third.
Palette: color-blind-safe tones (blue/orange/green/red accents) on a light background.
Typography: modern sans-serif, thin to medium weights, no decorative script.
Keep the figure crisp, technical, and calm, suitable for a paper first page.

## 2) Negative Prompt
- No cartoon style, no 3D mascot, no cyberpunk neon, no sci-fi glow.
- No overloaded textures, no random symbols, no handwritten fonts.
- No dense paragraph text, no unreadable tiny clutter.
- No dark black background, no purple-dominant style.
- No fake equations or nonsense code blocks.
- No exaggerated perspective distortion.

## 3) Layout Constraints
- Keep all elements inside safe margins (>= 5% border padding).
- Left-to-right information flow with 4 stages:
  1. Model/Config
  2. Runtime/Event Stream
  3. Audit/Checks/Profiles
  4. Reports/Figures/Reproducibility
- Use one main arrow path plus 1-2 secondary connectors only.
- Prefer one focal center node: Event Stream.

## 4) Typography Rules
- Use sans-serif only.
- Max 12 short labels in the whole image.
- Label length <= 3 words whenever possible.
- Ensure high contrast and no overlap.

## 5) Variant Prompts

### Variant A (Conservative)
Same as master prompt, but increase white space, reduce icons, and keep only 8 labels.

### Variant B (Detail-Enhanced)
Same as master prompt, but add subtle small callout boxes for "counterexample suite" and "95% CI".

## 6) Selection Checklist
- Readability at half-size thumbnail.
- Scientific tone aligned with systems/RT paper aesthetics.
- No conflict with quantitative figure style in main text.
- Color-blind-safe contrast.
- Labels are technically meaningful and correctly spelled.
