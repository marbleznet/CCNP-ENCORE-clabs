# 802.1Q Trunking & EtherChannel Lab (Cisco IOL + Edgeshark)

A 3-switch + 3-host `cisco_iol` containerlab topology for learning **VLANs,
802.1Q trunking and link aggregation** from the frame up. The switches boot with
**only hostnames and interface descriptions** — no VLANs, no trunks, no
EtherChannel. Every port starts life as a default access port in VLAN 1. You
build every concept by hand and use **Edgeshark packet captures** to *see* the
802.1Q tag, the DTP negotiation and the LACP/PAgP handshake on the wire.

By the end you will have configured and observed:

- **VLANs** as broadcast domains, and why two hosts one port apart in the same
  subnet cannot talk when they are in different VLANs
- **802.1Q tagging** — the 4-byte tag, the VID, and the CoS bits — captured live
- **The native VLAN**, why a mismatch is dangerous, and why it is the one trunk
  fault the switch actually *tells* you about
- **The allowed VLAN list**, and the three different lists `show interfaces
  trunk` prints
- **DTP** and the full negotiation matrix, including the **auto/auto deadlock**
- **EtherChannel** — and first, on the blank slate, the problem it solves:
  spanning tree blocking two of your three uplinks
- **LACP** (`active`/`passive`) and **PAgP** (`desirable`/`auto`) side by side in
  one topology, plus **static `mode on`** and why mixing it is dangerous
- **Load distribution by hashing**, and why "my EtherChannel is unbalanced" is
  usually not a fault at all

> 📖 **This lab has a companion:** [`CONCEPTS.md`](CONCEPTS.md) is the in-depth
> reference behind every step (what a VLAN really is, the 802.1Q frame format,
> the DTP and EtherChannel mode matrices, hashing, L2 vs L3 EtherChannel, and a
> troubleshooting method). Each lab opens with a **Deep dive** callout linking to
> the relevant sections — follow them for the *why*, skip them when you just want
> to type. It also reads well end-to-end as a switching primer.

---

## Topology

```
      host-a                       host-b            host-c
   10.10.10.11/24               10.10.10.12/24    10.10.20.13/24
      VLAN 10                      VLAN 10           VLAN 20
         |                             |               |
       E1/0                          E1/0            E1/1
    +---------+                      +---------+
    |   SW2   |                      |   SW3   |
    +---------+                      +---------+
     E0/1 E0/2 E0/3                E0/1 E0/2 E0/3
        \   |   /                      \   |   /
         \  |  /  Po1                   \  |  /  Po2
          \ | /  (LACP)                  \ | /  (PAgP)
           \|/                            \|/
     E0/1 E0/2 E0/3                E1/0 E1/1 E1/2
    +-------------------------------------------+
    |                    SW1                    |
    |               (distribution)              |
    +-------------------------------------------+
```

**Why three links per pair?** So that the blank slate demonstrates the problem
before you learn the solution. Three parallel links are three loops; spanning
tree blocks two of them and you get one link's worth of bandwidth. That is Lab 1.
EtherChannel (Labs 5–7) is how you get all three forwarding.

