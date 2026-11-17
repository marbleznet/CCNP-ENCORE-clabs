# Spanning Tree (RSTP / MST / the guards) — In-Depth Concepts

The companion reference to the [README](README.md) lab guide. The README is the
*hands-on* path (elect a root, watch ports converge, build an MST region, trip
every guard); this file is the *why*. Each 📖 **Deep dive** link in the README
jumps to a section here.

**Contents**
- [Why spanning tree exists](#why-spanning-tree-exists)
- [The BPDU and the Bridge ID](#the-bpdu-and-the-bridge-id)
- [Electing a root bridge](#electing-a-root-bridge)
- [Choosing ports: the three decisions](#choosing-ports-the-three-decisions)
- [Path cost and the long/short trap](#path-cost-and-the-longshort-trap)
- [Port roles and states in RSTP](#port-roles-and-states-in-rstp)
- [How RSTP actually converges fast](#how-rstp-actually-converges-fast)
- [The three flavours: PVST+, rapid-PVST, MST](#the-three-flavours-pvst-rapid-pvst-mst)
- [MST regions, instances, IST and CIST](#mst-regions-instances-ist-and-cist)
- [MST boundaries and max-hops](#mst-boundaries-and-max-hops)
- [The guards, and which direction each points](#the-guards-and-which-direction-each-points)
- [A troubleshooting method for spanning tree](#a-troubleshooting-method-for-spanning-tree)
- [Command summary](#command-summary)

---

## Why spanning tree exists

Ethernet has **no TTL**. That single fact is the whole justification for spanning
tree, and it is worth stating plainly because it is what makes a layer-2 loop
categorically worse than a layer-3 one.

An IP packet caught in a routing loop decrements TTL at each hop and dies after
at most 255 of them. An Ethernet frame has no such field. Put a loop in a
switched topology and a single broadcast frame circulates **forever**, and
because switches *flood* broadcasts out of every port, each pass around the loop
multiplies the number of copies. Within seconds you have a **broadcast storm**
that saturates every link, and simultaneously **MAC table instability** — the
same source MAC keeps arriving on different ports, so the switch rewrites its
forwarding table thousands of times a second and unicast traffic starts flooding
too. The network does not degrade; it stops. And it does not recover on its own,
because nothing ages the frames out.

Spanning tree's job is therefore not optimisation, redundancy or load balancing.
Its job is to take a physical topology that contains loops and **block enough
ports to leave exactly one active path between any two points** — a tree — while
keeping the blocked links ready to take over if an active one fails.

The cost of that guarantee is the thing everything else in this topic is trying
to claw back: **the blocked links carry nothing**. You paid for them and they sit
idle. [MST instances](#mst-regions-instances-ist-and-cist) and
[EtherChannel](../l2-trunk-etherchannel/CONCEPTS.md#why-etherchannel-exists) are
the two standard answers.

[↩ back to README Lab 1](README.md#lab-1--see-the-loop-and-watch-stp-resolve-it)

---

## The BPDU and the Bridge ID

Switches build the tree by exchanging **BPDUs** (Bridge Protocol Data Units) —
small layer-2 multicast frames sent to **`01:80:c2:00:00:00`**, every **2 seconds**
by default. They are not IP, so no IP ACL will ever match them.

> ⚠️ **A tempting assumption, disproved here.** Because BPDUs are layer-2
> multicast, it looks like a **MAC ACL** should be able to filter them. **Verified
> on IOS-XE 17.16: it cannot.** A `mac access-list extended` denying
> `0180.c200.0000`, applied inbound with `mac access-group`, installed cleanly,
> appeared in the running config, and recorded **zero hit counters** while
> `show spanning-tree interface <if> detail` showed the BPDU receive counter
> still climbing. A blunt `deny any any` MAC ACL on an access port did not stop
> ordinary host traffic either — on this platform `mac access-group` is accepted
> and **inert**.
>
> The generalisable half is the first one: **BPDUs are punted to the control
> plane and are not subject to port ACLs**, so you cannot filter spanning tree
> this way even on platforms where MAC ACLs otherwise work. If you want to stop
> BPDUs on a port, the tool is `spanning-tree bpdufilter`, and the reason that is
> dangerous is covered under
> [the guards](#the-guards-and-which-direction-each-points).
>
> The practical diagnostic: **a filter showing no hit counters is telling you it
> is not being consulted.** That is a signal, not a dead end.

Every BPDU carries the sender's view of the world:

| Field | Meaning |
|---|---|
| **Root Bridge ID** | who the sender believes is the root |
| **Root Path Cost** | the sender's total cost to reach that root |
| **Sender Bridge ID** | who the sender is |
| **Port ID** | which port it went out of |
| timers | Hello, Max Age, Forward Delay — dictated *by the root* |

The **Bridge ID** is the currency of every election, and it is 8 bytes in two
parts:

```
   Bridge ID  =  [ 4-bit priority ][ 12-bit sys-id-ext (VLAN/instance) ][ 48-bit MAC ]
                 \_____________ 16 bits _____________/
```

- **Priority** is configurable but only in steps of **4096**, because the low 12
  bits were repurposed to carry the VLAN or MST instance number (the *extended
  system ID*). That is why `spanning-tree mst 1 priority 5000` is rejected and
  `4096` is not. Default is **32768**.
- **sys-id-ext** is what makes a per-VLAN or per-instance tree possible from one
  set of hardware — the priority you see in `show` output is
  `priority + instance` (e.g. 32769 for VLAN 1, or 4097 for MSTI 1 at 4096).
- **MAC address** is the tiebreak, and it is why an unconfigured network elects
  its root essentially at random.

A BPDU is judged "superior" by comparing, in strict order: lowest Root Bridge ID,
then lowest Root Path Cost, then lowest Sender Bridge ID, then lowest Port ID.
Every decision spanning tree makes is that one comparison applied somewhere.

[↩ back to README Lab 2](README.md#lab-2--control-the-root-bridge)

---

## Electing a root bridge

Every switch boots believing it is the root and announces itself. As soon as it
hears a *superior* BPDU it stops claiming and starts relaying, and within a few
seconds the network agrees on the switch with the **lowest Bridge ID**.

Because the priority defaults to 32768 everywhere, **an unconfigured network
elects the switch with the lowest MAC address** — which in practice means the
oldest device in the building, quite possibly an access switch in a cupboard,
becomes the logical centre of your network. Every path is then computed toward
it.

**Root placement is a design decision you make, not an outcome you accept.** Put
the root on a distribution or core switch, in the middle of your traffic
patterns, and configure a **secondary** so that a failure lands somewhere
predictable rather than wherever the MAC lottery decides:

```
spanning-tree mst 0-1 priority 4096      ← primary
spanning-tree mst 0-1 priority 8192      ← secondary, on a different switch
```

The `spanning-tree vlan <n> root primary` / `root secondary` macros do the same
thing by inspecting the current root and picking a lower value; they are
convenient but they compute a value *once*, so an explicit priority is more
predictable and is what you should write in a config you intend to keep.

> **The failure mode to internalise:** a wrong root bridge produces **no error
> anywhere**. Nothing is blocked that shouldn't be, no log fires, no guard trips
> and every host pings. The `rootguard-disabled-then-hijack` fault in the
> catalogue is exactly this, and it is deliberately the one with no error state
> to find. The only way to detect it is to know who *should* be root and check.
> That is why [root guard](#the-guards-and-which-direction-each-points) belongs
> on every downlink.

[↩ back to README Lab 2](README.md#lab-2--control-the-root-bridge)

---

## Choosing ports: the three decisions

Once the root is known, every switch makes three decisions in this order. Almost
every "why is traffic taking that path?" question is answered by walking them.

**1. Which of MY ports is the Root Port?** — exactly one per switch (except on
the root, which has none). The tiebreak sequence:

1. lowest **root path cost**
2. lowest **sender Bridge ID** (i.e. the neighbour advertising it)
3. lowest **sender Port ID** (port priority, then port number)

**2. Who is the Designated Port on each segment?** — exactly one per segment,
belonging to whichever switch on it has the lowest root path cost (then lowest
Bridge ID). Every port on the root bridge is designated, always.

**3. Everything else blocks.** Those are Alternate (or Backup) ports.

Two points people get wrong constantly:

- **Cost is evaluated by the receiving switch, on its own ports.** SW4 chooses
  its root port using the cost of *SW4's* ports. Setting a cost on the far end of
  the link changes how the *far end* computes its tree, not how SW4 chooses. This
  is why cost changes so often appear to "do nothing" — it is the same
  directionality trap as OSPF cost, and it is why the `mst-cost-manipulation`
  fault is applied on SW4 itself.
- **Port priority only ever breaks a tie between two links to the same
  neighbour.** If the costs or the neighbours differ, port priority is never
  reached. It is the tool for parallel links, not for general path steering.

[↩ back to README Lab 4](README.md#lab-4--steer-the-tree-with-cost-and-priority)

---

## Path cost and the long/short trap

Cost is derived from interface bandwidth, and there are **two incompatible
scales**:

| Link speed | **Short** (16-bit, classic) | **Long** (32-bit, IEEE 802.1t) |
|---|---|---|
| 10 Mb | 100 | **2,000,000** |
| 100 Mb | 19 | 200,000 |
| 1 Gb | 4 | 20,000 |
| 10 Gb | **2** | 2,000 |
| 100 Gb | **1** ⚠ | 200 |
| 1 Tb | **1** ⚠ | 20 |

The short method saturates: **10 Gb, 100 Gb and 1 Tb all cost about the same**,
so a modern network using it cannot distinguish a 10 Gb path from a 100 Gb one
and will happily choose the slower. That is the entire argument for the long
method:

```
spanning-tree pathcost method long        ← set it consistently, everywhere
show spanning-tree pathcost method
```

> ⚠️ **Verified on IOS-XE 17.16 in this lab:** the IOL Ethernet interfaces are
> **10 Mb**, and `show spanning-tree summary` reports
> `Configured Pathcost method used is short (Operational value is long)` — MST
> operates the **long** method regardless of the configured setting, so the port
> costs you actually see are **2000000**, not the textbook 100. Any cost you set
> in a fault or a lab step has to be well above 2000000 to have any effect. Check
> the Cost column rather than assuming the classic table applies.

Mixing the two methods in one network is a real hazard: costs computed on
different scales are compared as plain numbers, so a switch using short costs
looks dramatically closer to the root than one using long, and paths bend toward
it for no legitimate reason.

[↩ back to README Lab 4](README.md#lab-4--steer-the-tree-with-cost-and-priority)

---

## Port roles and states in RSTP

RSTP separates **role** (the job a port has in the topology) from **state** (what
it is doing with frames). Reading them as two separate columns is the single most
useful habit in STP troubleshooting.

**Roles:**

| Role | Meaning |
|---|---|
| **Root** | this switch's best path toward the root — exactly one per switch |
| **Designated** | this port is the best path to the root *for its segment* |
| **Alternate** | a backup for the ROOT port — an alternative path to the root |
| **Backup** | a backup for a DESIGNATED port on the same segment (needs a hub/loopback; rare) |
| **Disabled** | administratively out of the topology |

**States** collapse from legacy STP's five to three:

| RSTP state | Learns MACs? | Forwards? | Legacy equivalent |
|---|---|:---:|:---:|
| **Discarding** | no | no | Disabled + Blocking + Listening |
| **Learning** | yes | no | Learning |
| **Forwarding** | yes | yes | Forwarding |

> The distinction that matters for the exam: **Alternate is a role, Discarding is
> a state.** `show spanning-tree` prints `Altn BLK` — the first is the role, the
> second the state, and they answer different questions. A port can be Designated
> and Discarding (that is what a tripped guard looks like: `Desg BKN`).

The lab's own inconsistency markers appear in the **Type** column, not the state
column: `*ROOT_Inc` and `*LOOP_Inc`. A guard that has tripped shows as `BKN` with
one of those flags — **not** as "down", and it will not appear in
`show interfaces` as anything unusual. `show spanning-tree inconsistentports` is
the direct check.

[↩ back to README Lab 3](README.md#lab-3--read-the-tree-roles-states-and-what-changed)

---

## How RSTP actually converges fast

Legacy 802.1D took **30–50 seconds** to bring a port up: 20s Max Age to notice a
failure, then 15s Listening, then 15s Learning. Those were *timers* — the
protocol waited out a worst case because it had no way to be sure.

RSTP (802.1w) replaces waiting with **asking**, and gets convergence into the low
single-digit seconds:

- **Proposal/Agreement handshake.** On a point-to-point link, a designated port
  sends a *proposal* to become forwarding. The neighbour blocks its other
  non-edge ports (a **sync**), then returns an *agreement*, and the port goes
  straight to forwarding. It is an explicit negotiation instead of a timer.
- **Port types.** RSTP classifies each port as **point-to-point** (full duplex —
  eligible for the handshake), **shared** (half duplex — must fall back to
  timers), or **edge** (PortFast — goes straight to forwarding, no handshake).
  This is why full duplex matters to STP at all, and why `show spanning-tree`
  prints `P2p` or `P2p Edge` in the Type column.
- **Every switch originates BPDUs.** In 802.1D only the root generated them and
  everyone else relayed; in RSTP each switch sends its own every hello, so a
  neighbour's silence is detected after **3 missed hellos (6 seconds)** instead
  of Max Age.
- **Faster topology changes.** A TC is only generated for non-edge ports moving
  to forwarding, and it directly flushes MAC tables rather than shortening the
  ageing timer.

Rapid-PVST and MST are both RSTP underneath, so all of this applies to
everything in this lab.

[↩ back to README Lab 3](README.md#lab-3--read-the-tree-roles-states-and-what-changed)

---

## The three flavours: PVST+, rapid-PVST, MST

| | **PVST+** | **Rapid-PVST+** | **MST** |
|---|---|---|---|
| Based on | 802.1D | **802.1w** | **802.1s** (+802.1w) |
| Trees | one per **VLAN** | one per **VLAN** | one per **instance** |
| Convergence | 30–50s | ~1–6s | ~1–6s |
| CPU/BPDU load | one BPDU set per VLAN | per VLAN | **per instance** |
| Load balancing | per VLAN | per VLAN | **per instance** |
| Cisco default | — | ✅ (`rapid-pvst`) | — |

The tension is between **granularity** and **scale**. Per-VLAN trees let you send
VLAN 10 one way and VLAN 20 another, but with 500 VLANs you are running 500
spanning tree instances and generating 500 sets of BPDUs — real CPU on the
switch, for trees that are almost certainly identical to each other.

**MST decouples the two.** You define a handful of *instances*, map many VLANs
into each, and run one tree per instance. Two instances give you the same load
balancing that per-VLAN mode offers while running two trees instead of five
hundred. That is the entire point of MST, and it is why this lab maps VLAN 10 to
MSTI 1 and VLAN 20 to MSTI 2 and roots them on different switches.

> **Verified on IOS-XE 17.16:** the IOL L2 image defaults to **rapid-pvst**, so
> the blank slate in this lab is running rapid-PVST before you convert it to MST
> in README Lab 5.

[↩ back to README Lab 5](README.md#lab-5--convert-to-mst)

---

## MST regions, instances, IST and CIST

An **MST region** is a group of switches that agree on three things — and they
must match **exactly**:

1. the **region name**
2. the **revision number**
3. the **complete VLAN-to-instance map**

Those three are hashed into a 16-byte **configuration digest** carried in every
MST BPDU. **Neighbours compare the digest, never the underlying configuration.**
Change any single input and the digest changes completely, so a one-digit
revision typo has exactly the same effect as mapping every VLAN differently.

```
spanning-tree mst configuration
 name ENCOR
 revision 1
 instance 1 vlan 10
 instance 2 vlan 20
!
show spanning-tree mst configuration digest      ← compare this between switches
```

The vocabulary, which the exam tests directly:

- **MSTI (MST Instance)** — a tree *inside* a region, numbered 1–4094. Purely
  internal; the outside world never sees it.
- **IST (Internal Spanning Tree) = instance 0** — the special instance that
  represents the whole region to the outside. **Every VLAN you do not explicitly
  map lands in instance 0**, which is a common source of surprise: forget to map
  a VLAN and it silently follows the IST's tree rather than the one you designed.
- **CST (Common Spanning Tree)** — the single tree running *between* regions and
  any non-MST switches.
- **CIST (Common and Internal Spanning Tree)** — the combination: the CST plus
  each region's IST. It is what makes the whole network, MST regions and legacy
  switches together, one loop-free topology.

The mental model that makes it click: **an entire MST region appears to the
outside world as a single logical switch.** Everything inside — all your MSTIs,
all your internal blocking — is invisible externally. Only the IST/CIST is
presented at the edges.

[↩ back to README Lab 5](README.md#lab-5--convert-to-mst) ·
[Lab 6](README.md#lab-6--mst-load-balancing-with-two-instances)

---

## MST boundaries and max-hops

A **boundary port** is one facing something that is not in your region — a
different MST region, a rapid-PVST switch, or a legacy 802.1D switch. Across a
boundary, **only the CIST is presented**; the internal MSTIs are collapsed and
invisible.

This is why a region mismatch is so destructive despite being a one-character
change. In the `mst-revision-mismatch` fault, SW3's revision goes from 1 to 2,
its digest changes, it is no longer in the region — and it therefore **cannot be
the MSTI2 root for the other switches**, because MSTI2 does not exist across the
boundary. VLAN 20 re-roots elsewhere. Nothing logs an error; the switches simply
stop considering each other regional peers.

When the neighbour is rapid-PVST, the MST switch runs **PVST simulation**,
mapping its CIST onto the neighbour's per-VLAN trees. If that cannot be done
consistently it raises `%SPANTREE-2-PVSTSIM_FAIL` and blocks the port rather than
risk a loop. That is the `stp-mode-mismatch` fault.

**Max-hops** is how a region ages BPDUs. Outside a region, BPDU freshness is
governed by Max Age; *inside* one, the root sends BPDUs with a hop count of
`max-hops` (default **20**) and each switch decrements it before relaying. At zero
the BPDU is discarded.

```
spanning-tree mst max-hops 20        ← effectively the region's diameter budget
```

So max-hops must exceed the number of switches between the root and the furthest
switch in the region.

> ⚠️ **Verified on IOS-XE 17.16 — and the result is the best argument for loop
> guard in this whole file.** Setting `max-hops 1` on the root in this lab means
> SW4 (two hops away) never receives a valid BPDU, so it concludes there is no
> root and **elects itself**. A switch that believes it is root sets every port
> to Designated/Forwarding — and SW4 forwarding on *both* uplinks would bridge
> SW2 to SW3 through it, closing a genuine layer-2 loop with no TTL to contain
> the resulting storm.
>
> **It does not happen.** SW4's uplinks are non-designated ports that abruptly
> stopped receiving BPDUs, which is precisely loop guard's trigger, so both go
> `*LOOP_Inc` and stay blocked. The lab loses connectivity to SW4 and stays
> stable. Loop guard converted a broadcast storm into an outage — which is an
> enormously better outcome, and the reason to configure it.

[↩ back to README Lab 7](README.md#lab-7--trip-every-guard)

---

## The guards, and which direction each points

Five features, and the single most useful way to hold them in your head is
**which direction each one faces** and **what it reacts to**.

| Feature | Applied to | Reacts to | Result |
|---|---|---|---|
| **PortFast** | access ports (**down**, to hosts) | — | skip listening/learning, forward immediately |
| **BPDU guard** | PortFast ports (**down**) | a BPDU **APPEARING** | **err-disable** the port |
| **BPDU filter** | (dangerous) | — | stop sending/processing BPDUs |
| **Root guard** | **downlinks**, away from root | a **superior** BPDU arriving | **root-inconsistent** (blocks) |
| **Loop guard** | **root/alternate ports**, toward root | BPDUs **DISAPPEARING** | **loop-inconsistent** (blocks) |

The pairing to memorise: **BPDU guard and loop guard are opposite bets.** BPDU
guard blocks when BPDUs *appear* where none should be; loop guard blocks when
BPDUs *vanish* from where they should be arriving. They are applied to opposite
ends of the switch and they protect against opposite mistakes.

And the direction rule: **root guard points DOWN, loop guard points UP.**
Getting that backwards is a fault in its own right — `rootguard-on-uplink-port`
puts root guard on a port facing *toward* the root, where the legitimate root's
superior BPDUs immediately trip it.

> ⚠️ **A port holds exactly ONE guard setting — `spanning-tree guard` has three
> values (`root`, `loop`, `none`), not two independent toggles. Verified on
> IOS-XE 17.16:** applying `spanning-tree guard root` to a port that already had
> `spanning-tree guard loop` **silently replaces it** — the running config shows
> only `guard root` — and `no spanning-tree guard root` then leaves the port with
> **no guard at all** rather than restoring the loop guard.
>
> This is a genuine production hazard: adding root guard to a port that was
> relying on loop guard removes the loop protection you thought you had, with no
> warning. It also caused a real cascade while this lab was being built — one
> fault's "obvious inverse" fix stripped loop guard from an uplink and silently
> invalidated three *later* faults that depended on it being there.

**PortFast + BPDU guard should be treated as inseparable.** PortFast asserts
"this port faces a host"; BPDU guard enforces it. Without the guard, PortFast on
a port that turns out to face a switch is a transient loop waiting to happen —
it forwards immediately, before the tree has been computed.

> ⚠️ **PortFast does nothing on a trunk port unless you say `trunk`. Verified on
> IOS-XE 17.16:** plain `spanning-tree portfast` on a trunking interface is
> accepted, prints a warning that is easy to scroll past (*"Portfast has been
> configured on Ethernet0/3 but will only have effect when the interface is in a
> non-trunking mode"*), and `show spanning-tree interface <if> portfast` then
> reports `disabled` for every instance.
>
> The consequence that matters: **BPDU guard did not fire either**, despite
> `spanning-tree bpduguard enable` being configured on the interface and BPDUs
> arriving every two seconds. On this platform the interface-level guard only
> acts where PortFast is *operational*. The explicit form
> `spanning-tree portfast trunk` is required — and `show spanning-tree interface
> <if> portfast` is how you tell an accepted command from an effective one.

```
interface Ethernet0/3
 spanning-tree portfast
 spanning-tree bpduguard enable
!
spanning-tree portfast default                 ← global: all access ports
spanning-tree portfast bpduguard default       ← global: guard all portfast ports
```

**Recovery behaviour differs, and this catches people:**

- **root-inconsistent and loop-inconsistent are SELF-CLEARING.** Remove the cause
  and the port recovers on its own within tens of seconds.
- **err-disable (BPDU guard) is LATCHED.** Removing the cause does **nothing**.
  The port must be bounced (`shutdown` / `no shutdown`) or recovered on a timer:
  ```
  errdisable recovery cause bpduguard
  errdisable recovery interval 300
  ```
  That asymmetry is why the `bpduguard-on-uplink` fault's `fix` is deliberately
  not a pure inverse of its `break`.

> **BPDU filter is the one to be careful with**, because it has two very
> different behaviours. Configured **globally** (`spanning-tree portfast
> bpdufilter default`) it applies only to PortFast ports and *stops filtering the
> moment a BPDU is received* — a relatively safe "don't leak BPDUs to hosts"
> setting. Configured **on an interface** (`spanning-tree bpdufilter enable`) it
> unconditionally disables BPDUs on that port in both directions, which
> effectively removes the port from spanning tree while leaving it forwarding
> data. That is a loop generator, and it is what the
> `loopguard-triggered-by-bpdufilter` fault exploits.

**UDLD** is the adjacent tool worth knowing: it detects a **unidirectional link**
(fibre receiving but not transmitting) by exchanging its own keepalives, and can
err-disable the port. Loop guard and UDLD overlap — both protect against a link
that stops delivering BPDUs one way — but loop guard acts on STP state while UDLD
acts on the physical link, and the usual recommendation is to run both on fibre.

[↩ back to README Lab 7](README.md#lab-7--trip-every-guard)

---

## A troubleshooting method for spanning tree

Work from the top of the tree down. Almost every fault is answered in the first
three steps.

1. **Which instance are you even looking at?** `show spanning-tree` with no
   arguments shows the **CIST (instance 0) only**. If your problem is VLAN 10 and
   VLAN 10 is in MSTI 1, that output is nearly irrelevant. Always
   `show spanning-tree mst 1`.
2. **Who is the root, and who should be?** `show spanning-tree mst <n>` on
   several switches. A wrong root produces no error — you must know the intended
   design to spot it.
3. **Is anything inconsistent?** `show spanning-tree inconsistentports` — one
   command that catches every tripped root guard and loop guard. Then read the
   `Type` column for `*ROOT_Inc` / `*LOOP_Inc`.
4. **Did a port disable itself?** `show interfaces status | include err-disabled`,
   then `show logging` for the cause. BPDU guard and port security both land here.
5. **Is the region intact?** (MST only) `show spanning-tree mst configuration
   digest` on two switches and compare. Different digest = different region =
   boundary, regardless of how similar the configs look.
6. **Are the modes the same?** `show spanning-tree summary | include mode`. A
   single switch in a different mode invalidates every other comparison.
7. **Is something filtering traffic?** `show run interface <if>` for
   `bpdufilter`, and **`show vlan filter`** for a VACL. Nothing in any
   spanning-tree command reveals either. Remember that a clean STP sweep proves
   the *topology* is right, not that traffic flows — a VACL drops frames on a
   perfectly built tree.

Two habits that separate fast diagnosis from slow:

> **Read roles, not reachability.** Most STP faults *reroute* rather than
> disconnect — the topology becomes wrong while every ping still succeeds. Ping
> is close to useless as an STP test. Compare port roles against the intended
> design.
>
> **The switch reporting the error is usually not the switch with the
> misconfiguration.** Loop guard trips on the switch that stopped *receiving*
> BPDUs; the cause (a BPDU filter, a MAC ACL, a failing fibre) is at the other
> end. Always look at the far side of the link before touching the one that is
> complaining.

[↩ back to README Lab 8](README.md#lab-8--the-verification-sweep)

---

## Command summary

| Question | Command |
|---|---|
| Which mode is this switch in? | `show spanning-tree summary \| include mode` |
| Who is the root of this instance? | `show spanning-tree mst <n>` |
| Port roles and states for one instance | `show spanning-tree mst <n>` |
| Everything, per VLAN (PVST modes) | `show spanning-tree vlan <n>` |
| Has any guard tripped? | `show spanning-tree inconsistentports` |
| Is my MST region consistent? | `show spanning-tree mst configuration digest` |
| What VLANs are in which instance? | `show spanning-tree mst configuration` |
| Which ports disabled themselves? | `show interfaces status \| include err-disabled` |
| Why did a port err-disable? | `show logging`, `show errdisable recovery` |
| Detail for one port (BPDU counters) | `show spanning-tree interface <if> detail` |
| Set the root | `spanning-tree mst <n> priority 4096` |
| Steer a path | `spanning-tree mst <n> cost <c>` (on the *receiving* switch) |
| Break a tie to the same neighbour | `spanning-tree mst <n> port-priority <p>` |
| Region diameter | `spanning-tree mst max-hops <n>` |
| Guards | `spanning-tree guard root` / `guard loop` / `bpduguard enable` |
| Recover a latched err-disable | `shutdown` / `no shutdown`, or `errdisable recovery cause bpduguard` |
