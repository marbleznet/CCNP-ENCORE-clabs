# 802.1Q Trunking & EtherChannel — In-Depth Concepts

The companion reference to the [README](README.md) lab guide. The README is the
*hands-on* path (build the VLANs, trunk them, bundle the links, break them); this
file is the *why*. Each 📖 **Deep dive** link in the README jumps to a section here.

**Contents**
- [What a VLAN actually is](#what-a-vlan-actually-is)
- [Access ports, trunk ports, and the 802.1Q tag](#access-ports-trunk-ports-and-the-8021q-tag)
- [The native VLAN, and why it keeps causing trouble](#the-native-vlan-and-why-it-keeps-causing-trouble)
- [The allowed VLAN list](#the-allowed-vlan-list)
- [DTP: letting switches negotiate trunks](#dtp-letting-switches-negotiate-trunks)
- [Why EtherChannel exists](#why-etherchannel-exists)
- [LACP, PAgP, and static "on"](#lacp-pagp-and-static-on)
- [What must match before a bundle forms](#what-must-match-before-a-bundle-forms)
- [Load balancing: the hashing myth](#load-balancing-the-hashing-myth)
- [Layer 2 vs Layer 3 EtherChannel](#layer-2-vs-layer-3-etherchannel)
- [A troubleshooting method for L2 paths](#a-troubleshooting-method-for-l2-paths)
- [EIGRP-style summary: the commands that matter](#eigrp-style-summary-the-commands-that-matter)

---

## What a VLAN actually is

A **VLAN is a broadcast domain**, and that is the whole definition. Everything
else follows from it.

A switch with no VLANs is one broadcast domain: a broadcast in at any port floods
out of every other port. Creating VLANs partitions the switch's forwarding logic
into several independent broadcast domains, each with its **own MAC address
table**. Two hosts in different VLANs on the *same switch*, in the *same IP
subnet*, wired one port apart, cannot talk — because the switch will not flood or
forward a frame between two VLANs. Ever. There is no ACL to bypass and no setting
to relax; **inter-VLAN traffic requires a router or an SVI**, full stop.

That last point is worth dwelling on because the README lab depends on it.
`host-c` sits in VLAN 20 and can reach nothing, and that is the *correct* result,
not a fault. There is no router anywhere in the topology. If you ever find VLAN 20
traffic reaching VLAN 10, something is badly wrong.

The consequences that matter operationally:

- **A VLAN is local to a switch unless you carry it between switches.** VLAN 10 on
  SW2 and VLAN 10 on SW3 are only "the same VLAN" because a trunk joins them.
- **VLANs must exist in the local database.** Assigning a port to VLAN 10 does not
  create VLAN 10; it is a reference to something that must already be there. A
  reference to a missing VLAN leaves the port *inactive* while still displaying
  the assignment in `show run` — see the `vlan-missing-from-database` fault.
- **VLANs have a state as well as an existence.** `state suspend` leaves a VLAN in
  the database, still listed against its ports, but stops it forwarding. `show
  vlan brief` reports `suspended` instead of `active` — a column people skip.
- **VLAN 1 is special and slightly cursed.** It is the default for every port, it
  cannot be deleted, and it carries control traffic (CDP, VTP, DTP, PAgP). Best
  practice is to use neither VLAN 1 for user data nor as the native VLAN.

[↩ back to README Lab 2](README.md#lab-2--vlans-and-access-ports)

---

## Access ports, trunk ports, and the 802.1Q tag

A physical switch port operates in one of two useful modes.

**An access port belongs to exactly one VLAN** and carries untagged frames. The
host plugged into it has no idea VLANs exist — it sends an ordinary Ethernet
frame, and the switch internally associates that frame with the port's access
VLAN. This is why `host-a` in the lab is a plain Linux container with no VLAN
configuration at all.

**A trunk port carries many VLANs** over one physical link, and needs a way to say
which VLAN each frame belongs to. That is **802.1Q**: a **4-byte tag inserted into
the Ethernet header**, between the source MAC and the EtherType.

```
 Untagged:  [ dst MAC ][ src MAC ][ EtherType ][ payload ][ FCS ]
 802.1Q:    [ dst MAC ][ src MAC ][ 0x8100 | PCP | DEI | VID ][ EtherType ][ payload ][ FCS ]
                                    \___________ 4 bytes ___________/
```

The fields you can actually see in a capture:

| Field | Bits | Meaning |
|---|---|---|
| **TPID** `0x8100` | 16 | "this frame is tagged" |
| **PCP** | 3 | Priority — this is **CoS**, the layer-2 QoS marking |
| **DEI** | 1 | Drop-eligible indicator (formerly CFI) |
| **VID** | 12 | The **VLAN ID**, 0–4095 |

Two exam-relevant consequences of that layout:

- **12 bits gives 4096 VLAN IDs.** 0 and 4095 are reserved, 1 is the default, and
  1002–1005 are legacy FDDI/Token Ring placeholders — you will see them in every
  `show vlan brief` and cannot delete them. Usable range is 2–1001 (normal) and
  1006–4094 (extended).
- **Tagging adds 4 bytes**, making a maximum tagged frame 1522 bytes instead of
  1518. Historically this produced "baby giant" errors on gear that didn't expect
  it; modern switches handle it silently.
- **CoS lives in the tag**, which means an untagged frame *has no CoS*. That is
  the entire reason the native VLAN cannot carry QoS markings, and one reason to
  keep user traffic off it.

The other encapsulation you may see referenced, **ISL**, was Cisco-proprietary and
*encapsulated* the whole frame (26-byte header + 4-byte trailer) rather than
inserting a tag. It is dead — every current platform is 802.1Q only — but it is
why the command reads `switchport trunk encapsulation dot1q`.

[↩ back to README Lab 3](README.md#lab-3--802-1q-trunking)

---

## The native VLAN, and why it keeps causing trouble

**Exactly one VLAN on each 802.1Q trunk is sent *untagged*** — the **native VLAN**
(VLAN 1 by default). Frames in the native VLAN cross the trunk as ordinary
untagged Ethernet; frames in every other allowed VLAN get a tag.

It exists for backward compatibility: it lets a trunk port interoperate with a
device that doesn't understand tagging at all. That is almost never useful now,
and the feature causes three recurring problems.

**1. A mismatch silently merges two VLANs.** If SW1 calls the native VLAN 99 and
SW3 calls it 1, then SW1's untagged VLAN 99 frames arrive at SW3 and get dropped
into VLAN 1, and vice versa. Two broadcast domains are now stitched together
across the trunk.

In theory this is one of the few L2 faults the switch reports for you: CDP is
documented to raise `%CDP-4-NATIVE_VLAN_MISMATCH`, and PVST+ to raise
`%SPANTREE-2-RECV_PVID_ERR` and put the port into a PVID-inconsistent blocking
state. Know that for the exam.

> ⚠️ **Verified on IOS-XE 17.16 — do not rely on it.** On this platform the
> mismatch is **not reported at all**. With CDP confirmed running and
> neighbours discovered, and spanning tree in `rapid-pvst` mode, a deliberate
> 99-vs-1 mismatch left `show spanning-tree inconsistentports` at **zero**, the
> log **empty**, and the port **forwarding every VLAN normally** — for minutes.
> The only dependable detection is comparing the `Native vlan` column of
> `show interfaces trunk` on both ends.
>
> The reason nothing appears broken is worth internalising: VLANs 10 and 20 are
> **tagged** in both directions and are completely unaffected. Only the *native*
> VLAN is merged — so **a native VLAN mismatch damages the one VLAN nobody is
> monitoring**, which is precisely what makes it a security finding rather than
> an outage.

**2. It is the basis of the VLAN-hopping attack.** In *double-tagging*, an
attacker on the native VLAN sends a frame with **two** tags. The first switch
strips the outer tag (it matches the native VLAN, so it is removed as normal) and
forwards the frame with the inner tag still attached — delivering it into a VLAN
the attacker was never allowed to reach. The mitigations follow directly from the
mechanism:

- make the native VLAN an **unused VLAN** (the lab uses 99) so no host is ever in
  it,
- never use VLAN 1 for anything,
- or force tagging of the native VLAN with `vlan dot1q tag native`.

**3. Untagged means unmarked.** As above — no tag, no PCP, no CoS.

> The lab therefore sets `switchport trunk native vlan 99` on every trunk, with
> VLAN 99 created but assigned to no port. That is the production-correct pattern,
> and it means the `native-vlan-mismatch` fault has something real to break.

[↩ back to README Lab 3.3](README.md#33-set-a-safe-native-vlan)

---

## The allowed VLAN list

By default a trunk carries **every VLAN it knows about** (1–4094). The **allowed
VLAN list** narrows that to an explicit whitelist:

```
switchport trunk allowed vlan 10,20,99          ← replaces the list entirely
switchport trunk allowed vlan add 30            ← adds to it
switchport trunk allowed vlan remove 20         ← removes from it
switchport trunk allowed vlan except 10         ← everything BUT 10
switchport trunk allowed vlan all               ← back to the default
```

> **The single most destructive typo in switching.** `switchport trunk allowed
> vlan 30` does **not** add VLAN 30 — it *replaces the whole list* with just 30 and
> drops every other VLAN off the trunk instantly. You want `... allowed vlan add
> 30`. People take down production networks with this monthly.

Restricting the list is worth doing — it limits broadcast flooding and shrinks the
spanning-tree topology — but it introduces a failure mode that produces **no log
message and no interface state change**. The VLAN simply stops crossing.

This is why `show interfaces trunk` prints **three separate lists**, and reading
only the first is how people miss the problem:

| Line | Means |
|---|---|
| `Vlans allowed on trunk` | what you **configured** |
| `Vlans allowed and active in management domain` | ...and which of those **exist and are active** in the local VLAN database |
| `Vlans in spanning tree forwarding state and not pruned` | ...and which of *those* are actually **forwarding** |

Each line is a subset of the one above it. **The gap between line 1 and line 2 is a
VLAN-database problem** (missing or suspended). **The gap between line 2 and line 3
is a spanning-tree problem** (blocked port). Learning to read the difference turns
three separate faults into a single ten-second check.

[↩ back to README Lab 3.4](README.md#34-restrict-the-allowed-vlan-list)

---

## DTP: letting switches negotiate trunks

**Dynamic Trunking Protocol** is a Cisco-proprietary protocol that lets two
switches agree to form a trunk instead of being told to. A port's *administrative*
mode is what you configure; its *operational* mode is what it negotiated.

| Administrative mode | Sends DTP? | Behaviour |
|---|---|---|
| `switchport mode access` | no (and refuses) | always access |
| `switchport mode trunk` | yes | always trunk, and asks the other end to trunk too |
| `switchport mode dynamic desirable` | **actively asks** | trunk if the other end will |
| `switchport mode dynamic auto` | **only answers** | trunk only if asked |
| `switchport nonegotiate` | **no** | disables DTP; mode must be set statically on both ends |

The resulting matrix — memorise this, it is directly examinable:

| | access | dynamic auto | dynamic desirable | trunk |
|---|---|---|---|---|
| **access** | access | access | access | ⚠ mismatch |
| **dynamic auto** | access | **access** ← | trunk | trunk |
| **dynamic desirable** | access | trunk | trunk | trunk |
| **trunk** | ⚠ mismatch | trunk | trunk | trunk |

The cell that catches people is **auto + auto = access**. Both switches are willing
to trunk; neither ever asks. The link quietly becomes an access port in VLAN 1 and
every VLAN except VLAN 1 stops crossing it — with both ends configured
*identically*, which is what makes it so counter-intuitive. It is the exact
analogue of [LACP passive/passive](#lacp-pagp-and-static-on), and worth filing in
your head as one idea rather than two.

**Should you use DTP at all? No.** On any link between switches you control, the
production-correct configuration is:

```
switchport mode trunk
switchport nonegotiate
```

Static, deterministic, and it removes an attack surface — an attacker on an access
port that is left at the `dynamic auto`/`desirable` default can negotiate a trunk
with the switch and gain access to every VLAN. Explicitly setting unused access
ports to `switchport mode access` closes that.

[↩ back to README Lab 4](README.md#lab-4--dtp-and-dynamic-trunking)

---

## Why EtherChannel exists

Run three cables between two switches for redundancy and bandwidth, and spanning
tree will **block two of them**. STP's job is to produce a loop-free tree, and
three parallel links are three loops; it does not care that you wanted the
bandwidth. You get redundancy, but you paid for 3 Gb and are using 1 Gb.

You can watch exactly this on the blank slate in README Lab 1 — `show spanning-tree`
on SW2 shows two of its three uplinks in `Altn BLK`.

**EtherChannel solves it by lying to spanning tree.** Bundle the physical links
into one logical **Port-channel** interface and STP sees a *single* port. One port
cannot loop, so nothing is blocked and all three links forward. You get:

- **Bandwidth** — all members carry traffic (subject to
  [hashing](#load-balancing-the-hashing-myth)).
- **Sub-second failover** — losing a member is handled *inside* the bundle. STP is
  never told anything changed, so there is no re-convergence. Compare with losing
  a link STP was actively using: that is a topology change and costs seconds.
- **Configuration simplicity** — configure the Port-channel once instead of
  every member.

The Port-channel is a real interface (`interface Port-channel1`) and is where you
should apply configuration from the moment it exists. IOS propagates the
Port-channel's switchport settings down to its members automatically.

[↩ back to README Lab 5](README.md#lab-5--lacp-etherchannel-sw1--sw2)

---

## LACP, PAgP, and static "on"

Three ways to form a bundle. The mode keywords are the exam's favourite target.

| Protocol | Standard | Modes | Notes |
|---|---|---|---|
| **LACP** | IEEE **802.3ad** | `active`, `passive` | multi-vendor; **use this** |
| **PAgP** | Cisco proprietary | `desirable`, `auto` | Cisco-only |
| **Static** | none | `on` | no negotiation at all |

The behavioural split is the same idea in both protocols:

- **`active` / `desirable`** — *initiates*. Sends negotiation packets asking to
  bundle.
- **`passive` / `auto`** — *responds only*. Will bundle if asked, never asks.

Which combinations form a channel:

| | LACP `active` | LACP `passive` | PAgP `desirable` | PAgP `auto` | `on` |
|---|---|---|---|---|---|
| **LACP `active`** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **LACP `passive`** | ✅ | ❌ ← | ❌ | ❌ | ❌ |
| **PAgP `desirable`** | ❌ | ❌ | ✅ | ✅ | ❌ |
| **PAgP `auto`** | ❌ | ❌ | ✅ | ❌ ← | ❌ |
| **`on`** | ❌ | ❌ | ❌ | ❌ | ✅ |

Three rules fall out of that table:

1. **passive+passive and auto+auto never bundle** — nobody initiates. Same trap as
   DTP auto/auto.
2. **You cannot mix protocols.** PAgP and LACP are mutually unintelligible, and
   the analogous-looking mode names (`desirable` ≈ `active`) tempt people into
   thinking they interoperate. They do not.
3. **`on` only works with `on`.** And mixing `on` with a negotiating mode is the
   most dangerous configuration in this whole topic — see below.

> **Why `mode on` is dangerous.** Static mode bundles unconditionally, with no
> protocol and no confirmation that the far end agrees. If SW1 is `on` and SW2 is
> LACP passive, SW1 starts hashing frames across three links while SW2 treats them
> as three independent ports. SW1's spanning tree sees one logical port and blocks
> nothing; SW2 sees three and blocks two. Any disagreement between the two views
> is a **genuine bridging loop** — and a bridging loop at layer 2 has no TTL to
> save you. Use LACP unless the far end truly cannot negotiate.

**LACP extras** worth knowing: `lacp rate fast` drops the keepalive from 30s to 1s
for faster failure detection; `lacp system-priority` and `lacp port-priority`
decide which ports bundle when more are configured than the platform can use
(the lower value wins), leaving the rest in **hot-standby** `(H)`.

[↩ back to README Lab 5](README.md#lab-5--lacp-etherchannel-sw1--sw2) ·
[Lab 6](README.md#lab-6--pagp-etherchannel-sw1--sw3) ·
[Lab 7](README.md#lab-7--static-mode-on-and-what-must-match)

---

## What must match before a bundle forms

Two separate sets of requirements, and confusing them wastes a lot of
troubleshooting time.

**Across the link (SW1's settings vs SW2's):**
- compatible **protocol and mode** (the table above)
- same **speed** and **duplex**
- same **trunk/access mode**, native VLAN and allowed VLAN list
- **same number of members**, wired to the corresponding ports

**Among the local members (SW1's own ports as a group):**
- identical speed and duplex
- identical switchport mode, native VLAN, allowed VLAN list
- no member with a port-level feature the others lack (SPAN destination, for
  instance, disqualifies a port)

A member that disagrees with its group is **suspended** from the bundle —
flagged `(s)` in `show etherchannel summary` — while the rest carry on. The
channel stays up, at reduced capacity, which is why this needs monitoring rather
than waiting for a ticket.

> ⚠️ **Verified on IOS-XE 17.16 — you cannot easily reproduce this after the fact.**
> Once a port is a member of a Port-channel, IOS keeps its switchport configuration
> **synchronised with the Port-channel**, so changing `switchport trunk allowed
> vlan` on the member alone does not create a lasting divergence. Member mismatch
> is a problem when ports are configured **before** they are bundled, not something
> you can inflict afterwards — which is exactly why the correct build order is
> *configure all members identically, then add `channel-group` last*. The
> `member-config-divergence` fault in `faults.yml` exists to demonstrate this
> no-op deliberately.

The `show etherchannel summary` flags you must be able to read:

| Flag | Meaning | Forwards traffic? |
|---|---|:---:|
| `(P)` | **bundled** in the port-channel — what you want | ✅ |
| `(w)` | **waiting to be aggregated** — negotiation started and got no answer | ❌ |
| `(I)` | stand-alone / individual — negotiation failed, port forwards **alone** | ✅ |
| `(s)` | **suspended** — incompatible configuration | ❌ |
| `(D)` | down | ❌ |
| `(H)` | hot-standby — more members than the platform will bundle | ❌ (until needed) |
| `(SU)` | the channel itself: layer-**2**, in **U**se | — |
| `(SD)` | the channel: layer-2, **down** | — |
| `(RU)` | the channel: layer-**3** (routed), in use | — |

> **The rightmost column is the one that matters, and it is why you must read
> the letter rather than just noting "the channel is down".** A failed bundle
> can fail *closed* (`(w)`, `(s)`) or *open* (`(I)`), and those produce opposite
> symptoms — a total outage versus everything working at reduced bandwidth.
> **Verified on IOS-XE 17.16:** this platform fails **closed** — LACP
> passive/passive yields `(w)`, and `mode on` against a negotiating peer yields
> `(s)` on the peer. Many Catalyst platforms yield `(I)` instead. Do not assume
> which one you are looking at.

[↩ back to README Lab 7](README.md#lab-7--static-mode-on-and-what-must-match)

---

## Load balancing: the hashing myth

**EtherChannel does not load-balance.** It **load-distributes by hashing**, and the
distinction is the source of most "my EtherChannel is broken" tickets that turn
out to be nothing.

For each frame the switch computes a hash over selected header fields and uses the
result to pick a member. The consequences:

- **A single conversation always takes one link.** Two hosts exchanging data over
  a 3×1 Gb channel get 1 Gb, never 3. This is *by design* — it prevents
  out-of-order delivery, which would wreck TCP performance far more than the extra
  bandwidth would help.
- **Distribution is only as good as the entropy in your traffic.** A channel
  hashing on source-destination MAC, carrying traffic that all crosses a router,
  sees one source MAC — so every frame lands on the same member and the other
  links sit idle. Hashing on IP or ports fixes it.
- **Utilisation is rarely even.** Uneven member counters are normal, not a fault.

```
port-channel load-balance src-dst-ip        ← global on most platforms
show etherchannel load-balance              ← what is configured
```

Typical options are `src-mac`, `dst-mac`, `src-dst-mac`, `src-ip`, `dst-ip`,
`src-dst-ip`, and on many platforms `src-dst-port`. **`src-dst-*` is almost always
the right answer** because it varies with both ends of a conversation.

> **Rule of thumb:** pick the hash on the field that *varies most* at that point
> in the network. On an access-to-distribution link, hash on IP. Behind a router
> where every frame shares a MAC, hashing on MAC is useless.
>
> One more: **member counts should be a power of two** (2, 4, 8). The hash result
> is distributed across members in a way that divides evenly only for powers of
> two — with 3 members, some get more buckets than others even with perfect
> traffic entropy. The lab deliberately uses **3** members so you can see that this
> is a real constraint, not folklore.

[↩ back to README Lab 8](README.md#lab-8--load-balancing-and-the-hashing-myth)

---

## Layer 2 vs Layer 3 EtherChannel

Everything above describes a **layer-2** EtherChannel — a bundle of switchports
carrying VLANs, shown as `(SU)`. A **layer-3** EtherChannel bundles *routed* ports
and carries an IP address on the Port-channel itself, shown as `(RU)`.

```
interface Port-channel1
 no switchport                       ← make it a routed interface FIRST
 ip address 10.0.0.1 255.255.255.252
interface range Ethernet0/1 - 3
 no switchport                       ← members must be routed too
 channel-group 1 mode active
```

The rule that catches people: **`no switchport` must be applied to the members and
the Port-channel consistently**, and it wipes any switchport configuration on the
interface as it goes. Layer-3 EtherChannel is what you use between distribution
and core in a routed campus, where there is no VLAN to carry and you want a
routing adjacency over an aggregated link — one OSPF neighbour instead of three.

This lab is entirely layer 2 (there is no router in the topology at all), but
recognising `(RU)` versus `(SU)` in `show etherchannel summary` is examinable.

---

## A troubleshooting method for L2 paths

Nearly every fault in this topic is one of six things. Work **outward from the
frame**, not inward from the diagram:

1. **Is the VLAN real?** `show vlan brief` — does it exist, and does its Status say
   `active` rather than `suspended`?
2. **Is the host in the right VLAN?** `show mac address-table` tells you which VLAN
   the MAC was actually learned in — ground truth, not intent. Then `show
   interfaces <port> switchport` for the configured access VLAN.
3. **Is the link a trunk at all?** `show interfaces trunk`. Remember it lists
   **only ports that are currently trunking** — a broken trunk *vanishes* from the
   output rather than appearing as failed. An empty table is the symptom.
4. **Is the VLAN allowed, active, and forwarding on that trunk?** The
   [three lists](#the-allowed-vlan-list) at the bottom of the same command.
5. **Do both ends agree?** Native VLAN, mode, allowed list, encapsulation. Nearly
   every remaining trunk fault is a disagreement, and half of them are silent.
6. **Is something filtering it?** VACL, port ACL, port security, protected ports,
   storm control. `show vlan filter` and `show port-security` are one-line checks
   and belong in the standard sweep — nothing in the trunk or EtherChannel output
   will ever hint at them.

And the EtherChannel-specific trap that wastes the most time:

> **Never infer EtherChannel health from ping, in either direction.** A failed
> bundle may fail *closed* — members at `(w)` or `(s)`, forwarding nothing, total
> outage — or fail *open* — members at `(I)`, forwarding individually with
> spanning tree blocking all but one, so everything still pings at a third of the
> bandwidth and nobody raises a ticket. **Verified on IOS-XE 17.16: this platform
> fails closed.** Many Catalyst platforms fail open. Read the member flag in
> `show etherchannel summary`; it is the only thing that tells you which.
>
> Conversely, a *healthy* bundle proves nothing about VLAN transport, because
> bundling and trunking are independent. `Po1(SU)` with three `(P)` members tells
> you the link is aggregated, not that VLAN 10 crosses it.

[↩ back to README Lab 9](README.md#lab-9--the-verification-sweep)

---

## EIGRP-style summary: the commands that matter

| Question | Command |
|---|---|
| Does the VLAN exist and is it active? | `show vlan brief` |
| Which VLAN did this host actually land in? | `show mac address-table` |
| Is this port access or trunk, and what did it negotiate? | `show interfaces <if> switchport` |
| Which trunks are up, native VLAN, and the three VLAN lists? | `show interfaces trunk` |
| Are my bundles formed and which members are in? | `show etherchannel summary` |
| Which protocol is each bundle speaking? | `show etherchannel summary` (Protocol column) |
| Is the far end even talking to me? | `show lacp neighbor` / `show pagp neighbor` |
| How are frames distributed across members? | `show etherchannel load-balance` |
| Is spanning tree blocking anything? | `show spanning-tree vlan <n>` |
| Is a native VLAN or PVID mismatch being reported? | `show spanning-tree inconsistentports` |
| Is something filtering traffic inside the VLAN? | `show vlan filter` / `show port-security` |
| Why did that port go down on its own? | `show interfaces status` → `err-disabled`, then `show errdisable recovery` |
