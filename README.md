# CCNP ENCOR (350-401) — containerlab study labs

A hands-on lab series for **Implementing Cisco Enterprise Network Core
Technologies (ENCOR 350-401 v1.2)**, built on **containerlab** + **Cisco IOL**,
with packet captures via **Edgeshark**.

Every lab boots from a **blank slate** — the startup configs apply *only*
hostnames, interfaces and (where relevant) IP addresses. There is no VLAN,
routing, tunnel, security or services config anywhere. You type every concept
yourself.

---

## Prerequisites

**1. Docker and [containerlab](https://containerlab.dev).**

Install containerlab by following the [official install
guide](https://containerlab.dev/install/); everything else here assumes a working
`containerlab` and `docker` on the same host.

The commands in this repo are written without `sudo`, which works if your user is
in the `docker` group (and, on some installs, `clab_admins`). If yours isn't,
prefix every `containerlab` command with `sudo`.

**2. The Cisco IOL images — you have to build these yourself.**

> ⚠️ **This is the one prerequisite you can't just download.** Cisco IOL (IOS On
> Linux) binaries are licensed and are **not published on Docker Hub** — there is
> no `docker pull` that will get you one. You need your own copy (IOL ships with a
> Cisco Modeling Labs entitlement), and you package it into a container image with
> [hellt/vrnetlab](https://github.com/hellt/vrnetlab). See containerlab's
> [`cisco_iol` kind docs](https://containerlab.dev/manual/kinds/cisco_iol/) for the
> build steps.

Every topology here references these two tags:

| Image tag | Used for |
|---|---|
| `vrnetlab/cisco_iol:17.16.01` | all routers (IOS-XE 17.16.1a) |
| `vrnetlab/cisco_iol:L2-17.16.01` | the L2 switches, via `type: l2` |

If your build produces different tags, either retag to match or edit the `image:`
lines in the `*.clab.yml` files. Nothing else in the repo hard-codes a version.

Some labs also use ordinary public images for Linux hosts and servers — these
pull automatically and need no setup, starting with `wbitt/network-multitool`.

**3. Python, for the break/fix driver only.**

```bash
pip install --user pexpect pyyaml
```

Not needed if you only want to build the labs by hand.

**4. Edgeshark — optional, but recommended.**

Each lab has 📸 **CAPTURE** checkpoints that open a browser-based Wireshark on a
container interface. Set it up with containerlab's
[Edgeshark integration guide](https://containerlab.dev/manual/wireshark/#edgeshark-integration).

It's entirely optional: every lab can be completed with `show` commands alone.
But seeing the protocol on the wire is a large part of why these labs are built
the way they are — and switching in particular rewards it, because the 802.1Q
tag, the DTP negotiation and the LACP handshake are all things you can *watch*.

Devices log in with **`admin` / `admin`**.

---

## Quick start

```bash
git clone <this repo> && cd CCNP-ENCORE-clabs
cd l2-trunk-etherchannel
containerlab deploy -t l2-trunk-lab.clab.yml     # ~60-90s for IOL to boot
ssh admin@clab-l2-trunk-lab-sw1                  # admin / admin
```

The switches come up with **hostnames and interface descriptions only** — every
port is a default access port in VLAN 1, and spanning tree is blocking two of
every three uplinks. Open
[`l2-trunk-etherchannel/README.md`](l2-trunk-etherchannel/README.md) and start
building. When you're done:

```bash
containerlab destroy -t l2-trunk-lab.clab.yml --cleanup
```

---

## The labs

Suggested order is top to bottom; the foundations feed the ones below them.

| # | Lab | Blueprint topics | Break/fix | Status |
|---|-----|------------------|:---:|:---:|
| 1 | [`l2-trunk-etherchannel/`](l2-trunk-etherchannel/) | 3.1.a trunking · 3.1.b EtherChannel | ✅ 13 faults | **built** |
| 2 | [`stp/`](stp/) | 3.1.c RSTP, MST, root/BPDU guard | ✅ 13 faults | **built** |
| 3 | `ospf/` | 3.2.b OSPFv2/v3 · 3.2.a EIGRP vs OSPF | planned | — |
| 4 | `bgp/` | 3.2.c eBGP, best-path selection | planned | — |
| 5 | `fhrp/` | 3.3.c HSRP/VRRP · 1.1.b HA techniques | planned | — |
| 6 | `nat-pbr/` | 3.3.b NAT/PAT · 3.2.d PBR | planned | — |
| 7 | `qos/` | 1.4 QoS interpretation | planned | — |
| 8 | `multicast/` | 3.3.d PIM-SM, IGMP, SSM, RPF | planned | — |
| 9 | `vrf-gre-ipsec/` | 2.2.a VRF · 2.2.b GRE and IPsec | planned | — |
| 10 | `security/` | 5.1 AAA/device access · 5.2 ACLs, CoPP | planned | — |
| 11 | `assurance/` | 4.1 debug/SNMP/syslog · 4.4 IP SLA · 3.3.a NTP | planned | — |
| 12 | `netflow-span/` | 4.2 Flexible NetFlow · 4.3 SPAN/RSPAN | planned | — |
| 13 | `automation/` | 6.1–6.7 · 4.6 NETCONF/RESTCONF · 5.3 | planned | — |
| 14 | `architecture/` | 1.1 design · 1.2 SD-WAN · 1.3 SD-Access · 2.1 · 2.3 · 4.5 | concepts only | — |

### What can't be labbed on IOL, and how it's covered instead

These were **verified against the actual image**, not assumed:

| Topic | Why not | Covered by |
|---|---|---|
| **4.6 NETCONF/RESTCONF** | `netconf-yang` and `restconf` **do not exist** on IOL 17.16 — both are rejected with `% Invalid input` | `automation/` — a real `netopeer2` NETCONF container plus a mock RESTCONF endpoint |
| **4.3 ERSPAN** | `monitor session … type erspan-source` is rejected; `monitor session` doesn't exist on the router image at all (local SPAN and RSPAN **do** work on the L2 image) | `netflow-span/CONCEPTS.md` |
| **5.4.d MACsec** | `macsec` is rejected on the interface. (`cts` commands parse, but there is no ISE to enforce anything) | `security/CONCEPTS.md` |
| **MAC ACLs (`mac access-group`)** | accepted on switchports but **completely inert** — zero hit counters, filters nothing | use **VACLs** (`vlan filter`), which work correctly; see `stp/CONCEPTS.md` |
| **1.1.b SSO** | needs dual supervisors | `fhrp/CONCEPTS.md` |
| **1.2 SD-WAN, 1.3 SD-Access, 4.5 Catalyst Center** | controller/GUI appliances with no packet-forwarding equivalent | `architecture/` + Cisco DevNet sandboxes |
| **2.1 hypervisors / VMs / vswitch** | nothing to configure on a router | `architecture/` — using containerlab's own Linux bridge plumbing as the worked example |
| **6.4 Catalyst Center / SD-WAN Manager APIs** | hosted controllers | `automation/` — mock API endpoint + DevNet sandbox pointers |

Everything else in the blueprint is hands-on. Notably **LISP** (`router lisp`),
**VXLAN** (`interface nve1`) and **PTP** *are* present on the image even though
the blueprint only asks you to describe them.

---

## What's in a lab

Each lab directory follows the same shape:

```
<lab>/
├── <lab>.clab.yml                   the topology (nodes, links, icons)
├── <lab>.clab.yml.annotations.json  diagram labels/regions for the graph view
├── configs/*.partial.cfg            blank-slate startup configs
├── configs/solution/*.cfg           known-good working config (the baseline)
├── faults.yml                       the fault catalogue
├── README.md                        the hands-on guide — progressive labs with
│                                    📸 CAPTURE checkpoints for Edgeshark
└── CONCEPTS.md                      the in-depth "why" companion, cross-linked
                                     from every lab section via 📖 Deep dive
```

**README = what to type. CONCEPTS = why it works.** The two are cross-linked in
both directions, and CONCEPTS reads well end-to-end as a standalone primer.

---

## Using a lab

### 1. Build it from scratch

```bash
cd l2-trunk-etherchannel
containerlab deploy -t l2-trunk-lab.clab.yml
ssh admin@clab-l2-trunk-lab-sw1                  # admin / admin
```

Then work through `README.md` top to bottom, running the packet captures as you
go. Tear down with `containerlab destroy -t <topo>.clab.yml --cleanup`.

### 2. Then break it — this is the part that matches the exam

The ENCOR blueprint leads with **"Troubleshoot"** on both Layer 2 sub-topics, and
leans on *verify* almost everywhere else. Once you can build a lab, the
higher-value drill is diagnosing it broken.

[`tools/labctl.py`](tools/labctl.py) loads a known-good config, injects **one**
fault from a catalogue, and tells you nothing but the symptom. Run it from the
repo root with the lab deployed:

```bash
./tools/labctl.py l2-trunk-etherchannel baseline   # push the known-good config
./tools/labctl.py l2-trunk-etherchannel break      # inject ONE fault
#   ...diagnose with show commands on the switches...
./tools/labctl.py l2-trunk-etherchannel hint       # a nudge
./tools/labctl.py l2-trunk-etherchannel reveal     # answer + why + how to find it
./tools/labctl.py l2-trunk-etherchannel fix        # restore, go again
```

| Command | What it does |
|---|---|
| `baseline` | Push `configs/solution/*.cfg` — the working end-state, not the blank slate |
| `list` | Show the whole fault catalogue with topics and difficulty |
| `break` | Inject one fault at random; `--id`, `--topic`, `--difficulty`, `--seed` to narrow it |
| `hint` / `reveal` | A nudge, or the full explanation |
| `fix` | Revert the active fault |
| `status` | Which fault is currently injected |
| `run "<cmd>" -n sw1` | Run one command on a node without SSHing in |

```bash
./tools/labctl.py l2-trunk-etherchannel break --difficulty hard   # only the nasty ones
./tools/labctl.py l2-trunk-etherchannel break --topic 3.1.b       # drill one blueprint area
./tools/labctl.py l2-trunk-etherchannel break --id vacl-drops-vlan10
./tools/labctl.py l2-trunk-etherchannel break --seed 42           # reproducible
```

Only one fault is active at a time; `break` refuses to stack a second until you
`fix`. The active fault is tracked in a gitignored `.faultstate.json` in the lab
directory, so it survives between shell sessions.

Aim to identify a fault in **under 5 minutes** using `show` commands only, and
write down your reasoning *before* revealing — the method is the transferable
skill.

---

## Adding break/fix to a lab

`labctl.py` is **lab-agnostic** — it needs no changes to support a new lab. Drop
two things into the lab directory and it works:

1. **`configs/solution/<node>.cfg`** — additive config pasted on top of the
   blank-slate startup config to reach a known-good working end-state. One file
   per node, named after the node. `labctl` strips blank lines and `!` comments,
   then wraps the rest in `configure terminal … end`.
2. **`faults.yml`** — a list of faults, each with:

```yaml
faults:
  - id: allowed-vlan-pruned         # unique, used by --id
    name: "VLAN 10 removed from the allowed list on Po1"
    topic: "3.1.a"                  # blueprint reference, used by --topic
    difficulty: easy                # easy | med | hard
    symptom: "What you'd see on a ticket."
    hint: "A nudge that doesn't give it away."
    explain: "Why it breaks — the teaching point."
    find: "The show commands that localise it."
    break:
      - node: sw1
        lines: ["interface Port-channel1", " switchport trunk allowed vlan 20,99"]
    fix:
      - node: sw1
        lines: ["interface Port-channel1", " switchport trunk allowed vlan 10,20,99"]
```

`fix` must be an exact inverse of `break`, so `break` → `fix` returns the lab to
the baseline byte for byte. Where it genuinely cannot be — `port-security-violation`
leaves the port latched in `err-disabled`, so the fix must also bounce the
interface — say so explicitly in `explain`, because that asymmetry is itself the
lesson.

> **Verify every fault against a running lab before trusting it.** A surprising
> number of plausible-looking faults silently do nothing — the change applies, the
> config looks wrong, and the network carries on working. A fault that no-ops is
> worse than no fault at all, because you'll hunt for a problem that isn't there.
> For each one: baseline → break → wait for convergence → check that the
> **specific** named VLAN, neighbour or bundle actually changed → fix → confirm it
> recovered. Where the obvious version of a fault doesn't fire, that's usually the
> most interesting thing in the catalogue — record why in `explain`.

---

## Conventions

- **`cisco_iol`** nodes (`vrnetlab/cisco_iol:17.16.01`; L2 switches use the
  `L2-17.16.01` image with `type: l2`). Login `admin`/`admin`.
- **`ethX` → `EthernetY/Z`**, and there are **8 ports per node**: `eth1`–`eth3`
  map to `Ethernet0/1`–`0/3`, `eth4`–`eth7` map to `Ethernet1/0`–`1/3`. `E0/0` is
  always management and sits in a `clab-mgmt` VRF — don't touch it.
- **Edgeshark shows the *container's* interface names** (`eth1`, `eth2`, …), not
  IOL's (`Ethernet0/1`). Each lab README gives the mapping.
- **Documentation addressing** throughout — `2001:db8::/32`, `192.0.2.0/24`,
  `203.0.113.0/24`, and RFC1918 space for host subnets.
- Node names follow containerlab's convention, `clab-<lab-name>-<node>` (e.g.
  `clab-l2-trunk-lab-sw1`), where `<lab-name>` is the `name:` field in the
  topology file.
- Commands are written **without `sudo`** — add it if your user isn't in the
  `docker` group.
- Generated runtime dirs (`clab-*/`) and `.faultstate.json` are gitignored.

---

## A note on accuracy

The CONCEPTS files are meant to be studied from, so factual claims are checked
against the actual platform rather than assumed. Where a lab says "verified on
IOS-XE 17.16", it was — and where the platform contradicted the textbook, the
**doc was corrected and the contradiction recorded**, because those are usually
the most valuable paragraphs in the file.

The same applies to the fault catalogues: every fault is injected against a live
lab by a scripted harness that checks the **specific named VLAN, bundle or
prefix** it claims to move, then reverts and re-checks that the lab recovered.
Faults that turn out to no-op are either replaced or — where the no-op is itself
instructive — **kept deliberately and labelled as such**, with the reason in the
fault's own `explain`.
