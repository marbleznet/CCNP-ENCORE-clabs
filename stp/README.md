# Spanning Tree Lab — RSTP, MST and the Guards (Cisco IOL + Edgeshark)

A 4-switch + 4-host `cisco_iol` containerlab topology for learning **spanning
tree** properly: electing a root on purpose, reading port roles, converting a
rapid-PVST network to **MST**, load-balancing two VLANs down two different
physical paths, and tripping **every guard** to see what each one actually
protects against.

The switches boot with **only hostnames and interface descriptions** — no VLANs,
no trunks, no STP tuning, no guards. Every port is a default access port in VLAN
1 running the default rapid-PVST, and there are **two physical loops** waiting
for spanning tree to resolve.

By the end you will have configured and observed:

- Why a layer-2 loop is categorically worse than a layer-3 one (**Ethernet has no
  TTL**) and what STP gives up to prevent it
- **Root bridge election**, why an unconfigured network picks the wrong switch,
  and how to place the root and a predictable secondary
- **RSTP port roles and states** — Root, Designated, **Alternate**, and the
  role/state distinction that makes `show spanning-tree` readable
- **Path cost** and the long/short scale trap
- **MST** — regions, the configuration **digest**, instances, IST vs CIST, and
  what a **boundary** collapses
- **Per-instance load balancing** — VLAN 10 over one uplink, VLAN 20 over the
  other, from the same physical topology
- **PortFast, BPDU guard, BPDU filter, root guard, loop guard** — including the
  one case where loop guard converts a broadcast storm into a mere outage
- Why **root guard points down and loop guard points up**, and what breaks when
  you swap them

> 📖 **This lab has a companion:** [`CONCEPTS.md`](CONCEPTS.md) is the in-depth
> reference behind every step (the BPDU and Bridge ID, the three port decisions,
> RSTP's proposal/agreement, MST regions and max-hops, all five guards, and a
> troubleshooting method). Each lab opens with a **Deep dive** callout — follow
> them for the *why*, skip them when you just want to type. It also reads well
> end-to-end as a spanning-tree primer.

> **Build [`../l2-trunk-etherchannel/`](../l2-trunk-etherchannel/) first** if you
> haven't. This lab assumes you can already configure a trunk and read
> `show interfaces trunk`, and it uses trunks on every inter-switch link — BPDUs
> have to get across them before any of this works.

---

## Topology

```
     host-b VLAN10 .12                    host-d VLAN20 .14
              \                            /
            E0/3                        E1/0
              +----------------------------+
              |            SW1             |   IST(MST0) + MSTI1 ROOT
              +----------------------------+     priority 4096
                E0/1                  E0/2
                  |                     |
                  |     LOOP 1          |
                E0/1                  E0/1
          +-----------+  E0/2   E0/2 +-----------+
          |    SW2    |--------------|    SW3    |   MSTI2 ROOT
          +-----------+              +-----------+     priority 4096
           IST backup                      |
             8192                          |
                E0/3     LOOP 2         E0/3
                  |                     |
                  |   [root guard]      |   [root guard]
                E0/1                  E0/2
              +----------------------------+
              |            SW4             |   access, never root
              +----------------------------+   [loop guard on both uplinks]
            E0/3                        E1/0
              /                            \
     host-a VLAN10 .11                    host-c VLAN20 .13
```

**Two loops on purpose.** Loop 1 is the distribution triangle (SW1–SW2–SW3);
loop 2 is SW4's dual uplinks. Two loops mean spanning tree has real work to do
*and* — crucially — that the two MST instances can compute **different trees**.

**The key fact to memorise about the healthy state:**

| Instance | VLAN | Root | SW4 reaches it via |
|---|---|---|---|
| **MSTI 1** | 10 | **SW1** | `E0/1` → SW2 (`E0/2` is Alternate) |
| **MSTI 2** | 20 | **SW3** | `E0/2` → SW3 (`E0/1` is Alternate) |

SW4 uses **both** uplinks — one per VLAN — instead of leaving one idle. That is
MST load balancing, and **most faults in this lab show up as that split
collapsing onto a single uplink**, not as an outage.

### Roles

| Node | Role | STP config |
|---|---|---|
| **SW1** | distribution | `mst 0-1 priority 4096` (IST + MSTI1 root), `mst 2 priority 8192` (MSTI2 backup) |
| **SW2** | distribution | `mst 0-1 priority 8192` (IST backup) · **root guard** on E0/3 |
| **SW3** | distribution | `mst 2 priority 4096` (MSTI2 root) · **root guard** on E0/3 |
| **SW4** | access | *no priority anywhere* · **loop guard** on E0/1 and E0/2 |

### VLANs and addressing

| VLAN | Name | MST instance | Hosts |
|---|---|---|---|
| **10** | `USERS` | **MSTI 1** (root SW1) | host-a (SW4 E0/3), host-b (SW1 E0/3) |
| **20** | `SERVERS` | **MSTI 2** (root SW3) | host-c (SW4 E1/0), host-d (SW1 E1/0) |
| **99** | `NATIVE-UNUSED` | IST (0) | *none — native VLAN on every trunk* |

