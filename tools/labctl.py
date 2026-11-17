#!/usr/bin/env python3
"""
labctl.py — study driver for the CCNP ENARSI containerlab labs.

Turns a build-from-scratch lab into a BREAK/FIX troubleshooting lab, which is what
ENARSI actually tests (18 of 25 blueprint items say "Troubleshoot").

    labctl.py <lab> baseline          push the known-good solution configs
    labctl.py <lab> list              show the fault catalogue
    labctl.py <lab> break [--id X] [--seed N] [--topic T] [--difficulty D]
                                      inject ONE fault (random unless --id)
    labctl.py <lab> hint              a nudge, without the answer
    labctl.py <lab> reveal            what was broken, and why
    labctl.py <lab> fix               revert the active fault
    labctl.py <lab> status            what's currently injected
    labctl.py <lab> run "<cmd>" -n r1 run an arbitrary command on a node

<lab> is a lab directory at the repo root (e.g. "ospf"). Requires the lab to be
deployed (`containerlab deploy -t <lab>/<topo>.clab.yml`) and python3 pexpect.

Typical session:
    containerlab deploy -t ospf/ospf-lab.clab.yml
    ./tools/labctl.py ospf baseline      # working network, verified
    ./tools/labctl.py ospf break         # something is now wrong
    ...diagnose with show/debug on the routers...
    ./tools/labctl.py ospf reveal        # check yourself
    ./tools/labctl.py ospf fix           # back to known-good, go again
"""
import argparse, json, os, random, sys, glob

try:
    import pexpect
except ImportError:
    sys.exit("need pexpect:  pip install --user pexpect")
try:
    import yaml
except ImportError:
    sys.exit("need pyyaml:  pip install --user pyyaml")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # repo root — lab dirs are siblings of tools/
PROMPT = r'[\r\n][A-Za-z0-9_.\-]+(\([^)]+\))?[#>]'


# ----------------------------------------------------------------- lab plumbing
def lab_paths(lab):
    d = os.path.join(ROOT, lab)
    if not os.path.isdir(d):
        sys.exit(f"no such lab: {d}")
    topo = glob.glob(os.path.join(d, "*.clab.yml"))
    if not topo:
        sys.exit(f"no *.clab.yml in {d}")
    return d, topo[0]


def lab_name(topo):
    return yaml.safe_load(open(topo))["name"]


def container(topo, node):
    return f"clab-{lab_name(topo)}-{node}"


def state_file(labdir):
    return os.path.join(labdir, ".faultstate.json")


def load_faults(labdir):
    f = os.path.join(labdir, "faults.yml")
    if not os.path.exists(f):
        sys.exit(f"no fault catalogue at {f}")
    return yaml.safe_load(open(f))["faults"]


# --------------------------------------------------------------- device access
def send(host, lines, config_mode=True, quiet=True, timeout=45):
    """Send lines to an IOL node over SSH. Returns the transcript."""
    c = pexpect.spawn(
        f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"-o ConnectTimeout=15 -o PreferredAuthentications=password admin@{host}",
        timeout=timeout, encoding='utf-8')
    buf = []
    c.logfile_read = None if quiet else sys.stdout

    for _ in range(6):
        i = c.expect([r'[Pp]assword:', r'\S+#', r'\S+>', 'RETURN to get',
                      pexpect.TIMEOUT, pexpect.EOF])
        if i == 0:
            c.sendline('admin')
        elif i == 1:
            break
        elif i == 2:
            c.sendline('enable')
            if c.expect([r'[Pp]assword:', r'\S+#']) == 0:
                c.sendline('admin'); c.expect(r'\S+#')
            break
        elif i == 3:
            c.sendline('')
        else:
            raise RuntimeError(f"cannot reach {host} (is the lab deployed?)")

    c.sendline('terminal length 0'); c.expect(PROMPT)
    seq = (['configure terminal'] + list(lines) + ['end']) if config_mode else list(lines)
    # Some IOS commands (clear ip ospf process, reload...) ask for confirmation.
    CONFIRM = r'\[(confirm|yes/no|no|yes)\]\s*:?'
    for ln in seq:
        c.sendline(ln)
        for _ in range(4):                      # allow a few confirmation rounds
            try:
                i = c.expect([PROMPT, CONFIRM], timeout=timeout)
            except pexpect.TIMEOUT:
                buf.append(f"[TIMEOUT after: {ln}]")
                break
            buf.append(c.before)
            if i == 0:
                break
            c.sendline('yes')                   # auto-answer the confirmation
    c.sendline('exit')
    try:
        c.expect(pexpect.EOF, timeout=8)
    except Exception:
        pass
    return "\n".join(buf)


