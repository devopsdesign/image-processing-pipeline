# CloudSight Intake — User Guide

A plain-language walkthrough for patients and health workers: where to go, what
to click, and how to read what comes back. If you're a developer, see the
[README](../README.md) for the technical internals.

> **This is a screening aid, not a diagnosis.** It flags photos that look like
> they may need a doctor's attention so a real person can review them — it
> does not itself diagnose anything. Always follow up with your health worker
> or doctor for anything urgent, regardless of what the app shows.

## What this does

You log in, upload a photo, and within a few seconds it's automatically routed:

- **Sent to a doctor for review** — if the photo appears to show a person/body
  part.
- **Rejected as not a valid subject** — if it doesn't look like a relevant
  photo (an object, an animal, a screenshot, etc.).
- **Sent for manual review** — if the result is unclear either way; a local
  health worker looks at it directly.

## Where to go

**<https://image-processing-pipeline-devops.streamlit.app/>**

Nothing to install — it's a page in your browser, on desktop or mobile. You
need an account first (see [Quick Start](#quick-start) below) — there's no
public sign-up, accounts are created for you.

## Quick Start

**1. Log in.** Your health worker or admin gives you a link and your login
email. On first login you'll be asked to set a permanent password:

```
┌───────────────────────────────────────────────────┐
│ 🩺  CloudSight Triage                               │
│  Sign in to continue                                │
├───────────────────────────────────────────────────┤
│  Email     [___________________]                    │
│  Password  [___________________]                    │
│              [ Log in ]  ← click here                │
└───────────────────────────────────────────────────┘
```

**2. Choose a photo and submit it.**

```
┌───────────────────────────────────────────────────┐
│  Submit a photo for screening                        │
│  Choose a JPG or PNG photo                           │
│  [ Browse files ]   ← click here                     │
│                                                       │
│  [ your photo preview appears here ]                 │
│              [ Submit for screening ]                │
└───────────────────────────────────────────────────┘
```

Only `.jpg`, `.jpeg`, and `.png` files are accepted.

**3. Wait a few seconds, then read the result.**

```
┌───────────────────────────────────────────────────┐
│  Analyzing… (3/20)                                   │
├───────────────────────────────────────────────────┤
│  ✅ Submitted to your doctor for review.             │
│     This is a screening aid, not a diagnosis.        │
│                                                       │
│  ▾ Details                                            │
│    Labels: 5   Text items: 1   Faces: 1               │
│    Summary: 5 labels, 1 text item, 1 faces            │
└───────────────────────────────────────────────────┘
```

Typically **2–10 seconds**. You'll see one of three messages (see
[Understanding your results](#understanding-your-results)), and — for anything
sent to the doctor — an email goes out automatically too.

## Photo Guidelines

Good technique moves a result from "unclear, sent for manual review" to a
confident, correctly-routed one:

- **Good lighting.** Soft, even light beats harsh shadows or backlighting.
  Don't shoot with a bright window or lamp behind the subject.
- **Focus.** Hold the phone steady; tap the screen on the area of concern
  before taking the photo so it's sharp, not blurry.
- **Framing.** Fill most of the frame with the area of concern, with a little
  surrounding context — not an extreme close-up, not a distant shot.
- **One subject per photo.** Don't include other people, pets, or objects in
  frame.
- **A few angles help.** If more than one angle is relevant, upload each as a
  separate photo — every file gets its own result.

### Handling rejections

- **"We couldn't recognize a valid subject in this photo"** — the system
  didn't detect a person/body part at all (e.g. it was actually a photo of an
  object, screen, or document). This is not an error — retake a photo that
  clearly shows the area of concern.
- **"Sent for manual review"** — not a rejection. A health worker will look at
  it directly, usually within a few hours. You don't need to do anything.

## Understanding your results

| Field | What it means |
|---|---|
| **Result message** | `Submitted to your doctor` (medical), `couldn't recognize a valid subject` (rejected), or `sent for manual review` (unclear) — see [What this does](#what-this-does). |
| **Labels** | What the system detected, most confident first. Higher % = more confident. |
| **Text items** | Any readable text found in the photo. |
| **Faces** | How many human faces were detected — just a count. |
| **Summary** | A one-line recap of the above. |

## Getting notified by email

Only photos routed to a doctor trigger an email — rejections and manual-review
items are in-app only, by design. When one does go out, you may get **two**:

1. **A plain-text email** — always sent, guaranteed to arrive.
2. **A nicer HTML email** — sent as a bonus, with the photo embedded inline.
   This one can occasionally be filtered to Spam by strict mail providers —
   check there if you don't see it.

## Role Instructions

**Patients**: log in, submit your own photos, and see your own results under
**My results**. You can't see anyone else's information.

**Power Users (local triage staff)**: in addition to submitting on a patient's
behalf (enter their email as the "Patient identifier"), you have a **Review
queue** — every photo the system couldn't confidently route lands there for
you to look at and either **Mark resolved** or **Escalate to doctor**
yourself. You can also see any patient's history.

**Owners (system admins)**: everything above, plus **Manage users** — create
new accounts (choosing their role), delete accounts, and see who's registered.
Use this power sparingly; changes here affect real accounts.

Everyone can change their own password any time from the sidebar.

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| Can't log in / forced to set a new password | Normal on first login for a new account | Set any password meeting the requirements (8+ characters, upper + lower + a number) and you're in |
| Stuck on "Analyzing…" | Rare backend hiccup, or a very unusual file | Wait up to 90s; if it times out, just try submitting again |
| "Couldn't recognize a valid subject" | See [Handling rejections](#handling-rejections) | Retake the photo — closer, better lit, one subject, clearly showing the area of concern |
| Submitted twice, no new result | You (or someone) already uploaded this exact file | Not an error — re-save or lightly edit the photo if you want a fresh run |
| No email after a doctor-routed result | Check Spam/Junk first | If it's truly missing every time, tell your admin — something's actually wrong |
| Connectivity issues mid-upload | Weak signal/Wi-Fi | Move somewhere with better connectivity and submit again; nothing is double-charged or double-processed |
| The page shows an AWS error message | The backend isn't deployed or is misconfigured | This is a "tell your admin" situation, not something to fix from the browser |

## Privacy

Only logged-in accounts can use this app — there's no public access. Everyone
who can use it can see their own data only (Patients) or more (Power
Users/Owners), per the roles above. Don't share your login.
