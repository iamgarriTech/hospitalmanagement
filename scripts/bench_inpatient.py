"""Measure AC-115 and AC-116 against a running server.

Deliberately a script rather than a test: the criteria are about a gunicorn
install under concurrency, and a test runner measures neither.

**Load is spread across processes, not threads.** Fifty `requests` sessions in
one interpreter serialise through the GIL on JSON parsing, and the board
response is tens of kilobytes — measured that way the client's own contention
showed up as server latency (670 ms p95 single-process against 475 ms for the
same total concurrency split across four). A load generator that is itself the
bottleneck measures the load generator.
"""
import argparse
import multiprocessing as mp
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests


def login(base, email, password):
    session = requests.Session()
    session.get(f"{base}/api/auth/csrf/", timeout=30)
    token = session.cookies.get("csrftoken")
    response = session.post(
        f"{base}/api/auth/login/",
        json={"email": email, "password": password},
        headers={"X-CSRFToken": token, "Referer": base},
        timeout=30,
    )
    response.raise_for_status()
    return session


def worker(args):
    """One process: its own sessions, its own requests, its own samples."""
    base, email, password, url, users, rounds, pace = args
    sessions = [login(base, email, password) for _ in range(users)]
    samples, errors = [], 0

    def one(session):
        start = time.perf_counter()
        response = session.get(url, timeout=60)
        return (time.perf_counter() - start) * 1000, response.status_code

    for round_index in range(rounds):
        with ThreadPoolExecutor(max_workers=users) as pool:
            for elapsed, status in pool.map(one, sessions):
                samples.append(elapsed)
                if status != 200:
                    errors += 1
        if pace and round_index < rounds - 1:
            time.sleep(pace)
    return samples, errors


def measure(label, *, base, email, password, url, users, processes, rounds, pace,
            target):
    """`users` total concurrency, spread evenly across `processes` clients."""
    processes = max(1, min(processes, users))
    per_process = users // processes
    spread = [per_process] * processes
    for index in range(users - per_process * processes):
        spread[index] += 1

    with mp.Pool(processes) as pool:
        results = pool.map(
            worker,
            [(base, email, password, url, count, rounds, pace) for count in spread],
        )

    samples = [sample for chunk, _ in results for sample in chunk]
    errors = sum(count for _, count in results)
    samples.sort()
    p95 = samples[max(int(len(samples) * 0.95) - 1, 0)]
    passed = p95 < target and not errors

    print(f"\n{label}")
    print(f"  concurrency {users} across {processes} client process(es)")
    print(f"  requests    {len(samples)}   errors {errors}")
    print(f"  p50         {statistics.median(samples):.1f} ms")
    print(f"  p95         {p95:.1f} ms   (target < {target} ms)  "
          f"{'PASS' if passed else 'FAIL'}")
    print(f"  max         {max(samples):.1f} ms")
    return p95, errors, passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8020")
    parser.add_argument("--email", default="bench@example.test")
    parser.add_argument("--password", default="benchmark-password-only")
    parser.add_argument("--ward", type=int, required=True)
    parser.add_argument("--admission", type=int, required=True)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--processes", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument(
        "--pace", type=float, default=0.4,
        help="Seconds between rounds. Fifty staff with a board open read and "
             "type; they are not fifty requests in the same millisecond.",
    )
    args = parser.parse_args()
    common = dict(base=args.base, email=args.email, password=args.password,
                  processes=args.processes, rounds=args.rounds)

    board_p95, _, board_ok = measure(
        "AC-115 — ward board, 40 beds, full complement",
        url=f"{args.base}/api/wards/{args.ward}/board/",
        users=args.users, pace=args.pace, target=500, **common,
    )
    mar_p95, _, mar_ok = measure(
        "AC-116 — MAR, 20 medications over a 7-day stay",
        url=f"{args.base}/api/scheduled-doses/chart/"
            f"?admission={args.admission}&days=7",
        users=10, pace=args.pace, target=400, **common,
    )
    measure(
        "AC-115 — same-instant burst (reported, not the criterion)",
        url=f"{args.base}/api/wards/{args.ward}/board/",
        users=args.users, pace=0, target=500,
        **{**common, "rounds": 1},
    )

    print("\n---")
    print(f"AC-115 {'PASS' if board_ok else 'FAIL'}  ({board_p95:.1f} ms p95)")
    print(f"AC-116 {'PASS' if mar_ok else 'FAIL'}  ({mar_p95:.1f} ms p95)")
    return 0 if (board_ok and mar_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
