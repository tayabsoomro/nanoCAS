#!/usr/bin/env python3
"""nanoCAS demo / simulation command line.

Run nanoCAS without a sequencer:

    python demo.py seed                       # create the demo projects (completed + live-ready)
    python demo.py list                       # show demo projects
    python demo.py simulate <projectId> --scenario contamination
    python demo.py reset                      # delete every demo project

`simulate` writes FASTQ batches + a sequencing summary into the project's
watched directory from *this* process, exactly like MinKNOW would. Start
the nanoCAS server separately and press "Start Monitoring" (or use the
"Simulate" button in the UI, which does both in one click).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging  # noqa: E402

logging.basicConfig(level=os.getenv('NANOCAS_LOG_LEVEL', 'INFO'),
                    format='%(asctime)s - %(levelname)s - %(message)s')

from app.main.utils import project_store, simulator  # noqa: E402


def _progress(pct, msg):
    print(f'  [{pct:3d}%] {msg}', end='\r', flush=True)


def cmd_seed(args):
    created = []
    plan = [
        ('contamination', True), ('flowcell_failure', True), ('clean', True), (args.live_scenario, False),
    ]
    for scenario, seeded in plan:
        print(f'Creating demo project: {simulator.SCENARIOS[scenario]["label"]}'
              f'{" (completed run)" if seeded else " (ready for a live simulation)"}')
        cfg = simulator.create_demo_project(scenario=scenario, seed_history=seeded,
                                            history_batches=args.batches, progress=_progress)
        print()
        created.append(cfg)
    print('\nDemo projects:')
    for cfg in created:
        print(f"  {cfg['projectId']}  {cfg['projectName']}")
    print('\nStart the server (python nanocas.py) and open http://localhost:3000.')


def cmd_list(_args):
    rows = simulator.list_demo_projects()
    if not rows:
        print('No demo projects. Run: python demo.py seed')
        return
    for p in rows:
        print(f"{p['id']}  {p['name']}  [{p['demo_scenario']}]")


def cmd_reset(_args):
    rows = simulator.list_demo_projects()
    for p in rows:
        project_store.delete_project(p['id'])
        print(f"Deleted {p['id']}  {p['name']}")
    if not rows:
        print('Nothing to delete.')


def cmd_simulate(args):
    cfg = project_store.load_config(args.project_id)
    if not cfg:
        sys.exit(f'Project {args.project_id} not found (python demo.py list)')
    pdir = project_store.project_dir(args.project_id)
    ref_path = os.path.join(pdir, 'demo_reference.fasta')
    refs = simulator.read_fasta(ref_path) if os.path.exists(ref_path) else simulator.build_demo_references()
    sim = simulator.SimulatedRun(args.project_id, cfg['minion'], refs, args.scenario,
                                 interval_sec=args.interval, reads_per_batch=args.reads,
                                 total_batches=args.batches, emit=False)
    print(f"Simulating '{simulator.SCENARIOS[args.scenario]['label']}' into {cfg['minion']}")
    print('Press Ctrl-C to stop.')
    sim.start()
    try:
        while sim.is_alive():
            st = sim.status()
            print(f"  batch {st['batches_written']}/{st['total_batches']}  reads {st['reads_written']}  "
                  f"run time {st['run_time_seconds'] / 60:.0f} min", end='\r', flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        sim.stop()
    print('\nSimulation finished.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('seed', help='create demo projects')
    s.add_argument('--batches', type=int, default=36, help='batches per replayed run (default 36 = 3 h at 5 min)')
    s.add_argument('--live-scenario', default='contamination', choices=list(simulator.SCENARIOS))
    s.set_defaults(func=cmd_seed)
    sub.add_parser('list', help='list demo projects').set_defaults(func=cmd_list)
    sub.add_parser('reset', help='delete all demo projects').set_defaults(func=cmd_reset)
    r = sub.add_parser('simulate', help='write a simulated run into a project directory')
    r.add_argument('project_id')
    r.add_argument('--scenario', default=simulator.DEFAULT_SCENARIO, choices=list(simulator.SCENARIOS))
    r.add_argument('--interval', type=float, default=5.0, help='seconds between batches')
    r.add_argument('--reads', type=int, default=200, help='reads per batch')
    r.add_argument('--batches', type=int, default=40)
    r.set_defaults(func=cmd_simulate)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
