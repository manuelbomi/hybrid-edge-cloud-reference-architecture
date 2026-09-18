# ADR-003: Edge inference for latency-sensitive zones

## Status

Accepted

## Context

Not every camera in a deployment has the same requirements. Some are purely
informational (did anyone walk past this hallway today?) and can tolerate a
delay of seconds or minutes before their events are processed. Others are
tied to a physical or safety-relevant action -- opening a gate, stopping
equipment, flagging an access-control decision -- where a slow or missing
response has a real-world consequence, not just a stale dashboard.

Running all inference in the cloud is operationally simpler (one place to
deploy models, one place to monitor, no edge compute to manage) but adds a
round trip over the WAN for every single decision, and that round trip's
latency and reliability are exactly the things this architecture treats as
untrustworthy (see ADR-001). Running all inference at the edge avoids that
problem everywhere but adds edge compute cost and operational complexity to
sites and cameras that did not need it.

See `docs/decision-framework.md` for the full checklist and flowchart this
decision is based on.

## Decision

Inference placement is decided per camera/zone, not globally, using latency
sensitivity as the strongest single signal (alongside bandwidth, data
sovereignty, camera count, and connectivity reliability). Any zone with a
latency-sensitive control loop, or a hard data-sovereignty requirement, runs
inference at the edge, regardless of how good that site's WAN link
currently is. Zones without those constraints default toward edge inference
too once camera count or link reliability makes it more efficient, and only
fall back to cloud inference when a site is small, well-connected, and has
no sovereignty or real-time requirement.

Regardless of where inference itself runs, the *events* it produces cross
the WAN via the store-and-forward path described in ADR-001 -- edge
inference does not mean the cloud never finds out what happened, it means
the decision that mattered didn't have to wait for the cloud to find out.

## Consequences

- **Latency-sensitive zones get a real-time guarantee that does not depend
  on the WAN.** A gate, conveyor, or access-control decision reacts to a
  local inference result in local-network time, not WAN round-trip time.
- **Edge sites need enough local compute for the model(s) they run.**
  This is a real cost and operational surface area (model updates, edge
  hardware lifecycle, monitoring) that a cloud-only design would not have.
  This architecture accepts that cost specifically for the zones that need
  it, rather than either paying it everywhere or avoiding it everywhere.
- **Model versioning becomes a distributed problem.** Multiple edge sites
  may run different versions of an inference model for some period during a
  rollout. This repo does not implement a model-distribution pipeline; a
  real system needs one (and it is called out in the README's hardening
  notes).
- **The decision is revisitable per camera.** As bandwidth, WAN reliability,
  or camera count change at a site, re-running the checklist in
  `docs/decision-framework.md` may change the answer for that camera without
  requiring a redesign of the rest of the architecture.
