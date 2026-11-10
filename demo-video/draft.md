# 45-second client proof film — Voice

**Status:** revised draft for review · **Target:** Upwork portfolio card and proposal attachment
**Primary:** 45 s · 1920×1080 · 30 fps · H.264/AAC · burned-in captions
**Teaser:** 22 s proposal autoplay · 1:1 mobile crop
**Email cut:** 60 s, only when you can send a link or a follow-up
**Audience:** home-services operators (HVAC, plumbing, electrical), dental and auto-service
front desks, and agencies building voice agents for local businesses.
**One-line promise:** A voice booking agent that reads back, confirms, writes once, and proves what
happened — with the model talking and the policy owning the write.
**What the client should think at the end:** “This is a working voice agent, not a chatbot demo. He
has solved the double-booking problem, and he is honest about the limits.”

## Why this version

The first draft tried to show booking, emergency and dashboard as three equal beats. That is a
product tour. This version follows one rule: **one failure, one fix, one metric, one why-me, one
CTA.** The failure is an unsafe booking write — the double booking the client already fears. The fix
is read-back, an explicit yes and one idempotent write. The metric is zero unsafe writes across 40
text scenarios. The emergency path moves to the 60-second email cut.

The voice is still the product. If you can record a real local call, do it; the draft includes a
labeled fallback if the live take is not clean.

## What the listings ask for

- Home-services voice listing: inbound booking, reschedule and cancel, real-time availability,
  human handoff, recordings and post-call summaries.
- Healthcare and voice listings: confirmation before a record write, duplicate prevention, and a
  fallback when an integration times out.
- Senior voice listings: latency, turn-taking, cost per minute, docs and handover.

Source: `forge-roadmap/research/upwork-voice-captures-2026-11.md`.

## Positioning

**Problem the client recognizes.** A missed call is a lost job. A double booking is a support
ticket. An invented slot, an unconfirmed write or a transfer that never connected is worse. Most
voice demos prove the first call and stop; they do not show the write path or the audit trail.

**The fear underneath it.** The client has seen a voice demo that sounded good and could not survive
a real caller. They want to know: will it book twice? Will it invent a time? Can I see what happened
afterwards?

**Why you.** The model talks and extracts; deterministic policy owns validation, confirmation,
writes, emergency classification and handoff. One explicit yes, one policy token, one idempotent
write. A retry returns the same booking. The dashboard shows the outcome, transcript, tool timeline
and latency.

**The one proof number.** **Zero unsafe writes across 40 text scenarios** — zero double bookings and
zero unconfirmed writes. Keep the live audio **5/6** as an honesty caveat, not as the headline
metric. The hybrid release gate is not claimed because the final sweep had no Groq key.

**Proof-of-concept framing.** Say it early and keep it on the end card: “This proof of concept uses
a synthetic two-tenant corpus. The same method applies to your call flow.” That is the bridge from
your demo to their business.

**Production signals, not a production claim.** Show the self-hosted LiveKit stack, Docker Compose,
typed tools, tenant YAMLs, dashboard, alerts, runbook and handover. Do not claim a hosted service,
SIP, real calendar/CRM/SMS, a production SLA or sub-3 s latency. The honest line is stronger:
“local-only demo, production path scoped separately.”

## The 45-second script

| Time | Picture | Voiceover | On-screen text |
|---|---|---|---|
| 0:00–0:05 | Dashboard with a missed-call alert, or the browser caller page with a ringing state. | How many calls did your front desk miss last week? | **How many calls missed?** |
| 0:05–0:10 | Caller page: choose Harborlight/Summit, press Start call. Small label: “synthetic two-tenant corpus.” | This proof of concept uses a synthetic two-tenant corpus; the method applies to your call flow. | **Proof of concept · synthetic corpus** |
| 0:10–0:18 | Real call audio or captioned transcript: service-area check, real slots, read-back of service, time, technician, address and phone. | A caller asks for a drain cleaning. The agent checks the service area, offers a real slot, and reads back the details. | **Read-back: service · time · tech · address** |
| 0:18–0:26 | Caller says yes. Show the booking ID, tool timeline and one write. Small overlay: retry → same booking. | The caller says yes. One token, one write. A retry returns the same booking. No double booking. | **Yes → one token → one write** |
| 0:26–0:34 | Three-step engagement strip over the dashboard: Reproduce → Measure → Fix + gate. | I can reproduce your booking failures, separate model from policy, and give you a ranked fix list with a before/after evaluation. | **Reproduce → Measure → Fix + gate** |
| 0:34–0:40 | One metric, large: zero unsafe writes across 40 text scenarios. Caveat overlay: live audio 5/6, all hard gates green. | On 40 text scenarios, zero unsafe writes. | **0 unsafe writes · live audio 5/6** |
| 0:40–0:45 | End card: title, GitHub URL, proof-of-concept line, one thin technical strip. | Send me two call flows and your worst failure. I’ll tell you what’s model, policy, or integration. | **Send 2 call flows** · `github.com/ArpanSM/forge-voice` · **Proof of concept · method applies to your call flow** |

**Word count:** about 110 (≈147 wpm). Record at 0.96–1.00. The voice is the product; do not rush
the read-back.

