# CloudSight Intake — User Guide

A plain-language walkthrough of the app: where to go, what to click, and how to
read what comes back. If you're photographing animals specifically, see the
[Wildlife Identification Guide](wildlife-identification.md) for photo tips. If
you're a developer, see the [README](../README.md) for the technical internals.

## What this does

You upload a photo. Within a few seconds it comes back with a **description of
what's in it** — labels like "Dog," "Laptop," "Person," each with a confidence
score — plus any readable text in the photo, and how many faces it found. You
get the result on-screen immediately, and by email as well.

## Where to go

**<https://image-processing-pipeline-devops.streamlit.app/>**

Nothing to install — it's a page in your browser, on desktop or mobile.

## Step by step

**1. Open the link and choose a photo.**

```
┌───────────────────────────────────────────────────┐
│ 🛰️  CloudSight Intake                              │
│  Upload an image → S3 event → Lambda + Rekognition │
│  → DynamoDB + S3 results                            │
├───────────────────────────────────────────────────┤
│  Choose a JPG or PNG image                          │
│  [ Browse files ]   ← click here                    │
└───────────────────────────────────────────────────┘
```

Only `.jpg`, `.jpeg`, and `.png` files are accepted.

**2. Preview it, then click Process image.**

```
┌───────────────────────────────────────────────────┐
│  [ your photo appears here ]                        │
│  image_id (ETag): 7f3a9c1e2b4d6f80...               │
│                                                       │
│              [ Process image ]  ← click here         │
└───────────────────────────────────────────────────┘
```

The long string under your photo (`image_id`) is just an internal fingerprint
of the file — it's how the app finds your result again a moment later. You
don't need to do anything with it.

**3. Wait a few seconds.**

```
┌───────────────────────────────────────────────────┐
│  ⏳ Waiting for the pipeline…                        │
│     polling… 3s                                      │
│     polling… 6s                                      │
└───────────────────────────────────────────────────┘
```

Typically **2–10 seconds**. If it's still going after a minute or two, see
[Troubleshooting](#troubleshooting) below — the page will eventually say so
itself and won't leave you guessing forever (it gives up after 90 seconds).

**4. Read your result.**

```
┌───────────────────────────────────────────────────┐
│  ✅ Done in 4.2s                                     │
│  ✅ Image processed — status "processed"             │
│                                                       │
│  Processing time   Labels   Text items   Faces       │
│       4.2 s           5         1          0         │
│                                                       │
│  Analysis mode: rekognition · Rekognition calls: 3    │
│  Summary: 5 labels, 1 text item                       │
│                                                       │
│  ▾ Summary JSON                                       │
│    { "labels": [ {"name": "Dog", "confidence": 98.7}… │
└───────────────────────────────────────────────────┘
```

## Understanding your results

| Field | What it means |
|---|---|
| **Status** | `processed` = it finished. `skipped` = didn't run (wrong file type, or you already uploaded this exact file before). |
| **Processing time** | Seconds from your click to the result appearing — end to end, not just the AI part. |
| **Labels** | What's in the photo, most confident first — e.g. "Dog 98.7%, Animal 97.1%, Grass 82.3%." Higher % = more confident. |
| **Text items** | Any readable text found in the photo (signs, tags, labels on objects). |
| **Faces** | How many human faces were detected — just a count, not who they are. |
| **Summary JSON** | The full, exact data behind the result — every label, every confidence score, every piece of text. Click to expand it. |

A result with only 1–2 generic labels and low confidence (under ~90%) usually
means the photo was unclear, too far away, or busy with multiple subjects —
not a bug. Try a clearer, closer, better-lit shot of one subject and re-upload.

## Getting notified by email

Every processed image also sends an email, so you don't have to keep the
browser tab open. You may get **two**:

1. **A plain-text email** — always sent, guaranteed to arrive. Contains the
   status, summary, and labels as plain text plus a link to view the photo
   (the link expires after about an hour).
2. **A nicer HTML email** — sent as a bonus, with your **photo embedded right
   in the message** plus a labels table. This one can occasionally be filtered
   to Spam by strict mail providers (this happens with some ProtonMail
   addresses, for technical reasons unrelated to the content) — check there if
   you don't see it in your inbox.

Either way, you'll always get at least the first one.

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| Stuck on "Waiting for the pipeline…" | Rare backend hiccup, or a very unusual file | Wait up to 90s; if it times out, just try uploading again |
| `status: skipped`, reason `unsupported_type` | The file isn't a `.jpg`/`.jpeg`/`.png` | Convert or re-export the photo and try again |
| `status: skipped`, reason `duplicate` | You (or someone) already uploaded this exact file | Not an error — see the earlier result, or make a trivial change to the file (e.g. re-save it) if you want a fresh run |
| Only 1–2 vague labels, low confidence | Photo is unclear/busy/far away | See [Understanding your results](#understanding-your-results) above, or the [photo tips](wildlife-identification.md#2-field-guide--taking-photos-that-identify-well) |
| No email at all | Check Spam/Junk first | If it's truly missing every time, flag it — something's actually wrong |
| The page shows an AWS error message | The backend isn't deployed or is misconfigured | This is a "call the developer" situation — not something to fix from the browser |

## Who this is for

Anyone with the link — no account, no login. Uploaded photos and their results
are not private: don't upload anything sensitive. Results (filenames, labels,
text found) are also queryable by anyone with API/AWS access via the read API
described in the README — again, nothing sensitive.