| Host | Address | VLAN | On | Pings |
|---|---|---|---|---|
| host-a | `10.10.10.11/24` | 10 | SW4 `E0/3` | host-b ✅ |
| host-b | `10.10.10.12/24` | 10 | SW1 `E0/3` | host-a ✅ |
| host-c | `10.10.20.13/24` | 20 | SW4 `E1/0` | host-d ✅ |
| host-d | `10.10.20.14/24` | 20 | SW1 `E1/0` | host-c ✅ |

Each pair spans the topology (one behind SW4, one behind SW1), so a ping actually
traverses the spanning tree rather than staying on one switch. **Cross-VLAN
pings fail by design** — there is no router or SVI anywhere in this lab.

Interface mapping: `eth1`→`Ethernet0/1`, `eth2`→`Ethernet0/2`,
`eth3`→`Ethernet0/3`, `eth4`→`Ethernet1/0`. `E0/0` is management.

---

## Deploy

```bash
containerlab deploy -t stp-lab.clab.yml
ssh admin@clab-stp-lab-sw1          # admin / admin
```

Give the nodes ~60–90s. Destroy with:

```bash
containerlab destroy -t stp-lab.clab.yml --cleanup
```

### Sanity check before you start

```
sw1# show spanning-tree summary | include mode    ! "rapid-pvst" -- the default
sw1# show vlan brief                              ! VLAN 1 only
sw1# show interfaces trunk                        ! EMPTY -- nothing is trunking
sw4# show spanning-tree vlan 1                    ! a loop already resolved, see Lab 1
```

### Platform quirks worth knowing before you start

> **1. `show spanning-tree` alone shows the CIST (instance 0) only.** Once you
> are in MST, VLAN 10 lives in MSTI 1 and VLAN 20 in MSTI 2, and **neither is
> visible** in the bare command. Always name the instance:
> `show spanning-tree mst 1`. More time is wasted on this than on any other
> single thing in this topic.
>
> **2. Port cost here is 2000000, not 100.** These IOL interfaces are 10 Mb and
> MST operates the **long** path-cost method — `show spanning-tree summary` even
> says `Configured Pathcost method used is short (Operational value is long)`. If
> you set a cost expecting the classic 19/100 scale, nothing will happen.
> *(Verified on IOS-XE 17.16.)*
>
> **3. IOL reports ports with no cable as `connected`.** Never infer topology
> from `show interfaces status`; use `show cdp neighbors`.
>
> **4. A tripped guard is not "down".** It shows as `BKN` with `*ROOT_Inc` or
> `*LOOP_Inc` in the **Type** column of `show spanning-tree`, and looks entirely
> normal in `show interfaces`. `show spanning-tree inconsistentports` is the
> direct check.

---

## Using Edgeshark for captures

