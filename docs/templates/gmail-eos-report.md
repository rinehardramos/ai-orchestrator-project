# Gmail EOS Report Template

Derived from `EOS REPORT.md` in the Obsidian vault, retrieved via the
`obsidian-vault` MCP server.

Two versions below: a plain-text version that pastes cleanly into Gmail's
compose window, and an HTML version for Gmail's rich-text mode (lists
render as bullets automatically).

---

## Subject line

```
EOS Report — {{DATE}} — {{YOUR_NAME}}
```

## Plain-text body

```text
Hi {{RECIPIENT_NAME}},

Here is my EOS report for {{DATE}}.

1. What Did I Do Today?
- {{TODAY_ITEM_1}}
- {{TODAY_ITEM_2}}
- {{TODAY_ITEM_3}}

2. Goals for Tomorrow
- {{TOMORROW_ITEM_1}}
- {{TOMORROW_ITEM_2}}

3. Blockers / Impediments
- {{BLOCKER_OR_NONE}}

4. Saved a copy in the portal: {{YES_OR_NO}}

Thanks,
{{YOUR_NAME}}
```

## HTML body (for Gmail rich-text)

```html
<p>Hi {{RECIPIENT_NAME}},</p>

<p>Here is my EOS report for <strong>{{DATE}}</strong>.</p>

<p><strong>1. What Did I Do Today?</strong></p>
<ul>
  <li>{{TODAY_ITEM_1}}</li>
  <li>{{TODAY_ITEM_2}}</li>
  <li>{{TODAY_ITEM_3}}</li>
</ul>

<p><strong>2. Goals for Tomorrow</strong></p>
<ul>
  <li>{{TOMORROW_ITEM_1}}</li>
  <li>{{TOMORROW_ITEM_2}}</li>
</ul>

<p><strong>3. Blockers / Impediments</strong></p>
<ul>
  <li>{{BLOCKER_OR_NONE}}</li>
</ul>

<p><strong>4. Saved a copy in the portal:</strong> {{YES_OR_NO}}</p>

<p>Thanks,<br>{{YOUR_NAME}}</p>
```

---

## Pre-filled example (from the current EOS REPORT.md)

```text
Subject: EOS Report — 2026-04-08 — Rinehard Ramos

Hi <recipient>,

Here is my EOS report for 2026-04-08.

1. What Did I Do Today?
- New Udemy Technical Course — Certified Kubernetes Administrator (CKA) with Practice Tests — Ongoing
- AI Enabled Software Delivery Course — Week 2 — Done
- AI Enabled Software Delivery Group Project — Ongoing

2. Goals for Tomorrow
- New Udemy Technical Course — Certified Kubernetes Administrator (CKA) with Practice Tests — Ongoing
- AI Enabled Software Delivery Group Project — Ongoing

3. Blockers / Impediments
- None

4. Saved a copy in the portal: Yes

Thanks,
Rinehard
```

---

## How to install as a Gmail canned response

1. Gmail → Settings ⚙️ → See all settings → **Advanced** → enable
   **Templates** → Save.
2. Compose → paste the plain-text or HTML body above → fill in your
   name/date placeholders.
3. Three-dot menu (bottom right of compose) → **Templates → Save draft
   as template → Save as new template** → name it `EOS Report`.
4. Next time: Compose → three-dot → **Templates → EOS Report** →
   update the daily fields → Send.
