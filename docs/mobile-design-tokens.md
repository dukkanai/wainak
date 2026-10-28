# Flutter visual foundation — proposed identity, implemented development tokens

The starting identity retains the existing prototype's calm ivory/plum direction. It is **not a final brand approval or evidence of user preference**. It avoids swipe-based appearance ratings, generic pink dating imagery and unverified trust badges.

| Role | Light | Dark |
|---|---|---|
| Canvas | `#FFF9F5` | `#211A20` |
| Surface | `#FFFFFF` | `#2D242B` |
| Body | `#2B2528` | `#F4EAF0` |
| Secondary text | `#6B5F65` | `#CABAC4` |
| Primary action | `#6F304A` | `#E4A6BE` |
| On primary | `#FFFFFF` | `#2F1421` |
| Interactive outline | `#8C747F` | `#B29BA9` |
| Error text | `#9E313D` | `#FFB2BF` |

Static sRGB pair calculations: body/ivory 14.39:1, secondary/ivory 5.83:1, white/plum 9.56:1, interactive outline/white 4.27:1. These do not certify every rendered state or alpha-composited color. Decorative `#E3D6D8` from the old prototype is 1.41:1 on white and is not used as the sole necessary boundary of fields.

Typography: bundled Noto Sans Arabic; body 18, helper 16, heading 24–28 logical pixels. Weights 400/600, generous Arabic line height, no fixed-height text cards, no text-scaling suppression. Preserve the OFL and copyright file. The web prototype's `.tiny`/`.badge` rem sizes are deliberately not copied.

Spacing: 4/8/12/16/20/24/32; screen inset 20; field/button radius 12; card radius 20. Minimum touch target 48×48. Use Material line icons with explicit labels for standalone actions; selected choices have text, radio symbol and a thicker border, plus semantics. No status relies only on color.

Screens and priority components: eligibility with separately readable declarations; profile with explicit synthetic identity; a non-scientific self-reflection card; a candidate without hidden identity leakage; request/decision/activation as separate states; structured question selection and send; offline status and retry; separate report/block; account deletion distinct from subscription cancellation.

Consent copy must distinguish relationship acceptance, exclusivity, photo, name, phone and purchase. None implies another. No visual reward or pressure for consent. Safety does not require a subscription. D25 is optional evidence only after preview and explicit consent; not silently attached.

The design requires a textual description of each screen's hierarchy, controls and state for the owner. Screenshots and color labels alone are not an accessible review deliverable.

## Acceptance and open checks

- Normal text ≥4.5:1; necessary non-text UI indicators ≥3:1; full light/dark/error/focus-state audit remains necessary.
- Smallest supported display plus largest native font setting; no clipping, scale clamping or essential horizontal scroll. A widget 200% test is supporting evidence, not native Dynamic Type proof.
- Arabic VoiceOver and TalkBack journeys on actual platforms; NVDA for web review separately. Test heading announcements, selection states, dialog entry/exit focus, cancellation and no hidden content from another relationship.
- Focus must remain visible above keyboards and fixed content. No drag-only action. Framework route transitions must honor reduced motion; this slice adds no custom animation.
- Store and security acceptance are separate; no production readiness claim follows from widget tests or web compilation.

Official references checked 2026-10-24: [Flutter accessibility](https://docs.flutter.dev/ui/accessibility), [design and scaling](https://docs.flutter.dev/ui/accessibility/ui-design-and-styling), [screen readers](https://docs.flutter.dev/ui/accessibility/assistive-technologies), [W3C contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