**Why two different protocols?** SW1↔SW2 uses **LACP** (the IEEE standard) and
SW1↔SW3 uses **PAgP** (Cisco's) so you can compare them without rebuilding
anything, and so the `pagp-lacp-protocol-mismatch` fault has two real protocols
to confuse.

**Why no SW2↔SW3 link?** So the bundled topology is a loop-free tree
(SW2 — SW1 — SW3) and any blocked port you see afterwards is a genuine symptom
rather than normal spanning-tree behaviour. Spanning tree itself is the **next**
lab (`../stp/`).

### Roles

| Node | Role | Bundle | Hosts |
|---|---|---|---|
| **SW1** | distribution | Po1 (LACP **active**), Po2 (PAgP **desirable**) | — |
| **SW2** | access | Po1 (LACP **passive**) | host-a |
| **SW3** | access | Po2 (PAgP **auto**) | host-b, host-c |

SW1 is the *initiating* end of both bundles on purpose. The access switches are
`passive`/`auto`, so the channels only form because SW1 asks — which is what
makes the `lacp-passive-passive` fault meaningful.

### VLANs and addressing

| VLAN | Name | Purpose | Members |
|---|---|---|---|
| **10** | `USERS` | the VLAN under test | host-a (SW2 E1/0), host-b (SW3 E1/0) |
| **20** | `SERVERS` | proves isolation | host-c (SW3 E1/1) |
| **99** | `NATIVE-UNUSED` | native VLAN on every trunk | *no ports, deliberately* |

| Host | Address | VLAN | Attached to | Should reach |
|---|---|---|---|---|
| host-a | `10.10.10.11/24` | 10 | SW2 `E1/0` | host-b ✅ |
| host-b | `10.10.10.12/24` | 10 | SW3 `E1/0` | host-a ✅ |
| host-c | `10.10.20.13/24` | 20 | SW3 `E1/1` | **nothing** ❌ |

> **host-c is supposed to fail.** It is alone in VLAN 20, on a different subnet,
> and there is **no router or SVI anywhere in this lab**. Its unreachability is
> your proof that the VLANs are genuinely separate — not a fault to fix. Use
> **host-a → host-b** as your connectivity test throughout.

Interface mapping: containerlab `ethX` → IOL `EthernetY/Z`. `E0/0` is management.

| clab | IOL | | clab | IOL |
|---|---|---|---|---|
| `eth1` | `Ethernet0/1` | | `eth4` | `Ethernet1/0` |
| `eth2` | `Ethernet0/2` | | `eth5` | `Ethernet1/1` |
| `eth3` | `Ethernet0/3` | | `eth6` | `Ethernet1/2` |

---

## Deploy

Run everything in this guide from this lab's directory
(`l2-trunk-etherchannel/`).

```bash
containerlab deploy -t l2-trunk-lab.clab.yml
```

Log in to any switch with `admin` / `admin`:

```bash
ssh admin@clab-l2-trunk-lab-sw1
```

Give the nodes ~60–90s after deploy before the CLI is ready. Destroy with:

```bash
containerlab destroy -t l2-trunk-lab.clab.yml --cleanup
```

### Sanity check before you start (no VLANs yet)

```
sw1# show interfaces status         ! every port "connected", VLAN 1
sw1# show vlan brief                ! only VLAN 1 (+ the 1002-1005 legacy entries)
sw1# show etherchannel summary      ! "Number of channel-groups in use: 0"
sw1# show interfaces trunk          ! EMPTY -- nothing is trunking
```

```bash
docker exec clab-l2-trunk-lab-host-a ping -c2 10.10.10.12   # works -- all VLAN 1
```

### Platform quirks worth knowing before you start

> **1. IOL reports ports with no cable as `connected`.** `show interfaces status`
> on SW1 lists `Et1/3` as connected, but the topology file never links it to
> anything. **Never treat "connected" as proof a link exists** — use
> `show cdp neighbors` or read the topology. This bites hardest when you are
> counting EtherChannel members.
>
> **2. Unaddressed *routed* interfaces come up admin-down on IOL; switchports do
> not.** Everything in this lab is a switchport, so all ports come up `up/up`
> with no addressing at all. (If you go on to build a router lab in this repo,
> that changes — an unaddressed routed port stays down despite `no shutdown`.)
>
> **3. `show interfaces trunk` only lists ports that are *currently trunking*.**
> A trunk that breaks does not appear as failed — it **disappears from the
> output**. An empty table *is* the symptom. This catches everyone at least once.

---

## Using Edgeshark for captures

> **New here?** Edgeshark is **optional** — see the
> [repo README](../README.md#prerequisites) for what it is and how to get it.
> Every step in this lab can also be completed with `show` commands alone.

Edgeshark lets you capture on any container interface straight from the browser:

1. Open the **Edgeshark / Ghostwire** web UI.
2. Find the container (e.g. `clab-l2-trunk-lab-sw1`) and expand its interfaces.
3. Click the **capture** (shark-fin) icon next to the interface you want.

> ⚠️ **The interfaces are named `eth1`…`eth6`, not `Ethernet0/1`.** Edgeshark
> shows the *container's* Linux interfaces, not IOL's internal names. Use the
> mapping table above: to capture SW1's link to SW3's first port
> (IOL `Ethernet1/0`), pick **`eth4`** on `clab-l2-trunk-lab-sw1`.
> *(Verified on this host.)*

This lab is unusually rewarding to capture, because almost everything you
configure is a **protocol you can watch negotiate**:

| Filter | Shows |
|---|---|
| `vlan` | any **802.1Q-tagged** frame — expand to see TPID / PCP / VID |
| `vlan.id == 10` | only VLAN 10 traffic |
| `!vlan` | **untagged** frames — this is your native VLAN traffic |
| `dtp` | **DTP** trunk negotiation |
| `cdp` | **CDP** — carries the native VLAN, so mismatches are reported here |
| `slow` | the *Slow Protocols* group — **LACP** lives here |
| `slow.subtype == 1` | **LACP** only |
| `pagp` | **PAgP** |
| `stp` | spanning-tree **BPDUs** |
| `eth.dst == 01:80:c2:00:00:02` | LACP / slow-protocol destination MAC |
| `eth.dst == 01:00:0c:cc:cc:cc` | the Cisco multicast MAC — **CDP, DTP, PAgP, VTP** all use it |

Multicast MACs to recognise:
- **`01:80:c2:00:00:00`** = spanning-tree BPDUs
- **`01:80:c2:00:00:02`** = slow protocols (LACP)
- **`01:00:0c:cc:cc:cc`** = Cisco control plane (CDP/DTP/PAgP/VTP)

> 📖 **Deep dive:** [Access ports, trunk ports, and the 802.1Q tag](CONCEPTS.md#access-ports-trunk-ports-and-the-8021q-tag)

> Tip: these control protocols are slow — CDP and DTP every 30–60s, LACP every
> 30s, BPDUs every 2s. Start the capture, apply the config, then **wait**. If you
> see nothing in ten seconds that does not mean it is broken.

---

# Lab 1 — See the problem: spanning tree is wasting two thirds of your links

**Goal:** before configuring anything, understand *why* EtherChannel exists. You
have three cables between SW1 and SW2. Find out how many are actually carrying
traffic.

> 📖 **Deep dive:** [Why EtherChannel exists](CONCEPTS.md#why-etherchannel-exists)

### 1.1 Count the forwarding links

```
sw2# show spanning-tree vlan 1
```

Look at the `Role`/`Sts` columns for `Et0/1`, `Et0/2`, `Et0/3`:

```
Et0/1               Root FWD 100       128.2    P2p
Et0/2               Altn BLK 100       128.3    P2p
Et0/3               Altn BLK 100       128.4    P2p
```

**Two of your three uplinks are `Altn BLK` — alternate, blocking.** You bought
three links and you are using one. Spanning tree is not malfunctioning; it is
doing exactly its job, because three parallel links between two switches are
three loops and STP exists to eliminate loops.

> **This is the entire motivation for EtherChannel.** Not redundancy — STP
> already gives you that — but *using the bandwidth you paid for*. In Lab 5 you
> will bundle these three links into one logical port; STP will see a single port,
> have nothing to block, and all three will forward.

### 1.2 Confirm the blank slate is one flat network

```
sw1# show vlan brief                ! VLAN 1 only
sw1# show interfaces trunk          ! empty -- no trunks anywhere
sw1# show etherchannel summary      ! no channel-groups
```

```bash
docker exec clab-l2-trunk-lab-host-a ping -c2 10.10.10.12    # SUCCEEDS
```

Every port is an access port in VLAN 1, so the whole lab is a single broadcast
domain and host-a reaches host-b with no configuration at all. Note that this
works *through* the blocked links — traffic takes the one forwarding path.

> **📸 CAPTURE — `sw2` interface `eth2`** (a **blocked** port, IOL `Ethernet0/2`).
> Filter `stp`. You will see BPDUs arriving every 2 seconds and **no user
> traffic at all**, even while host-a is pinging host-b. That is a blocking port
> in one picture: the control plane is alive, the data plane is shut. Compare
> with `eth1` (the root port), which carries both.

---

# Lab 2 — VLANs and access ports

**Goal:** partition the flat network into broadcast domains, and watch
connectivity *break* as a direct consequence.

> 📖 **Deep dive:** [What a VLAN actually is](CONCEPTS.md#what-a-vlan-actually-is)

### 2.1 Create the VLAN database on all three switches

VTP transparent first — it stops any switch learning or teaching VLANs, so the
database you build is the database you get.

```
sw1# conf t
sw1(config)# vtp mode transparent
sw1(config)# vlan 10
sw1(config-vlan)#  name USERS
sw1(config-vlan)# vlan 20
sw1(config-vlan)#  name SERVERS
sw1(config-vlan)# vlan 99
sw1(config-vlan)#  name NATIVE-UNUSED
sw1(config-vlan)# end
```

Repeat **identically on SW2 and SW3**. All three VLANs go on all three switches
even though SW2 has no VLAN 20 port — a VLAN missing from the local database is
not carried over a trunk, and an incomplete database looks exactly like a
pruning problem.

```
sw1# show vlan brief          ! 10, 20, 99 now present and "active"
```

### 2.2 Put the hosts into their VLANs

```
sw2(config)# interface Ethernet1/0
sw2(config-if)#  switchport mode access
sw2(config-if)#  switchport access vlan 10
sw2(config-if)#  spanning-tree portfast
```

```
sw3(config)# interface Ethernet1/0
sw3(config-if)#  switchport mode access
sw3(config-if)#  switchport access vlan 10
sw3(config-if)#  spanning-tree portfast
sw3(config)# interface Ethernet1/1
sw3(config-if)#  switchport mode access
sw3(config-if)#  switchport access vlan 20
sw3(config-if)#  spanning-tree portfast
```

> `spanning-tree portfast` on an **access port facing a host** is correct and
> expected: an end host cannot create a loop, so the port skips
> listening/learning and gives the host link immediately. On a port facing a
> *switch* it is dangerous — that is `../stp/`'s territory (BPDU guard exists
> precisely to catch it).

### 2.3 Watch connectivity break — on purpose

```bash
docker exec clab-l2-trunk-lab-host-a ping -c2 10.10.10.12    # NOW FAILS
```

**This is correct.** host-a and host-b are now in VLAN 10, but the links between
the switches are still access ports in **VLAN 1**. A VLAN is local to a switch
until something carries it between switches — and nothing does yet. VLAN 10 on
SW2 and VLAN 10 on SW3 are, at this moment, two unrelated broadcast domains that
merely share a number.

```
sw2# show vlan brief          ! Et1/0 now listed under VLAN 10, not VLAN 1
sw2# show mac address-table   ! host-a's MAC is learned in VLAN 10
```

Fixing this is what a trunk is for.

---

# Lab 3 — 802.1Q trunking

**Goal:** carry VLAN 10 and VLAN 20 between the switches over the existing links,
and see the tag on the wire.

> 📖 **Deep dive:** [Access ports, trunk ports, and the 802.1Q tag](CONCEPTS.md#access-ports-trunk-ports-and-the-8021q-tag)
> · [The native VLAN, and why it keeps causing trouble](CONCEPTS.md#the-native-vlan-and-why-it-keeps-causing-trouble)
> · [The allowed VLAN list](CONCEPTS.md#the-allowed-vlan-list)

### 3.1 Start the capture FIRST

> **📸 CAPTURE — `sw1` interface `eth1`** (IOL `Ethernet0/1`, the link to SW2).
> Start it **before** the next step, with filter `vlan`. Right now you will see
> **nothing** — the port is an access port and every frame is untagged. The
> moment you configure the trunk, tagged frames appear. That before/after is the
> clearest possible demonstration of what a trunk actually does.

### 3.2 Turn the inter-switch links into trunks

Configure all three links of each bundle. Still no EtherChannel — one thing at a
time.

```
sw1(config)# interface range Ethernet0/1 - 3
sw1(config-if-range)#  switchport trunk encapsulation dot1q
sw1(config-if-range)#  switchport mode trunk
sw1(config)# interface range Ethernet1/0 - 2
sw1(config-if-range)#  switchport trunk encapsulation dot1q
sw1(config-if-range)#  switchport mode trunk
```

```
sw2(config)# interface range Ethernet0/1 - 3
sw2(config-if-range)#  switchport trunk encapsulation dot1q
sw2(config-if-range)#  switchport mode trunk
```

```
sw3(config)# interface range Ethernet0/1 - 3
sw3(config-if-range)#  switchport trunk encapsulation dot1q
sw3(config-if-range)#  switchport mode trunk
```

> `switchport trunk encapsulation dot1q` is a historical artefact — it existed to
> choose between 802.1Q and Cisco's dead **ISL**. Some platforms are dot1q-only
> and reject the command entirely. Type it by reflex; it is harmless where it is
> accepted.

```bash
docker exec clab-l2-trunk-lab-host-a ping -c2 10.10.10.12    # WORKS AGAIN
```

**On the capture now:** frames appear under filter `vlan`. Open one and expand
the 802.1Q header:

- **TPID `0x8100`** — the "I am tagged" marker
- **PCP** — the 3 priority bits (this is **CoS**, layer-2 QoS)
- **VID** — `10`, the VLAN this frame belongs to

Switch the filter to `!vlan` and you will see the *untagged* frames — CDP, STP,
DTP and anything in the native VLAN. **One VLAN per trunk is always untagged**;
that is the native VLAN, and it is VLAN 1 until you change it.

### 3.3 Set a safe native VLAN

```
sw1(config)# interface range Ethernet0/1 - 3
sw1(config-if-range)#  switchport trunk native vlan 99
sw1(config)# interface range Ethernet1/0 - 2
sw1(config-if-range)#  switchport trunk native vlan 99
```

Do the same on SW2 (`Et0/1-3`) and SW3 (`Et0/1-3`).

> **Change one end first and watch — then notice what does *not* happen.**
> Configure SW1 and pause before SW2, so the two disagree about the native VLAN.
> The textbook says the switch will tell you: CDP logs
> `%CDP-4-NATIVE_VLAN_MISMATCH`, and PVST+ adds `%SPANTREE-2-RECV_PVID_ERR` and
> blocks the port. Run the checks:
>
> ```
> sw1# show spanning-tree inconsistentports
> sw1# show logging | include NATIVE_VLAN|PVID
> ```
>
> ⚠️ **Verified on IOS-XE 17.16: both come back empty, and traffic keeps
> flowing.** CDP is running and has discovered its neighbours, spanning tree is
> in `rapid-pvst` mode, and *still* nothing is reported — for minutes. Know the
> self-reporting behaviour for the exam, but in the field the only dependable
> detection is **comparing the `Native vlan` column of `show interfaces trunk` on
> both ends**.
>
> The reason nothing looks broken is the real lesson: VLANs 10 and 20 are
> **tagged** both ways and are unaffected. Only the *native* VLAN is merged — so
> a native VLAN mismatch quietly damages **the one VLAN nobody is monitoring**.
> That is what makes it a security finding (double-tagging VLAN hopping) rather
> than an outage.

VLAN 99 has no ports in it anywhere, deliberately. A native VLAN that carries no
user traffic defeats the double-tagging VLAN-hopping attack, which depends on
the attacker sitting *in* the native VLAN.

### 3.4 Restrict the allowed VLAN list

```
sw1(config)# interface range Ethernet0/1 - 3
sw1(config-if-range)#  switchport trunk allowed vlan 10,20,99
```

Repeat on SW1's `Et1/0-2`, SW2's `Et0/1-3` and SW3's `Et0/1-3`.

> ⚠️ **The most destructive typo in switching.** `switchport trunk allowed vlan
> 30` does **not** add VLAN 30 — it *replaces the entire list* with just 30 and
> instantly drops every other VLAN off the trunk. The keyword you want is
> **`add`**:
> ```
> switchport trunk allowed vlan add 30
> ```
> People take down production networks with this every month.

### 3.5 Read all three VLAN lists

```
sw1# show interfaces trunk
```

The bottom of that output has **three separate lists**, and reading only the
first is how people miss faults:

| Line | Means | A gap here means |
|---|---|---|
| `Vlans allowed on trunk` | what you **configured** | — |
| `Vlans allowed and active in management domain` | ...and which of those **exist and are active** locally | a **VLAN database** problem (missing or suspended) |
| `Vlans in spanning tree forwarding state and not pruned` | ...and which of those are actually **forwarding** | a **spanning-tree** problem (blocked) |

Each is a subset of the one above. Learning to read the difference collapses
three separate faults into one ten-second check.

---

# Lab 4 — DTP and dynamic trunking

**Goal:** see trunks *negotiate* rather than being told, and reproduce the
auto/auto deadlock.

> 📖 **Deep dive:** [DTP: letting switches negotiate trunks](CONCEPTS.md#dtp-letting-switches-negotiate-trunks)

### 4.1 Look at what you have now

```
sw1# show interfaces Ethernet0/1 switchport | include Administrative|Operational|Negotiation
```

`switchport mode trunk` still sends DTP — it trunks *and* asks the other end to.

> **📸 CAPTURE — `sw1` interface `eth1`.** Filter `dtp`. DTP frames go to the
> Cisco multicast MAC `01:00:0c:cc:cc:cc` roughly every 30s. Expand one to see
> the advertised trunk status and the domain.

### 4.2 Reproduce the auto/auto deadlock

Use **one** link so the others keep the lab alive. Set both ends to `dynamic
auto` — the mode that answers but never asks:

```
sw1(config)# interface Ethernet0/1
sw1(config-if)#  switchport mode dynamic auto
```
```
sw2(config)# interface Ethernet0/1
sw2(config-if)#  switchport mode dynamic auto
```

Wait ~30s, then:

```
sw1# show interfaces Ethernet0/1 switchport | include Administrative Mode|Operational Mode
```

```
Administrative Mode: dynamic auto
Operational Mode: static access          <-- NOT a trunk
```

**Both ends are configured identically and it still failed.** `dynamic auto` only
*responds*; nobody ever initiates, so the link silently settles as an access port
in VLAN 1. This is the single most counter-intuitive cell in the DTP matrix, and
its exact analogue is [LACP passive/passive](CONCEPTS.md#lacp-pagp-and-static-on)
in Lab 5.

### 4.3 Fix it by making one end ask

```
sw1(config-if)# switchport mode dynamic desirable
```

Within ~30s the link trunks. `desirable` actively solicits; `auto` answers. Now
try the other combinations and confirm the matrix:

| SW1 | SW2 | Result |
|---|---|---|
| `dynamic auto` | `dynamic auto` | ❌ access |
| `dynamic desirable` | `dynamic auto` | ✅ trunk |
| `dynamic desirable` | `dynamic desirable` | ✅ trunk |
| `trunk` | `dynamic auto` | ✅ trunk |
| `trunk` | `access` | ⚠️ mismatch |

### 4.4 Then turn DTP off, because you should

```
sw1(config)# interface Ethernet0/1
sw1(config-if)#  switchport mode trunk
sw1(config-if)#  switchport nonegotiate
sw2(config)# interface Ethernet0/1
sw2(config-if)#  switchport mode trunk
sw2(config-if)#  switchport nonegotiate
```

> **Production-correct is static.** `switchport mode trunk` + `switchport
> nonegotiate` on every inter-switch link. DTP is a security hole: an attacker on
> an access port left at the `dynamic auto` default can negotiate a trunk with
> your switch and reach **every VLAN**. Set unused ports to `switchport mode
> access` explicitly.
>
> Re-capture with filter `dtp` after `nonegotiate` — the frames stop entirely.

Put `Ethernet0/1` back to plain `switchport mode trunk` (without `nonegotiate`)
before Lab 5, so all three members are configured identically.

---

# Lab 5 — LACP EtherChannel (SW1 ↔ SW2)

**Goal:** bundle the three SW1↔SW2 links into one logical interface, and watch
spanning tree stop blocking.

> 📖 **Deep dive:** [Why EtherChannel exists](CONCEPTS.md#why-etherchannel-exists)
> · [LACP, PAgP, and static "on"](CONCEPTS.md#lacp-pagp-and-static-on)
> · [What must match before a bundle forms](CONCEPTS.md#what-must-match-before-a-bundle-forms)

### 5.1 Capture the handshake

> **📸 CAPTURE — `sw1` interface `eth1`.** Filter `slow` (or
> `eth.dst == 01:80:c2:00:00:02`). Start it **before** the config. LACPDUs appear
> every 30s once negotiation begins; expand one to see the **System ID**, **Key**,
> and the **Actor/Partner state flags** each end advertises.

### 5.2 Bundle the links

Configure the **physical members identically first**, then add `channel-group`
last. The Port-channel inherits its configuration from the first member to join,
so members that disagree never bundle.

```
sw1(config)# interface range Ethernet0/1 - 3
sw1(config-if-range)#  switchport trunk encapsulation dot1q
sw1(config-if-range)#  switchport mode trunk
sw1(config-if-range)#  switchport trunk native vlan 99
sw1(config-if-range)#  switchport trunk allowed vlan 10,20,99
sw1(config-if-range)#  channel-protocol lacp
sw1(config-if-range)#  channel-group 1 mode active
```

```
sw2(config)# interface range Ethernet0/1 - 3
sw2(config-if-range)#  switchport trunk encapsulation dot1q
sw2(config-if-range)#  switchport mode trunk
sw2(config-if-range)#  switchport trunk native vlan 99
sw2(config-if-range)#  switchport trunk allowed vlan 10,20,99
sw2(config-if-range)#  channel-protocol lacp
sw2(config-if-range)#  channel-group 1 mode passive
```

SW1 is **active** (initiates), SW2 is **passive** (responds). One initiator is
enough. Two passives would be a deadlock — that is the
`lacp-passive-passive` fault.

### 5.3 Verify the bundle

```
sw1# show etherchannel summary
```

```
Group  Port-channel  Protocol    Ports
------+-------------+-----------+---------------------------------------------
1      Po1(SU)         LACP        Et0/1(P)   Et0/2(P)   Et0/3(P)
```

- **`(SU)`** — the channel is layer-**2** and in **U**se
- **`(P)`** — the member is **bundled**. All three must show `(P)`

```
sw1# show lacp neighbor          ! SW2's System ID and port state
sw1# show interfaces Port-channel1 switchport
```

### 5.4 The payoff — spanning tree has nothing left to block

```
sw2# show spanning-tree vlan 10
```

```
Interface           Role Sts Cost      Prio.Nbr Type
------------------- ---- --- --------- -------- ------------
Et1/0               Desg FWD 100       128.5    P2p Edge
Po1                 Root FWD 47        128.65   P2p
```

**The three `Altn BLK` ports from Lab 1 are gone.** Spanning tree now sees a
single logical port, `Po1`, and a single port cannot loop — so all three physical
links forward. Note the **cost has dropped from 100 to 47**: STP costs the bundle
as one higher-bandwidth link, which also makes it more attractive as a path.

> Failure of a *member* is now handled inside the bundle and spanning tree is
> never told anything changed — so there is no topology change and no
> re-convergence. That sub-second failover is a bigger practical win than the
> bandwidth.

---

# Lab 6 — PAgP EtherChannel (SW1 ↔ SW3)

**Goal:** build the same thing with Cisco's PAgP and compare.

> 📖 **Deep dive:** [LACP, PAgP, and static "on"](CONCEPTS.md#lacp-pagp-and-static-on)

> **📸 CAPTURE — `sw1` interface `eth4`** (IOL `Ethernet1/0`). Filter `pagp`.
> Note it uses the **Cisco** multicast MAC `01:00:0c:cc:cc:cc`, the same one CDP
> and DTP use — unlike LACP, which uses the IEEE slow-protocols address. That
> difference alone tells you which protocol a link is running.

```
sw1(config)# interface range Ethernet1/0 - 2
sw1(config-if-range)#  switchport trunk encapsulation dot1q
sw1(config-if-range)#  switchport mode trunk
sw1(config-if-range)#  switchport trunk native vlan 99
sw1(config-if-range)#  switchport trunk allowed vlan 10,20,99
sw1(config-if-range)#  channel-protocol pagp
sw1(config-if-range)#  channel-group 2 mode desirable
```

```
sw3(config)# interface range Ethernet0/1 - 3
sw3(config-if-range)#  switchport trunk encapsulation dot1q
sw3(config-if-range)#  switchport mode trunk
sw3(config-if-range)#  switchport trunk native vlan 99
sw3(config-if-range)#  switchport trunk allowed vlan 10,20,99
sw3(config-if-range)#  channel-protocol pagp
sw3(config-if-range)#  channel-group 2 mode auto
```

```
sw1# show etherchannel summary        ! Po2(SU), Protocol PAgP, three (P) members
sw1# show pagp neighbor
```

**The mapping to remember:** PAgP `desirable` ≡ LACP `active` (initiates), PAgP
`auto` ≡ LACP `passive` (responds only). `auto`+`auto` deadlocks exactly like
`passive`+`passive` and exactly like DTP's `dynamic auto`+`dynamic auto`. Three
protocols, one idea.

> **Which should you use?** **LACP.** PAgP is Cisco-only; LACP is IEEE 802.3ad and
> works with everything. PAgP is here because the exam asks about it and because
> you will meet it in old configs — not because you should deploy it.

---

# Lab 7 — Static `mode on`, and what must match

**Goal:** understand the third option and why mixing it is the most dangerous
thing in this topic.

> 📖 **Deep dive:** [LACP, PAgP, and static "on"](CONCEPTS.md#lacp-pagp-and-static-on)
> · [What must match before a bundle forms](CONCEPTS.md#what-must-match-before-a-bundle-forms)

### 7.1 Break it deliberately: `on` against `passive`

```
sw1(config)# interface range Ethernet0/1 - 3
sw1(config-if-range)#  no channel-group 1
sw1(config-if-range)#  channel-group 1 mode on
```

Leave SW2 as LACP `passive`. Wait ~30s and compare **both** switches:

```
sw1# show etherchannel summary        ! Po1 bundled, Protocol "-"  (no protocol!)
sw2# show etherchannel summary        ! NOT bundled
```

**The two ends disagree about whether an EtherChannel exists.** SW1 bundles
unconditionally — `mode on` performs no negotiation and never confirms the far
end agrees — and starts hashing frames across three links. SW2 sees three
independent ports.

> **Why this is genuinely dangerous.** SW1's spanning tree sees **one** logical
> port and blocks nothing. SW2's sees **three** and blocks two. Any window in
> which those two views disagree is a **real bridging loop** — and layer 2 has no
> TTL to save you. This is precisely what LACP and PAgP exist to prevent.
> A `Protocol` column reading `-` with no LACP/PAgP neighbours is the signature.

### 7.2 Put it back

```
sw1(config)# interface range Ethernet0/1 - 3
sw1(config-if-range)#  no channel-group 1
sw1(config-if-range)#  channel-protocol lacp
sw1(config-if-range)#  channel-group 1 mode active
```

Confirm `Po1(SU)` with three `(P)` members on **both** switches before moving on.

### 7.3 The flags you must be able to read

```
sw1# show etherchannel summary
```

| Flag | Meaning |
|---|---|
| `(P)` | **bundled** — what you want |
| `(D)` | down |
| `(I)` | stand-alone/individual — negotiation failed, forwarding **alone** |
| `(s)` | **suspended** — incompatible configuration |
| `(H)` | hot-standby — more members than the platform will bundle |
| `(SU)` / `(SD)` | the **channel**: layer-2, in use / down |
| `(RU)` | the channel: layer-**3** (routed) |

### 7.4 Why the build order in this lab is "members first, channel-group last"

Every member must agree on speed, duplex, trunk mode, native VLAN and allowed
VLAN list; a member that disagrees is **suspended** `(s)` while the others carry
on. But you cannot easily demonstrate that after the fact:

> ⚠️ **Verified on IOS-XE 17.16:** once a port is a member of a Port-channel, IOS
> keeps its switchport configuration **synchronised with the Port-channel**.
> Changing `switchport trunk allowed vlan` on a single member afterwards does
> **not** create a lasting divergence — the change is absorbed and nothing breaks.
> Member mismatch is a problem you create by configuring ports **before** bundling
> them, which is exactly why the correct order is *configure all members
> identically, then add `channel-group` last*. The `member-config-divergence`
> fault in the break/fix catalogue exists to demonstrate this no-op deliberately.

---

# Lab 8 — Load balancing and the hashing myth

**Goal:** understand why one host pair never gets the full bundle bandwidth, and
why uneven member utilisation is normal.

> 📖 **Deep dive:** [Load balancing: the hashing myth](CONCEPTS.md#load-balancing-the-hashing-myth)

```
sw1# show etherchannel load-balance
```

```
sw1(config)# port-channel load-balance src-dst-ip
```

```
sw1# show etherchannel port-channel        ! per-member load share
```

**EtherChannel does not load-balance; it load-*distributes* by hashing.** For each
frame the switch hashes selected header fields and picks a member from the
result. Three consequences:

- **A single conversation always takes one link.** host-a → host-b will use one
  member and one member only, no matter how many are bundled. That is *by
  design*: splitting a flow would deliver frames out of order and hurt TCP far
  more than the extra bandwidth would help.
- **The hash is only as good as the entropy you feed it.** Hashing on MAC
  addresses behind a router — where every frame carries the router's MAC — sends
  everything down one link. Hash on the field that actually **varies** at that
  point in the network.
- **Uneven counters are not a fault.** With **3** members (as here) they cannot
  be even — hash buckets divide cleanly only across a **power of two**. This lab
  uses three members precisely so you can see that this is a real constraint
  rather than folklore. Production bundles should be 2, 4 or 8 links.

Generate some traffic and look at the distribution:

```bash
docker exec clab-l2-trunk-lab-host-a ping -c 50 10.10.10.12
```
```
sw1# show interfaces Port-channel1 | include packets
sw1# show etherchannel port-channel
```

---

# Lab 9 — The verification sweep

**Goal:** build the muscle memory you will use on every L2 ticket for the rest of
your career — and which the break/fix catalogue below will test.

> 📖 **Deep dive:** [A troubleshooting method for L2 paths](CONCEPTS.md#a-troubleshooting-method-for-l2-paths)

Work **outward from the frame**, not inward from the diagram:

| # | Question | Command |
|---|---|---|
| 1 | Does the VLAN exist, and is it `active` (not `suspended`)? | `show vlan brief` |
| 2 | Which VLAN did the host **actually** land in? | `show mac address-table` |
| 3 | Is the link even a trunk? | `show interfaces trunk` |
| 4 | Is the VLAN allowed, active **and** forwarding on it? | the three lists in the same output |
| 5 | Do both ends agree? (native VLAN, mode, allowed list) | `show interfaces <if> switchport` on both |
| 6 | Is something **filtering** it? | `show vlan filter`, `show port-security` |

And the two traps that waste the most time:

> **Never infer EtherChannel health from ping — in either direction.** A failed
> bundle can fail **closed** (members `(w)` or `(s)`, forwarding nothing, total
> outage) or fail **open** (members `(I)`, forwarding individually with spanning
> tree blocking all but one, so everything still pings at a third of the
> bandwidth and nobody notices). **Verified on IOS-XE 17.16: this platform fails
> closed** — LACP passive/passive gives `(w)`, and `mode on` against a
> negotiating peer gives `(s)` on that peer. Many Catalyst platforms fail open
> instead. **Read the member flag**; it is the only thing that tells you which
> world you are in.
>
> **A healthy bundle proves nothing about VLAN transport.** Bundling and trunking
> are independent. `Po1(SU)` with three `(P)` members tells you the *link* is
> aggregated, not that VLAN 10 crosses it.

---

## Suggested end-state verification

```
sw1# show etherchannel summary     ! Po1(SU) LACP + Po2(SU) PAgP, all six members (P)
sw1# show interfaces trunk         ! both Po trunking, native 99, all three lists = 10,20,99
sw1# show vlan brief               ! 10/20/99 present and active on all three switches
sw2# show spanning-tree vlan 10    ! NOTHING blocking -- loop-free tree
sw3# show mac address-table        ! host-b in VLAN 10, host-c in VLAN 20
```

```bash
docker exec clab-l2-trunk-lab-host-a ping -c2 10.10.10.12   # MUST succeed
docker exec clab-l2-trunk-lab-host-c ping -c2 10.10.10.11   # MUST fail (no router)
```

## Command cheat-sheet

| Task | Command |
|---|---|
| Create a VLAN | `vlan 10` → `name USERS` |
| Suspend a VLAN (without deleting) | `vlan 10` → `state suspend` |
| Access port | `switchport mode access` / `switchport access vlan 10` |
| Trunk port | `switchport trunk encapsulation dot1q` / `switchport mode trunk` |
| Native VLAN | `switchport trunk native vlan 99` |
| **Add** a VLAN to a trunk | `switchport trunk allowed vlan add 30` ⚠️ **not** without `add` |
| Disable DTP | `switchport nonegotiate` |
| LACP bundle | `channel-protocol lacp` / `channel-group 1 mode active｜passive` |
| PAgP bundle | `channel-protocol pagp` / `channel-group 2 mode desirable｜auto` |
| Static bundle | `channel-group 1 mode on` (both ends, or not at all) |
| Hash algorithm | `port-channel load-balance src-dst-ip` |
| Faster LACP detection | `lacp rate fast` |
| L3 EtherChannel | `no switchport` on members **and** the Port-channel |

---

## Reset the whole lab

```bash
containerlab destroy -t l2-trunk-lab.clab.yml --cleanup
containerlab deploy  -t l2-trunk-lab.clab.yml
```

Because the startup configs contain **no VLANs, trunks or EtherChannels**, every
redeploy gives you a genuinely clean slate — right back to spanning tree blocking
two of every three links.

---

## Where this fits

**Blueprint closed by this lab:**

| Topic | Covered by |
|---|---|
| **3.1.a** Troubleshoot static and dynamic 802.1Q trunking protocols | Labs 2, 3, 4 + 7 trunking faults |
| **3.1.b** Troubleshoot static and dynamic EtherChannels | Labs 5, 6, 7, 8 + 4 EtherChannel faults |

**Next:** [`../stp/`](../stp/) — 3.1.c, spanning tree proper (RSTP, MST, root
guard, BPDU guard). It reuses everything here: trunks carry the BPDUs, and an
EtherChannel is what stops STP blocking your uplinks in the first place. Build
this lab before that one.

---

# Break/fix practice — the part that actually matches the exam

Building the lab (Labs 1–9) is how you *learn* trunking and EtherChannel. But the
blueprint says **"Troubleshoot static and dynamic 802.1q trunking"** and
**"Troubleshoot static and dynamic EtherChannels"** — *troubleshoot*, not
configure. Once you can build this lab, the higher-value drill is diagnosing it
**broken**.

`../tools/labctl.py` does that: it loads a known-good config, injects **one**
fault from a catalogue, and tells you nothing but the symptom.

```bash
containerlab deploy -t l2-trunk-lab.clab.yml
cd ..                                              # repo root
./tools/labctl.py l2-trunk-etherchannel baseline   # push the working end-state
./tools/labctl.py l2-trunk-etherchannel break      # inject one random fault
#   ...diagnose using only show commands on the switches...
./tools/labctl.py l2-trunk-etherchannel hint       # a nudge, if you're stuck
./tools/labctl.py l2-trunk-etherchannel reveal     # the answer + why
./tools/labctl.py l2-trunk-etherchannel fix        # restore, and go again
```

Useful variants:

```bash
./tools/labctl.py l2-trunk-etherchannel list                       # the whole catalogue
./tools/labctl.py l2-trunk-etherchannel break --difficulty hard    # only the nasty ones
./tools/labctl.py l2-trunk-etherchannel break --topic 3.1.b        # EtherChannel only
./tools/labctl.py l2-trunk-etherchannel break --id vacl-drops-vlan10
./tools/labctl.py l2-trunk-etherchannel break --seed 42            # reproducible
./tools/labctl.py l2-trunk-etherchannel run "show etherchannel summary" -n sw1
```

### The 13 faults

| Fault | Topic | Diff | What you'll chase |
|---|---|---|---|
| `allowed-vlan-pruned` | 3.1.a | easy | one VLAN dead, trunk perfectly healthy |
| `native-vlan-mismatch` | 3.1.a | med | the one trunk fault the switch **reports** |
| `trunk-forced-to-access` | 3.1.a | med | trunk config present but inert |
| `dtp-auto-auto-deadlock` | 3.1.a | med | both ends identical, still not a trunk |
| `vlan-missing-from-database` | 3.1.a | easy | port assigned to a VLAN that doesn't exist |
| `vlan-suspended` | 3.1.a | med | the VLAN *is* there — read the Status column |
| `access-port-wrong-vlan` | 3.1.a | easy | infrastructure fine, last hop wrong |
| `lacp-passive-passive` | 3.1.b | med | nobody initiates; members stuck at `(w)` |
| `pagp-lacp-protocol-mismatch` | 3.1.b | med | both ends active, mutually unintelligible |
| `etherchannel-mode-on-mismatch` | 3.1.b | hard | one end bundles, the other suspends |
| `member-config-divergence` | 3.1.b | hard | **a deliberate no-op** — and why |
| `vacl-drops-vlan10` | 3.1.a | hard | every infrastructure check passes, traffic still dies |
| `port-security-violation` | 3.1.a | med | port disabled itself; `fix` is *not* a pure inverse |

### How to get value from it

1. **Time yourself.** Aim to identify the fault in under 5 minutes using `show`
   commands only. That is roughly exam pace.
2. **Write down your reasoning before you `reveal`** — what you checked, in what
   order, and what it ruled out. The *method* is the transferable skill.
3. **Run the Lab 9 sweep in order** rather than guessing. Six commands localise
   almost every fault here, and the discipline is the point.
4. **Do not trust ping alone — in either direction.** `vacl-drops-vlan10` kills
   traffic while every infrastructure command reports perfect health.
   `member-config-divergence` and `native-vlan-mismatch` change nothing you can
   ping at all — one is a deliberate no-op, the other is a genuine security
   finding with no traffic impact in this topology. A working ping is not a
   clean bill of health, and a broken one does not tell you which layer failed.
5. **Be patient.** Allow ~30s after a break and ~30s after a fix. DTP
   re-negotiation can take a full 30s on its own, and looking too early will fool
   you.
6. **Add your own.** `faults.yml` is plain YAML; copy an entry and change the
   `break`/`fix` lines. Any gotcha in [`CONCEPTS.md`](CONCEPTS.md) is a candidate.

> **All 13 faults were injected against a live lab on IOS-XE 17.16 by a scripted
> harness**, which checked the *specific* named VLAN, bundle or port flag each
> one claims to change, then reverted it and confirmed the lab returned to a
> healthy baseline. All 13 revert cleanly. Four things needed correcting, and
> each is a better lesson than the fault it came from:
>
> - **`etherchannel-mode-on-mismatch` did not fire at all at first.**
>   `channel-protocol lacp` *pins* an interface to a protocol, so
>   `channel-group 1 mode on` is refused with `Command rejected: the interface
>   can not be added to the channel group`. IOS rejects only that one line and
>   accepts the preceding `no channel-group 1`, so the ports were left in **no
>   channel group at all** — a different bug, silently. The break now runs
>   `no channel-protocol` first.
> - **`lacp-passive-passive` does the opposite of what is usually taught.** The
>   common claim (which an earlier draft of this guide repeated) is that a failed
>   LACP negotiation drops members to `(I)` stand-alone so they forward
>   individually and nothing appears broken. On IOL the members sit at **`(w)`,
>   forward nothing, and connectivity is lost outright**. Same for
>   `mode on` against a negotiating peer, which suspends the peer's ports at
>   `(s)`. **This platform fails closed.**
> - **`native-vlan-mismatch` is not self-reporting here.** CDP is running and
>   spanning tree is `rapid-pvst`, yet no `%CDP-4-NATIVE_VLAN_MISMATCH`, no
>   `%SPANTREE-2-RECV_PVID_ERR`, zero inconsistent ports, and no traffic loss.
>   The fault's symptom was rewritten to be honest about that, which makes it a
>   better exercise: you have to decide whether a finding with no symptom matters.
> - **`member-config-divergence` is a deliberate no-op** and is documented as
>   such — IOS re-synchronises a member's switchport config with its
>   Port-channel, so the divergence the fault tries to create never survives.
>
> The harness itself also had to be fixed before any of this was trustworthy: its
> first version tested ping with `"0% packet loss" in output`, which is a
> substring of `"100% packet loss"`, so **every** ping read as successful. It now
> uses the exit code. Worth remembering if you write your own checks.