> **New here?** Edgeshark is **optional** — see the
> [repo README](../README.md#prerequisites). Every step works with `show`
> commands alone.

> ⚠️ **Interfaces are named `eth1`…`eth4`, not `Ethernet0/1`.** Edgeshark shows
> the *container's* Linux interfaces. To capture SW4's uplink to SW3
> (IOL `Ethernet0/2`), pick **`eth2`** on `clab-stp-lab-sw4`.

Spanning tree is one of the most satisfying protocols to watch, because the BPDU
contains the entire election in plain sight:

| Filter | Shows |
|---|---|
| `stp` | all BPDUs |
| `stp.type == 0x02` | RSTP/MST BPDUs (`0x00` = legacy config BPDU) |
| `stp.flags.tc == 1` | **topology change** flag set |
| `stp.root.hw` | filter/inspect the advertised **root** bridge address |
| `mstp` | MST-specific fields (region name, revision, digest, MSTI records) |
| `eth.dst == 01:80:c2:00:00:00` | the STP destination multicast |
| `eth.dst == 01:00:0c:cc:cc:cd` | **PVST+** per-VLAN BPDUs (Cisco's SSTP address) |

What to look for inside a BPDU: **Root Identifier** (priority + MAC),
**Root Path Cost**, **Bridge Identifier** (the sender), **Port identifier**, and
the **flags** byte carrying the Proposal/Agreement bits and the TC flag. In an
MST BPDU, expand the **MST Extension** to see the **region name, revision and
configuration digest** — the three things that must match, right there on the
wire.

> 📖 **Deep dive:** [The BPDU and the Bridge ID](CONCEPTS.md#the-bpdu-and-the-bridge-id)

> Tip: BPDUs are every 2 seconds, so captures fill fast. Start the capture,
> make the change, and filter on `stp.flags.tc == 1` to find the moment the
> topology actually moved.

---

# Lab 1 — See the loop, and watch STP resolve it

**Goal:** before configuring anything, confirm there are two physical loops and
find which ports spanning tree has already blocked to break them.

> 📖 **Deep dive:** [Why spanning tree exists](CONCEPTS.md#why-spanning-tree-exists)

### 1.1 Find the blocked ports

```
sw4# show spanning-tree vlan 1
```

Everything is in VLAN 1 on the blank slate, so one tree covers the whole lab. On
SW4 you should see one uplink `Root FWD` and the other `Altn BLK`:

```
Et0/1               Root FWD 2000000   128.2    P2p
Et0/2               Altn BLK 2000000   128.3    P2p
```

Check SW3 too — it will also have an Alternate port, because the distribution
triangle is a loop as well.

**Spanning tree has already done its job.** Nobody configured it; it ran by
default, elected a root, and blocked exactly enough ports to leave a tree.

### 1.2 Understand what you gave up

Count it: of the five inter-switch links, **two are carrying nothing**. That is
the price of loop freedom, and everything later in this lab is about buying some
of it back — [MST instances](CONCEPTS.md#mst-regions-instances-ist-and-cist) let
different VLANs use different blocked links, and
[EtherChannel](../l2-trunk-etherchannel/README.md) makes several links look like
one.

### 1.3 See who won the root election — and why that is a problem

```
sw1# show spanning-tree vlan 1 | include Root ID|This bridge
sw4# show spanning-tree vlan 1 | include Root ID|This bridge
```

Whichever switch is root, it won on **lowest MAC address**, because every
priority is the default 32768. Nobody chose it.

> **This is the single most common real-world STP misconfiguration**, and it is
> invisible: the network works, nothing is logged, every host pings. It just
> routes all your layer-2 traffic through whichever switch happens to be oldest.
> Lab 2 fixes it.

> **📸 CAPTURE — `sw4` interface `eth1`.** Filter `stp`. Open a BPDU and read the
> **Root Identifier** — that is the election result, advertised every 2 seconds.
> Note the destination MAC `01:80:c2:00:00:00`. It is tempting to assume a **MAC
> ACL** could filter these — *verified on IOS-XE 17.16, it cannot*: BPDUs are
> punted to the control plane and are not subject to port ACLs. See
> [CONCEPTS](CONCEPTS.md#the-bpdu-and-the-bridge-id).

---

# Lab 2 — Control the root bridge

**Goal:** stop leaving the most important switch in your layer-2 topology to a
MAC address lottery.

> 📖 **Deep dive:** [Electing a root bridge](CONCEPTS.md#electing-a-root-bridge)
> · [The BPDU and the Bridge ID](CONCEPTS.md#the-bpdu-and-the-bridge-id)

### 2.1 First build the VLANs and trunks

Spanning tree needs the trunks before any of the per-VLAN work makes sense. On
**all four** switches:

```
sw1(config)# vtp mode transparent
sw1(config)# vlan 10
sw1(config-vlan)#  name USERS
sw1(config-vlan)# vlan 20
sw1(config-vlan)#  name SERVERS
sw1(config-vlan)# vlan 99
sw1(config-vlan)#  name NATIVE-UNUSED
sw1(config-vlan)# exit
```

Then trunk every inter-switch link — SW1 `E0/1-2`, SW2 `E0/1-3`, SW3 `E0/1-3`,
SW4 `E0/1-2`:

```
sw1(config)# interface range Ethernet0/1 - 2
sw1(config-if-range)#  switchport trunk encapsulation dot1q
sw1(config-if-range)#  switchport mode trunk
sw1(config-if-range)#  switchport trunk native vlan 99
sw1(config-if-range)#  switchport trunk allowed vlan 10,20,99
```

And the access ports (SW1 `E0/3`=VLAN 10, `E1/0`=VLAN 20; SW4 `E0/3`=VLAN 10,
`E1/0`=VLAN 20):

```
sw1(config)# interface Ethernet0/3
sw1(config-if)#  switchport mode access
sw1(config-if)#  switchport access vlan 10
sw1(config-if)#  spanning-tree portfast
sw1(config-if)#  spanning-tree bpduguard enable
```

> **PortFast and BPDU guard go on together, always.** PortFast asserts "this port
> faces a host, skip the delay"; BPDU guard enforces that assertion by shutting
> the port down if a BPDU ever arrives. PortFast without BPDU guard on a port
> that turns out to face a switch is a transient loop waiting to happen.

### 2.2 Place the root deliberately

```
sw1(config)# spanning-tree vlan 1,10,20 priority 4096
sw2(config)# spanning-tree vlan 1,10,20 priority 8192
```

```
sw1# show spanning-tree vlan 10 | include Root ID|This bridge
```

SW1 is now root for every VLAN, and SW2 will take over predictably if it fails.

> **Priority moves in steps of 4096** because the low 12 bits of the priority
> field carry the VLAN or instance number (the *extended system ID*). `priority
> 5000` is rejected. And the value you see in `show` output is
> `priority + VLAN` — 4106 for VLAN 10 at 4096, not 4096.

### 2.3 Watch the tree move

> **📸 CAPTURE — `sw4` interface `eth1`** *before* the priority command. Filter
> `stp`. Watch the **Root Identifier** in the BPDUs change to SW1's address, and
> look for BPDUs with the **topology change flag** set (`stp.flags.tc == 1`)
> during the re-convergence.

```
sw4# show spanning-tree vlan 10        ! root is now SW1; port roles may have moved
```

---

# Lab 3 — Read the tree: roles, states, and what changed

**Goal:** build the habit of reading `show spanning-tree` properly, because every
remaining lab and every fault depends on it.

> 📖 **Deep dive:** [Port roles and states in RSTP](CONCEPTS.md#port-roles-and-states-in-rstp)
> · [How RSTP actually converges fast](CONCEPTS.md#how-rstp-actually-converges-fast)
> · [Choosing ports: the three decisions](CONCEPTS.md#choosing-ports-the-three-decisions)

```
sw4# show spanning-tree vlan 10
```

Read the columns as **two separate questions**:

| Column | Question it answers |
|---|---|
| **Role** | what job this port has: `Root`, `Desg`, `Altn`, `Back` |
| **Sts** | what it is doing with frames: `FWD`, `BLK`, `LRN` |
| **Cost** | this port's contribution to the root path cost |
| **Type** | `P2p`, `P2p Edge` (PortFast), `Shared`, or a `*_Inc` guard flag |

- **Root** — exactly one per switch (none on the root bridge itself)
- **Desg** — the best path to the root *for that segment*; every port on the root
  bridge is designated
- **Altn** — a backup for the **root port**; this is what "blocking" usually is
- `P2p Edge` confirms PortFast took effect on your access ports

> **Role and state are not the same question**, and the exam tests the
> difference. A tripped guard shows as `Desg BKN` — designated *role*, broken
> *state*. A normal blocked link shows `Altn BLK`.

### 3.1 Prove RSTP is fast

```
sw4(config)# interface Ethernet0/1
sw4(config-if)# shutdown
```
```
sw4# show spanning-tree vlan 10        ! Et0/2 takes over in a couple of seconds
```

The Alternate port becomes Root almost immediately — no 30-second wait. That is
RSTP's **proposal/agreement** handshake replacing 802.1D's timers. Undo it:

```
sw4(config-if)# no shutdown
```

---

# Lab 4 — Steer the tree with cost and priority

**Goal:** move traffic deliberately, and learn which end of a link to configure.

> 📖 **Deep dive:** [Path cost and the long/short trap](CONCEPTS.md#path-cost-and-the-longshort-trap)
> · [Choosing ports: the three decisions](CONCEPTS.md#choosing-ports-the-three-decisions)

```
sw4# show spanning-tree vlan 10 | include Cost
```

> ⚠️ **The cost is 2000000, not 100.** These are 10 Mb IOL interfaces and MST/RSTP
> here operates the **long** path-cost method. Any cost you set must be well
> above 2000000 to change anything. *(Verified on IOS-XE 17.16 — if you set
> `cost 500` expecting the classic scale, nothing will happen and you will think
> the command is broken.)*

```
sw4(config)# interface Ethernet0/1
sw4(config-if)#  spanning-tree vlan 10 cost 20000000
```

```
sw4# show spanning-tree vlan 10        ! root port has moved to Et0/2
```

> **Cost is evaluated by the RECEIVING switch on its OWN port.** SW4 chose its
> root port using the cost of SW4's ports. Setting a cost on SW2's `E0/3` would
> change how **SW2** computes its tree, not how SW4 picks its uplink. Getting the
> end wrong is the usual reason a cost change "does nothing" — the same
> directionality trap as OSPF cost.

Remove it before moving on:

```
sw4(config-if)# no spanning-tree vlan 10 cost
```

> **Port priority** (`spanning-tree vlan 10 port-priority 64`) only ever breaks a
> tie between **two links to the same neighbour**. If the costs or the neighbours
> differ, it is never consulted. It is the tool for parallel links, not for
> general path steering.

---

# Lab 5 — Convert to MST

**Goal:** replace one-tree-per-VLAN with one-tree-per-instance, and build a
region.

> 📖 **Deep dive:** [The three flavours: PVST+, rapid-PVST, MST](CONCEPTS.md#the-three-flavours-pvst-rapid-pvst-mst)
> · [MST regions, instances, IST and CIST](CONCEPTS.md#mst-regions-instances-ist-and-cist)

### 5.1 Why bother

With two VLANs, rapid-PVST runs two trees. With 500 VLANs it runs **500** — 500
sets of BPDUs and 500 topology computations, for trees that are almost certainly
identical. MST decouples *how many trees you run* from *how many VLANs you have*:
map many VLANs into a few instances and run one tree each.

### 5.2 Build the region — identically on all four switches

```
sw1(config)# spanning-tree mode mst
sw1(config)# spanning-tree mst configuration
sw1(config-mst)#  name ENCOR
sw1(config-mst)#  revision 1
sw1(config-mst)#  instance 1 vlan 10
sw1(config-mst)#  instance 2 vlan 20
sw1(config-mst)# exit
```

**Paste that same block on SW2, SW3 and SW4, byte for byte.**

> **A region is defined by three things that must match EXACTLY:** the **name**,
> the **revision number**, and the **complete VLAN-to-instance map**. Those are
> hashed into a 16-byte **configuration digest** carried in every BPDU, and
> neighbours compare *the digest*, never the config. So a one-digit revision typo
> has precisely the same effect as mapping every VLAN differently — the switch
> silently drops out of the region.

### 5.3 Verify the region before anything else

```
sw1# show spanning-tree mst configuration digest
```

```
Name      [ENCOR]
Revision  1     Instances configured 3
Digest    0x9357EBB7A8D74DD5FEF4F2BAB50531AA
```

**Run this on all four and compare the digest.** Same digest = same region.
Different digest = a boundary, no matter how identical the configs look to the
eye. This is the single most valuable MST verification command.

### 5.4 Note where the unmapped VLANs went

```
sw1# show spanning-tree mst configuration
```

```
Instance  Vlans mapped
--------  -------------------------------
0         1-9,11-19,21-4094
1         10
2         20
```

**Everything you did not map is in instance 0**, the IST. Forget to map a VLAN
and it silently follows the IST's tree instead of the one you designed for it —
a quiet and common design bug.

---

# Lab 6 — MST load balancing with two instances

**Goal:** the payoff. Send VLAN 10 and VLAN 20 down **different physical paths**
so both of SW4's uplinks carry traffic.

> 📖 **Deep dive:** [MST regions, instances, IST and CIST](CONCEPTS.md#mst-regions-instances-ist-and-cist)

### 6.1 Root each instance somewhere different

```
sw1(config)# spanning-tree mst 0-1 priority 4096      ! IST + MSTI1 root
sw1(config)# spanning-tree mst 2 priority 8192        ! MSTI2 BACKUP
sw2(config)# spanning-tree mst 0-1 priority 8192      ! IST + MSTI1 backup
sw3(config)# spanning-tree mst 2 priority 4096        ! MSTI2 root
```

SW4 gets **no priority at all** — it must never be root.

### 6.2 See the two trees diverge

```
sw4# show spanning-tree mst 1
sw4# show spanning-tree mst 2
```

```
MST1:  Et0/1  Root FWD      Et0/2  Altn BLK
MST2:  Et0/1  Altn BLK      Et0/2  Root FWD
```

**Both uplinks are now carrying traffic** — VLAN 10 via SW2, VLAN 20 via SW3 —
from exactly the same physical topology that previously left one idle. That is
the entire argument for MST, and it is the fact to memorise: most faults in this
lab show up as this split **collapsing onto one uplink**.

```bash
docker exec clab-stp-lab-host-a ping -c2 10.10.10.12    # VLAN 10, via SW2
docker exec clab-stp-lab-host-c ping -c2 10.10.20.14    # VLAN 20, via SW3
```

> **📸 CAPTURE — `sw4` interface `eth2`.** Filter `mstp`. Expand the **MST
> Extension**: you can read the **region name**, **revision**, **configuration
> digest** and the per-**MSTI** records with their own root and cost, all in one
> BPDU. Seeing the digest on the wire makes the region-mismatch faults obvious in
> retrospect.

---

# Lab 7 — Trip every guard

**Goal:** configure all five protections and deliberately fire each one, because
knowing what a tripped guard *looks like* is most of diagnosing it.

> 📖 **Deep dive:** [The guards, and which direction each points](CONCEPTS.md#the-guards-and-which-direction-each-points)
> · [MST boundaries and max-hops](CONCEPTS.md#mst-boundaries-and-max-hops)

### 7.1 The direction rule

> **Root guard points DOWN. Loop guard points UP.**
>
> - **Root guard** on ports facing **away** from the root (downlinks). Reacts to
>   a **superior BPDU arriving** → `*ROOT_Inc`.
> - **Loop guard** on **root and alternate** ports facing **toward** the root.
>   Reacts to BPDUs **disappearing** → `*LOOP_Inc`.
>
> BPDU guard and loop guard are **opposite bets**: one blocks when BPDUs appear
> where none should be, the other when they vanish from where they should be.

```
sw2(config)# interface Ethernet0/3
sw2(config-if)#  spanning-tree guard root
sw3(config)# interface Ethernet0/3
sw3(config-if)#  spanning-tree guard root
sw4(config)# interface range Ethernet0/1 - 2
sw4(config-if-range)#  spanning-tree guard loop
```

> ⚠️ **A port holds exactly ONE guard.** `spanning-tree guard` is a single
> setting with three values — `root`, `loop`, `none` — not two independent
> toggles. **Verified on IOS-XE 17.16:** applying `guard root` to a port that
> already had `guard loop` **silently replaces it**, and `no spanning-tree guard
> root` then leaves the port with **no guard at all** rather than restoring the
> loop guard. Adding root guard to a port that was relying on loop guard removes
> the protection you thought you had, with no warning. Verify with
> `show run interface <if> | include guard` — not from memory.

### 7.2 Fire root guard

Make SW4 claim the MSTI1 root:

```
sw4(config)# spanning-tree mst 1 priority 0
```

```
sw2# show spanning-tree inconsistentports
sw3# show spanning-tree mst 1 | include Et0/3
```

```
Et0/3     Desg BKN  ...  *ROOT_Inc
```

Both downlinks block, SW4 is cut off for VLAN 10, and **VLAN 20 keeps working**.

> **Verified on IOS-XE 17.16: the guard acts PER INSTANCE.** SW4 only advertised
> a superior BPDU for MSTI1, so only MSTI1 goes root-inconsistent — MSTI2 keeps
> forwarding over the very same physical port. A port is not simply "blocked"; it
> is blocked *for one instance*. Check both before concluding a guard did
> nothing.

```
sw4(config)# no spanning-tree mst 1 priority 0
```

Root-inconsistent is **self-clearing** — the ports recover on their own in a few
tens of seconds. No bounce needed.

### 7.3 Fire BPDU guard (and meet a latched state)

Put an access-port template on an uplink:

```
sw3(config)# interface Ethernet0/3
sw3(config-if)#  spanning-tree portfast trunk
sw3(config-if)#  spanning-tree bpduguard enable
```

> ⚠️ **It must be `portfast trunk` here, and the reason is worth a minute.**
> Plain `spanning-tree portfast` on a **trunk** port does nothing: IOS accepts
> it, prints a warning that is easy to scroll past — *"Portfast has been
> configured on Ethernet0/3 but will only have effect when the interface is in a
> non-trunking mode"* — and `show spanning-tree interface Ethernet0/3 portfast`
> then reports `disabled` for every instance. **Verified on IOS-XE 17.16: BPDU
> guard did not fire either**, even with `spanning-tree bpduguard enable` on the
> interface and BPDUs arriving every two seconds, because on this platform the
> interface-level guard only acts where PortFast is *operational*.
>
> **A command that is accepted is not necessarily a command that is in effect.**
> `show spanning-tree interface <if> portfast` is how you tell the difference.

Within ~2 seconds:

```
sw3# show interfaces status | include err-disabled
```

> ⚠️ **err-disable is LATCHED.** Removing PortFast and BPDU guard does **not**
> bring the port back — nothing re-evaluates it. You must bounce the interface,
> or configure recovery in advance:
> ```
> errdisable recovery cause bpduguard
> errdisable recovery interval 300
> ```
> Contrast with root/loop-inconsistent, which clear themselves. **Removing a
> cause does not undo an effect.**

```
sw3(config-if)# no spanning-tree bpduguard enable
sw3(config-if)# no spanning-tree portfast trunk
sw3(config-if)# shutdown
sw3(config-if)# no shutdown
```

### 7.4 Fire loop guard — and see it prevent a storm

The most instructive experiment in this lab. Shrink the region's hop budget so
SW4 stops hearing the root at all:

```
sw1(config)# spanning-tree mst max-hops 1
```

SW2 and SW3 are one hop from the root and still hear it. SW4 is **two** hops, so
its BPDUs expire in transit. Wait ~30s:

```
sw4# show spanning-tree mst 0 | include Root
sw4# show spanning-tree mst 1
```

```
Root  this switch for the CIST                 <-- SW4 thinks IT is the root
Et0/1   Desg BKN  ...  *LOOP_Inc
Et0/2   Desg BKN  ...  *LOOP_Inc
```

**That should have been a broadcast storm.** A switch that believes it is root
sets every port Designated/Forwarding — and SW4 forwarding on *both* uplinks
bridges SW2 to SW3 through it, closing a real layer-2 loop with no TTL to contain
it. Instead, loop guard saw two non-designated ports stop receiving BPDUs, its
exact trigger, and blocked them.

> **Verified on IOS-XE 17.16: no storm occurred, connectivity to SW4 simply
> failed, and the lab stayed stable.** Loop guard converted a broadcast storm
> into an outage. An outage is enormously preferable — that is the entire value
> proposition, and it is why loop guard belongs on every root and alternate port.

```
sw1(config)# spanning-tree mst max-hops 20
```

### 7.5 BPDU filter — the dangerous one

```
sw2(config)# interface Ethernet0/3
sw2(config-if)#  spanning-tree bpdufilter enable
```

SW4's `E0/1` stops receiving BPDUs and loop guard blocks it. Without loop guard,
that port would have aged out its stored BPDU and started **forwarding** — into a
loop.

> **Interface-level and global BPDU filter behave very differently.** Globally
> (`spanning-tree portfast bpdufilter default`) it applies only to PortFast ports
> and **stops filtering the moment a BPDU arrives** — a reasonably safe "don't
> leak BPDUs to hosts" setting. On an **interface** it unconditionally kills
> BPDUs in both directions while the port keeps forwarding data. That is a loop
> generator.

```
sw2(config-if)# no spanning-tree bpdufilter enable
```

---

# Lab 8 — The verification sweep

**Goal:** the seven commands that localise almost any STP fault, in order.

> 📖 **Deep dive:** [A troubleshooting method for spanning tree](CONCEPTS.md#a-troubleshooting-method-for-spanning-tree)

| # | Question | Command |
|---|---|---|
| 1 | **Which instance am I looking at?** | `show spanning-tree mst 1` — *not* bare `show spanning-tree` |
| 2 | Who is root, and who should be? | `show spanning-tree mst <n>` on several switches |
| 3 | Has any guard tripped? | `show spanning-tree inconsistentports` |
| 4 | Did a port disable itself? | `show interfaces status \| include err-disabled` |
| 5 | Is the MST region intact? | `show spanning-tree mst configuration digest` |
| 6 | Are all switches in the same mode? | `show spanning-tree summary \| include mode` |
| 7 | Is something **filtering traffic**? | `show run interface <if>` (bpdufilter), **`show vlan filter`** (VACL) |

Two habits that separate fast diagnosis from slow:

> **Read roles, not reachability.** Most STP faults **reroute** rather than
> disconnect — the topology becomes wrong while every ping still succeeds. Ping
> is close to useless as an STP test.
>
> **The switch reporting the error is usually not the switch with the
> misconfiguration.** Loop guard trips on the switch that stopped *receiving*
> BPDUs; the cause — a BPDU filter, a MAC ACL, a failing fibre — is at the far
> end. Look across the link before touching the switch that is complaining.

---

## Suggested end-state verification

```
sw1# show spanning-tree mst 0 | include Root      ! "this switch for the CIST"
sw3# show spanning-tree mst 2                     ! SW3 is MSTI2 root, all Desg
sw4# show spanning-tree mst 1                     ! Et0/1 Root FWD, Et0/2 Altn BLK
sw4# show spanning-tree mst 2                     ! Et0/1 Altn BLK, Et0/2 Root FWD
any# show spanning-tree inconsistentports          ! ZERO ports
any# show spanning-tree mst configuration digest   ! identical on all four
```

```bash
docker exec clab-stp-lab-host-a ping -c2 10.10.10.12   # VLAN 10 — must succeed
docker exec clab-stp-lab-host-c ping -c2 10.10.20.14   # VLAN 20 — must succeed
docker exec clab-stp-lab-host-a ping -c2 10.10.20.14   # cross-VLAN — must FAIL
```

## Command cheat-sheet

| Task | Command |
|---|---|
| Set STP mode | `spanning-tree mode mst \| rapid-pvst` |
| Build a region | `spanning-tree mst configuration` → `name` / `revision` / `instance N vlan X` |
| **Verify a region** | `show spanning-tree mst configuration digest` |
| Set the root | `spanning-tree mst <n> priority 4096` (steps of 4096) |
| Per-VLAN root (PVST) | `spanning-tree vlan <n> priority 4096` |
| Steer a path | `spanning-tree mst <n> cost <c>` — on the **receiving** switch |
| Break a tie to one neighbour | `spanning-tree mst <n> port-priority <p>` |
| Region diameter | `spanning-tree mst max-hops <n>` (default 20) |
| Edge port | `spanning-tree portfast` + `spanning-tree bpduguard enable` |
| Protect root placement | `spanning-tree guard root` (**downlinks**) |
| Protect against BPDU loss | `spanning-tree guard loop` (**uplinks**) |
| Find tripped guards | `show spanning-tree inconsistentports` |
| Recover a latched err-disable | `shutdown`/`no shutdown`, or `errdisable recovery cause bpduguard` |
| Long path costs | `spanning-tree pathcost method long` |

---

## Reset the whole lab

```bash
containerlab destroy -t stp-lab.clab.yml --cleanup
containerlab deploy  -t stp-lab.clab.yml
```

The startup configs contain **no VLANs, trunks, STP tuning or guards**, so every
redeploy returns you to rapid-PVST with two unresolved loops.

---

## Where this fits

| Topic | Covered by |
|---|---|
| **3.1.c** Configure and verify common Spanning Tree Protocols (RSTP, MST) | Labs 1–6 |
| **3.1.c** Spanning Tree enhancements such as root guard and BPDU guard | Lab 7 + 6 guard faults |

**Previous:** [`../l2-trunk-etherchannel/`](../l2-trunk-etherchannel/) — 3.1.a
trunking and 3.1.b EtherChannel. Trunks carry the BPDUs this lab depends on, and
an EtherChannel is how you stop STP blocking your uplinks in the first place.

**Next:** `../ospf/` — 3.2.b OSPFv2/v3 and 3.2.a the EIGRP-vs-OSPF comparison.
Layer 2 is done; everything after this is layer 3.

---

# Break/fix practice — the part that actually matches the exam

Building the tree (Labs 1–8) is how you *learn* spanning tree. The blueprint says
**"Configure and verify"** for 3.1.c, but every STP problem you will ever meet in
production arrives as a symptom, not a config. Once you can build this lab, the
higher-value drill is diagnosing it **broken**.

```bash
containerlab deploy -t stp-lab.clab.yml
cd ..                              # repo root
./tools/labctl.py stp baseline     # push the working end-state
./tools/labctl.py stp break        # inject one random fault
#   ...diagnose using only show commands...
./tools/labctl.py stp hint
./tools/labctl.py stp reveal
./tools/labctl.py stp fix
```

```bash
./tools/labctl.py stp list
./tools/labctl.py stp break --difficulty hard
./tools/labctl.py stp break --id vacl-drops-vlan20
./tools/labctl.py stp run "show spanning-tree inconsistentports" -n sw4
```

### The 13 faults

| Fault | Topic | Diff | What you'll chase |
|---|---|---|---|
| `root-priority-cleared` | 3.1.c | easy | root moved; **nothing is broken** |
| `msti2-root-lost` | 3.1.c | easy | load balancing quietly gone |
| `root-hijack-blocked-by-rootguard` | 3.1.c | med | one VLAN down, guard did its job |
| `rootguard-disabled-then-hijack` | 3.1.c | hard | **no error anywhere** — the access switch is root |
| `rootguard-on-uplink-port` | 3.1.c | hard | right guard, wrong direction |
| `mst-revision-mismatch` | 3.1.c | hard | one digit → a boundary |
| `vlan20-remapped-to-msti1` | 3.1.c | med | region consistent, design wrong |
| `mst-cost-manipulation` | 3.1.c | med | one instance reroutes, the other doesn't |
| `mst-max-hops-too-low` | 3.1.c | med | SW4 elects itself; loop guard saves you |
| `stp-mode-mismatch` | 3.1.c | med | one global line invalidates every comparison |
| `bpduguard-on-uplink` | 3.1.c | med | err-disable; `fix` is *not* a pure inverse |
| `loopguard-triggered-by-bpdufilter` | 3.1.c | hard | the error is on the *other* switch |
| `vacl-drops-vlan20` | 5.2.a | hard | every STP check passes, traffic still dies |

### How to get value from it

1. **Always name the instance.** `show spanning-tree` alone shows the CIST and
   hides most of these faults entirely. This is the number-one time-waster.
2. **Compare against the intended design, not against "does anything look
   odd".** Two faults here (`root-priority-cleared`,
   `rootguard-disabled-then-hijack`) produce a perfectly healthy-looking network
   that is simply the wrong shape. You cannot find them without knowing what
   right looks like — memorise the table at the top of this README.
3. **Don't trust ping.** Most of these reroute rather than disconnect.
4. **When a guard trips, look at the far end.** The switch showing `*LOOP_Inc` is
   the victim, not the culprit.
5. **Be patient** — allow ~45s. Guard recovery after a fix can take ~35s, and the
   BPDU-starvation faults need a full max-age before the port reacts.

> **All 13 faults were injected against a live lab on IOS-XE 17.16 by a scripted
> harness** that checked the specific per-instance port role, guard state or root
> identity each one claims to change, then reverted it and confirmed the lab
> returned to the healthy baseline above. All 13 revert cleanly. **Four needed
> correcting**, and every correction is a better lesson than the fault it came
> from:
>
> - **One fault silently sabotaged three others.** `rootguard-on-uplink-port`
>   originally reverted with `no spanning-tree guard root` — the obvious inverse.
>   But a port holds exactly **one** guard, so `guard root` had *replaced* the
>   baseline's `guard loop`, and negating it left the uplink with **no guard at
>   all**. Three later faults that depend on loop guard being present then failed
>   for reasons that had nothing to do with them. The fix now re-applies
>   `spanning-tree guard loop` explicitly. In production the same trap loses you
>   loop protection the moment you add root guard to a port.
> - **`bpduguard-on-uplink` did nothing at first.** Plain `spanning-tree
>   portfast` on a **trunk** port is accepted, warns, and has no effect — and
>   BPDU guard therefore never fired either, despite BPDUs arriving every two
>   seconds. It needs `spanning-tree portfast trunk`.
> - **`mac-acl-blocks-bpdus` was removed entirely and replaced by
>   `vacl-drops-vlan20`.** The plan was to starve a port of BPDUs with a MAC ACL
>   denying `0180.c200.0000`. Verified on this platform: `mac access-group` is
>   accepted and **completely inert** — zero hit counters while the BPDU receive
>   counter kept climbing, and a blunt `deny any any` did not stop host traffic
>   either. The generalisable half is that **BPDUs are punted to the control
>   plane and are not subject to port ACLs**, so you cannot filter spanning tree
>   this way anywhere. VACLs, by contrast, work properly.
> - **`mst-revision-mismatch` had to be judged from the right end.** A switch
>   with a mismatched digest becomes a **region of one**, so it still reports
>   itself as its own MSTI2 root — correctly, for its private region. The change
>   is only visible from the *other* switches. Checking the wrong switch produced
>   a false negative.
>
> The harness needed fixing too: `show spanning-tree inconsistentports` prints
> full interface names (`Ethernet0/3`) while `show spanning-tree mst N` prints
> abbreviated ones (`Et0/3`), so comparing them naively made every guard check
> report failure while the faults were firing perfectly. Worth remembering if you
> write your own checks.