## The important production decision

A voice project without voice is a weak pitch. The best version records a **real local browser call**
with the local LFM3-Audio-2B agent voice:

- 2–3 turns: caller asks for a drain cleaning; agent checks the service area, offers a real slot,
  reads back the service/date/technician/address/phone, caller says yes, booking commits.
- Caption both speakers. Label the video **“local synthetic demo.”**

If the live local take is not reliable enough to record cleanly, use the committed storyboard and
real call records with a narrator and captions. Label it **“simulated call · real policy/tool run.”**
Do not fake phone audio, a live human transfer or a real customer.

**Do not use the old voice portfolio copy that says the emergency handoff fails.** The current
release report says the live local audio run is **5/6 with every hard gate green**; the remaining
failure is a genuine ASR entity miss in the address read-back. Use the release report as the source
of truth.

## What to capture

- **Caller page:** tenant choice, disclosure, Start call.
- **Booking call:** real audio or captioned transcript; service-area check, real slots, read-back.
- **Write:** explicit yes, booking ID, tool timeline, one write; small retry/same-booking overlay.
- **Dashboard:** outcome, transcript, tool timeline, p95 first audio, alerts.
- **Metric:** 40 text scenarios, zero unsafe writes; live audio 5/6 caveat.
- **End card:** GitHub URL, “Local-only · synthetic · no production SLA,” and the technical strip.

Use the real local app and real call records. If you record a live call, use a clean microphone for
the caller and keep the agent voice at a natural level. Hide browser bookmarks, notifications and
any terminal with keys.

## The why-me beat

The eight seconds at 0:26 are the turn of the film. Do not fill them with an architecture diagram.
Show a three-step engagement:

> **1 Reproduce the booking failures · 2 Measure model vs policy · 3 Fix + regression gate**

That tells the client what hiring you looks like. The 8 typed tools, tenant claim and dashboard
belong on the end card and in the README.

## Production notes

- **Voice:** the agent’s actual LFM3 voice. Do not replace it with a generic TTS narrator for the
  call segments. A narrator can bridge the sections.
- **Caller:** use a real human caller if possible. If you use a synthetic caller, label it
  “simulated caller.” Do not present a TTS caller as a customer.
- **Music:** none under the call audio; a low pulse between sections. Duck under the narrator.
- **Captions:** burned in for both speakers. The viewer may be muted; the words still sell the work.
- **Labels:** “local synthetic demo,” “no production SLA.” Keep them visible during the relevant
  shots, not only on the end card.
- **Pacing:** one idea per 5–8 seconds. Let the read-back and the metric land.
- **Screen:** 1920×1080, clean browser profile, no real phone numbers or customer data.
- **Audio:** −14 LUFS integrated, −1.5 dBTP; AAC 192 kbps.
- **Export:** H.264 High, 30 fps, `+faststart`, under 100 MB.
- **End card:** at least 4 seconds; URL and caveat readable on a phone.

## 22-second teaser

| Time | Beat |
|---|---|
| 0:00–0:04 | “How many calls did your front desk miss last week?” |
| 0:04–0:10 | Booking: read-back and explicit yes. |
| 0:10–0:14 | “I can reproduce your booking failures and rank the fixes.” |
| 0:14–0:18 | “Zero unsafe writes across 40 scenarios.” |
| 0:18–0:22 | “Send me two call flows.” End card. |

For the 1:1 crop, keep the caller page, the read-back and the dashboard call detail in frame. Do not
crop the “simulated” label or the metric.

## 60-second email cut

Keep the 45-second film and add two beats:

- **After the booking write —** the emergency path: 911-first script, structured ticket, simulated
  transfer or honest callback. Label the transfer simulated.
- **After the metric —** the admin and handover layer: two tenant YAMLs, validating editor,
  dashboard, runbook.

Do not use the 60-second cut as the Upwork attachment. It is for email, a follow-up link, or a
client who has already asked for the delivery detail.

## What not to do

- Do not show booking, emergency and dashboard as three equal beats. The 45-second cut is the
  booking write.
- Do not fake a phone call, a live human transfer or a real customer.
- Do not use the stale copy that says the emergency handoff fails; check the current release report.
- Do not claim sub-3 s, sub-2 s, a production SLA or a hosted service.
- Do not hide the 5/6. Put it next to the zero-unsafe-writes metric as a caveat.
- Do not show a silent dashboard for 45 seconds. The client needs to hear the agent.
- Do not end with “read the runbook.” End with “send me two call flows.”

## Acceptance test

Show the 45-second cut to a home-services owner or an agency that sells voice agents. Ask:

1. What does the agent do on a normal call?
2. What stops a double booking?
3. What would you send this person first?

If they cannot answer all three, the film is still a dashboard tour.

## Portfolio card copy

**Title:** Local-first voice booking agent — LiveKit, typed tools and an evaluation gate

**Short description:** A proof of concept for home-services teams that answers, books, reschedules,
cancels and hands off — with read-back confirmation, one idempotent write, a per-call dashboard and
a measured evaluation. Local synthetic demo; no production SLA.

**Proposal line:** Send me two call flows and your worst failure. I’ll tell you what’s model,
policy, or integration, and what I would fix first.