# -------------------------------------------------------------------- commands
def cmd_baseline(args, labdir, topo):
    sols = sorted(glob.glob(os.path.join(labdir, "configs", "solution", "*.cfg")))
    if not sols:
        sys.exit("no configs/solution/*.cfg for this lab")
    print("Pushing known-good configs (this is the working end-state, not the blank slate):")
    for path in sols:
        node = os.path.basename(path).split('.')[0]
        lines = [l.rstrip() for l in open(path)
                 if l.strip() and not l.strip().startswith('!')]
        print(f"  {node:<6} {len(lines):>3} lines ... ", end="", flush=True)
        try:
            send(container(topo, node), lines)
            print("ok")
        except Exception as e:
            print(f"FAILED ({e})")
    # clear any previously injected fault
    if os.path.exists(state_file(labdir)):
        os.remove(state_file(labdir))
    print("\nBaseline applied. Give OSPF/EIGRP ~30s to converge, then verify before breaking.")


def cmd_list(args, labdir, topo):
    faults = load_faults(labdir)
    print(f"{'ID':<22} {'DIFF':<6} {'TOPIC':<9} NAME")
    print("-" * 78)
    for f in faults:
        print(f"{f['id']:<22} {f.get('difficulty','?'):<6} {f.get('topic','-'):<9} {f['name']}")
    print(f"\n{len(faults)} faults. Inject one:  labctl.py <lab> break [--id <ID>]")


def cmd_break(args, labdir, topo):
    faults = load_faults(labdir)
    if os.path.exists(state_file(labdir)):
        cur = json.load(open(state_file(labdir)))
        sys.exit(f"fault '{cur['id']}' is already active — run `fix` (or `reveal`) first.")

    pool = faults
    if args.topic:
        pool = [f for f in pool if f.get('topic', '').startswith(args.topic)]
    if args.difficulty:
        pool = [f for f in pool if f.get('difficulty') == args.difficulty]
    if args.id:
        pool = [f for f in faults if f['id'] == args.id]
        if not pool:
            sys.exit(f"no fault with id '{args.id}'")
    if not pool:
        sys.exit("no faults match those filters")

    if args.seed is not None:
        random.seed(args.seed)
    fault = random.choice(pool)

    for step in fault['break']:
        send(container(topo, step['node']), step['lines'])

    json.dump(fault, open(state_file(labdir), 'w'), indent=2)
    print("💥 A fault has been injected.\n")
    print(f"   Symptom to chase: {fault['symptom']}")
    print("\nDiagnose it with show/debug on the routers. Then:")
    print("   labctl.py <lab> hint     — a nudge")
    print("   labctl.py <lab> reveal   — the answer + why")
    print("   labctl.py <lab> fix      — restore the baseline")


def cmd_hint(args, labdir, topo):
    if not os.path.exists(state_file(labdir)):
        sys.exit("no active fault.")
    f = json.load(open(state_file(labdir)))
    print(f"💡 {f.get('hint','(no hint recorded)')}")


def cmd_reveal(args, labdir, topo):
    if not os.path.exists(state_file(labdir)):
        sys.exit("no active fault.")
    f = json.load(open(state_file(labdir)))
    print(f"🔍 {f['name']}   [{f['id']}]")
    print(f"   blueprint topic : {f.get('topic','-')}   difficulty: {f.get('difficulty','?')}")
    print(f"   symptom         : {f['symptom']}")
    print("\n   what was changed:")
    for step in f['break']:
        for ln in step['lines']:
            print(f"     {step['node']}: {ln}")
    print(f"\n   why it breaks   : {f['explain']}")
    if f.get('find'):
        print(f"   how to find it  : {f['find']}")


def cmd_fix(args, labdir, topo):
    if not os.path.exists(state_file(labdir)):
        sys.exit("no active fault.")
    f = json.load(open(state_file(labdir)))
    for step in f['fix']:
        send(container(topo, step['node']), step['lines'])
    os.remove(state_file(labdir))
    print(f"✅ reverted '{f['id']}'. Back to baseline (allow ~30s to reconverge).")


def cmd_status(args, labdir, topo):
    if not os.path.exists(state_file(labdir)):
        print("no active fault — network should be at baseline.")
        return
    f = json.load(open(state_file(labdir)))
    print(f"active fault: {f['id']}  ({f.get('topic','-')}, {f.get('difficulty','?')})")
    print(f"symptom     : {f['symptom']}")


def cmd_run(args, labdir, topo):
    out = send(container(topo, args.node), [args.command], config_mode=False)
    print(out)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lab", help="lab directory at the repo root (e.g. ospf)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline")
    sub.add_parser("list")
    b = sub.add_parser("break")
    b.add_argument("--id"); b.add_argument("--seed", type=int)
    b.add_argument("--topic"); b.add_argument("--difficulty",
                                              choices=["easy", "med", "hard"])
    sub.add_parser("hint"); sub.add_parser("reveal")
    sub.add_parser("fix"); sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("command"); r.add_argument("-n", "--node", required=True)

    a = p.parse_args()
    labdir, topo = lab_paths(a.lab)
    {"baseline": cmd_baseline, "list": cmd_list, "break": cmd_break, "hint": cmd_hint,
     "reveal": cmd_reveal, "fix": cmd_fix, "status": cmd_status, "run": cmd_run}[a.cmd](a, labdir, topo)


if __name__ == "__main__":
    main()
